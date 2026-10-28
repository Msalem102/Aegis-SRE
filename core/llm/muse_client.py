"""
Meta Muse Spark Client Wrapper (100% Domain-Agnostic).
Provides structured prompt orchestration for:
- API Breaking Change Refactoring (Vector B)
- Incident Post-Mortem & Pull Request Synthesis (Vector A & Vector B)
"""

from typing import Dict, Any, List, Optional
import os
import json
import re
import httpx


class MuseSparkClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_name: str = "muse-spark"
    ):
        self.api_key = api_key or os.getenv("META_API_KEY") or os.getenv("BASETEN_API_KEY")
        self.base_url = base_url or os.getenv("META_MODEL_API_URL") or "https://api.meta.ai/v1"
        self.model_name = model_name

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
        """
        system_prompt = (
            "You are Aegis SRE's Code Synthesis Core powered by Meta Muse Spark. "
            "An upstream API change has caused runtime errors in a downstream service. "
            "You are given:\n"
            "1. The runtime error log / HTTP failure payload that triggered this incident.\n"
            "2. The structural diff between the previous and new upstream API specifications.\n"
            "3. The downstream source files that interact with this API.\n"
            "4. (Optional) Test failure logs from a previous sandbox verification attempt.\n\n"
            "Your task is to refactor the downstream source files so they conform to the new upstream API contract "
            "while preserving backward compatibility for internal callers.\n\n"
            "You must output STRICT JSON matching this schema:\n"
            "{\n"
            '  "diagnosis": "concise technical root-cause analysis connecting the runtime error to the schema diff",\n'
            '  "refactored_files": {\n'
            '     "relative/path/to/file.py": "complete refactored file source code"\n'
            "  }\n"
            "}\n"
            "Rules:\n"
            "1. Output ONLY valid JSON.\n"
            "2. Reconcile any renamed fields, type conversions, or newly nested object hierarchies shown in the diff.\n"
            "3. Do NOT modify test assertions in test files unless the test itself is invalid; prefer fixing the client and model implementation so existing caller patterns continue to work seamlessly.\n"
            "4. If previous_sandbox_test_failure is provided, fix the exact error shown in the traceback."
        )

        # Filter out test files from modification targets so the agent fixes implementation, not tests,
        # while still giving the agent visibility into the test files as context.
        editable_files = {}
        readonly_test_context = {}
        for path, content in affected_files.items():
            norm = path.replace("\\", "/")
            if "test" in os.path.basename(norm).lower():
                readonly_test_context[path] = content
            else:
                editable_files[path] = content

        user_prompt = {
            "triggering_incident_error": incident_error_log,
            "openapi_structural_diff": breaking_changes,
            "editable_source_files": editable_files,
            "readonly_test_context": readonly_test_context,
            "previous_sandbox_test_failure": previous_errors
        }

        if self.api_key and self.api_key != "MOCK":
            try:
                return self._call_live_api(system_prompt, json.dumps(user_prompt, indent=2))
            except Exception as e:
                print(f"[Aegis LLM Warning] Live API call failed ({e}). Using local AST synthesizer.")

        return self._generic_ast_contract_synthesizer(
            incident_error_log, breaking_changes, editable_files, previous_errors
        )

    def _call_live_api(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        """Invokes the Meta Model API chat completion endpoint."""
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

        with httpx.Client(timeout=60.0) as client:
            resp = client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]

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
                print(f"[Aegis LLM Warning] Live API call failed ({e}). Using local report generator.")

        return self._fallback_artifact_synthesis(
            incident_id, vector_type, incident_trigger, diagnosis, changes_or_plan, unified_diff_or_ddl, sandbox_result
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
        is_db = vector_type.upper() == "VECTOR_A_DB"
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

        md = f"""# Incident Post-Mortem: {incident_id}
**Service:** `{service}`  
**Vector:** `{vector_type}`  
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
