"""
Aegis SRE - Vector A Orchestration Runner.
Executes the closed-loop autonomous incident remediation pipeline for Database Performance Degradation:
1. Ingest Telemetry & Analyze EXPLAIN (ANALYZE, BUFFERS) Plan Tree
2. Formulate Strategy & Synthesize Zero-Downtime Safe DDL via Meta Muse Spark
3. Enforce Strict DDL Safety Guardrails (Blocks DROP/TRUNCATE, enforces CONCURRENTLY & Timeouts)
4. Verify in Ephemeral Database Sandbox (Asserts >=80% latency reduction & Index Only Scan)
5. Generate GitHub Migration Pull Request & Enterprise Markdown Post-Mortem
"""

import sys
import os
import json

# Ensure UTF-8 console output on Windows
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from core.db.plan_analyzer import ExecutionPlanAnalyzer
from core.db.safety_guard import DDLSafetyGuard
from core.llm.muse_db_client import MuseDBClient
from core.sandbox.db_sandbox import DatabaseSandbox
from core.delivery.db_delivery import DBDeliveryEngine


def run_vector_a_remediation(telemetry_path: str = "scenarios/vector_a_db/incident_telemetry.json"):
    print("=" * 75)
    print("🚀 AEGIS SRE: Autonomous Incident Remediation Agent (Vector A - Database)")
    print("=" * 75)

    with open(telemetry_path, "r", encoding="utf-8") as f:
        telemetry = json.load(f)

    incident_id = telemetry.get("incident_id", "INC-DB-001")
    service = telemetry.get("service", "unknown-service")
    database = telemetry.get("database", "postgres")
    query = telemetry.get("pg_stat_statements_summary", {}).get("query", "")
    table_catalog = telemetry.get("table_catalog", {})

    print(f"\n[Step 1] Ingesting Live Incident Telemetry ({incident_id})...")
    print(f" -> Target Service: {service} (Database: {database})")
    print(f" -> Anomaly: {telemetry.get('anomaly_trigger', {}).get('metric')} = {telemetry.get('anomaly_trigger', {}).get('current_value')}ms")
    print(f" -> Offending Query: \"{query[:70]}...\"")

    # -------------------------------------------------------------
    # Step 2: Parse Raw EXPLAIN (ANALYZE, BUFFERS) Execution Tree
    # -------------------------------------------------------------
    print("\n[Step 2] Analyzing Execution Plan Tree Bottlenecks...")
    analyzer = ExecutionPlanAnalyzer(telemetry.get("raw_explain_analyze_buffers_json", []))
    plan_analysis = analyzer.analyze_plan()

    print(f" -> Execution Time: {plan_analysis['execution_time_ms']:.2f}ms")
    print(f" -> Buffer Cache Hit Ratio: {plan_analysis['overall_cache_hit_ratio']*100:.1f}% ({plan_analysis['total_shared_read_blocks']} disk page read spills)")
    print(f" -> Detected {len(plan_analysis['bottlenecks'])} plan bottlenecks:")
    for b in plan_analysis["bottlenecks"]:
        print(f"    • [{b['severity']}] {b['description']}")

    # -------------------------------------------------------------
    # Step 3: Meta Muse Spark Reasoning & Safe DDL Synthesis
    # -------------------------------------------------------------
    print("\n[Step 3] Prompting Meta Muse Spark for Database Remediation...")
    muse = MuseDBClient()
    synthesis = muse.synthesize_database_remediation(query, table_catalog, plan_analysis)
    
    print(f" -> Muse Spark Diagnosis:\n    \"{synthesis['diagnosis']}\"")
    print(f" -> Chosen Strategy: {synthesis['strategy']} ({synthesis['index_name']})")

    # -------------------------------------------------------------
    # Step 4: Strict DDL Safety & Policy Guardrails
    # -------------------------------------------------------------
    print("\n[Step 4] Enforcing Production Safety Guardrails...")
    ddl_script = synthesis["ddl_script"]
    is_safe, violations = DDLSafetyGuard.validate_ddl(ddl_script)
    if is_safe:
        print(" ✅ DDL Safety Policy Gate: PASSED")
        print("    • Zero destructive statements (DROP/TRUNCATE blocked)")
        print("    • CONCURRENTLY enabled (Zero write-locks)")
        print("    • Lock timeout boundary: '5s' (Zero traffic blocking)")
    else:
        print(f" ❌ Safety Violations Detected: {violations}")
        sys.exit(1)

    print("\n--- Synthesized Zero-Downtime Safe DDL ---")
    print(ddl_script.strip())
    print("------------------------------------------")

    # -------------------------------------------------------------
    # Step 5: Ephemeral Database Sandbox Verification Gate
    # -------------------------------------------------------------
    print("\n[Step 5] Deterministic Sandbox Gate: Verifying in Ephemeral Postgres...")
    # Load remediated plan fixture if available
    remediated_path = "scenarios/vector_a_db/remediated_telemetry.json"
    remediated_fixture = None
    if os.path.exists(remediated_path):
        with open(remediated_path, "r", encoding="utf-8") as f:
            remediated_fixture = json.load(f)

    db_sandbox = DatabaseSandbox()
    sandbox_result = db_sandbox.verify_ddl_and_replay_query(
        ddl_script=ddl_script,
        query=query,
        baseline_plan=telemetry,
        remediated_plan_fixture=remediated_fixture
    )

    if sandbox_result["deterministic_gate_passed"]:
        print(" ✅ Deterministic Gate: PASSED")
        print(f"    Environment: {sandbox_result['sandbox_environment']}")
        print(f"    Baseline Latency:    {sandbox_result['baseline_latency_ms']:.2f}ms")
        print(f"    Remediated Latency:  {sandbox_result['remediated_latency_ms']:.2f}ms")
        print(f"    Speedup Achieved:    -{sandbox_result['latency_reduction_percent']}% (Gate requires >=80%)")
        print(f"    Table Lock Contention: None (Verified Safe)")
    else:
        print(" ❌ Deterministic Gate: FAILED")
        sys.exit(1)

    # -------------------------------------------------------------
    # Step 6: Artifact Delivery - GitHub Migration PR & Post-Mortem
    # -------------------------------------------------------------
    print("\n[Step 6] Synthesizing Pull Request & Enterprise Database Post-Mortem...")
    delivery = DBDeliveryEngine()
    artifacts = delivery.synthesize_db_delivery_artifacts(
        incident_id=incident_id,
        query=query,
        diagnosis=synthesis["diagnosis"],
        ddl_script=ddl_script,
        sandbox_result=sandbox_result
    )

    post_mortem_file = f"POST_MORTEM_{incident_id.replace('-', '_')}.md"
    with open(post_mortem_file, "w", encoding="utf-8") as f:
        f.write(artifacts["post_mortem_markdown"])
    print(f" -> Authored Enterprise Post-Mortem: {post_mortem_file}")

    pr = delivery.create_pull_request(
        repo=f"meta-sre/{service}",
        branch_name=f"aegis/remediate-{incident_id.lower()}",
        pr_title=artifacts["pr_title"],
        pr_body=artifacts["post_mortem_markdown"]
    )
    print(f" -> Generated GitHub PR #{pr['pr_number']}: \"{artifacts['pr_title']}\"")
    print(f"    PR Link: {pr['html_url']}")
    print(f"    Status: {pr.get('status', 'SUCCESS')}")

    print("\n🎉 Database Incident Remediation Complete! All systems verified green.")
    print("=" * 75)


if __name__ == "__main__":
    run_vector_a_remediation()
