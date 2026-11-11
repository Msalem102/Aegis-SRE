"""
Aegis SRE — Zero-Idle-Cost Cloud Serverless Deployment (`aegis_serverless.py`).

Deploys Aegis SRE onto Modal Cloud as an event-driven, scale-to-zero autonomous SRE service:
  1. Scales to ZERO containers when healthy ($0.00/month idle infrastructure cost).
  2. Exposes a live HTTPS Alert Webhook (`POST /webhooks/alert` & `GET /health`) via `@modal.asgi_app()`.
     When an application throws an HTTP 422 contract error or 504 DB timeout, the webhook wakes up,
     spawns an isolated `remediate_incident_worker` cloud job in <50ms, verifies the fix in a Modal
     PostgreSQL 16 / Linux micro-VM, opens a ready-to-merge GitHub PR, and scales back down to zero.
  3. Runs an automated Read-Only PostgreSQL Scheduled Watchdog (`modal.Period(minutes=30)`) that
     periodically inspects `DATABASE_RO_URL` for sequential-scan bottlenecks without needing a 24/7 VPS.

Deploy with:
  python aegis_cli.py deploy --config aegis.yaml
  (or directly: modal deploy aegis_serverless.py)

Test watchdog on-demand:
  modal run aegis_serverless.py
"""

import os
from typing import Dict, Any
import modal

LOCAL_ROOT = os.path.dirname(os.path.abspath(__file__))
ACTIVE_CONFIG = os.getenv("AEGIS_DEPLOY_CONFIG", "aegis.yaml")
LOCAL_CONFIG_ABS = (
    ACTIVE_CONFIG if os.path.isabs(ACTIVE_CONFIG) else os.path.join(LOCAL_ROOT, ACTIVE_CONFIG)
)
REMOTE_CONFIG_PATH = "/root/aegis.yaml"

EXCLUDED_MODAL_CLIENT_VARS = {
    "MODAL_TOKEN_ID",
    "MODAL_TOKEN_SECRET",
    "MODAL_OAUTH_REFRESH_TOKEN",
    "MODAL_OAUTH_CLIENT_ID",
    "MODAL_OAUTH_CLIENT_SECRET",
}


def _load_runtime_secret_dict() -> Dict[str, str]:
    """
    Loads `.env` values locally at deploy/run time while returning `{}` inside remote containers.
    Keeping `modal.Secret.from_dict(...)` unconditional guarantees identical Modal dependency graphs
    between local CLI hydration and remote container entrypoints, and stripping client token variables
    prevents container-side credential warnings.
    """
    if os.environ.get("MODAL_IS_REMOTE") == "1":
        return {}
    dotenv_file = os.path.join(LOCAL_ROOT, ".env")
    if not os.path.isfile(dotenv_file):
        return {}
    from dotenv import dotenv_values

    return {
        k: (v or "")
        for k, v in dotenv_values(dotenv_file).items()
        if k and k not in EXCLUDED_MODAL_CLIENT_VARS
    }


# IMPORTANT: Define Image and Secret unconditionally at module scope (zero local-vs-remote branches)
# so Modal's function hydration always resolves the exact same dependency object graph.
image = (
    modal.Image.debian_slim()
    .pip_install(
        "httpx>=0.27.0",
        "pydantic>=2.7.0",
        "PyYAML>=6.0.1",
        "python-dotenv>=1.0.1",
        "modal>=0.64.0",
        "sqlglot>=25.0.0",
        "jsonref>=1.1.0",
        "rich>=13.7.0",
        "psycopg2-binary>=2.9.9",
        "fastapi>=0.111.0",
        "uvicorn>=0.30.0",
        "pytest>=8.2.0",
    )
    .add_local_python_source(
        "core",
        "aegis_vector_a_runner",
        "aegis_vector_b_runner",
        "aegis_cli",
    )
    .add_local_file(LOCAL_CONFIG_ABS, REMOTE_CONFIG_PATH)
)

runtime_secret = modal.Secret.from_dict(_load_runtime_secret_dict())

app = modal.App("aegis-sre-daemon", image=image, secrets=[runtime_secret])


@app.function(timeout=600)
def remediate_incident_worker(
    classified: Dict[str, Any],
    config_path: str = REMOTE_CONFIG_PATH
) -> Dict[str, Any]:
    """
    Background serverless worker spawned by `/webhooks/alert`.
    Runs the full closed-loop Muse Spark synthesis + Modal micro-VM verification + GitHub PR pipeline
    independently of the HTTP request lifecycle, then scales back to zero.
    """
    from core.webhooks.listener import execute_classified_remediation

    effective_cfg = config_path if os.path.exists(config_path) else "aegis.yaml"
    return execute_classified_remediation(classified, config_path=effective_cfg)


