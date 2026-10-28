"""
Aegis SRE - Vector A Orchestration Runner (Error-Activated, Read-Only DB Access, Live Sandbox).
Workflow:
1. Outage Activation: Production database outage alert (HTTP 504 timeout / P99 latency breach)
   activates the Aegis SRE agent with error logs and the offending query.
2. Read-Only DB Inspection: Agent connects to the database in strictly READ-ONLY mode (mode=ro)
   to inspect table schemas, existing indexes, and execute live EXPLAIN & timing benchmarks.
3. Self-Healing Sandbox Loop (Max 3 Attempts):
   - Meta Muse Spark diagnoses the plan and synthesizes zero-downtime DDL.
   - DDLSafetyGuard enforces production safety (blocks DROP/TRUNCATE, mandates CONCURRENTLY & lock_timeout).
   - DatabaseSandbox clones the database into an ephemeral sandbox, executes the DDL, replays the query,
     and verifies that the plan converts to an Index Scan with >=80% latency reduction.
   - If verification fails, error logs feed back into Meta Muse Spark to self-correct.
4. Delivery: Meta Muse Spark authors the full Incident Post-Mortem report and opens a ready-to-merge GitHub PR.
"""

import sys
import os
import json
from typing import Dict, Any, Optional

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from core.db.inspector import ReadOnlyDatabaseInspector
from core.db.safety_guard import DDLSafetyGuard
from core.llm.muse_db_client import MuseDBClient
from core.llm.muse_client import MuseSparkClient
from core.sandbox.db_sandbox import DatabaseSandbox
from core.delivery.github_delivery import GitHubDeliveryEngine


