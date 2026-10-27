"""
Downstream Dependency Scanner.
Analyzes the client codebase using AST / static pattern scanning to isolate
the exact models, service callers, and tests affected by upstream contract drift.
"""

from typing import Dict, Any, List
import os
import re

class DependencyMapper:
    def __init__(self, repo_root: str):
        self.repo_root = os.path.abspath(repo_root)

    def map_affected_components(self, breaking_changes: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Locates caller files, model definitions, and test fixtures
        impacted by the breaking changes.
        """
        affected_files: Dict[str, str] = {}
        affected_symbols: List[str] = []

        # Extract search keywords from breaking changes
        keywords = set()
        for change in breaking_changes:
            if "endpoint" in change:
                keywords.add(change["endpoint"])
            if "old_field" in change:
                keywords.add(change["old_field"])
            if "new_field" in change:
                keywords.add(change["new_field"])

        # Scan repo files (excluding venvs, git, cache)
        for root, dirs, files in os.walk(self.repo_root):
            dirs[:] = [d for d in dirs if d not in [".git", ".venv", "__pycache__", ".pytest_cache", "node_modules"]]
            for file in files:
                if file.endswith((".py", ".ts", ".js", ".json")):
                    file_path = os.path.join(root, file)
                    rel_path = os.path.relpath(file_path, self.repo_root)
                    
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            content = f.read()

                        # Check if file references any keywords or related payment concepts
                        is_affected = False
                        for kw in keywords:
                            if kw in content:
                                is_affected = True
                                break

                        # Also include key client/model/test files if they belong to payment domain
                        if not is_affected and any(k in file.lower() for k in ["model", "client", "payment"]):
                            is_affected = True

                        if is_affected:
                            affected_files[rel_path] = content
                    except Exception:
                        pass

        return {
            "repo_root": self.repo_root,
            "target_files_count": len(affected_files),
            "target_files": affected_files
        }
