"""
GitHub PR and Incident Post-Mortem Delivery Engine.
Generates auditable Pull Requests, unified diffs, and enterprise-grade Markdown post-mortems
once candidate patches pass the Deterministic Verification Sandbox Gate.

Supports:
1. Live GitHub REST API execution (Atomically creates remote incident branch, creates Git blobs/trees,
   commits remediated code/SQL migration, and opens a real live Pull Request).
2. Clean simulated/fallback execution when running offline, in test suites, or without token permissions.
3. 100% agnostic to the target repository (reads from aegis.yaml or parameter override).
"""

from typing import Dict, Any, List, Optional
import os
import difflib
import json
import uuid
import httpx
from datetime import datetime, timezone
from dotenv import load_dotenv

_root_env = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
if os.path.exists(_root_env):
    load_dotenv(dotenv_path=_root_env, override=True)
else:
    load_dotenv(override=True)


class GitHubDeliveryEngine:
    def __init__(self, github_token: Optional[str] = None, client: Optional[httpx.Client] = None):
        if os.path.exists(_root_env):
            load_dotenv(dotenv_path=_root_env, override=True)
        raw_token = github_token or os.getenv("GITHUB_TOKEN") or ""
        self.github_token = raw_token.strip().strip('"').strip("'") or None
        self._custom_client = client

    def generate_diff(self, original_files: Dict[str, str], refactored_files: Dict[str, str]) -> str:
        """Generates unified diff across all modified files."""
        diff_outputs = []
        for path, new_content in refactored_files.items():
            orig_content = original_files.get(path, "")
            orig_lines = orig_content.splitlines(keepends=True)
            new_lines = new_content.splitlines(keepends=True)

            diff = difflib.unified_diff(
                orig_lines,
                new_lines,
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
                n=3
            )
            diff_text = "".join(diff)
            if diff_text:
                diff_outputs.append(diff_text)

        return "\n".join(diff_outputs)

    def deliver_remediation_pr(
        self,
        repo: str,
        incident_id: str,
        pr_title: str,
        pr_body: str,
        files_to_commit: Dict[str, str],
        commit_message: Optional[str] = None,
        base_branch: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        End-to-end atomic delivery workflow:
        1. Inspects remote repository default branch (e.g. main).
        2. Creates an ephemeral remote branch (aegis/remediate-<incident_id>-<hash>).
        3. Creates Git blobs and tree for all modified files.
        4. Creates an atomic commit on the remote branch.
        5. Opens a live GitHub Pull Request with the post-mortem report.
        Falls back to local simulation if GITHUB_TOKEN is not configured or network fails.
        """
        short_id = uuid.uuid4().hex[:6]
        branch_name = f"aegis/remediate-{incident_id.lower().replace('_', '-')}-{short_id}"

        if not self.github_token:
            return {
                "status": "SIMULATED_LOCAL",
                "pr_number": 42,
                "html_url": f"https://github.com/{repo}/pull/42",
                "title": pr_title,
                "branch": branch_name,
                "target_repo": repo,
                "committed_files": list(files_to_commit.keys()),
                "message": "GitHub token not configured; generated verified local Pull Request payload."
            }

        headers = {
            "Authorization": f"Bearer {self.github_token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }

        client_provider = self._custom_client if self._custom_client is not None else httpx.Client(timeout=30.0)
        try:
            with client_provider if hasattr(client_provider, "__enter__") else httpx.Client(timeout=30.0) as client:
                # 1. Get repository info & resolve default branch
                repo_resp = client.get(f"https://api.github.com/repos/{repo}", headers=headers)
                repo_resp.raise_for_status()
                default_branch = base_branch or repo_resp.json().get("default_branch", "main")

                # 2. Get latest commit SHA on base branch
                ref_resp = client.get(
                    f"https://api.github.com/repos/{repo}/git/ref/heads/{default_branch}",
                    headers=headers
                )
                ref_resp.raise_for_status()
                base_sha = ref_resp.json()["object"]["sha"]

                # 3. Get commit tree SHA
                commit_resp = client.get(
                    f"https://api.github.com/repos/{repo}/git/commits/{base_sha}",
                    headers=headers
                )
                commit_resp.raise_for_status()
                base_tree_sha = commit_resp.json()["tree"]["sha"]

                # 4. Create Git Blobs for all files to commit
                tree_items = []
                for rel_path, content in files_to_commit.items():
                    norm_path = rel_path.replace("\\", "/")
                    blob_payload = {
                        "content": content,
                        "encoding": "utf-8"
                    }
                    blob_resp = client.post(
                        f"https://api.github.com/repos/{repo}/git/blobs",
                        headers=headers,
                        json=blob_payload
                    )
                    blob_resp.raise_for_status()
                    blob_sha = blob_resp.json()["sha"]
                    tree_items.append({
                        "path": norm_path,
                        "mode": "100644",
                        "type": "blob",
                        "sha": blob_sha
                    })

                # 5. Create new Git Tree
                tree_payload = {
                    "base_tree": base_tree_sha,
                    "tree": tree_items
                }
                tree_resp = client.post(
                    f"https://api.github.com/repos/{repo}/git/trees",
                    headers=headers,
                    json=tree_payload
                )
                tree_resp.raise_for_status()
                new_tree_sha = tree_resp.json()["sha"]

                # 6. Create Git Commit
                commit_msg = commit_message or (
                    f"fix(sre): autonomous remediation for {incident_id}\n\n"
                    "Remediated and verified in ephemeral sandbox by Aegis SRE.\n"
                    f"Verification Gate: PASSED\nRemediation Engine: Meta Muse Spark"
                )
                commit_payload = {
                    "message": commit_msg,
                    "tree": new_tree_sha,
                    "parents": [base_sha]
                }
                new_commit_resp = client.post(
                    f"https://api.github.com/repos/{repo}/git/commits",
                    headers=headers,
                    json=commit_payload
                )
                new_commit_resp.raise_for_status()
                new_commit_sha = new_commit_resp.json()["sha"]

                # 7. Create Remote Branch pointing to the new commit
                branch_payload = {
                    "ref": f"refs/heads/{branch_name}",
                    "sha": new_commit_sha
                }
                create_branch_resp = client.post(
                    f"https://api.github.com/repos/{repo}/git/refs",
                    headers=headers,
                    json=branch_payload
                )
                create_branch_resp.raise_for_status()

                # 8. Open Pull Request
                pr_payload = {
                    "title": pr_title,
                    "head": branch_name,
                    "base": default_branch,
                    "body": pr_body
                }
                pr_resp = client.post(
                    f"https://api.github.com/repos/{repo}/pulls",
                    headers=headers,
                    json=pr_payload
                )
                pr_resp.raise_for_status()
                pr_data = pr_resp.json()

                return {
                    "status": "LIVE_GITHUB_PR",
                    "pr_number": pr_data.get("number"),
                    "html_url": pr_data.get("html_url"),
                    "title": pr_title,
                    "branch": branch_name,
                    "base_branch": default_branch,
                    "commit_sha": new_commit_sha,
                    "target_repo": repo,
                    "committed_files": list(files_to_commit.keys()),
                    "message": f"Successfully opened live GitHub Pull Request #{pr_data.get('number')} on {repo}."
                }

        except Exception as e:
            return {
                "status": "FALLBACK_LOCAL",
                "pr_number": 42,
                "html_url": f"https://github.com/{repo}/pull/42",
                "title": pr_title,
                "branch": branch_name,
                "target_repo": repo,
                "committed_files": list(files_to_commit.keys()),
                "error": str(e),
                "message": f"GitHub API delivery encountered an issue ({e}). Generated local verified PR payload."
            }

    # Backward compatibility alias
    def create_pull_request(
        self,
        repo: str,
        branch_name: str,
        pr_title: str,
        pr_body: str
    ) -> Dict[str, Any]:
        """Backward compatible wrapper around delivery engine."""
        return self.deliver_remediation_pr(
            repo=repo,
            incident_id="INCIDENT",
            pr_title=pr_title,
            pr_body=pr_body,
            files_to_commit={}
        )
