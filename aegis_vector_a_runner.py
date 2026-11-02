"""
Aegis SRE - Vector A Orchestration Runner (Error-Activated, Read-Only DB Access, Live Cloud Sandbox).
Workflow:
1. Outage Activation: Production database outage alert (inbound alert webhook, live pg_stat_statements,
   or JSON telemetry alert) activates the Aegis SRE agent.
2. Read-Only DB Inspection: Agent connects to PostgreSQL (`readonly=True`) or SQLite (`mode=ro`)
   using the manifest's `read_only_connection_env` to inspect live schemas, indexes, and EXPLAIN plans.
3. Self-Healing Sandbox Loop (Max 3 Attempts):
   - Meta Muse Spark diagnoses the plan and synthesizes zero-downtime PostgreSQL DDL.
   - DDLSafetyGuard enforces production safety (blocks DROP/TRUNCATE, mandates CONCURRENTLY & lock_timeout).
   - DatabaseSandbox spins up an ephemeral PostgreSQL micro-VM on Modal Cloud,
     executes the unmodified DDL, replays the query, and verifies Index Scan conversion + >=80% speedup.
   - If verification fails, error logs feed back into Meta Muse Spark to self-correct.
4. Delivery: Meta Muse Spark authors the full Incident Post-Mortem report and opens an atomic GitHub PR.
"""

import sys
import os
import json
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from dotenv import load_dotenv

_runner_env = os.path.abspath(os.path.join(os.path.dirname(__file__), ".env"))
if os.path.exists(_runner_env):
    load_dotenv(dotenv_path=_runner_env, override=True)
else:
    load_dotenv(override=True)

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from core.config.aegis_config import AegisConfigLoader, LIVE_SCHEMA_MODES, LIVE_TELEMETRY_MODES
from core.db.inspector import ReadOnlyDatabaseInspector
from core.db.safety_guard import DDLSafetyGuard
from core.llm.muse_db_client import MuseDBClient
from core.llm.muse_client import MuseSparkClient
from core.sandbox.db_sandbox import DatabaseSandbox
from core.delivery.github_delivery import GitHubDeliveryEngine


