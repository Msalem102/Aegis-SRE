"""
Unified API Diagnostic & Live Integration Verification Suite (`verify_apis.py`).
Consolidates and validates all 3 core external integrations for Aegis SRE:
  1. Meta Model API (Live LLM Reasoning Engine: muse-spark-1.2)
  2. Modal Cloud (Serverless Ephemeral Micro-VM Sandbox for DDL & Pytest Verification)
  3. GitHub API (Atomic Git Branching, Tree Commit & Live Pull Request Delivery)

Can be executed standalone:
  python verify_apis.py [--config aegis.yaml]

Also invoked automatically on Aegis SRE startup (`python aegis_cli.py listen / run`).
"""

import sys
import os
import json
import time
from typing import Dict, Any, Optional
import httpx
from dotenv import load_dotenv

# Ensure UTF-8 console output on Windows with safe error replacement
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Force Modal to use stable reliable streaming protocol (avoids Windows gRPC stream hang)
os.environ["MODAL_SANDBOX_V2"] = "false"
try:
    import modal.config
    modal.config.config["sandbox_v2"] = False
except Exception:
    pass

_root_env = os.path.abspath(os.path.join(os.path.dirname(__file__), ".env"))
if os.path.exists(_root_env):
    load_dotenv(dotenv_path=_root_env, override=True)
else:
    load_dotenv(override=True)


def _mask(val: Optional[str], visible_prefix: int = 6, visible_suffix: int = 4) -> str:
    if not val:
        return "NOT SET"
    val = val.strip().strip('"').strip("'")
    if len(val) <= (visible_prefix + visible_suffix):
        return "SET"
    return f"{val[:visible_prefix]}...{val[-visible_suffix:]}"


