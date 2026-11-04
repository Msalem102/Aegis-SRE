"""
Aegis SRE - Vector B Orchestration Runner (Error-Activated, Self-Healing, 100% Generic).
Workflow:
1. Outage Activation: Downstream service suffers runtime API failure (inbound alert webhook / HTTP 4xx event
   or failing verification suite), activating the Aegis SRE agent.
2. Contract Discovery: Supports 3 modes seamlessly:
   - Two-Spec Structural AST Diff (`baseline_spec` vs `spec_url`)
   - Single-Spec Live Target Discovery (`spec_url` HTTP URL or file without requiring `baseline_spec`)
   - Pure Error-Driven Schema Inference (zero external spec required)
3. Dependency Mapping: Scans `code_root` + runtime tracebacks + AST imports to isolate impacted callers & models.
4. Self-Healing Sandbox Loop (Max 3 Attempts):
   - Meta Muse Spark synthesizes code refactors from error log + contract context + source files.
   - Ephemeral Sandbox (Modal Cloud micro-VM with dynamic `requirements.txt` installation) runs pytest.
   - If tests fail, traceback is fed back into Meta Muse Spark to self-correct.
5. Delivery: Meta Muse Spark authors the full Incident Post-Mortem report and opens an atomic GitHub PR.
"""

import sys
import os
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from dotenv import load_dotenv

_runner_env = os.path.abspath(os.path.join(os.path.dirname(__file__), ".env"))
if os.path.exists(_runner_env):
    load_dotenv(dotenv_path=_runner_env, override=True)
else:
    load_dotenv(override=True)

if getattr(sys.stdout, "encoding", "utf-8") != "utf-8":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from core.config.aegis_config import AegisConfigLoader
from core.diff.openapi_differ import diff_specs
from core.analysis.dependency_mapper import DependencyMapper
from core.llm.muse_client import MuseSparkClient
from core.sandbox.modal_sandbox import EphemeralSandbox, apply_verified_patch_to_repo
from core.delivery.github_delivery import GitHubDeliveryEngine