@app.function(schedule=modal.Period(minutes=30), timeout=600)
def scheduled_db_watchdog() -> Dict[str, Any]:
    """
    Zero-server cron heartbeat: wakes up every 30 minutes on Modal Cloud, inspects the read-only
    PostgreSQL replica (`DATABASE_RO_URL`) for unindexed sequential scans breaching SLA thresholds,
    autonomously opens a verified index migration PR if needed, and scales back to $0.
    """
    from urllib.parse import urlparse
    from core.config.aegis_config import AegisConfigLoader
    from core.db.inspector import ReadOnlyDatabaseInspector
    from core.webhooks.listener import execute_classified_remediation

    cfg_path = REMOTE_CONFIG_PATH if os.path.exists(REMOTE_CONFIG_PATH) else "aegis.yaml"
    manifest = AegisConfigLoader.load_or_default(cfg_path)
    db_cfg = manifest.database
    if not db_cfg:
        return {"status": "SKIPPED_NO_DB_CONFIG"}

    raw_conn = db_cfg.connection_url or db_cfg.read_only_connection_env
    inspector = ReadOnlyDatabaseInspector(read_only_env_var=raw_conn, engine=db_cfg.engine)
    if not inspector.is_postgres or not inspector.db_url:
        return {"status": "SKIPPED_NO_REMOTE_POSTGRES_URL"}

    parsed_db = urlparse(inspector.db_url)
    db_host = (parsed_db.hostname or "").lower()
    if os.environ.get("MODAL_IS_REMOTE") == "1" and db_host in {
        "localhost",
        "127.0.0.1",
        "::1",
        "0.0.0.0",
        "host.docker.internal",
    }:
        msg = (
            f"DATABASE_RO_URL points to local loopback '{db_host}:{parsed_db.port or 5432}', "
            "which is unreachable from a remote Modal Cloud container. "
            "For 24/7 Modal Cloud watchdog monitoring, point DATABASE_RO_URL to a cloud PostgreSQL "
            "host (Supabase, Neon, RDS, Railway) or TCP tunnel (e.g. 'ngrok tcp 5432'). "
            "To continuously monitor a localhost database on your machine right now, run: "
            "'python aegis_cli.py listen --config mockstore_aegis.yaml --watchdog'."
        )
        print(f"⚠️  [Modal Cloud Watchdog] {msg}")
        return {
            "status": "SKIPPED_LOCALHOST_DB_IN_CLOUD",
            "db_host": db_host,
            "detail": msg,
        }

    try:
        discovered = inspector.discover_slow_query_telemetry()
    except Exception as exc:
        err_msg = f"Failed to connect to PostgreSQL host '{db_host}': {exc}"
        print(f"⚠️  [Modal Cloud Watchdog] {err_msg}")
        return {"status": "DB_CONNECTION_ERROR", "db_host": db_host, "error": err_msg}

    if not discovered:
        return {"status": "HEALTHY_NO_SLOW_QUERIES"}

    anomaly = discovered.get("anomaly_trigger", {})
    current_val = float(anomaly.get("current_value", 0.0))
    threshold = float(anomaly.get("threshold", db_cfg.sla_thresholds.p99_latency_ms))
    if current_val < threshold:
        return {"status": "HEALTHY_WITHIN_SLA", "current_value": current_val, "threshold": threshold}

    classified = {
        "vector": "a",
        "event_uid": discovered.get("incident_id", "watchdog-auto"),
        "payload": discovered,
    }
    return execute_classified_remediation(classified, config_path=cfg_path)


@app.function(timeout=600)
@modal.asgi_app()
def webhook_daemon():
    """
    Scale-to-zero HTTPS FastAPI endpoint hosted on Modal Cloud.
    Routes:
      - POST /webhooks/alert   (spawns `remediate_incident_worker` asynchronously, or pass `?sync=true`)
      - GET  /health
      - GET  /incidents
    """
    from core.webhooks.listener import create_webhook_app

    cfg_path = REMOTE_CONFIG_PATH if os.path.exists(REMOTE_CONFIG_PATH) else "aegis.yaml"
    return create_webhook_app(
        config_path=cfg_path,
        enable_db_watchdog=False,
        async_spawner=lambda classified, cp: remediate_incident_worker.spawn(classified, cp),
    )


@app.local_entrypoint()
def main():
    """Triggers `scheduled_db_watchdog` on-demand in Modal Cloud for instant end-to-end verification."""
    print("☁️  Triggering Aegis SRE Scheduled Read-Only DB Watchdog on Modal Cloud...")
    result = scheduled_db_watchdog.remote()
    if result.get("status") == "SKIPPED_LOCALHOST_DB_IN_CLOUD":
        print(f"\nℹ️  Modal Cloud container booted cleanly, but skipped DB inspection:")
        print(f"   {result['detail']}")
    else:
        print(f"✅ Watchdog Result: {result}")
