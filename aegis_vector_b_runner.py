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
from core.sandbox.test_runner import SandboxTestRunner, apply_verified_patch_to_repo
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
    sandbox = SandboxTestRunner(client_repo_path, python_interpreter=interpreter_path)
    baseline_run = sandbox.verify_patch({}) # empty patch = current codebase
    if not baseline_run["passed"]:
        print(" ❌ Baseline Status: TESTS FAILING (Exit Code 1) - Incident Active!")
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
    sandbox_result = sandbox.verify_patch(refactored_files)

    if sandbox_result["passed"]:
        print(" ✅ Deterministic Gate: PASSED (Exit Code 0)")
        print(f"    Sandbox ID: {sandbox_result['sandbox_id']}")
        print(f"    All integration tests passed successfully.")
    else:
        print(" ❌ Deterministic Gate: FAILED")
        print(sandbox_result["stdout"])
        print(sandbox_result["stderr"])
        sys.exit(1)

    # -------------------------------------------------------------
    # Step 6: Artifact Delivery - GitHub PR & Post-Mortem
    # -------------------------------------------------------------
    print("\n[Step 6] Generating GitHub PR & Markdown Incident Post-Mortem...")
    delivery = GitHubDeliveryEngine()
    unified_diff = delivery.generate_diff(target_files, refactored_files)
    
    post_mortem = delivery.generate_post_mortem(
        incident_id="INC-20261027-API-01",
        service_name="payment-gateway-client",
        diagnosis=synthesis["diagnosis"],
        breaking_changes=breaking_changes,
        unified_diff=unified_diff,
        sandbox_result=sandbox_result
    )

    # Write post-mortem to artifacts directory or repo
    post_mortem_file = "POST_MORTEM_INC_20261027_API_01.md"
    with open(post_mortem_file, "w", encoding="utf-8") as f:
        f.write(post_mortem)
    print(f" -> Created Enterprise Post-Mortem: {post_mortem_file}")

    # Generate PR
    pr = delivery.create_pull_request(
        repo="meta-sre/payment-client",
        branch_name="aegis/remediate-inc-20261027-api-01",
        pr_title="fix(contract): reconcile payment client with upstream OpenAPI v2 schema",
        pr_body=post_mortem
    )
    print(f" -> Generated GitHub PR #{pr['pr_number']}: {pr['html_url']}")
    print(f"    Status: {pr.get('status', 'SUCCESS')}")

    # Apply verified patch to client repo so it stays in remediated state if desired
    apply_verified_patch_to_repo(client_repo_path, refactored_files)
    print("\n🎉 Incident Remediation Complete! All systems verified green.")
    print("=" * 75)


if __name__ == "__main__":
    run_vector_b_remediation()
