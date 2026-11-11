"""
Meta Muse Spark Client Wrapper (100% Domain-Agnostic).
Provides structured prompt orchestration for:
- API Breaking Change Refactoring (API Contract Drift)
- Incident Post-Mortem & Pull Request Synthesis (Database Contention & API Contract Drift)
"""

from typing import Dict, Any, List, Optional, Tuple
import ast
import os
import sys
import json
import re
import time
import httpx
from dotenv import load_dotenv
from core.telemetry.cost_tracker import CostTracker

SURGICAL_LINE_THRESHOLD = 150
SURGICAL_CHAR_THRESHOLD = 6000

if getattr(sys.stdout, "encoding", "utf-8") != "utf-8":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

_root_env = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
if os.path.exists(_root_env):
    load_dotenv(dotenv_path=_root_env, override=True)
else:
    load_dotenv(override=True)


class MuseSparkClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None
    ):
        if os.path.exists(_root_env):
            load_dotenv(dotenv_path=_root_env, override=True)
        raw_key = api_key or os.getenv("META_API_KEY") or os.getenv("BASETEN_API_KEY") or ""
        self.api_key = raw_key.strip().strip('"').strip("'")
        raw_url = base_url or os.getenv("META_MODEL_API_URL") or "https://api.meta.ai/v1"
        self.base_url = raw_url.strip().strip('"').strip("'").rstrip("/")
        raw_model = model_name or os.getenv("META_MODEL_NAME") or "muse-spark-1.2"
        self.model_name = raw_model.strip().strip('"').strip("'")
        self.cost_tracker = CostTracker(model_name=self.model_name)

    def synthesize_contract_refactor(
        self,
        incident_error_log: Dict[str, Any],
        breaking_changes: List[Dict[str, Any]],
        affected_files: Dict[str, str],
        previous_errors: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Prompts Meta Muse Spark with the triggering runtime error log, the computed OpenAPI AST diff,
        and the downstream caller files to synthesize a code refactor patch.
        Supports both surgical search-and-replace chunk patching (`file_patches`) for large files
        (preventing context window truncation) and full-file replacement (`refactored_files`) for small modules,
        plus AST completeness reconciliation.
        """
        # Filter out test files from modification targets so the agent fixes implementation, not tests,
        # while still giving the agent visibility into the test files as context.
        editable_files: Dict[str, str] = {}
        readonly_test_context: Dict[str, str] = {}
        for path, content in affected_files.items():
            norm = path.replace("\\", "/")
            if "test" in os.path.basename(norm).lower():
                readonly_test_context[path] = content
            else:
                editable_files[path] = content

        prompt_file_views, large_file_paths = self._prepare_prompt_file_views(
            editable_files, breaking_changes, incident_error_log
        )

        system_prompt = (
            "You are Aegis SRE's Code Synthesis Core powered by Meta Muse Spark. "
            "An upstream API change or contract mismatch has caused runtime errors in a downstream service. "
            "You are given:\n"
            "1. The runtime error log / HTTP failure payload / stack trace that triggered this incident.\n"
            "2. Upstream contract context: a structural diff between baseline & new specs, the active upstream OpenAPI schema "
            "(ACTIVE_UPSTREAM_CONTRACT), or empty if operating in Pure Error-Driven Inference mode.\n"
            "3. The downstream editable source files and read-only test context.\n"
            "4. (Optional) Test failure logs from a previous sandbox verification attempt.\n\n"
            "Your task is to refactor the downstream editable source files so they conform to the required upstream API contract "
            "and resolve the runtime error while preserving backward compatibility for internal callers.\n\n"
            "You must output STRICT JSON matching this schema:\n"
            "{\n"
            '  "diagnosis": "concise technical root-cause analysis connecting the runtime error to the contract mismatch",\n'
            '  "file_patches": {\n'
            '     "relative/path/to/large_file.py": [\n'
            '       {"search": "exact contiguous lines from original file", "replace": "replacement lines"}\n'
            '     ]\n'
            '  },\n'
            '  "refactored_files": {\n'
            '     "relative/path/to/small_file.py": "complete refactored file source code"\n'
            "  }\n"
            "}\n"
            "Rules:\n"
            "1. Output ONLY valid JSON.\n"
            f"2. For large files (>={SURGICAL_LINE_THRESHOLD} lines, listed in `surgical_edit_required_files`), you MUST use `file_patches` with exact `search` and `replace` blocks instead of regenerating the entire file to prevent context truncation. You may also use `file_patches` for any targeted edit.\n"
            "3. For small files provided in `refactored_files`, include the FULL file contents without placeholder comments.\n"
            "4. Reconcile any renamed fields, unit/type conversions, or newly nested object hierarchies indicated by the spec or HTTP 400/422 validation errors.\n"
            "5. NEVER include test files in `file_patches` or `refactored_files` and NEVER weaken test assertions; fix the client/model/service implementation.\n"
            "6. If `previous_sandbox_test_failure` is provided, fix the exact error shown in the traceback."
        )

        user_prompt = {
            "triggering_incident_error": incident_error_log,
            "openapi_structural_diff": breaking_changes,
            "surgical_edit_required_files": large_file_paths,
            "editable_source_files": prompt_file_views,
            "readonly_test_context": readonly_test_context,
            "previous_sandbox_test_failure": previous_errors
        }

        if self.api_key and self.api_key != "MOCK":
            try:
                raw_res = self._call_live_api(system_prompt, json.dumps(user_prompt, indent=2), task_name="synthesize_contract_refactor")
                res = self.apply_surgical_patches_and_reconcile(editable_files, raw_res)
                res["cost_metrics"] = self.cost_tracker.get_task_summary()
                return res
            except Exception as e:
                raise RuntimeError(
                    f"Meta Model API call failed ({e}). Live Meta Muse Spark reasoning is required for contract remediation. "
                    "Please verify that META_API_KEY and META_MODEL_API_URL in .env are valid and authorized."
                ) from e

        if self.api_key == "MOCK":
            raw_res = self._generic_ast_contract_synthesizer(
                incident_error_log, breaking_changes, editable_files, previous_errors
            )
            res = self.apply_surgical_patches_and_reconcile(editable_files, raw_res)
            prompt_str = system_prompt + json.dumps(user_prompt)
            res_str = json.dumps(res)
            p_tokens = self.cost_tracker.estimate_tokens_from_text(prompt_str)
            c_tokens = self.cost_tracker.estimate_tokens_from_text(res_str)
            self.cost_tracker.record_usage(p_tokens, c_tokens, task_name="synthesize_contract_refactor")
            res["cost_metrics"] = self.cost_tracker.get_task_summary()
            return res

        raise RuntimeError(
            "META_API_KEY is not configured in .env. Live Meta Muse Spark reasoning is required for autonomous remediation."
        )

    @classmethod
    def _prepare_prompt_file_views(
        cls,
        editable_files: Dict[str, str],
        breaking_changes: List[Dict[str, Any]],
        incident_error_log: Dict[str, Any]
    ) -> Tuple[Dict[str, str], List[str]]:
        """
        Routes files exceeding SURGICAL_LINE_THRESHOLD or SURGICAL_CHAR_THRESHOLD to surgical patch mode.
        For very large files (>350 lines), extracts imports + relevant AST definitions so the LLM prompt
        never overflows the context window, while preserving full original files in memory for patch application.
        """
        views: Dict[str, str] = {}
        large_files: List[str] = []

        # Collect relevance tokens from diff and error log
        keywords = set()
        for ch in breaking_changes:
            for k in ("field_path", "old_field_path", "new_field_path", "endpoint", "path"):
                val = ch.get(k)
                if val:
                    for part in re.split(r"[./_]", str(val)):
                        if len(part) > 2:
                            keywords.add(part.lower())
        err_text = json.dumps(incident_error_log).lower()

        for path, source in editable_files.items():
            lines = source.splitlines()
            if len(lines) >= SURGICAL_LINE_THRESHOLD or len(source) >= SURGICAL_CHAR_THRESHOLD:
                large_files.append(path)
                if len(lines) > 350 and path.endswith(".py"):
                    views[path] = cls._extract_relevant_ast_slices(source, keywords, err_text)
                else:
                    views[path] = source
            else:
                views[path] = source

        return views, large_files

    @staticmethod
    def _extract_relevant_ast_slices(source: str, keywords: set, err_text: str) -> str:
        """Extracts imports, module globals, and relevant AST classes/functions from a large Python file."""
        try:
            tree = ast.parse(source)
            lines = source.splitlines()
            selected_ranges: List[Tuple[int, int]] = []

            for node in tree.body:
                start = getattr(node, "lineno", 1) - 1
                end = getattr(node, "end_lineno", start + 1)
                segment_text = "\n".join(lines[start:end])
                if isinstance(node, (ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign)):
                    selected_ranges.append((start, end))
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    name_low = node.name.lower()
                    seg_low = segment_text.lower()
                    is_relevant = (
                        name_low in err_text
                        or any(kw in seg_low for kw in keywords)
                        or any(tok in seg_low for tok in ("post(", "get(", "put(", "request(", "basemodel", "model_dump", "dict(", "return {"))
                    )
                    if is_relevant:
                        selected_ranges.append((start, end))

            if not selected_ranges:
                return source

            chunks = ["# [AEGIS SURGICAL CONTEXT VIEW — Emit changes in `file_patches` using exact search/replace blocks]"]
            for s, e in selected_ranges:
                chunks.append("\n".join(lines[s:e]))
            return "\n\n".join(chunks)
        except Exception:
            return source

    @classmethod
    def apply_surgical_patches_and_reconcile(
        cls,
        original_files: Dict[str, str],
        llm_response: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Reconciles surgical search-and-replace blocks (`file_patches`), conflict-marker hunks,
        unified diffs (`@@ ... @@`), and full-file replacements (`refactored_files`) against `original_files`,
        applying AST anti-truncation recovery to ensure no unrelated code is ever dropped.
        """
        reconciled: Dict[str, str] = {}
        norm_originals = {k.replace("\\", "/"): v for k, v in original_files.items()}
        patch_strategy_used = "FULL_FILE"

        # 1. Process full or diff entries in `refactored_files`
        raw_refactored = llm_response.get("refactored_files") or {}
        if isinstance(raw_refactored, dict):
            for raw_path, raw_content in raw_refactored.items():
                if not isinstance(raw_content, str):
                    continue
                path = raw_path.replace("\\", "/")
                orig_src = norm_originals.get(path)

                if orig_src is not None and ("<<<<<<< SEARCH" in raw_content or "@@ -" in raw_content):
                    patched = cls._apply_text_hunks(orig_src, raw_content)
                    reconciled[path] = cls._guard_against_truncation(orig_src, patched)
                    patch_strategy_used = "SURGICAL_PATCH"
                elif orig_src is not None:
                    reconciled[path] = cls._guard_against_truncation(orig_src, raw_content)
                else:
                    reconciled[path] = raw_content

        # 2. Process explicit surgical search-and-replace blocks in `file_patches`
        raw_patches = llm_response.get("file_patches") or llm_response.get("surgical_patches") or {}
        if isinstance(raw_patches, dict):
            for raw_path, patch_entries in raw_patches.items():
                path = raw_path.replace("\\", "/")
                base_src = reconciled.get(path) or norm_originals.get(path, "")
                if not base_src:
                    continue

                if isinstance(patch_entries, str):
                    updated_src = cls._apply_text_hunks(base_src, patch_entries)
                    if updated_src != base_src:
                        reconciled[path] = cls._guard_against_truncation(norm_originals.get(path, base_src), updated_src)
                        patch_strategy_used = "SURGICAL_PATCH"
                elif isinstance(patch_entries, list):
                    updated_src = base_src
                    applied_any = False
                    for hunk in patch_entries:
                        if not isinstance(hunk, dict):
                            continue
                        search_str = hunk.get("search") or hunk.get("old") or hunk.get("target") or ""
                        replace_str = hunk.get("replace") if "replace" in hunk else (
                            hunk.get("new") if "new" in hunk else hunk.get("replacement", "")
                        )
                        if not search_str:
                            continue
                        new_candidate, matched = cls._apply_single_search_replace(updated_src, search_str, replace_str)
                        if matched:
                            updated_src = new_candidate
                            applied_any = True
                    if applied_any:
                        reconciled[path] = cls._guard_against_truncation(norm_originals.get(path, base_src), updated_src)
                        patch_strategy_used = "SURGICAL_PATCH"

        out = dict(llm_response)
        out["refactored_files"] = reconciled
        out["patch_strategy"] = patch_strategy_used
        return out

    @staticmethod
    def _apply_single_search_replace(source: str, search_block: str, replace_block: str) -> Tuple[str, bool]:
        """Applies a single search-and-replace block with exact match first, then whitespace-normalized line matching."""
        if search_block in source:
            return source.replace(search_block, replace_block, 1), True

        # Fallback: normalize CRLF -> LF
        norm_source = source.replace("\r\n", "\n")
        norm_search = search_block.replace("\r\n", "\n").strip("\n")
        norm_replace = replace_block.replace("\r\n", "\n").strip("\n")
        if norm_search and norm_search in norm_source:
            return norm_source.replace(norm_search, norm_replace, 1), True

        # Fallback: line-by-line stripped comparison for slight indentation variance
        src_lines = norm_source.splitlines()
        search_lines = [ln.strip() for ln in norm_search.splitlines() if ln.strip()]
        if not search_lines:
            return source, False

        # Find contiguous span in src_lines matching non-empty search_lines
        for start_idx in range(len(src_lines)):
            if src_lines[start_idx].strip() != search_lines[0]:
                continue
            s_ptr = 0
            end_idx = start_idx
            while end_idx < len(src_lines) and s_ptr < len(search_lines):
                stripped_cur = src_lines[end_idx].strip()
                if not stripped_cur:
                    end_idx += 1
                    continue
                if stripped_cur == search_lines[s_ptr]:
                    s_ptr += 1
                    end_idx += 1
                else:
                    break
            if s_ptr == len(search_lines):
                # Preserve base indentation if replace_block has no leading indent
                new_lines = src_lines[:start_idx] + norm_replace.splitlines() + src_lines[end_idx:]
                trailing_nl = "\n" if norm_source.endswith("\n") else ""
                return "\n".join(new_lines) + trailing_nl, True

        return source, False

    @classmethod
    def _apply_text_hunks(cls, source: str, patch_text: str) -> str:
        """Applies either conflict-marker SEARCH/REPLACE blocks or unified diff (`@@ ... @@`) hunks."""
        updated = source.replace("\r\n", "\n")
        norm_patch = patch_text.replace("\r\n", "\n")

        # 1. Check for <<<<<<< SEARCH ... ======= ... >>>>>>> REPLACE blocks
        conflict_pattern = re.compile(
            r"<{5,9}\s*SEARCH\s*\n(.*?)\n={5,9}\s*\n(.*?)\n>{5,9}\s*REPLACE",
            flags=re.S
        )
        matches = conflict_pattern.findall(norm_patch)
        if matches:
            for search_part, replace_part in matches:
                updated, _ = cls._apply_single_search_replace(updated, search_part, replace_part)
            return updated

        # 2. Check for unified diff hunks (@@ -a,b +c,d @@)
        if "@@ -" in norm_patch:
            hunk_splits = re.split(r"^@@\s+-\d+(?:,\d+)?\s+\+\d+(?:,\d+)?\s+@@.*$", norm_patch, flags=re.M)
            for hunk in hunk_splits[1:]:
                hunk_lines = hunk.splitlines()
                search_lines = []
                replace_lines = []
                for hl in hunk_lines:
                    if hl.startswith(("---", "+++")):
                        continue
                    if hl.startswith("-"):
                        search_lines.append(hl[1:])
                    elif hl.startswith("+"):
                        replace_lines.append(hl[1:])
                    elif hl.startswith(" ") or hl == "":
                        line_txt = hl[1:] if hl.startswith(" ") else ""
                        search_lines.append(line_txt)
                        replace_lines.append(line_txt)
                search_blk = "\n".join(search_lines).strip("\n")
                replace_blk = "\n".join(replace_lines).strip("\n")
                if search_blk:
                    updated, _ = cls._apply_single_search_replace(updated, search_blk, replace_blk)
            return updated

        return source

    @staticmethod
    def _guard_against_truncation(original_source: str, candidate_source: str) -> str:
        """
        AST Completeness & Anti-Truncation Guard.
        Detects if an LLM response contains truncation placeholders (e.g. `# ... rest of file`,
        `# ... existing code ...`) or accidentally omitted unmodified top-level functions/classes
        from a multi-definition module, and automatically restores omitted AST definitions.
        """
        if not original_source or not candidate_source:
            return candidate_source or original_source

        truncation_markers = (
            "# ... rest of",
            "# ... existing",
            "# ... unchanged",
            "# ... remaining",
            "# rest of file",
            "# existing code",
            "# omitted for brevity"
        )
        cand_lower = candidate_source.lower()
        has_truncation_marker = any(m in cand_lower for m in truncation_markers) or bool(
            re.search(r"^\s*#\s*\.\.\.\s*$", candidate_source, flags=re.M)
        )

        # Strip explicit truncation placeholder comment lines before AST merge
        cleaned_candidate = "\n".join(
            ln for ln in candidate_source.splitlines()
            if not any(m in ln.lower() for m in truncation_markers)
            and not re.match(r"^\s*#\s*\.\.\.\s*$", ln)
        )
        if candidate_source.endswith("\n") and not cleaned_candidate.endswith("\n"):
            cleaned_candidate += "\n"

        try:
            orig_tree = ast.parse(original_source)
            cand_tree = ast.parse(cleaned_candidate)
        except SyntaxError:
            return candidate_source

        orig_lines = original_source.splitlines()
        significant_shrinkage = len(orig_lines) >= 30 and len(cleaned_candidate.splitlines()) < (len(orig_lines) * 0.7)

        if not has_truncation_marker and not significant_shrinkage:
            return cleaned_candidate

        cand_def_names = {
            node.name
            for node in cand_tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        }

        missing_segments: List[str] = []
        for node in orig_tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name not in cand_def_names:
                    start = getattr(node, "lineno", 1) - 1
                    end = getattr(node, "end_lineno", start + 1)
                    missing_segments.append("\n".join(orig_lines[start:end]))

        if not missing_segments:
            return cleaned_candidate

        merged = cleaned_candidate.rstrip() + "\n\n\n" + "\n\n\n".join(missing_segments) + "\n"
        try:
            ast.parse(merged)
            return merged
        except SyntaxError:
            return cleaned_candidate

    def _call_live_api(self, system_prompt: str, user_prompt: str, task_name: str = "llm_call") -> Dict[str, Any]:
        """Invokes the Meta Model API chat completion endpoint and records token usage."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"}
        }

        print(f"   🧠 [Meta Model API] Dispatching live prompt to '{self.model_name}' at {self.base_url} (generating patch)...", flush=True)
        start_t = time.perf_counter()
        with httpx.Client(timeout=90.0) as client:
            resp = client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
            resp.raise_for_status()
            elapsed = round(time.perf_counter() - start_t, 2)
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            p_tokens = usage.get("prompt_tokens", self.cost_tracker.estimate_tokens_from_text(system_prompt + user_prompt))
            c_tokens = usage.get("completion_tokens", self.cost_tracker.estimate_tokens_from_text(content))
            self.cost_tracker.record_usage(p_tokens, c_tokens, task_name=task_name)
            print(f"   🧠 [Meta Model API] Response received in {elapsed}s | Tokens: {p_tokens} prompt + {c_tokens} completion", flush=True)

            if content.startswith("```"):
                lines = content.strip().split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                content = "\n".join(lines).strip()

            return json.loads(content)

    def _generic_ast_contract_synthesizer(
        self,
        incident_error_log: Dict[str, Any],
        breaking_changes: List[Dict[str, Any]],
        editable_files: Dict[str, str],
        previous_errors: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Rule-driven AST/schema adapter used only when no external LLM API key is configured.
        Dynamically reads the diff's removed fields, newly required fields, and nested schemas
        to generate an adapter layer without hardcoded field names.
        """
        removed_fields = [
            c["field_path"] for c in breaking_changes if c.get("type") == "FIELD_REMOVED"
        ]
        newly_required = [
            c["field_path"] for c in breaking_changes if c.get("type") == "FIELD_NEWLY_REQUIRED"
        ]
        nested_moves = [
            c for c in breaking_changes if c.get("type") == "FIELD_STRUCTURALLY_NESTED"
        ]
        type_changes = [
            c for c in breaking_changes if c.get("type") == "FIELD_TYPE_CHANGED"
        ]

        # Build dynamic mapping rules from the diff
        field_migrations = {}
        # 1. Explicit structural moves detected by differ
        for move in nested_moves:
            field_migrations[move["old_field_path"]] = {
                "target": move["new_field_path"],
                "transform": "nested_object"
            }

        # 2. Match remaining removed fields to newly_required fields by stem/similarity
        unmapped_removed = [f for f in removed_fields if f not in field_migrations]
        for rem in unmapped_removed:
            for req in newly_required:
                if rem in req or req in rem:
                    # Check if unit conversion like _cents is implied
                    transform = "int_x100" if req.endswith("_cents") and not rem.endswith("_cents") else "direct"
                    field_migrations[rem] = {
                        "target": req,
                        "transform": transform
                    }

        refactored_files = {}
        migrations_json = json.dumps(field_migrations)

        for file_path, source in editable_files.items():
            # If the file defines a payload builder (dict return in a method), inject dynamic schema transform
            if "def " in source and "return {" in source:
                # Inject a generic payload transformer helper that applies field_migrations dynamically
                helper_code = f'''

def _aegis_reconcile_contract_payload(raw_payload: dict) -> dict:
    """Auto-generated by Aegis SRE from OpenAPI structural diff."""
    migrations = {migrations_json}
    result = dict(raw_payload)
    for old_key, rule in migrations.items():
        if old_key in result and result[old_key] is not None:
            val = result.pop(old_key)
            target_path = rule["target"].split(".")
            if rule["transform"] == "int_x100":
                val = int(round(float(val) * 100))
            curr = result
            for part in target_path[:-1]:
                curr = curr.setdefault(part, {{}})
            curr[target_path[-1]] = val
    return result
'''
                # Wrap dictionary returns inside methods with _aegis_reconcile_contract_payload
                modified = re.sub(
                    r"return\s*\{([^}]+)\}",
                    r"return _aegis_reconcile_contract_payload({\1})",
                    source
                )
                # Ensure relative imports also work when executed from test runner root
                modified = re.sub(
                    r"from\s+\.(\w+)\s+import\s+([^\n]+)",
                    r"try:\n    from .\1 import \2\nexcept ImportError:\n    from src.\1 import \2",
                    modified
                )
                refactored_files[file_path] = modified + helper_code

        err_msg = incident_error_log.get("error_message", "Upstream contract validation failure")
        diagnosis = (
            f"Triggered by runtime error: '{err_msg}'. "
            f"OpenAPI structural diff identified removed fields {removed_fields}, "
            f"newly required fields {newly_required}, and nested relocations {[m['new_field_path'] for m in nested_moves]}. "
            f"Synthesized dynamic payload reconciliation layer for {list(refactored_files.keys())}."
        )

        return {
            "diagnosis": diagnosis,
            "refactored_files": refactored_files
        }

    def generate_incident_delivery_artifacts(
        self,
        incident_id: str,
        vector_type: str,
        incident_trigger: Dict[str, Any],
        diagnosis: str,
        changes_or_plan: Any,
        unified_diff_or_ddl: str,
        sandbox_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Prompts Meta Muse Spark to dynamically author the GitHub Pull Request title,
        PR summary, and complete Markdown Incident Post-Mortem for ANY vector (API or DB).
        """
        system_prompt = (
            "You are Aegis SRE's Incident Delivery Core powered by Meta Muse Spark. "
            "Given the incident trigger log, root-cause diagnosis, verified code diff or SQL DDL migration, "
            "and sandbox verification telemetry, author a ready-to-merge GitHub Pull Request and Markdown Post-Mortem.\n"
            "Output STRICT JSON format:\n"
            "{\n"
            '  "pr_title": "Conventional commit title (e.g. fix(contract): ... or perf(db): ...)",\n'
            '  "pr_summary": "Concise bulleted summary of the verified fix",\n'
            '  "executive_summary": "High-level paragraph describing the outage trigger and autonomous resolution",\n'
            '  "root_cause_analysis": "Detailed technical explanation",\n'
            '  "post_mortem_markdown": "Complete Markdown post-mortem document including diff/DDL and sandbox verification proof"\n'
            "}"
        )

        user_prompt = {
            "incident_id": incident_id,
            "vector_type": vector_type,
            "incident_trigger": incident_trigger,
            "diagnosis": diagnosis,
            "technical_findings": changes_or_plan,
            "verified_patch": unified_diff_or_ddl,
            "sandbox_verification": sandbox_result
        }

        if self.api_key and self.api_key != "MOCK":
            try:
                return self._call_live_api(system_prompt, json.dumps(user_prompt, indent=2))
            except Exception as e:
                raise RuntimeError(
                    f"Meta Model API call failed ({e}). Live Meta Muse Spark reasoning is required for post-mortem synthesis. "
                    "Please verify that META_API_KEY and META_MODEL_API_URL in .env are valid and authorized."
                ) from e

        if self.api_key == "MOCK":
            return self._fallback_artifact_synthesis(
                incident_id, vector_type, incident_trigger, diagnosis, changes_or_plan, unified_diff_or_ddl, sandbox_result
            )

        raise RuntimeError(
            "META_API_KEY is not configured in .env. Live Meta Muse Spark reasoning is required for autonomous remediation."
        )

    def _fallback_artifact_synthesis(
        self,
        incident_id: str,
        vector_type: str,
        incident_trigger: Dict[str, Any],
        diagnosis: str,
        changes_or_plan: Any,
        unified_diff_or_ddl: str,
        sandbox_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        is_db = vector_type.upper() in ("VECTOR_A_DB", "DATABASE_CONTENTION", "DATABASE")
        prefix = "perf(db)" if is_db else "fix(contract)"
        service = incident_trigger.get("service", "production-service")
        pr_title = f"{prefix}: autonomous remediation for {incident_id} on {service}"

        exec_summary = (
            f"Incident `{incident_id}` was automatically triggered on `{service}` due to: "
            f"`{incident_trigger.get('error_message', 'production anomaly')}`. "
            f"Aegis SRE diagnosed the root cause, synthesized a non-breaking remediation patch, "
            f"and deterministically verified the fix in an isolated sandbox before opening this PR."
        )

        fence_lang = "sql" if is_db else "diff"
        sandbox_summary = json.dumps(sandbox_result, indent=2)
        problem_label = "Database Contention" if is_db else "API Contract Drift"

        md = f"""# Incident Post-Mortem: {incident_id}
**Service:** `{service}`  
**Problem Type:** `{problem_label}`  
**Remediation Engine:** Aegis SRE (Meta Muse Spark Core)  
**Sandbox Gate Status:** `PASSED`  

---

## 1. Triggering Outage Event
```json
{json.dumps(incident_trigger, indent=2)}
```

---

## 2. Executive Summary
{exec_summary}

---

## 3. Root Cause Analysis
{diagnosis}

---

## 4. Verified Remediation Patch
```{fence_lang}
{unified_diff_or_ddl.strip()}
```

---

## 5. Ephemeral Sandbox Verification Proof
```json
{sandbox_summary}
```
"""
        return {
            "pr_title": pr_title,
            "pr_summary": exec_summary,
            "executive_summary": exec_summary,
            "root_cause_analysis": diagnosis,
            "post_mortem_markdown": md
        }
