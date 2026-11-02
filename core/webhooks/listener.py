"""
Aegis SRE Autonomous Alert Webhook & Direct DB Watchdog Daemon (`core/webhooks/listener.py`).
Exposes real-time HTTP endpoints for application middleware, Alertmanager, or serverless triggers:
  - POST /webhooks/alert
  - GET  /health
  - GET  /incidents
Also supports an optional direct Read-Only PostgreSQL Watchdog (`--watchdog`) that monitors
`pg_stat_statements` / `pg_stat_user_tables` directly without third-party observability SaaS.
"""

from typing import Dict, Any, List, Optional, Set, Callable
from contextlib import asynccontextmanager
import asyncio
import os
import threading
import time
import hashlib
from fastapi import FastAPI, BackgroundTasks, HTTPException, Request

from core.config.aegis_config import AegisConfigLoader
from core.webhooks.alert_normalizer import AlertEventNormalizer


def execute_classified_remediation(
    classified: Dict[str, Any],
    config_path: str = "aegis.yaml"
) -> Dict[str, Any]:
    """Executes Vector A or Vector B closed-loop remediation for a normalized alert event."""
    from dotenv import load_dotenv
    _root_env = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
    if os.path.exists(_root_env):
        load_dotenv(dotenv_path=_root_env, override=True)

    vector = classified["vector"]
    uid = classified["event_uid"]
    payload = classified["payload"]

    try:
        if vector == "a":
            from aegis_vector_a_runner import run_vector_a_remediation
            res = run_vector_a_remediation(config_path=config_path, alert_payload_override=payload)
        else:
            from aegis_vector_b_runner import run_vector_b_remediation
            res = run_vector_b_remediation(config_path=config_path, runtime_error_override=payload)

        return {
            "event_uid": uid,
            "vector": vector,
            "incident_id": res.get("incident_id", payload.get("incident_id")),
            "status": "REMEDIATED",
            "pr_url": res.get("pr", {}).get("html_url"),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        }
    except Exception as e:
        print(f"\n❌ [Aegis SRE] Autonomous Remediation Failed for incident '{payload.get('incident_id', 'ALERT')}': {e}\n", flush=True)
        return {
            "event_uid": uid,
            "vector": vector,
            "incident_id": payload.get("incident_id"),
            "status": "FAILED",
            "error": str(e),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        }