def run_vector_b_remediation(
    v1_spec_path: Optional[str] = None,
    v2_spec_path: Optional[str] = None,
    client_repo_path: Optional[str] = None,
    test_target: Optional[str] = None,
    max_retries: Optional[int] = None,
    config_path: str = "aegis.yaml",
    runtime_error_override: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    print("=" * 78)
    print("🚨 AEGIS SRE: Autonomous API Contract Drift Remediation")
    print("=" * 78)

    config_dir = (
        os.path.dirname(os.path.abspath(config_path))
        if config_path and os.path.exists(config_path)
        else os.getcwd()
    )
    manifest = AegisConfigLoader.load_or_default(config_path)
    resolved_code_dir = (
        AegisConfigLoader.resolve_path(config_dir, manifest.project.code_dir)
        if manifest.project.code_dir
        else None
    )
    base_dir = resolved_code_dir if (resolved_code_dir and os.path.isdir(resolved_code_dir)) else config_dir
    api_cfg = manifest.upstream_apis[0] if manifest.upstream_apis else None

    if not api_cfg and not client_repo_path and not v2_spec_path:
        alt_path = os.path.join(config_dir, "mockstore_aegis.yaml")
        if os.path.exists(alt_path):
            alt_manifest = AegisConfigLoader.load_or_default(alt_path)
            if alt_manifest.upstream_apis:
                manifest = alt_manifest
                api_cfg = alt_manifest.upstream_apis[0]
                config_path = alt_path
                resolved_code_dir = (
                    AegisConfigLoader.resolve_path(config_dir, manifest.project.code_dir)
                    if manifest.project.code_dir
                    else None
                )
                base_dir = resolved_code_dir if (resolved_code_dir and os.path.isdir(resolved_code_dir)) else config_dir

    if not api_cfg and not client_repo_path and not v2_spec_path:
        raise RuntimeError(
            f"No 'upstream_apis' entries configured in '{config_path}'. "
            "Add an upstream API contract configuration to run Vector B remediation."
        )

    raw_v1 = v1_spec_path if v1_spec_path is not None else (api_cfg.baseline_spec if api_cfg else None)
    raw_v2 = v2_spec_path if v2_spec_path is not None else (api_cfg.get_effective_spec() if api_cfg else None)
    raw_repo = client_repo_path or (api_cfg.client_repo_root if api_cfg else ".")

    resolved_v1 = AegisConfigLoader.resolve_path(base_dir, raw_v1)
    resolved_v2 = AegisConfigLoader.resolve_path(base_dir, raw_v2)
    resolved_repo = AegisConfigLoader.resolve_path(base_dir, raw_repo) or base_dir
    test_target = test_target or (api_cfg.test_target if api_cfg else "tests")
    code_root = api_cfg.code_root if api_cfg else None
    isolated_modules = api_cfg.isolated_client_modules if api_cfg else None
    max_retries = max_retries or (api_cfg.max_healing_retries if api_cfg else 3)

    print(f"[Contract Manifest] Loaded '{config_path}' for service '{manifest.project.service_name}'")

    sandbox = EphemeralSandbox(
        resolved_repo,
        python_interpreter=sys.executable,
        app_name=manifest.sandbox.app_name,
        timeout_seconds=manifest.sandbox.timeout_seconds,
        provider=manifest.sandbox.provider.lower()
    )

    # -------------------------------------------------------------
    # Step 1: Outage Detection & Error-Driven Agent Activation
    # -------------------------------------------------------------
    print("\n[Step 1] Live Outage Detection -> Capturing Runtime Error & Activating Agent...")

    alert_context: Optional[Dict[str, Any]] = runtime_error_override
    if alert_context:
        print(f" -> Ingested Inbound Alert Webhook Telemetry [{alert_context.get('incident_id')}]")

    baseline_run = sandbox.execute_test_suite({}, test_path=test_target)
    if baseline_run["passed"] and not alert_context:
        print(" ⚠️ No active contract outage detected (all verification tests currently passing).")
        return {"status": "NO_OUTAGE_DETECTED"}

    combined_output = baseline_run["stdout"] + "\n" + baseline_run["stderr"]
    error_lines = [
        line.strip() for line in combined_output.splitlines()
        if any(tok in line for tok in ["ValueError", "AssertionError", "ValidationError", "KeyError", "422", "400", "Error", "FAILED"])
    ]

    utc_today = datetime.now(timezone.utc).strftime("%Y%m%d")
    default_inc_id = f"INC-{utc_today}-API-{uuid.uuid4().hex[:4].upper()}"

    incident_error_log = {
        "incident_id": (alert_context or {}).get("incident_id") or default_inc_id,
        "service": manifest.project.service_name or os.path.basename(os.path.abspath(resolved_repo)),
        "http_status": (alert_context or {}).get("http_status", 422),
        "endpoint": (alert_context or {}).get("endpoint", ""),
        "error_message": (
            (alert_context or {}).get("error_message")
            or (" | ".join(error_lines[:4]) if error_lines else "Upstream API contract validation failure")
        ),
        "raw_traceback": (
            combined_output[-1500:]
            + ("\n" + str(alert_context.get("raw_traceback", "")) if alert_context else "")
        ).strip()
    }
    print(f" ❌ Outage Triggered [{incident_error_log['incident_id']}]:")
    print(f"    {incident_error_log['error_message']}")
    print(" ⚡ Aegis SRE Agent Activated!")

    # -------------------------------------------------------------
    # Step 2: Upstream OpenAPI Spec Inspection & Structural Diff
    # -------------------------------------------------------------
    print("\n[Step 2] Inspecting Upstream API Contract Context...")
    try:
        diff_result = diff_specs(resolved_v1, resolved_v2)
    except Exception as spec_err:
        print(f" ⚠️ Could not fetch OpenAPI spec ({spec_err}). Falling back to Pure Error-Driven Schema Inference.")
        diff_result = {
            "mode": "PURE_ERROR_INFERENCE",
            "breaking_changes_count": 0,
            "breaking_changes": []
        }

    breaking_changes = diff_result["breaking_changes"]
    discovery_mode = diff_result.get("mode", "TWO_SPEC_DIFF")
    if discovery_mode == "TWO_SPEC_DIFF":
        print(f" -> Mode: TWO_SPEC_DIFF | Diffed '{diff_result['v1_title']}' ({diff_result['v1_version']} -> {diff_result['v2_version']})")
        print(f" -> Isolated {len(breaking_changes)} structural contract changes:")
        for change in breaking_changes:
            print(f"    • [{change['type']}] {change.get('description', '')}")
    elif discovery_mode == "SINGLE_TARGET_SPEC":
        print(f" -> Mode: SINGLE_TARGET_SPEC | Loaded live upstream contract '{diff_result['v2_title']}' ({diff_result['v2_version']})")
        print(f" -> Extracted {len(breaking_changes)} active endpoint schema contract(s).")
    else:
        print(" -> Mode: PURE_ERROR_INFERENCE | Inferring upstream contract requirements directly from runtime 4xx payload & traceback.")

    # -------------------------------------------------------------
    # Step 3: Downstream Dependency Mapping
    # -------------------------------------------------------------
    print("\n[Step 3] Scanning Downstream Repository for Impacted Callers & Models...")
    mapper = DependencyMapper(
        resolved_repo,
        code_root=code_root,
        test_target=test_target,
        isolated_client_modules=isolated_modules
    )
    dep_result = mapper.map_affected_components(breaking_changes, incident_error_log=incident_error_log)
    target_files = dep_result["target_files"]
    print(f" -> Mapped {len(target_files)} context files: {list(target_files.keys())}")

    # -------------------------------------------------------------
    # Step 3.5: Pre-Flight Idempotency Gate (Save 100% Token & Modal Compute Costs)
    # -------------------------------------------------------------
    target_repo = manifest.project.repository or os.getenv("GITHUB_REPOSITORY") or "org/repo"
    delivery = GitHubDeliveryEngine()
    api_name = api_cfg.name if api_cfg else None
    existing_pr = delivery.find_open_remediation_pr(
        repo=target_repo,
        incident_id=incident_error_log["incident_id"],
        keywords=[api_name] if api_name else None,
        vector="b"
    )
    if existing_pr:
        return {
            "status": "PR_ALREADY_OPEN",
            "incident_id": incident_error_log["incident_id"],
            "service": manifest.project.service_name,
            "diagnosis": f"Existing Pull Request #{existing_pr['pr_number']} is already open for this contract drift.",
            "unified_diff": f"# Active remediation in PR #{existing_pr['pr_number']}\n# {existing_pr['html_url']}",
            "patch_code": f"# Active remediation in PR #{existing_pr['pr_number']}\n# {existing_pr['html_url']}",
            "pr": existing_pr,
            "tokens_saved": True
        }

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
        raw_refactored = synthesis.get("refactored_files", {})
        # Enforce test-file immutability & normalize POSIX paths
        refactored_files = {
            k.replace("\\", "/"): v
            for k, v in raw_refactored.items()
            if "test" not in os.path.basename(k.replace("\\", "/")).lower()
        }
        synthesis["refactored_files"] = refactored_files

        cost_info = synthesis.get("cost_metrics", {})
        print(f" -> Diagnosis: \"{synthesis.get('diagnosis', '')}\"")
        print(f" -> Synthesized candidate patch across {len(refactored_files)} file(s): {list(refactored_files.keys())}")
        if cost_info:
            print(f" -> Task Accounting ({cost_info['model']}): {cost_info['total_tokens']} tokens | Remediation Cost: {cost_info['total_cost_formatted']} (Human SRE Baseline: ${cost_info['roi_comparison']['manual_sre_triage_cost_usd']:.2f})")

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
        msg = "Sandbox Mandate Enforced: Patch failed after maximum retries. Escalating to human on-call."
        print(f"\n🚨 {msg}")
        raise RuntimeError(msg)

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

    # Respect read_only_source to guarantee external client repos are never modified
    is_read_only_src = getattr(manifest.project, "read_only_source", False)
    output_base_dir = (
        os.path.join(os.getcwd(), "artifacts", manifest.project.service_name)
        if is_read_only_src
        else base_dir
    )

    reports_dir = os.path.join(output_base_dir, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    post_mortem_file = os.path.join(reports_dir, f"POST_MORTEM_{incident_id.replace('-', '_')}.md")
    with open(post_mortem_file, "w", encoding="utf-8") as f:
        f.write(artifacts["post_mortem_markdown"])
    print(f" -> Saved Incident Post-Mortem Report: {post_mortem_file}")

    patches_dir = os.path.join(
        os.getcwd(),
        "artifacts",
        manifest.project.service_name,
        "patches",
        incident_id.replace("-", "_")
    )
    apply_verified_patch_to_repo(patches_dir, verified_synthesis["refactored_files"])
    print(f" -> Saved Verified Refactored Artifacts: {patches_dir}")

    # Compute Git repository root-relative POSIX file paths for atomic GitHub PR commit
    files_to_commit: Dict[str, str] = {}
    for rel_p, content in verified_synthesis["refactored_files"].items():
        abs_p = os.path.normpath(os.path.join(resolved_repo, rel_p))
        try:
            repo_rel = os.path.relpath(abs_p, base_dir).replace(os.sep, "/")
            if repo_rel.startswith(".."):
                repo_rel = rel_p.replace("\\", "/")
        except ValueError:
            repo_rel = rel_p.replace("\\", "/")
        files_to_commit[repo_rel] = content

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
        print(f" -> 🚀 Opened Live GitHub PR #{pr['pr_number']}: \"{artifacts['pr_title']}\"")
        print(f"    Target Repository: {pr['target_repo']}")
        print(f"    Remote Branch:     {pr['branch']}")
        print(f"    PR URL:            {pr['html_url']}")
    else:
        print(f" -> Opened Ready-to-Merge Pull Request #{pr['pr_number']}: \"{artifacts['pr_title']}\"")
        print(f"    Delivery Mode:     {pr['status']}")
        print(f"    Target Repository: {pr['target_repo']}")
        print(f"    PR URL:            {pr['html_url']}")

    if "--apply" in sys.argv and not is_read_only_src:
        apply_verified_patch_to_repo(resolved_repo, verified_synthesis["refactored_files"])
        print(" -> Applied verified patch to repository.")

    print("\n🎉 API Contract Drift Autonomous Remediation Complete!")
    print("=" * 78)

    return {
        "incident_id": incident_id,
        "trigger": incident_error_log,
        "discovery_mode": discovery_mode,
        "breaking_changes": breaking_changes,
        "diagnosis": verified_synthesis["diagnosis"],
        "unified_diff": unified_diff,
        "sandbox_result": verified_sandbox_result,
        "pr": pr,
        "post_mortem_markdown": artifacts["post_mortem_markdown"]
    }


if __name__ == "__main__":
    try:
        run_vector_b_remediation()
    except Exception as exc:
        print(f"❌ API Contract Drift Execution Aborted: {exc}")
        sys.exit(1)
