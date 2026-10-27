"""
Deterministic Verification Sandbox Engine.
Executes test suites against synthesized candidate patches in an isolated runner.
Enforces the Aegis SRE Sandbox Mandate: No patch is ever delivered to GitHub without exit code 0.
"""

from typing import Dict, Any, List, Optional
import os
import subprocess
import shutil
import tempfile
import sys


class SandboxTestRunner:
    def __init__(self, repo_root: str, python_interpreter: Optional[str] = None):
        self.repo_root = os.path.abspath(repo_root)
        self.python_interpreter = python_interpreter or sys.executable

    def verify_patch(
        self,
        refactored_files: Dict[str, str],
        test_path: str = "tests/test_payment_client.py"
    ) -> Dict[str, Any]:
        """
        Applies candidate files to an ephemeral copy of the repository
        and executes the test suite.
        Returns execution telemetry, logs, and pass/fail status.
        """
        # Create an ephemeral workspace
        with tempfile.TemporaryDirectory(prefix="aegis_sandbox_") as tmp_dir:
            # Copy client repo to temporary directory
            dest_repo = os.path.join(tmp_dir, "repo")
            shutil.copytree(
                self.repo_root,
                dest_repo,
                ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache")
            )

            # Apply candidate refactored files
            for rel_path, content in refactored_files.items():
                target_file = os.path.join(dest_repo, rel_path)
                os.makedirs(os.path.dirname(target_file), exist_ok=True)
                with open(target_file, "w", encoding="utf-8") as f:
                    f.write(content)

            # Run pytest inside the ephemeral sandbox
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

            passed = (result.returncode == 0)

            return {
                "sandbox_id": os.path.basename(tmp_dir),
                "passed": passed,
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "test_target": test_path,
                "applied_files": list(refactored_files.keys())
            }


def apply_verified_patch_to_repo(repo_root: str, refactored_files: Dict[str, str]) -> None:
    """Permanently commits the verified patch to the target repository only after sandbox approval."""
    for rel_path, content in refactored_files.items():
        target_file = os.path.join(repo_root, rel_path)
        os.makedirs(os.path.dirname(target_file), exist_ok=True)
        with open(target_file, "w", encoding="utf-8") as f:
            f.write(content)