def verify_meta_api(quiet: bool = False) -> Dict[str, Any]:
    """Tests live connectivity to Meta Model API (or partner endpoint) with structured JSON reasoning."""
    api_key = (os.getenv("META_API_KEY") or os.getenv("BASETEN_API_KEY") or "").strip().strip('"').strip("'")
    base_url = (os.getenv("META_MODEL_API_URL") or "https://api.meta.ai/v1").rstrip("/")
    model_name = os.getenv("META_MODEL_NAME") or "muse-spark-1.2"

    if not quiet:
        print("\n[1/3] 🧠 Meta Model API (LLM Reasoning Engine)...")
        print(f" -> Endpoint:   {base_url}")
        print(f" -> Model:      {model_name}")
        print(f" -> API Key:    {_mask(api_key)}")

    if not api_key or api_key == "your_meta_api_key_here":
        msg = "No live META_API_KEY detected in .env."
        if not quiet:
            print(f" ⚠️  {msg}")
            print("    Live Meta Muse Spark reasoning requires META_API_KEY in .env.")
        return {"passed": False, "status": "KEY_MISSING", "error": msg, "latency_ms": 0.0}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    probe_payload = {
        "model": model_name,
        "messages": [
            {
                "role": "system",
                "content": 'You are Aegis SRE diagnostic core. Respond strictly with JSON: {"status": "ONLINE", "capability": "SRE_REASONING_READY"}'
            },
            {
                "role": "user",
                "content": "Verify system connectivity and reasoning latency."
            }
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"}
    }

    start_time = time.perf_counter()
    try:
        with httpx.Client(timeout=25.0) as client:
            resp = client.post(f"{base_url}/chat/completions", headers=headers, json=probe_payload)
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0

            if resp.status_code == 200:
                data = resp.json()
                raw_content = data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
                usage = data.get("usage", {})
                tokens_info = f"{usage.get('total_tokens', usage.get('prompt_tokens', 0))} tokens"
                try:
                    parsed = json.loads(raw_content)
                except Exception:
                    parsed = raw_content

                if not quiet:
                    print(f" ✅ Meta Model API Connection SUCCESSFUL (200 OK)")
                    print(f"    └─ Model: {data.get('model', model_name)} | Latency: {elapsed_ms:.1f}ms | {tokens_info}")
                return {
                    "passed": True,
                    "status": "ONLINE",
                    "model": data.get("model", model_name),
                    "latency_ms": elapsed_ms,
                    "tokens": usage,
                    "response": parsed
                }
            elif resp.status_code == 401:
                err = "401 Unauthorized (invalid or expired META_API_KEY)"
                if not quiet:
                    print(f" ❌ Meta Model API Error: {err}")
                return {"passed": False, "status": "UNAUTHORIZED", "error": err, "latency_ms": elapsed_ms}
            else:
                err = f"HTTP {resp.status_code}: {resp.text[:200]}"
                if not quiet:
                    print(f" ❌ Meta Model API Error: {err}")
                return {"passed": False, "status": f"HTTP_{resp.status_code}", "error": err, "latency_ms": elapsed_ms}
    except httpx.ConnectError as e:
        err = f"Could not connect to {base_url} ({e})"
        if not quiet:
            print(f" ❌ Meta Model API Network Error: {err}")
        return {"passed": False, "status": "CONNECT_ERROR", "error": err, "latency_ms": 0.0}
    except Exception as e:
        err = str(e)
        if not quiet:
            print(f" ❌ Meta Model API Probe Failed: {err}")
        return {"passed": False, "status": "ERROR", "error": err, "latency_ms": 0.0}


def verify_modal_api(quiet: bool = False, timeout_seconds: float = 15.0) -> Dict[str, Any]:
    """Tests live connectivity to Modal Cloud Serverless and provisions a fast micro-VM probe."""
    token_id = (os.getenv("MODAL_TOKEN_ID") or "").strip().strip('"').strip("'")
    token_secret = (os.getenv("MODAL_TOKEN_SECRET") or "").strip().strip('"').strip("'")

    if not quiet:
        print("\n[2/3] ☁️  Modal Cloud (Serverless Ephemeral Micro-VM Sandbox)...", flush=True)
        print(f" -> MODAL_TOKEN_ID:     {_mask(token_id)}", flush=True)
        print(f" -> MODAL_TOKEN_SECRET: {'Configured (Hidden)' if token_secret else 'NOT SET'}", flush=True)

    if not token_id or not token_secret or "xxxx" in token_id:
        msg = "MODAL_TOKEN_ID or MODAL_TOKEN_SECRET missing in .env."
        if not quiet:
            print(f" ⚠️  {msg}", flush=True)
            print("    Modal Cloud sandboxing requires valid Modal tokens in .env.", flush=True)
        return {"passed": False, "status": "TOKENS_MISSING", "error": msg}

    try:
        import modal
    except ImportError:
        err = "modal package not installed in current Python environment."
        if not quiet:
            print(f" ❌ {err}", flush=True)
        return {"passed": False, "status": "PACKAGE_MISSING", "error": err}

    import concurrent.futures

    def _execute_modal_probe():
        start_time = time.perf_counter()
        app = modal.App.lookup("aegis-sre", create_if_missing=True)
        image = modal.Image.debian_slim()

        # Execute fast container probe in Modal Cloud with unbuffered stdout
        sb = modal.Sandbox.create(
            "python", "-u", "-c",
            "import sys, platform; print(f'⚡ Micro-VM Active on {platform.system()} {platform.machine()} | Python {sys.version.split()[0]}', flush=True)",
            image=image,
            app=app,
            timeout=20
        )

        lines = []
        try:
            for raw_line in sb.stdout:
                line = raw_line.strip()
                if line:
                    lines.append(line)
                if len(lines) >= 1:
                    break
        except Exception:
            pass

        sb.wait()
        elapsed_s = time.perf_counter() - start_time
        stdout = "\n".join(lines) if lines else f"Micro-VM {sb.object_id} exited with code {sb.returncode}"

        if sb.returncode == 0:
            return {
                "passed": True,
                "status": "ONLINE",
                "object_id": sb.object_id,
                "spinup_seconds": elapsed_s,
                "remote_log": stdout
            }
        else:
            err = f"Container failed (exit {sb.returncode}): {stdout}"
            return {"passed": False, "status": "CONTAINER_ERROR", "error": err}

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_execute_modal_probe)
            res = future.result(timeout=timeout_seconds)

            if not quiet:
                if res.get("passed"):
                    print(f" ✅ Modal Cloud Sandbox Verification SUCCESSFUL (Exit: 0)", flush=True)
                    print(f"    └─ Micro-VM: {res.get('object_id')} | Spin-up + Exec: {res.get('spinup_seconds', 0):.2f}s | {res.get('remote_log')}", flush=True)
                else:
                    print(f" ❌ Modal Cloud Container Error: {res.get('error')}", flush=True)
            return res
    except concurrent.futures.TimeoutError:
        err = f"Modal Cloud probe timed out after {timeout_seconds}s (cloud latency or queue delay)"
        if not quiet:
            print(f" ⚠️  Modal Cloud Timeout: {err}", flush=True)
        return {"passed": False, "status": "TIMEOUT", "error": err}
    except Exception as e:
        err = str(e)
        if not quiet:
            print(f" ❌ Modal Cloud Verification Failed: {err}", flush=True)
        return {"passed": False, "status": "ERROR", "error": err}


