"""
Aegis SRE - Vector B Orchestration Runner.
Executes the closed-loop autonomous incident remediation pipeline for API Contract Drift:
1. Ingestion & Diffing
2. Downstream Dependency Scanning
3. Meta Muse Spark Synthesis
4. Ephemeral Sandbox Verification Gate
5. GitHub Pull Request & Post-Mortem Delivery
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

from core.diff.openapi_differ import diff_specs_from_files
from core.analysis.dependency_mapper import DependencyMapper
from core.llm.muse_client import MuseSparkClient
from core.sandbox.modal_sandbox import EphemeralSandbox
from core.sandbox.test_runner import apply_verified_patch_to_repo
from core.delivery.github_delivery import GitHubDeliveryEngine


def run_vector_b_remediation():
    print("=" * 75)
    print("🚀 AEGIS SRE: Autonomous Incident Remediation Agent (Vector B)")
    print("=" * 75)

    v1_spec_path = "scenarios/vector_b_contract/upstream/openapi_v1.json"
    v2_spec_path = "scenarios/vector_b_contract/upstream/openapi_v2_breaking.json"
    client_repo_path = "scenarios/vector_b_contract/client_repo"
    interpreter_path = sys.executable

    # -------------------------------------------------------------
    # Step 1: Upstream Contract Drift Ingestion & AST Diff
    # -------------------------------------------------------------
    print("\n[Step 1] Ingesting Upstream Contract Drift & Computing AST Diff...")
    diff_result = diff_specs_from_files(v1_spec_path, v2_spec_path)
    breaking_changes = diff_result["breaking_changes"]
    print(f" -> Detected {len(breaking_changes)} breaking schema changes:")
    for change in breaking_changes:
        print(f"    • [{change['type']}] {change.get('description', '')}")

    # -------------------------------------------------------------
    # Step 2: Downstream Static Dependency Mapping
    # -------------------------------------------------------------
    print("\n[Step 2] Scanning Downstream Client Repository...")
    mapper = DependencyMapper(client_repo_path)
    dep_result = mapper.map_affected_components(breaking_changes)
    target_files = dep_result["target_files"]
    print(f" -> Isolated {len(target_files)} target source files:")
    for fpath in target_files.keys():
        print(f"    • {fpath}")

    # -------------------------------------------------------------
    # Step 3: Verify Pre-Remediation Baseline (Assert Failure)
    # -------------------------------------------------------------
    print("\n[Step 3] Executing Baseline Test Suite in Isolated Sandbox...")
    sandbox = EphemeralSandbox(client_repo_path, python_interpreter=interpreter_path)
    baseline_run = sandbox.execute_test_suite({}) # empty patch = current codebase
    if not baseline_run["passed"]:
        print(f" ❌ Baseline Status: TESTS FAILING (Exit Code {baseline_run['exit_code']}) - Incident Active!")
        print(f"    Runner Environment: {baseline_run['runner_type']} ({baseline_run['sandbox_id']})")
        first_err_line = [line for line in baseline_run["stdout"].splitlines() if "ValueError" in line or "FAILED" in line]
        print(f"    Error: {' | '.join(first_err_line[:2])}")
    else:
        print(" ⚠️ Warning: Baseline unexpectedly passed.")

    # -------------------------------------------------------------
    # Step 4: Meta Muse Spark Reasoning & Code Synthesis
    # -------------------------------------------------------------
    print("\n[Step 4] Prompting Meta Muse Spark for AST Remediation...")
    muse = MuseSparkClient()
    synthesis = muse.synthesize_contract_refactor(breaking_changes, target_files)
    print(f" -> Muse Spark Diagnosis:\n    \"{synthesis['diagnosis']}\"")
    refactored_files = synthesis["refactored_files"]
    print(f" -> Synthesized patches for {len(refactored_files)} files.")

    # -------------------------------------------------------------
    # Step 5: Ephemeral Sandbox Verification Gate
    # -------------------------------------------------------------
    print("\n[Step 5] Deterministic Sandbox Gate: Testing Candidate Patch...")
    sandbox_result = sandbox.execute_test_suite(refactored_files)

    if sandbox_result["passed"]:
        print(f" ✅ Deterministic Gate: PASSED (Exit Code {sandbox_result['exit_code']})")
        print(f"    Runner Environment: {sandbox_result['runner_type']} ({sandbox_result['sandbox_id']})")
        print(f"    All integration tests passed successfully.")
    else:
        print(f" ❌ Deterministic Gate: FAILED (Exit Code {sandbox_result['exit_code']})")
        print(sandbox_result["stdout"])
        print(sandbox_result["stderr"])
        sys.exit(1)

    # -------------------------------------------------------------
    # Step 6: Artifact Delivery - Model-Authored PR & Post-Mortem
    # -------------------------------------------------------------
    print("\n[Step 6] Synthesizing Pull Request & Enterprise Post-Mortem with Meta Muse Spark...")
    delivery = GitHubDeliveryEngine()
    unified_diff = delivery.generate_diff(target_files, refactored_files)
    
    # Prompt Muse Spark to author the complete PR and Post-Mortem
    incident_id = "INC-20261027-API-01"
    artifacts = muse.generate_incident_delivery_artifacts(
        incident_id=incident_id,
        breaking_changes=breaking_changes,
        unified_diff=unified_diff,
        sandbox_result=sandbox_result
    )

    # Save model-generated post-mortem
    post_mortem_file = f"POST_MORTEM_{incident_id.replace('-', '_')}.md"
    with open(post_mortem_file, "w", encoding="utf-8") as f:
        f.write(artifacts["post_mortem_markdown"])
    print(f" -> Authored Enterprise Post-Mortem: {post_mortem_file}")

    # Generate PR
    pr = delivery.create_pull_request(
        repo="meta-sre/payment-client",
        branch_name=f"aegis/remediate-{incident_id.lower()}",
        pr_title=artifacts["pr_title"],
        pr_body=artifacts["post_mortem_markdown"]
    )
    print(f" -> Generated GitHub PR #{pr['pr_number']}: \"{artifacts['pr_title']}\"")
    print(f"    PR Link: {pr['html_url']}")
    print(f"    Status: {pr.get('status', 'SUCCESS')}")

    # Apply verified patch only if explicitly requested via argument
    if "--apply" in sys.argv:
        apply_verified_patch_to_repo(client_repo_path, refactored_files)
        print(" -> Applied verified patch to client repository files.")
    else:
        print(" -> Sandbox Mandate preserved: client repository left in clean reproducible outage state (use --apply to write to disk).")

    print("\n🎉 Incident Remediation Complete! All systems verified green.")
    print("=" * 75)


if __name__ == "__main__":
    run_vector_b_remediation()
