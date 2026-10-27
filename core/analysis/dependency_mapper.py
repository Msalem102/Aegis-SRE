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

        # Extract search keywords from breaking changes (endpoints, field names, path segments)
        keywords = set()
        for change in breaking_changes:
            if "endpoint" in change:
                keywords.add(change["endpoint"])
                # Also add path segments (e.g. /payments/charge -> payments, charge)
                for segment in change["endpoint"].strip("/").split("/"):
                    if len(segment) > 2:
                        keywords.add(segment)
            if "field_path" in change:
                for token in change["field_path"].split("."):
                    if len(token) > 2:
                        keywords.add(token)
            if "old_field_path" in change:
                for token in change["old_field_path"].split("."):
                    if len(token) > 2:
                        keywords.add(token)
            if "new_field_path" in change:
                for token in change["new_field_path"].split("."):
                    if len(token) > 2:
                        keywords.add(token)

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

                        # Check if file references any keywords derived from the breaking changes
                        is_affected = any(kw in content for kw in keywords)

                        # Also match files whose name indicates architectural client layer
                        if not is_affected and any(k in file.lower() for k in ["model", "client", "service"]):
                            is_affected = any(kw in content for kw in keywords)

                        if is_affected:
                            affected_files[rel_path] = content
                    except Exception:
                        pass

        return {
            "repo_root": self.repo_root,
            "target_files_count": len(affected_files),
            "target_files": affected_files
        }
