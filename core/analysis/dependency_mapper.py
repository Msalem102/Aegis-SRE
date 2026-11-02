"""
Downstream Dependency Scanner (AST & Runtime Traceback Aware).
Analyzes the client codebase using Python AST imports/calls, OpenAPI diff keywords,
and runtime stack traces / HTTP 4xx error payloads to isolate impacted models,
service callers, and read-only test context — even in Zero-Spec (Pure Error-Driven) mode.
"""

from typing import Dict, Any, List, Optional, Set
import ast
import os
import re


IGNORED_DIRS = {".git", ".venv", "venv", "env", "__pycache__", ".pytest_cache", "node_modules", "migrations", "reports"}
STOP_TOKENS = {
    "error", "failed", "value", "assert", "assertionerror", "valueerror", "typeerror",
    "true", "false", "none", "null", "json", "http", "https", "post", "get", "put",
    "delete", "patch", "status", "code", "detail", "message", "input", "type", "missing",
    "required", "field", "body", "string", "integer", "number", "object", "test", "tests"
}


class DependencyMapper:
    def __init__(
        self,
        repo_root: str,
        code_root: Optional[str] = None,
        test_target: str = "tests",
        isolated_client_modules: Optional[List[str]] = None
    ):
        self.repo_root = os.path.abspath(repo_root)
        self.code_root = code_root
        self.test_target = test_target
        self.isolated_client_modules = isolated_client_modules or []

    def map_affected_components(
        self,
        breaking_changes: List[Dict[str, Any]],
        incident_error_log: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Locates caller files, model definitions, and test files impacted by upstream contract drift
        or runtime HTTP 4xx/5xx failures.
        """
        affected_files: Dict[str, str] = {}
        keywords: Set[str] = set()
        traceback_rel_paths: Set[str] = set()

        # 1. Extract search keywords from OpenAPI diff / target contract summary
        for change in breaking_changes:
            ep = change.get("endpoint") or change.get("path")
            if ep:
                keywords.add(ep)
                for segment in ep.strip("/").split("/"):
                    if len(segment) > 2 and not segment.startswith("{"):
                        keywords.add(segment)

            for key in ("field_path", "old_field_path", "new_field_path"):
                if key in change and change[key]:
                    for token in str(change[key]).split("."):
                        if len(token) > 2 and token != "(root)":
                            keywords.add(token)

            for list_key in ("required_fields", "required_leaf_paths"):
                for item in change.get(list_key, []) or []:
                    for token in str(item).split("."):
                        if len(token) > 2:
                            keywords.add(token)

        # 2. Extract file paths, URLs, and quoted field identifiers from runtime error / traceback
        if incident_error_log:
            combined_err = "\n".join([
                str(incident_error_log.get("error_message", "")),
                str(incident_error_log.get("raw_traceback", "")),
                str(incident_error_log.get("endpoint", "")),
                str(incident_error_log.get("exception_stack", ""))
            ])

            # Direct Python file references in traceback (e.g. "app/payment_client.py:42:")
            for match in re.findall(r"([A-Za-z0-9_./\\-]+\.py)", combined_err):
                cleaned = match.replace("\\", "/").lstrip("./")
                candidate_abs = os.path.normpath(os.path.join(self.repo_root, cleaned))
                if os.path.isfile(candidate_abs):
                    rel = os.path.relpath(candidate_abs, self.repo_root).replace(os.sep, "/")
                    traceback_rel_paths.add(rel)
                else:
                    # Try matching basename inside repo
                    base = os.path.basename(cleaned)
                    if base and base != "pytest.py":
                        traceback_rel_paths.add(base)

            # URL path segments (e.g. /v1/charges, /api/checkout)
            for path_match in re.findall(r"(/[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)+)", combined_err):
                if not path_match.endswith(".py"):
                    keywords.add(path_match)
                    for seg in path_match.strip("/").split("/"):
                        if len(seg) > 3 and seg.lower() not in STOP_TOKENS:
                            keywords.add(seg)

            # Quoted identifiers (field names in 422 JSON / KeyError / ValidationError)
            for quoted in re.findall(r"['\"]([a-zA-Z_][a-zA-Z0-9_]{2,35})['\"]", combined_err):
                if quoted.lower() not in STOP_TOKENS:
                    keywords.add(quoted)

        # 3. Honor explicit isolated_client_modules if specified in aegis.yaml
        for mod_rel in self.isolated_client_modules:
            mod_abs = os.path.join(self.repo_root, mod_rel)
            if os.path.isfile(mod_abs):
                norm_rel = os.path.relpath(mod_abs, self.repo_root).replace(os.sep, "/")
                content = self._safe_read(mod_abs)
                if content is not None:
                    affected_files[norm_rel] = content

        # 4. Determine primary code scan directory + test target directory
        scan_dir = os.path.join(self.repo_root, self.code_root) if self.code_root else self.repo_root
        if not os.path.exists(scan_dir):
            scan_dir = self.repo_root

        all_source_candidates: List[tuple] = []  # (score, norm_rel, content)

        for root, dirs, files in os.walk(scan_dir):
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
            for file in files:
                if not file.endswith((".py", ".ts", ".js")):
                    continue
                file_path = os.path.join(root, file)
                norm_rel = os.path.relpath(file_path, self.repo_root).replace(os.sep, "/")
                content = self._safe_read(file_path)
                if content is None:
                    continue

                is_test = "test" in file.lower() or norm_rel.startswith("tests/")
                direct_tb_hit = (norm_rel in traceback_rel_paths) or (file in traceback_rel_paths)
                kw_hits = sum(1 for kw in keywords if kw in content)

                if direct_tb_hit or kw_hits > 0:
                    affected_files[norm_rel] = content
                elif not is_test and file.endswith(".py") and file != "__init__.py":
                    score = self._score_api_relevance(file, content)
                    all_source_candidates.append((score, norm_rel, content))

        # 5. Zero-Spec / Pure Error-Driven Fallback:
        # Ensure at least one editable (non-test) source file is included for Muse Spark
        editable_Selected = [
            p for p in affected_files.keys()
            if "test" not in os.path.basename(p).lower()
        ]
        if not editable_Selected and all_source_candidates:
            all_source_candidates.sort(key=lambda item: item[0], reverse=True)
            for score, norm_rel, content in all_source_candidates[:10]:
                affected_files[norm_rel] = content

        # 6. Expand local Python imports among selected editable files (e.g. client -> models)
        self._include_imported_siblings(affected_files, scan_dir)

        # 7. Include test files from test_target so MuseSparkClient gets readonly_test_context
        test_abs = os.path.join(self.repo_root, self.test_target)
        if os.path.isfile(test_abs):
            norm_rel = os.path.relpath(test_abs, self.repo_root).replace(os.sep, "/")
            content = self._safe_read(test_abs)
            if content is not None:
                affected_files[norm_rel] = content
        elif os.path.isdir(test_abs):
            for root, dirs, files in os.walk(test_abs):
                dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
                for file in files:
                    if file.endswith(".py") and "test" in file.lower():
                        fp = os.path.join(root, file)
                        norm_rel = os.path.relpath(fp, self.repo_root).replace(os.sep, "/")
                        content = self._safe_read(fp)
                        if content is not None:
                            affected_files[norm_rel] = content

        return {
            "repo_root": self.repo_root,
            "target_files_count": len(affected_files),
            "target_files": affected_files
        }

    def _include_imported_siblings(self, affected_files: Dict[str, str], scan_dir: str) -> None:
        """Uses Python AST to pull in local sibling modules imported by already-matched files (e.g. models.py)."""
        imported_module_names: Set[str] = set()
        for rel_path, content in list(affected_files.items()):
            if not rel_path.endswith(".py"):
                continue
            try:
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.module:
                        imported_module_names.add(node.module.split(".")[-1])
                    elif isinstance(node, ast.Import):
                        for alias in node.names:
                            imported_module_names.add(alias.name.split(".")[-1])
            except Exception:
                pass

        if not imported_module_names:
            return

        for root, dirs, files in os.walk(scan_dir):
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
            for file in files:
                if file.endswith(".py"):
                    stem = file[:-3]
                    if stem in imported_module_names:
                        fp = os.path.join(root, file)
                        norm_rel = os.path.relpath(fp, self.repo_root).replace(os.sep, "/")
                        if norm_rel not in affected_files:
                            content = self._safe_read(fp)
                            if content is not None:
                                affected_files[norm_rel] = content

    @staticmethod
    def _score_api_relevance(filename: str, content: str) -> int:
        """Scores a Python module by likelihood of containing HTTP/API client or schema definitions."""
        score = 1
        fname = filename.lower()
        if any(k in fname for k in ("client", "api", "gateway", "payment", "service", "model", "schema", "checkout")):
            score += 5
        if any(lib in content for lib in ("httpx", "requests", "aiohttp", "urllib", "BaseModel", "APIRouter", "FastAPI")):
            score += 5
        if any(call in content for call in (".post(", ".get(", ".put(", ".request(", "json=")):
            score += 3
        return score

    @staticmethod
    def _safe_read(file_path: str) -> Optional[str]:
        try:
            if os.path.getsize(file_path) > 256_000:
                return None
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return None