def run_vector_a_remediation(
    telemetry_path: Optional[str] = None,
    schema_sql_path: Optional[str] = None,
    live_db_file: Optional[str] = None,
    max_retries: Optional[int] = None,
    config_path: str = "aegis.yaml",
    alert_payload_override: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    print("=" * 78)
    print("🚨 AEGIS SRE: Autonomous Database Performance Remediation (Vector A)")
    print("=" * 78)

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
    db_cfg = manifest.database

    raw_telemetry_src = telemetry_path or (db_cfg.telemetry_source if db_cfg else "auto")
    raw_schema_src = schema_sql_path or (db_cfg.schema_path if db_cfg else "auto")
    raw_live_db = live_db_file or (db_cfg.live_db_path if db_cfg else None)

    resolved_telemetry = AegisConfigLoader.resolve_path(base_dir, raw_telemetry_src)
    resolved_schema = (
        None
        if (not raw_schema_src or raw_schema_src.strip().lower() in LIVE_SCHEMA_MODES)
        else AegisConfigLoader.resolve_path(base_dir, raw_schema_src)
    )
    resolved_live_db = AegisConfigLoader.resolve_path(base_dir, raw_live_db)
    max_retries = max_retries or (db_cfg.max_healing_retries if db_cfg else 3)
    raw_conn = (db_cfg.connection_url or db_cfg.read_only_connection_env) if db_cfg else "DATABASE_RO_URL"
    min_speedup = db_cfg.sla_thresholds.min_sandbox_speedup_percent if db_cfg else 80.0

    print(f"[Contract Manifest] Loaded '{config_path}' for service '{manifest.project.service_name}'")

    db_engine = db_cfg.engine if db_cfg else "postgres"
    inspector = ReadOnlyDatabaseInspector(
        read_only_env_var=raw_conn,
        schema_sql_path=resolved_schema,
        row_count=100000,
        engine=db_engine
    )

    # Resolve triggering alert payload from webhook override -> JSON file -> Live PostgreSQL catalog
    alert_payload: Optional[Dict[str, Any]] = alert_payload_override
    if not alert_payload and resolved_telemetry and resolved_telemetry.lower() not in LIVE_TELEMETRY_MODES:
        if os.path.isfile(resolved_telemetry):
            with open(resolved_telemetry, "r", encoding="utf-8") as f:
                alert_payload = json.load(f)

    if not alert_payload and inspector.is_postgres:
        print(" -> Introspecting live PostgreSQL telemetry (pg_stat_statements / pg_stat_user_tables)...")
        alert_payload = inspector.discover_slow_query_telemetry(code_search_dir=base_dir)

    if not alert_payload:
        raise RuntimeError(
            "No database outage telemetry found. Provide an alert webhook payload, telemetry JSON file, "
            f"or set '{raw_conn}' to a live PostgreSQL URL for automatic slow-query discovery."
        )

    utc_today = datetime.now(timezone.utc).strftime("%Y%m%d")
    default_inc_id = f"INC-{utc_today}-DB-{uuid.uuid4().hex[:4].upper()}"
    incident_id = alert_payload.get("incident_id") or default_inc_id
    service = alert_payload.get("service") or manifest.project.service_name
    offending_query = (
        alert_payload.get("pg_stat_statements_summary", {}).get("query")
        or alert_payload.get("offending_query")
        or alert_payload.get("query")
        or ""
    ).strip()

    # Pair HTTP 504 / latency alerts (which may omit raw SQL) with live Postgres slow-query discovery
    if not offending_query and inspector.is_postgres:
        discovered = inspector.discover_slow_query_telemetry(code_search_dir=base_dir)
        if discovered:
            offending_query = discovered.get("pg_stat_statements_summary", {}).get("query", "").strip()

    if not offending_query:
        raise RuntimeError("Outage alert did not contain an offending SQL query and live Postgres discovery is not active.")

    sample_params = alert_payload.get("sample_params")
    anomaly = alert_payload.get("anomaly_trigger", {})
    cpu_percent = anomaly.get("host_cpu_percent")
    p99_latency = anomaly.get("current_value") or 250.0
    sla_p99 = anomaly.get("threshold") or (db_cfg.sla_thresholds.p99_latency_ms if db_cfg else 1000.0)

    err_code = "CRITICAL_CPU_SPIKE / PG_SLOW_QUERY_BREACH" if cpu_percent else "PG_SLOW_QUERY_BREACH"
    err_details = (
        f"Host CPU surged to {cpu_percent}% and P99 query latency spiked to {p99_latency}ms (SLA threshold: {sla_p99}ms)"
        if cpu_percent
        else f"P99 query latency spiked to {p99_latency}ms (SLA threshold: {sla_p99}ms)"
    )

    outage_alert = {
        "incident_id": incident_id,
        "service": service,
        "error_code": err_code,
        "error_message": err_details,
        "offending_query": offending_query,
        "host_cpu_percent": cpu_percent
    }

    # -------------------------------------------------------------
    # Step 1: Outage Alert Activation
    # -------------------------------------------------------------
    print(f"\n[Step 1] Outage Alert Received [{incident_id}] -> Activating Aegis SRE Agent...", flush=True)
    print(f" -> Service: {service}", flush=True)
    cpu_info = f"CPU = {cpu_percent}% | " if cpu_percent else ""
    print(f" -> Telemetry Breach: {cpu_info}P99 Latency = {p99_latency}ms", flush=True)
    print(f" -> Trigger Details: {outage_alert['error_message']}", flush=True)
    print(f" -> Offending SQL: \"{offending_query}\"", flush=True)

    # -------------------------------------------------------------
    # Step 2: Live Read-Only Database Inspection (Schema, Indexes, EXPLAIN)
    # -------------------------------------------------------------
    engine_label = "PostgreSQL (readonly=True)" if inspector.is_postgres else "Embedded SQL (mode=ro)"
    print(f"\n[Step 2] Connecting to Database via Read-Only Inspector [{engine_label}]...", flush=True)
    db_path = inspector.ensure_database_initialized(resolved_live_db) if not inspector.is_postgres else None
    live_inspection = inspector.inspect_outage_context(offending_query, sample_params=sample_params)

    catalog = live_inspection["table_catalog"]
    explain_plan = live_inspection["explain_plan"]
    executable_query = live_inspection["executable_query"]

    print(f" -> Read-Only Connection Verified: {live_inspection['read_only_verified']}", flush=True)
    print(f" -> Inspected Table '{catalog['table_name']}': {catalog.get('row_count')} rows, {len(catalog['columns'])} columns", flush=True)
    print(f" -> Existing Indexes: {[idx['indexname'] for idx in catalog['existing_indexes']] or 'None (Unindexed!)'}", flush=True)
    print(f" -> Live EXPLAIN Plan: {explain_plan.get('plan_nodes')}", flush=True)
    print(f" -> Baseline Latency: {explain_plan.get('production_equivalent_latency_ms')}ms (Measured scan: {explain_plan.get('measured_local_ms')}ms)", flush=True)

    # -------------------------------------------------------------
    # Step 3: Self-Healing Synthesis, Safety Gate & Ephemeral DB Sandbox (Max 3 Loops)
    # -------------------------------------------------------------
    muse_db = MuseDBClient()
    db_sandbox = DatabaseSandbox(
        source_db_path=db_path,
        schema_sql_path=resolved_schema,
        app_name=manifest.sandbox.app_name,
        timeout_seconds=max(manifest.sandbox.timeout_seconds, 90),
        min_speedup_percent=min_speedup,
        provider=manifest.sandbox.provider.lower()
    )

    last_error: Optional[str] = None
    verified_synthesis: Optional[Dict[str, Any]] = None
    verified_sandbox_result: Optional[Dict[str, Any]] = None

    for attempt in range(1, max_retries + 1):
        print(f"\n[Step 3.{attempt}] Meta Muse Spark DDL Synthesis & Sandbox Benchmark (Attempt {attempt}/{max_retries})...", flush=True)
        synthesis = muse_db.synthesize_database_remediation(
            outage_alert=outage_alert,
            query=executable_query,
            table_catalog=catalog,
            raw_explain_plan=explain_plan,
            previous_sandbox_error=last_error
        )
        ddl_script = synthesis["ddl_script"]
        cost_info = synthesis.get("cost_metrics", {})
        print(f" -> Diagnosis: \"{synthesis['plan_tree_diagnosis']}\"", flush=True)
        print(f" -> Synthesized Index: {synthesis['index_name']} on ({', '.join(synthesis.get('indexed_columns', []))})", flush=True)
        if cost_info:
            print(f" -> Task Accounting ({cost_info['model']}): {cost_info['total_tokens']} tokens | Remediation Cost: {cost_info['total_cost_formatted']} (Human SRE Baseline: ${cost_info['roi_comparison']['manual_sre_triage_cost_usd']:.2f})", flush=True)

        # Validate DDL against Safety Guardrails
        is_safe, violations = DDLSafetyGuard.validate_ddl(ddl_script)
        if not is_safe:
            last_error = f"DDL Safety Policy Violation: {violations}"
            print(f" ❌ Safety Gate Blocked DDL: {last_error}", flush=True)
            continue

        print(" ✅ DDL Safety Gate PASSED (Zero destructive ops, CONCURRENTLY & lock_timeout='5s' verified)", flush=True)
        print(f" -> Deploying candidate DDL to Ephemeral DB Sandbox ({manifest.sandbox.provider.upper()})...", flush=True)

        # Execute DDL and replay query inside Ephemeral Database Sandbox
        sandbox_result = db_sandbox.verify_ddl_and_replay_query(
            ddl_script=ddl_script,
            executable_query=executable_query,
            baseline_inspection=live_inspection
        )

        if sandbox_result["deterministic_gate_passed"]:
            print(f" ✅ Ephemeral DB Sandbox Gate PASSED on Attempt {attempt} ({sandbox_result.get('sandbox_environment')})!", flush=True)
            print(f"    Before Plan: {sandbox_result.get('before_plan_nodes')}", flush=True)
            print(f"    After Plan:  {sandbox_result.get('after_plan_nodes')}", flush=True)
            print(f"    Latency Drop: {sandbox_result['baseline_latency_ms']}ms -> {sandbox_result['remediated_latency_ms']}ms (-{sandbox_result['latency_reduction_percent']}%)", flush=True)
            verified_synthesis = synthesis
            verified_sandbox_result = sandbox_result
            break
        else:
            last_error = sandbox_result.get("error") or "Insufficient speedup or index not used by query planner"
            print(f" ❌ DB Sandbox Attempt {attempt} Failed: {last_error}. Feeding back to Muse Spark...", flush=True)

    if not verified_synthesis or not verified_sandbox_result:
        msg = "Sandbox Mandate Enforced: Database remediation failed verification after max retries."
        print(f"\n🚨 {msg}", flush=True)
        raise RuntimeError(msg)

    # -------------------------------------------------------------
    # Step 4: Model-Authored Report & Ready-to-Merge GitHub PR
    # -------------------------------------------------------------
    print("\n[Step 4] Generating Incident Report & Ready-to-Merge Migration Pull Request...", flush=True)
    muse_author = MuseSparkClient()
    delivery = GitHubDeliveryEngine()

    artifacts = muse_author.generate_incident_delivery_artifacts(
        incident_id=incident_id,
        vector_type="VECTOR_A_DB",
        incident_trigger=outage_alert,
        diagnosis=verified_synthesis["plan_tree_diagnosis"] + " " + verified_synthesis["cost_and_buffer_analysis"],
        changes_or_plan=explain_plan,
        unified_diff_or_ddl=verified_synthesis["ddl_script"],
        sandbox_result=verified_sandbox_result
    )

    # Respect read_only_source to guarantee external client repos are never modified
    output_base_dir = (
        os.path.join(os.getcwd(), "artifacts", manifest.project.service_name)
        if getattr(manifest.project, "read_only_source", False)
        else base_dir
    )

    reports_dir = os.path.join(output_base_dir, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    post_mortem_file = os.path.join(reports_dir, f"POST_MORTEM_{incident_id.replace('-', '_')}.md")
    with open(post_mortem_file, "w", encoding="utf-8") as f:
        f.write(artifacts["post_mortem_markdown"])
    print(f" -> Saved Incident Post-Mortem Report: {post_mortem_file}")

    # Save SQL migration artifact to configured migration directory (preserving POSIX repo-relative path for GitHub)
    migration_rel_dir = (db_cfg.migration_output_dir if db_cfg else "migrations").replace("\\", "/").strip("/")
    clean_idx = verified_synthesis.get("index_name", "index").lower()
    migration_rel_path = f"{migration_rel_dir}/{utc_today}_add_{clean_idx}.sql"
    migration_abs_path = os.path.join(output_base_dir, migration_rel_path.replace("/", os.sep))
    os.makedirs(os.path.dirname(migration_abs_path), exist_ok=True)

    with open(migration_abs_path, "w", encoding="utf-8") as mf:
        mf.write(verified_synthesis["ddl_script"])
    print(f" -> Saved Production DDL Migration: {migration_abs_path}")

    files_to_commit = {
        migration_rel_path: verified_synthesis["ddl_script"]
    }

    target_repo = manifest.project.repository or os.getenv("GITHUB_REPOSITORY") or "org/repo"
    base_branch = manifest.project.default_branch

    pr = delivery.deliver_remediation_pr(
        repo=target_repo,
        incident_id=incident_id,
        pr_title=artifacts["pr_title"],
        pr_body=artifacts["post_mortem_markdown"],
        files_to_commit=files_to_commit,
        base_branch=base_branch
    )

    if pr.get("status") == "LIVE_GITHUB_PR":
        print(f" -> 🚀 Opened Live GitHub PR #{pr['pr_number']}: \"{artifacts['pr_title']}\"", flush=True)
        print(f"    Target Repository: {pr['target_repo']}", flush=True)
        print(f"    Remote Branch:     {pr['branch']}", flush=True)
        print(f"    PR URL:            {pr['html_url']}", flush=True)
    else:
        print(f" -> Opened Ready-to-Merge Pull Request #{pr['pr_number']}: \"{artifacts['pr_title']}\"", flush=True)
        print(f"    Delivery Mode:     {pr['status']}", flush=True)
        print(f"    Target Repository: {pr['target_repo']}", flush=True)
        print(f"    PR URL:            {pr['html_url']}", flush=True)

    print("\n🎉 Vector A Autonomous Remediation Complete!", flush=True)
    print("=" * 78, flush=True)

    return {
        "incident_id": incident_id,
        "trigger": outage_alert,
        "inspection": live_inspection,
        "diagnosis": verified_synthesis["plan_tree_diagnosis"],
        "ddl_script": verified_synthesis["ddl_script"],
        "sandbox_result": verified_sandbox_result,
        "pr": pr,
        "post_mortem_markdown": artifacts["post_mortem_markdown"]
    }


if __name__ == "__main__":
    try:
        run_vector_a_remediation()
    except Exception as exc:
        print(f"❌ Vector A Execution Aborted: {exc}")
        sys.exit(1)