def run_vector_a_remediation(
    telemetry_path: str = "scenarios/vector_a_db/incident_telemetry.json",
    schema_sql_path: str = "scenarios/vector_a_db/schema.sql",
    live_db_file: str = "scenarios/vector_a_db/live_production_sim.db",
    max_retries: int = 3
) -> Dict[str, Any]:
    print("=" * 78)
    print("🚨 AEGIS SRE: Autonomous Database Performance Remediation (Vector A)")
    print("=" * 78)

    with open(telemetry_path, "r", encoding="utf-8") as f:
        alert_payload = json.load(f)

    incident_id = alert_payload.get("incident_id", "INC-20261028-DB-01")
    service = alert_payload.get("service", "orders-checkout-api")
    offending_query = alert_payload.get("pg_stat_statements_summary", {}).get(
        "query",
        "SELECT id, user_id, status, total_amount, created_at FROM orders WHERE user_id = $1 AND status = $2 ORDER BY created_at DESC LIMIT $3"
    )
    sample_params = alert_payload.get("sample_params", [42819, "completed", 50])

    anomaly = alert_payload.get("anomaly_trigger", {})
    cpu_percent = anomaly.get("host_cpu_percent", 94.2)
    p99_latency = anomaly.get("current_value", 3580.0)

    outage_alert = {
        "incident_id": incident_id,
        "service": service,
        "error_code": "CRITICAL_CPU_SPIKE / PG_SLOW_QUERY_BREACH",
        "error_message": (
            f"Host CPU surged to {cpu_percent}% (threshold: 80.0%) and P99 latency spiked to {p99_latency}ms "
            f"(threshold: {anomaly.get('threshold', 1500.0)}ms)"
        ),
        "offending_query": offending_query,
        "host_cpu_percent": cpu_percent
    }

    # -------------------------------------------------------------
    # Step 1: Outage Alert Activation
    # -------------------------------------------------------------
    print(f"\n[Step 1] Outage Alert Received [{incident_id}] -> Activating Aegis SRE Agent...")
    print(f" -> Service: {service}")
    print(f" -> Telemetry Breach: CPU = {cpu_percent}% | P99 Latency = {p99_latency}ms")
    print(f" -> Trigger Details: {outage_alert['error_message']}")
    print(f" -> Offending SQL: \"{offending_query}\"")

    # -------------------------------------------------------------
    # Step 2: Live Read-Only Database Inspection (Schema, Indexes, EXPLAIN)
    # -------------------------------------------------------------
    print("\n[Step 2] Connecting to Database via Read-Only Inspector (mode=ro)...")
    inspector = ReadOnlyDatabaseInspector(schema_sql_path=schema_sql_path, row_count=100000)
    db_path = inspector.ensure_database_initialized(live_db_file)
    live_inspection = inspector.inspect_outage_context(offending_query, sample_params=sample_params)

    catalog = live_inspection["table_catalog"]
    explain_plan = live_inspection["explain_plan"]
    executable_query = live_inspection["executable_query"]

    print(f" -> Read-Only Connection Verified: {live_inspection['read_only_verified']}")
    print(f" -> Inspected Table '{catalog['table_name']}': {catalog.get('row_count')} rows, {len(catalog['columns'])} columns")
    print(f" -> Existing Indexes: {[idx['indexname'] for idx in catalog['existing_indexes']] or 'None (Unindexed!)'}")
    print(f" -> Live EXPLAIN Plan: {explain_plan.get('plan_nodes')}")
    print(f" -> Baseline Latency: {explain_plan.get('production_equivalent_latency_ms')}ms (Local scan: {explain_plan.get('measured_local_ms')}ms)")

    # -------------------------------------------------------------
    # Step 3: Self-Healing Synthesis, Safety Gate & Ephemeral DB Sandbox (Max 3 Loops)
    # -------------------------------------------------------------
    muse_db = MuseDBClient()
    db_sandbox = DatabaseSandbox(source_db_path=db_path)

    last_error: Optional[str] = None
    verified_synthesis: Optional[Dict[str, Any]] = None
    verified_sandbox_result: Optional[Dict[str, Any]] = None

    for attempt in range(1, max_retries + 1):
        print(f"\n[Step 3.{attempt}] Meta Muse Spark DDL Synthesis & Sandbox Benchmark (Attempt {attempt}/{max_retries})...")
        synthesis = muse_db.synthesize_database_remediation(
            outage_alert=outage_alert,
            query=executable_query,
            table_catalog=catalog,
            raw_explain_plan=explain_plan,
            previous_sandbox_error=last_error
        )
        ddl_script = synthesis["ddl_script"]
        print(f" -> Diagnosis: \"{synthesis['plan_tree_diagnosis']}\"")
        print(f" -> Synthesized Index: {synthesis['index_name']} on ({', '.join(synthesis.get('indexed_columns', []))})")

        # Validate DDL against Safety Guardrails
        is_safe, violations = DDLSafetyGuard.validate_ddl(ddl_script)
        if not is_safe:
            last_error = f"DDL Safety Policy Violation: {violations}"
            print(f" ❌ Safety Gate Blocked DDL: {last_error}")
            continue

        print(" ✅ DDL Safety Gate PASSED (Zero destructive ops, CONCURRENTLY & lock_timeout='5s' verified)")

        # Execute DDL and replay query inside Ephemeral Database Sandbox
        sandbox_result = db_sandbox.verify_ddl_and_replay_query(
            ddl_script=ddl_script,
            executable_query=executable_query,
            baseline_inspection=live_inspection
        )

        if sandbox_result["deterministic_gate_passed"]:
            print(f" ✅ Ephemeral DB Sandbox Gate PASSED on Attempt {attempt}!")
            print(f"    Before Plan: {sandbox_result.get('before_plan_nodes')}")
            print(f"    After Plan:  {sandbox_result.get('after_plan_nodes')}")
            print(f"    Latency Drop: {sandbox_result['baseline_latency_ms']}ms -> {sandbox_result['remediated_latency_ms']}ms (-{sandbox_result['latency_reduction_percent']}%)")
            verified_synthesis = synthesis
            verified_sandbox_result = sandbox_result
            break
        else:
            last_error = sandbox_result.get("error") or "Insufficient speedup or index not used by query planner"
            print(f" ❌ DB Sandbox Attempt {attempt} Failed: {last_error}. Feeding back to Muse Spark...")

    if not verified_synthesis or not verified_sandbox_result:
        print("\n🚨 Sandbox Mandate Enforced: Database remediation failed verification after max retries.")
        sys.exit(1)

    # -------------------------------------------------------------
    # Step 4: Model-Authored Report & Ready-to-Merge GitHub PR
    # -------------------------------------------------------------
    print("\n[Step 4] Generating Incident Report & Ready-to-Merge Migration Pull Request...")
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

    post_mortem_file = f"POST_MORTEM_{incident_id.replace('-', '_')}.md"
    with open(post_mortem_file, "w", encoding="utf-8") as f:
        f.write(artifacts["post_mortem_markdown"])
    print(f" -> Saved Incident Post-Mortem Report: {post_mortem_file}")

    pr = delivery.create_pull_request(
        repo=f"meta-sre/{service}",
        branch_name=f"aegis/remediate-{incident_id.lower()}",
        pr_title=artifacts["pr_title"],
        pr_body=artifacts["post_mortem_markdown"]
    )
    print(f" -> Opened Ready-to-Merge GitHub PR #{pr['pr_number']}: \"{artifacts['pr_title']}\"")
    print(f"    PR URL: {pr['html_url']}")

    print("\n🎉 Vector A Autonomous Remediation Complete!")
    print("=" * 78)

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
    run_vector_a_remediation()