def create_webhook_app(
    config_path: str = "aegis.yaml",
    enable_db_watchdog: bool = False,
    async_spawner: Optional[Callable[[Dict[str, Any], str], Any]] = None
) -> FastAPI:
    manifest = AegisConfigLoader.load_or_default(config_path)
    config_dir = (
        os.path.dirname(os.path.abspath(config_path))
        if config_path and os.path.exists(config_path)
        else os.getcwd()
    )
    resolved_code_dir = (
        AegisConfigLoader.resolve_path(config_dir, manifest.project.code_dir)
        if manifest.project.code_dir
        else None
    )
    base_dir = resolved_code_dir if (resolved_code_dir and os.path.isdir(resolved_code_dir)) else config_dir

    active_uids: Set[str] = set()
    last_handled_time: Dict[str, float] = {}
    incident_history: List[Dict[str, Any]] = []
    remediation_lock = threading.Lock()
    COOLDOWN_SECONDS = 15.0

    def _dispatch_remediation(classified: Dict[str, Any]) -> Dict[str, Any]:
        uid = classified["event_uid"]
        with remediation_lock:
            try:
                record = execute_classified_remediation(classified, config_path=config_path)
                incident_history.append(record)
                return record
            finally:
                last_handled_time[uid] = time.time()
                active_uids.discard(uid)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        stop_event = asyncio.Event()
        watchdog_task = None

        if enable_db_watchdog and manifest.database:
            from core.db.inspector import ReadOnlyDatabaseInspector
            db_cfg = manifest.database
            raw_conn = db_cfg.connection_url or db_cfg.read_only_connection_env
            interval = manifest.observability.watchdog_interval_seconds if manifest.observability else 60
            last_seq_snapshot: Dict[str, int] = {}
            is_initial_poll = True

            async def _db_watchdog_loop():
                nonlocal is_initial_poll
                print(f"📡 [Aegis Direct DB Watchdog] Monitoring PostgreSQL read-only telemetry every {interval}s...")
                while not stop_event.is_set():
                    try:
                        inspector = ReadOnlyDatabaseInspector(
                            read_only_env_var=raw_conn,
                            engine=db_cfg.engine
                        )
                        if inspector.is_postgres:
                            discovered = await asyncio.to_thread(
                                inspector.discover_slow_query_telemetry,
                                base_dir
                            )
                            if discovered:
                                hot_table = discovered.get("table") or discovered.get("pg_stat_statements_summary", {}).get("query", "")
                                current_reads = int(discovered.get("pg_stat_statements_summary", {}).get("seq_tuples_read", 0))
                                prev_reads = last_seq_snapshot.get(hot_table, 0)
                                last_seq_snapshot[hot_table] = current_reads

                                if is_initial_poll:
                                    print(f"📡 [Aegis Direct DB Watchdog] Baseline initialized for '{manifest.project.service_name}'. Active monitoring engaged.")
                                    is_initial_poll = False
                                elif current_reads > prev_reads:
                                    query_sig = discovered.get("pg_stat_statements_summary", {}).get("query", "")
                                    sig_uid = f"watchdog-{hashlib.sha256(query_sig.encode('utf-8')).hexdigest()[:8]}"
                                    now = time.time()
                                    if (
                                        query_sig
                                        and sig_uid not in active_uids
                                        and (now - last_handled_time.get(sig_uid, 0.0)) >= COOLDOWN_SECONDS
                                    ):
                                        print(f"⚡ [Aegis Direct DB Watchdog] Active unindexed sequential scan surge detected on '{manifest.project.service_name}' (+{current_reads - prev_reads} tuples read)!", flush=True)
                                        active_uids.add(sig_uid)
                                        await asyncio.to_thread(
                                            _dispatch_remediation,
                                            {"vector": "a", "event_uid": sig_uid, "payload": discovered}
                                        )
                                        try:
                                            fresh_status = await asyncio.to_thread(inspector.discover_slow_query_telemetry, base_dir)
                                            if fresh_status:
                                                last_seq_snapshot[hot_table] = int(fresh_status.get("pg_stat_statements_summary", {}).get("seq_tuples_read", current_reads))
                                        except Exception:
                                            pass
                                        print(f"\n📡 [Aegis Direct DB Watchdog] Remediation cycle finished. Resuming active monitoring (polling every {interval}s)...\n", flush=True)
                            else:
                                is_initial_poll = False
                    except Exception as err:
                        print(f"   ⚠️ [Aegis Direct DB Watchdog] Poll warning: {err}")

                    try:
                        await asyncio.wait_for(stop_event.wait(), timeout=interval)
                    except asyncio.TimeoutError:
                        pass

            watchdog_task = asyncio.create_task(_db_watchdog_loop())

        yield
        stop_event.set()
        if watchdog_task:
            await watchdog_task

    app = FastAPI(
        title="Aegis SRE Autonomous Webhook & Watchdog Daemon",
        version="1.0.0",
        lifespan=lifespan
    )

    @app.get("/health")
    def health() -> Dict[str, Any]:
        return {
            "status": "online",
            "service_monitored": manifest.project.service_name,
            "repository": manifest.project.repository,
            "watchdog_enabled": enable_db_watchdog,
            "incidents_handled": len(incident_history)
        }

    @app.get("/incidents")
    def list_incidents() -> Dict[str, Any]:
        return {
            "count": len(incident_history),
            "incidents": incident_history
        }

    @app.post("/webhooks/alert")
    async def ingest_alert_webhook(
        request: Request,
        background_tasks: BackgroundTasks,
        sync: bool = False
    ) -> Dict[str, Any]:
        try:
            raw_body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON alert payload.")

        classified = AlertEventNormalizer.classify_and_normalize(
            raw_body,
            default_service=manifest.project.service_name
        )
        if not classified:
            return {
                "status": "IGNORED_BENIGN_EVENT",
                "detail": "Payload did not match database outage or API contract failure criteria."
            }

        uid = classified["event_uid"]
        now = time.time()

        if uid in active_uids:
            return {
                "status": "DUPLICATE_IGNORED",
                "event_uid": uid,
                "message": "Remediation already actively running for this incident signature."
            }

        if (now - last_handled_time.get(uid, 0.0)) < COOLDOWN_SECONDS:
            return {
                "status": "DUPLICATE_IGNORED",
                "event_uid": uid,
                "message": f"Incident signature recently remediated (within {COOLDOWN_SECONDS}s debounce window)."
            }

        # Mark active immediately to prevent race conditions from concurrent duplicate bursts
        active_uids.add(uid)

        if sync:
            result = await asyncio.to_thread(_dispatch_remediation, classified)
            return {"status": "COMPLETED", "remediation": result}

        # When deployed on Modal Serverless, spawn an independent cloud worker so the HTTP container can scale to zero immediately
        if async_spawner is not None:
            try:
                call_handle = async_spawner(classified, config_path)
                call_id = getattr(call_handle, "object_id", None)
                return {
                    "status": "ACCEPTED_SERVERLESS_SPAWNED",
                    "vector": classified["vector"],
                    "event_uid": uid,
                    "incident_id": classified["payload"].get("incident_id"),
                    "modal_call_id": call_id
                }
            finally:
                active_uids.discard(uid)
                last_handled_time[uid] = time.time()

        background_tasks.add_task(_dispatch_remediation, classified)
        return {
            "status": "ACCEPTED_REMEDIATING",
            "vector": classified["vector"],
            "event_uid": uid,
            "incident_id": classified["payload"].get("incident_id")
        }

    return app
