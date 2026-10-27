"""
Meta Muse Spark Database Performance SRE Core.
Ingests raw execution plan diagnostics, table catalogs, and offending SQL statements.
Prompts Meta Muse Spark to formulate optimal indexing strategies (Composite, Covering INCLUDE,
or Partial) and synthesize zero-downtime, idempotent DDL scripts.
"""

from typing import Dict, Any, List, Optional
import os
import json
import httpx
from core.db.safety_guard import DDLSafetyGuard


class MuseDBClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_name: str = "muse-spark"
    ):
        self.api_key = api_key or os.getenv("META_API_KEY") or os.getenv("BASETEN_API_KEY")
        self.base_url = base_url or os.getenv("META_MODEL_API_URL") or "https://api.meta.ai/v1"
        self.model_name = model_name

    def synthesize_database_remediation(
        self,
        query: str,
        table_catalog: Dict[str, Any],
        plan_analysis: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Prompts Meta Muse Spark to diagnose query bottlenecks and synthesize
        zero-downtime PostgreSQL DDL.
        """
        system_prompt = (
            "You are Aegis SRE's Database Performance Core powered by Meta Muse Spark. "
            "You are a Principal PostgreSQL Database Administrator. "
            "Given an offending query, its table catalog, and execution plan tree bottlenecks, "
            "formulate an optimal indexing strategy and synthesize zero-downtime DDL.\n"
            "STRICT RULES:\n"
            "1. Output valid JSON only matching this schema:\n"
            "{\n"
            '  "diagnosis": "technical explanation of plan bottlenecks (Seq Scan, disk read spills)",\n'
            '  "strategy": "COMPOSITE_INDEX | COVERING_INDEX | PARTIAL_INDEX",\n'
            '  "index_name": "idx_tablename_columns",\n'
            '  "ddl_script": "-- Safe migration SQL script\\nSET statement_timeout = \'30s\';\\nSET lock_timeout = \'5s\';\\nCREATE INDEX CONCURRENTLY IF NOT EXISTS ...",\n'
            '  "expected_impact": "predicted latency drop and node conversion"\n'
            "}\n"
            "2. Always mandate CREATE INDEX CONCURRENTLY IF NOT EXISTS.\n"
            "3. Always prefix with SET lock_timeout = '5s' and SET statement_timeout = '30s'.\n"
            "4. NEVER output destructive commands (DROP, TRUNCATE)."
        )

        user_prompt = {
            "query": query,
            "table_catalog": table_catalog,
            "execution_plan_analysis": plan_analysis
        }

        if self.api_key and self.api_key != "MOCK":
            try:
                response = self._call_live_api(system_prompt, json.dumps(user_prompt, indent=2))
                # Enforce safety guard validation
                is_safe, violations = DDLSafetyGuard.validate_ddl(response.get("ddl_script", ""))
                if not is_safe:
                    print(f"[Aegis Safety Alert] LLM DDL had violations: {violations}. Enforcing safety envelope.")
                    response["ddl_script"] = DDLSafetyGuard.enforce_safety_envelope(response.get("ddl_script", ""))
                return response
            except Exception as e:
                print(f"[Aegis LLM Warning] Live API call failed ({e}). Using deterministic SRE synthesis.")

        # Generalized Deterministic Synthesis Fallback
        return self._deterministic_db_synthesis(query, table_catalog, plan_analysis)

    def _call_live_api(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        """Calls the Meta Model API chat completion endpoint."""
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

        with httpx.Client(timeout=45.0) as client:
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

    def _deterministic_db_synthesis(
        self, query: str, table_catalog: Dict[str, Any], plan_analysis: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Dynamically formulates an optimal indexing strategy based on the extracted
        filter columns, sort keys, and table catalog.
        """
        table_name = table_catalog.get("table_name", "target_table")
        table_scans = plan_analysis.get("table_scans", [])
        sort_nodes = plan_analysis.get("sort_nodes", [])

        # Extract indexed candidates
        indexed_cols = []
        for scan in table_scans:
            indexed_cols.extend(scan.get("filter_columns", []))

        # Extract sort columns
        sort_cols = []
        for s in sort_nodes:
            for k in s.get("sort_keys", []):
                # e.g., orders.created_at DESC -> created_at DESC
                col_name = k.split()[0].split(".")[-1]
                direction = "DESC" if "DESC" in k.upper() else "ASC"
                sort_cols.append(f"{col_name} {direction}")

        # Combine equality filter columns + sort columns
        target_cols = []
        for c in indexed_cols:
            if c not in target_cols:
                target_cols.append(c)

        for sc in sort_cols:
            base = sc.split()[0]
            if base not in target_cols:
                target_cols.append(sc)

        if not target_cols:
            target_cols = ["id"]

        clean_col_names = [c.split()[0] for c in target_cols]
        index_name = f"idx_{table_name}_{'_'.join(clean_col_names[:3])}"

        # Check if covering index with INCLUDE total_amount or numeric columns is beneficial
        all_table_cols = [c.get("column_name") for c in table_catalog.get("columns", [])]
        include_cols = [c for c in all_table_cols if c in ["total_amount", "amount", "price"] and c not in clean_col_names]

        include_clause = f"\nINCLUDE ({', '.join(include_cols)})" if include_cols else ""

        raw_ddl = (
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {index_name}\n"
            f"ON {table_name} ({', '.join(target_cols)}){include_clause};"
        )
        safe_ddl = DDLSafetyGuard.enforce_safety_envelope(raw_ddl)

        diagnosis = (
            f"Query performance degradation caused by unindexed sequential scan on table '{table_name}'. "
            f"Execution time: {plan_analysis.get('execution_time_ms', 0):.2f}ms. "
            f"The planner scanned and filtered millions of rows due to absence of composite index on "
            f"({', '.join(clean_col_names)}), resulting in {plan_analysis.get('total_shared_read_blocks', 0)} disk buffer read spills."
        )

        return {
            "diagnosis": diagnosis,
            "strategy": "COMPOSITE_COVERING_INDEX",
            "index_name": index_name,
            "ddl_script": safe_ddl,
            "expected_impact": "Convert Seq Scan to Index Only Scan, reducing P99 latency by >=90%."
        }
