"""
Aegis SRE - Vector B Orchestration Runner (Error-Activated, Self-Healing, 100% Generic).
Workflow:
1. Outage Activation: Downstream service suffers runtime API failure (HTTP 4xx/5xx error & stack trace),
   which triggers and activates the Aegis SRE agent.
2. Contract Diffing: Agent inspects upstream API specification changes and computes a structural AST diff.
3. Dependency Mapping: Agent scans the downstream repository to isolate impacted models and callers.
4. Self-Healing Sandbox Loop (Max 3 Attempts):
   - Meta Muse Spark synthesizes code refactors from the error log + schema diff + source files.
   - Ephemeral Sandbox (Modal Cloud / isolated container) runs the integration test suite.
   - If tests fail, traceback is fed back into Meta Muse Spark to self-correct.
5. Delivery: Meta Muse Spark authors the full Incident Post-Mortem report and opens a ready-to-merge GitHub PR.
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

from core.diff.openapi_differ import diff_specs_from_files
from core.analysis.dependency_mapper import DependencyMapper
from core.llm.muse_client import MuseSparkClient
from core.sandbox.modal_sandbox import EphemeralSandbox
from core.sandbox.test_runner import apply_verified_patch_to_repo
from core.delivery.github_delivery import GitHubDeliveryEngine


def run_vector_b_remediation(
    v1_spec_path: str = "scenarios/vector_b_contract/upstream/openapi_v1.json",
    v2_spec_path: str = "scenarios/vector_b_contract/upstream/openapi_v2_breaking.json",
    client_repo_path: str = "scenarios/vector_b_contract/client_repo",
    test_target: str = "tests",
    max_retries: int = 3
) -> Dict[str, Any]:
    print("=" * 78)
    print("🚨 AEGIS SRE: Autonomous API Contract Drift Remediation (Vector B)")
    print("=" * 78)

    interpreter_path = sys.executable
    sandbox = EphemeralSandbox(client_repo_path, python_interpreter=interpreter_path)

    # -------------------------------------------------------------
    # Step 1: Outage Detection & Error-Driven Agent Activation
    # -------------------------------------------------------------
    print("\n[Step 1] Live Outage Detected -> Capturing Runtime Error & Activating Agent...")
    baseline_run = sandbox.execute_test_suite({}, test_path=test_target)
    if baseline_run["passed"]:
        print(" ⚠️ No active contract outage detected (all tests currently passing).")
        return {"status": "NO_OUTAGE_DETECTED"}

    error_lines = [
        line.strip() for line in (baseline_run["stdout"] + "\n" + baseline_run["stderr"]).splitlines()
        if any(tok in line for tok in ["ValueError", "AssertionError", "422", "400", "Error", "FAILED"])
    ]
    incident_error_log = {
        "incident_id": "INC-20261028-API-01",
        "service": os.path.basename(os.path.abspath(client_repo_path)),
        "http_status": 422,
        "error_message": " | ".join(error_lines[:3]) if error_lines else "Upstream API contract validation failure",
        "raw_traceback": baseline_run["stdout"][-1200:]
    }
    print(f" ❌ Outage Triggered [{incident_error_log['incident_id']}]:")
    print(f"    {incident_error_log['error_message']}")
    print(" ⚡ Aegis SRE Agent Activated!")

    # -------------------------------------------------------------
    # Step 2: Upstream OpenAPI Spec Inspection & Structural Diff
    # -------------------------------------------------------------
    print("\n[Step 2] Inspecting Upstream API Specifications & Computing Structural Diff...")
    diff_result = diff_specs_from_files(v1_spec_path, v2_spec_path)
    breaking_changes = diff_result["breaking_changes"]
    print(f" -> Diffed '{diff_result['v1_title']}' ({diff_result['v1_version']} -> {diff_result['v2_version']})")
    print(f" -> Isolated {len(breaking_changes)} structural contract changes:")
    for change in breaking_changes:
        print(f"    • [{change['type']}] {change.get('description', '')}")

    # -------------------------------------------------------------
    # Step 3: Downstream Dependency Mapping
    # -------------------------------------------------------------
    print("\n[Step 3] Scanning Downstream Repository for Impacted Callers & Models...")
    mapper = DependencyMapper(client_repo_path)
    dep_result = mapper.map_affected_components(breaking_changes)
    target_files = dep_result["target_files"]
    print(f" -> Mapped {len(target_files)} impacted files: {list(target_files.keys())}")

    # -------------------------------------------------------------
    # Step 4: Closed-Loop Synthesis & Ephemeral Sandbox Verification (Max 3 Loops)
    # -------------------------------------------------------------
    muse = MuseSparkClient()
    last_sandbox_error: Optional[str] = None
    verified_synthesis: Optional[Dict[str, Any]] = None
    verified_sandbox_result: Optional[Dict[str, Any]] = None

    for attempt in range(1, max_retries + 1):
        print(f"\n[Step 4.{attempt}] Meta Muse Spark Synthesis & Sandbox Verification (Attempt {attempt}/{max_retries})...")
        synthesis = muse.synthesize_contract_refactor(
            incident_error_log=incident_error_log,
            breaking_changes=breaking_changes,
            affected_files=target_files,
            previous_errors=last_sandbox_error
        )
        refactored_files = synthesis.get("refactored_files", {})
        print(f" -> Diagnosis: \"{synthesis.get('diagnosis', '')}\"")
        print(f" -> Synthesized candidate patch across {len(refactored_files)} file(s): {list(refactored_files.keys())}")

        sandbox_result = sandbox.execute_test_suite(refactored_files, test_path=test_target)
        if sandbox_result["passed"]:
            print(f" ✅ Deterministic Sandbox Gate PASSED on Attempt {attempt} (Exit Code 0)!")
            print(f"    Environment: {sandbox_result['runner_type']} ({sandbox_result['sandbox_id']})")
            verified_synthesis = synthesis
            verified_sandbox_result = sandbox_result
            break
        else:
            last_sandbox_error = sandbox_result["stdout"] + "\n" + sandbox_result["stderr"]
            print(f" ❌ Sandbox Attempt {attempt} Failed (Exit Code {sandbox_result['exit_code']}). Feeding traceback back to Muse Spark...")

    if not verified_synthesis or not verified_sandbox_result:
        print("\n🚨 Sandbox Mandate Enforced: Patch failed after maximum retries. Escalating to human on-call.")
        sys.exit(1)

    # -------------------------------------------------------------
    # Step 5: Model-Authored Report & Ready-to-Merge GitHub PR
    # -------------------------------------------------------------
    print("\n[Step 5] Generating Incident Report & Ready-to-Merge Pull Request...")
    delivery = GitHubDeliveryEngine()
    unified_diff = delivery.generate_diff(target_files, verified_synthesis["refactored_files"])

    incident_id = incident_error_log["incident_id"]
    artifacts = muse.generate_incident_delivery_artifacts(
        incident_id=incident_id,
        vector_type="VECTOR_B_API_CONTRACT",
        incident_trigger=incident_error_log,
        diagnosis=verified_synthesis["diagnosis"],
        changes_or_plan=breaking_changes,
        unified_diff_or_ddl=unified_diff,
        sandbox_result=verified_sandbox_result
    )

    post_mortem_file = f"POST_MORTEM_{incident_id.replace('-', '_')}.md"
    with open(post_mortem_file, "w", encoding="utf-8") as f:
        f.write(artifacts["post_mortem_markdown"])
    print(f" -> Saved Incident Post-Mortem Report: {post_mortem_file}")

    pr = delivery.create_pull_request(
        repo=f"meta-sre/{incident_error_log['service']}",
        branch_name=f"aegis/remediate-{incident_id.lower()}",
        pr_title=artifacts["pr_title"],
        pr_body=artifacts["post_mortem_markdown"]
    )
    print(f" -> Opened Ready-to-Merge GitHub PR #{pr['pr_number']}: \"{artifacts['pr_title']}\"")
    print(f"    PR URL: {pr['html_url']}")

    if "--apply" in sys.argv:
        apply_verified_patch_to_repo(client_repo_path, verified_synthesis["refactored_files"])
        print(" -> Applied verified patch to repository.")

    print("\n🎉 Vector B Autonomous Remediation Complete!")
    print("=" * 78)

    return {
        "incident_id": incident_id,
        "trigger": incident_error_log,
        "breaking_changes": breaking_changes,
        "diagnosis": verified_synthesis["diagnosis"],
        "unified_diff": unified_diff,
        "sandbox_result": verified_sandbox_result,
        "pr": pr,
        "post_mortem_markdown": artifacts["post_mortem_markdown"]
    }


if __name__ == "__main__":
    run_vector_b_remediation()