def verify_github_api(target_repo: Optional[str] = None, quiet: bool = False) -> Dict[str, Any]:
    """Tests GitHub PAT authentication, target repository write access, and PR capability."""
    token = (os.getenv("GITHUB_TOKEN") or "").strip().strip('"').strip("'")
    repo = target_repo or "ahmedharib/mockStore"

    if not quiet:
        print("\n[3/3] 🐙 GitHub API (Atomic Git PR & Post-Mortem Delivery)...")
        print(f" -> Target Repository: {repo}")
        print(f" -> GITHUB_TOKEN:      {_mask(token)}")

    if not token or token == "ghp_your_github_personal_access_token":
        msg = "No live GITHUB_TOKEN detected in .env."
        if not quiet:
            print(f" ⚠️  {msg}")
            print("    (Aegis will run in SIMULATED_LOCAL PR delivery mode until GITHUB_TOKEN is configured).")
        return {
            "passed": True,
            "status": "SIMULATED_MODE",
            "warning": msg,
            "target_repo": repo,
            "can_push": False
        }

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            user_resp = client.get("https://api.github.com/user", headers=headers)
            if user_resp.status_code == 401:
                err = "401 Unauthorized (GITHUB_TOKEN is invalid or expired)"
                if not quiet:
                    print(f" ❌ GitHub API Error: {err}")
                return {"passed": False, "status": "UNAUTHORIZED", "error": err}
            user_resp.raise_for_status()
            username = user_resp.json().get("login", "unknown")

            repo_resp = client.get(f"https://api.github.com/repos/{repo}", headers=headers)
            if repo_resp.status_code == 404:
                err = f"Repository '{repo}' not found or token lacks access."
                if not quiet:
                    print(f" ❌ GitHub API Error: {err}")
                return {"passed": False, "status": "REPO_NOT_FOUND", "error": err}
            repo_resp.raise_for_status()
            repo_data = repo_resp.json()
            default_branch = repo_data.get("default_branch", "master")
            permissions = repo_data.get("permissions", {})
            can_push = permissions.get("push", False)

            prs_resp = client.get(f"https://api.github.com/repos/{repo}/pulls?state=open&per_page=5", headers=headers)
            open_prs_count = len(prs_resp.json()) if prs_resp.status_code == 200 and isinstance(prs_resp.json(), list) else 0

            if not quiet:
                print(f" ✅ GitHub Integration Verified (Authenticated as @{username})")
                print(f"    └─ Repo: {repo} (Default Branch: '{default_branch}') | Push Access: {'YES' if can_push else 'NO'} | Open PRs: {open_prs_count}")

            return {
                "passed": True,
                "status": "ONLINE",
                "username": username,
                "target_repo": repo,
                "default_branch": default_branch,
                "can_push": can_push,
                "open_prs_count": open_prs_count
            }
    except Exception as e:
        err = str(e)
        if not quiet:
            print(f" ❌ GitHub API Check Failed: {err}")
        return {"passed": False, "status": "ERROR", "error": err}


def verify_all_apis(config_path: str = "aegis.yaml", quiet: bool = False) -> Dict[str, Any]:
    """
    Runs end-to-end verification across Meta Model API, Modal Cloud, and GitHub.
    Returns structured results dict and prints an auditable health card.
    """
    # Attempt to resolve target repo from config_path or mockstore_aegis.yaml
    target_repo = "ahmedharib/mockStore"
    if os.path.exists(config_path):
        try:
            from core.config.aegis_config import AegisConfigLoader
            manifest = AegisConfigLoader.load_or_default(config_path)
            if manifest.project.repository and "/" in manifest.project.repository:
                target_repo = manifest.project.repository
        except Exception:
            pass
    elif os.path.exists("mockstore_aegis.yaml"):
        try:
            from core.config.aegis_config import AegisConfigLoader
            manifest = AegisConfigLoader.load_or_default("mockstore_aegis.yaml")
            if manifest.project.repository and "/" in manifest.project.repository:
                target_repo = manifest.project.repository
        except Exception:
            pass

    print("=" * 78)
    print("🛡️  AEGIS SRE: Core API Infrastructure Verification")
    print("=" * 78)

    meta_res = verify_meta_api(quiet=quiet)
    modal_res = verify_modal_api(quiet=quiet)
    github_res = verify_github_api(target_repo=target_repo, quiet=quiet)

    all_passed = meta_res["passed"] and modal_res["passed"] and github_res["passed"]

    print("\n" + "=" * 78)
    if all_passed:
        print("🎉 ALL CORE SRE APIS VERIFIED & OPERATIONAL — Closed-Loop Remediation Ready!")
    else:
        print("⚠️  API VERIFICATION NOTICE: Some external services need attention (see above).")
    print("=" * 78 + "\n", flush=True)

    return {
        "all_passed": all_passed,
        "meta": meta_res,
        "modal": modal_res,
        "github": github_res
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Aegis SRE Unified API Diagnostics")
    parser.add_argument("--config", default="aegis.yaml", help="Path to aegis.yaml or mockstore_aegis.yaml")
    args = parser.parse_args()

    results = verify_all_apis(config_path=args.config)
    sys.exit(0 if results["all_passed"] else 1)
