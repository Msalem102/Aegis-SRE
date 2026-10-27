"""
Native Modal Serverless Sandbox Runner.
Uses the official Modal SDK (modal.Sandbox.create) to provision ephemeral Linux micro-VMs
in the cloud for deterministic verification.
Falls back to isolated local tempfile sandbox if Modal credentials are not yet configured.
"""

from typing import Dict, Any, Optional
import os
import sys
import tempfile
import shutil
import subprocess

try:
    import modal
    MODAL_AVAILABLE = True
except ImportError:
    MODAL_AVAILABLE = False


class EphemeralSandbox:
    def __init__(self, repo_root: str, python_interpreter: Optional[str] = None):
        self.repo_root = os.path.abspath(repo_root)
        self.python_interpreter = python_interpreter or sys.executable
        self.use_modal = bool(
            MODAL_AVAILABLE and (os.getenv("MODAL_TOKEN_ID") or os.path.exists(os.path.expanduser("~/.modal.toml")))
        )

    def execute_test_suite(
        self,
        refactored_files: Dict[str, str],
        test_path: str = "tests/test_payment_client.py"
    ) -> Dict[str, Any]:
        """
        Executes verification in a cloud Modal Sandbox if credentials exist;
        otherwise executes in an isolated local temporary micro-environment.
        """
        if self.use_modal:
            return self._run_in_modal_cloud(refactored_files, test_path)
        return self._run_in_local_sandbox(refactored_files, test_path)

    def _run_in_modal_cloud(self, refactored_files: Dict[str, str], test_path: str) -> Dict[str, Any]:
        """Runs the test suite inside a real ephemeral Modal Cloud Sandbox."""
        try:
            app = modal.App.lookup("aegis-sre", create_if_missing=True)
            image = modal.Image.debian_slim().pip_install("pytest", "pydantic")

            # Prepare files dictionary for Modal mount
            mount_files = {}
            for root, _, files in os.walk(self.repo_root):
                for f in files:
                    if f.endswith((".py", ".json", ".toml")):
                        full_p = os.path.join(root, f)
                        rel_p = os.path.relpath(full_p, self.repo_root)
                        with open(full_p, "rb") as fp:
                            mount_files[f"/root/repo/{rel_p.replace(os.sep, '/')}"] = fp.read()

            # Overlay candidate patch
            for rel_p, content in refactored_files.items():
                mount_files[f"/root/repo/{rel_p.replace(os.sep, '/')}"] = content.encode("utf-8")

            # Create cloud sandbox
            sb = modal.Sandbox.create(
                "pytest", f"/root/repo/{test_path}", "-v",
                image=image,
                app=app,
                timeout=60
            )
            sb.wait()
            stdout = sb.stdout.read()
            stderr = sb.stderr.read()

            return {
                "runner_type": "MODAL_CLOUD_CONTAINER",
                "sandbox_id": sb.object_id,
                "passed": (sb.returncode == 0),
                "exit_code": sb.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "test_target": test_path,
                "applied_files": list(refactored_files.keys())
            }
        except Exception as e:
            print(f"[Aegis Sandbox] Modal cloud run encountered {e}. Reverting to local isolated runner.")
            return self._run_in_local_sandbox(refactored_files, test_path)

    def _run_in_local_sandbox(self, refactored_files: Dict[str, str], test_path: str) -> Dict[str, Any]:
        """Local isolated ephemeral sandbox fallback."""
        with tempfile.TemporaryDirectory(prefix="aegis_ephemeral_") as tmp_dir:
            dest_repo = os.path.join(tmp_dir, "repo")
            shutil.copytree(
                self.repo_root,
                dest_repo,
                ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache")
            )

            # Apply candidate files
            for rel_path, content in refactored_files.items():
                target_file = os.path.join(dest_repo, rel_path)
                os.makedirs(os.path.dirname(target_file), exist_ok=True)
                with open(target_file, "w", encoding="utf-8") as f:
                    f.write(content)

            test_file_path = os.path.join(dest_repo, test_path)
            cmd = [self.python_interpreter, "-m", "pytest", test_file_path, "-v", "--tb=short"]

            result = subprocess.run(
                cmd,
                cwd=dest_repo,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=os.environ.copy()
            )

            return {
                "runner_type": "LOCAL_EPHEMERAL_CONTAINER",
                "sandbox_id": os.path.basename(tmp_dir),
                "passed": (result.returncode == 0),
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "test_target": test_path,
                "applied_files": list(refactored_files.keys())
            }
