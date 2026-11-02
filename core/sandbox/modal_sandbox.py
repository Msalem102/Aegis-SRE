"""
Native Modal Serverless Sandbox Runner.
Uses the official Modal SDK (modal.Sandbox.create) to provision ephemeral Linux micro-VMs
in the cloud for deterministic verification.
Dynamically inspects the target project's `requirements.txt` / `pyproject.toml` so external
FastAPI, Pydantic, SQLAlchemy, or PostgreSQL repositories execute inside Modal without missing dependencies.
Zero offline/local fallback.
"""

from typing import Dict, Any, Optional, List, Set
import os
import re
import sys
import base64
import json
import time
from dotenv import load_dotenv

load_dotenv()

try:
    import modal
    import modal.config
    os.environ["MODAL_SANDBOX_V2"] = "false"
    try:
        modal.config.config["sandbox_v2"] = False
    except Exception:
        pass
    MODAL_AVAILABLE = True
except ImportError:
    MODAL_AVAILABLE = False


import zlib

MOUNTABLE_EXTENSIONS = (
    ".py", ".json", ".toml", ".yaml", ".yml", ".txt", ".ini", ".cfg"
)
IGNORED_SANDBOX_DIRS = {".git", ".venv", "venv", "env", "__pycache__", ".pytest_cache", "node_modules", ".mypy_cache"}


class EphemeralSandbox:
    def __init__(
        self,
        repo_root: str,
        python_interpreter: Optional[str] = None,
        app_name: str = "aegis-sre",
        timeout_seconds: int = 60,
        provider: Optional[str] = None
    ):
        self.repo_root = os.path.abspath(repo_root)
        self.python_interpreter = python_interpreter or sys.executable
        self.app_name = app_name
        self.timeout_seconds = timeout_seconds
        self.provider = (provider or "modal").lower()
        self.use_modal = bool(self.provider == "modal")

    def _discover_project_dependencies(self) -> List[str]:
        """
        Reads the target repository's `requirements.txt` or `pyproject.toml` to dynamically
        install required packages inside the ephemeral Modal Cloud container.
        """
        packages: List[str] = ["pytest", "pydantic", "httpx"]
        seen_names: Set[str] = {"pytest", "pydantic", "httpx"}

        req_path = os.path.join(self.repo_root, "requirements.txt")
        if os.path.isfile(req_path):
            try:
                with open(req_path, "r", encoding="utf-8") as rf:
                    for raw_line in rf:
                        line = raw_line.split("#", 1)[0].strip()
                        if not line or line.startswith(("-", "git+", "http://", "https://", ".", "/", "\\")):
                            continue
                        pkg_name = re.split(r"[<>=!~\[\s]", line, maxsplit=1)[0].strip().lower()
                        if not pkg_name or pkg_name in {"modal"}:
                            continue
                        if pkg_name == "psycopg2":
                            line = re.sub(r"^psycopg2\b", "psycopg2-binary", line, flags=re.I)
                            pkg_name = "psycopg2-binary"
                        if pkg_name not in seen_names:
                            seen_names.add(pkg_name)
                            packages.append(line)
            except Exception:
                pass

        pyproject_path = os.path.join(self.repo_root, "pyproject.toml")
        if len(packages) <= 3 and os.path.isfile(pyproject_path):
            try:
                import tomllib
                with open(pyproject_path, "rb") as pf:
                    pdata = tomllib.load(pf)
                deps = pdata.get("project", {}).get("dependencies", [])
                for dep in deps:
                    line = str(dep).strip()
                    pkg_name = re.split(r"[<>=!~\[\s;]", line, maxsplit=1)[0].strip().lower()
                    if not pkg_name or pkg_name in {"modal"}:
                        continue
                    if pkg_name == "psycopg2":
                        line = "psycopg2-binary"
                        pkg_name = "psycopg2-binary"
                    if pkg_name not in seen_names:
                        seen_names.add(pkg_name)
                        packages.append(line)
            except Exception:
                pass

        return packages

    def execute_test_suite(
        self,
        refactored_files: Dict[str, str],
        test_path: str = "tests"
    ) -> Dict[str, Any]:
        """
        Executes verification strictly in a cloud Modal Sandbox.
        Zero offline fallback: Modal credentials and SDK are strictly required.
        """
        if self.provider == "modal":
            if not MODAL_AVAILABLE:
                raise RuntimeError(
                    "Modal SDK is not installed ('pip install modal'). Offline fallback is permanently disabled."
                )
            has_modal_auth = bool(
                os.getenv("MODAL_IS_REMOTE") == "1"
                or os.getenv("MODAL_TOKEN_ID")
                or os.path.exists(os.path.expanduser("~/.modal.toml"))
            )
            if not has_modal_auth:
                raise RuntimeError(
                    "Modal Cloud Sandbox is configured (provider: 'modal'), but Modal credentials were not found. "
                    "Offline fallback is permanently disabled. Please set MODAL_TOKEN_ID and MODAL_TOKEN_SECRET in .env or run 'modal setup'."
                )
            return self._run_in_modal_cloud(refactored_files, test_path)
        raise RuntimeError(
            f"Unsupported sandbox provider '{self.provider}'. "
            "Aegis SRE requires live cloud execution (provider: 'modal'). Offline/local fallback is permanently disabled."
        )

    def _run_in_modal_cloud(self, refactored_files: Dict[str, str], test_path: str) -> Dict[str, Any]:
        """Runs the test suite inside a real ephemeral Modal Cloud Sandbox with mounted files (no offline fallback)."""
        start_time = time.perf_counter()
        deps = self._discover_project_dependencies()
        print(f"   ☁️ [Modal Cloud Sandbox] Provisioning ephemeral Linux container (App: {self.app_name}, Deps: {len(deps)} pkgs)...")
        app = modal.App.lookup(self.app_name, create_if_missing=True)
        image = modal.Image.debian_slim().pip_install(*deps)

        # Collect repository files (strictly excluding .env secrets and large binaries)
        mount_files = {}
        for root, dirs, files in os.walk(self.repo_root):
            dirs[:] = [d for d in dirs if d not in IGNORED_SANDBOX_DIRS]
            for f in files:
                if f == ".env" or f.startswith(".env."):
                    continue
                if f.endswith(MOUNTABLE_EXTENSIONS):
                    full_p = os.path.join(root, f)
                    try:
                        if os.path.getsize(full_p) > 512_000:
                            continue
                        rel_p = os.path.relpath(full_p, self.repo_root).replace(os.sep, "/")
                        with open(full_p, "rb") as fp:
                            mount_files[rel_p] = base64.b64encode(fp.read()).decode("ascii")
                    except Exception:
                        pass

        for rel_p, content in refactored_files.items():
            norm_p = rel_p.replace("\\", "/").replace(os.sep, "/")
            mount_files[norm_p] = base64.b64encode(content.encode("utf-8")).decode("ascii")

        norm_test_path = test_path.replace("\\", "/").replace(os.sep, "/")
        compressed_payload = base64.b64encode(
            zlib.compress(json.dumps(mount_files).encode("utf-8"), level=9)
        ).decode("ascii")
        bootstrap_code = (
            "import os, json, base64, zlib, subprocess, sys; "
            f"files = json.loads(zlib.decompress(base64.b64decode('{compressed_payload}')).decode('utf-8')); "
            "os.makedirs('/tmp/repo', exist_ok=True); "
            "[ (os.makedirs(os.path.dirname('/tmp/repo/' + k) or '/tmp/repo', exist_ok=True), open('/tmp/repo/' + k, 'wb').write(base64.b64decode(v))) for k, v in files.items() ]; "
            "env = os.environ.copy(); env['PYTHONPATH'] = '/tmp/repo'; "
            f"res = subprocess.run([sys.executable, '-m', 'pytest', '/tmp/repo/{norm_test_path}', '-v', '--tb=short'], cwd='/tmp/repo', env=env); "
            "sys.exit(res.returncode)"
        )

        sb = modal.Sandbox.create(
            "python", "-u", "-c", bootstrap_code,
            image=image,
            app=app,
            timeout=self.timeout_seconds
        )

        dash_url = None
        try:
            dash_url = sb.get_dashboard_url()
        except Exception:
            pass

        print(f"   ☁️ [Modal Cloud Sandbox] Container Active: {sb.object_id} (Running remote pytest...)")
        if dash_url:
            print(f"   🔗 Live Modal Dashboard: {dash_url}")

        server_reader = None
        try:
            from modal.io_streams import StreamReader, _StreamReaderThroughServerParams
            from modal_proto import api_pb2

            modal_client = getattr(sb, "_client", None)
            if modal_client is None and hasattr(app, "_client"):
                modal_client = getattr(app, "_client", None)

            if modal_client:
                server_reader = StreamReader(
                    _StreamReaderThroughServerParams(
                        file_descriptor=api_pb2.FILE_DESCRIPTOR_STDOUT,
                        object_id=sb.object_id,
                        client=modal_client,
                    ),
                    by_line=True,
                )
        except Exception:
            pass

        stream_src = server_reader if server_reader is not None else sb.stdout

        stdout_lines = []
        try:
            for raw_line in stream_src:
                line = raw_line.strip()
                if line:
                    print(f"      {line}", flush=True)
                    stdout_lines.append(line)
        except Exception:
            pass

        try:
            sb.wait()
        except Exception:
            pass

        elapsed_seconds = round(time.perf_counter() - start_time, 2)
        stdout = "\n".join(stdout_lines)
        if not stdout:
            try:
                stdout = sb.stdout.read()
            except Exception:
                stdout = ""

        stderr = ""
        try:
            stderr = sb.stderr.read()
        except Exception:
            stderr = ""

        returncode = 0
        try:
            returncode = sb.returncode
        except Exception:
            pass

        print(f"   ☁️ [Modal Cloud Sandbox] Finished in {elapsed_seconds}s (Exit Code {returncode})")

        return {
            "runner_type": "MODAL_CLOUD_CONTAINER",
            "sandbox_id": sb.object_id,
            "passed": (returncode == 0),
            "exit_code": returncode,
            "duration_seconds": elapsed_seconds,
            "installed_dependencies": deps,
            "stdout": stdout,
            "stderr": stderr,
            "test_target": test_path,
            "applied_files": list(refactored_files.keys())
        }


def apply_verified_patch_to_repo(repo_root: str, refactored_files: Dict[str, str]) -> None:
    """Permanently commits the verified patch to the target repository only after sandbox approval."""
    for rel_path, content in refactored_files.items():
        norm_rel = rel_path.replace("/", os.sep).replace("\\", os.sep)
        target_file = os.path.join(repo_root, norm_rel)
        os.makedirs(os.path.dirname(target_file), exist_ok=True)
        with open(target_file, "w", encoding="utf-8") as f:
            f.write(content)
