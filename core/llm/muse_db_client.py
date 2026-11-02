"""
Meta Muse Spark Database Performance SRE Core (100% Domain-Agnostic).
Receives:
1. Outage Error & Telemetry Logs (504 timeouts, slow query alerts)
2. Live Read-Only Database Catalog (tables, columns, existing indexes)
3. Live EXPLAIN Execution Plan
4. Optional Sandbox Error Logs (for iterative self-healing)
Synthesizes optimal zero-downtime PostgreSQL DDL without any hardcoded table or column names.
"""

from typing import Dict, Any, List, Optional
import os
import sys
import re
import json
import time
import httpx
from dotenv import load_dotenv
from core.db.safety_guard import DDLSafetyGuard
from core.telemetry.cost_tracker import CostTracker

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

_root_env = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
if os.path.exists(_root_env):
    load_dotenv(dotenv_path=_root_env, override=True)
else:
    load_dotenv(override=True)


class MuseDBClient:
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

    def synthesize_database_remediation(
        self,
        outage_alert: Dict[str, Any],
        query: str,
        table_catalog: Dict[str, Any],
        raw_explain_plan: Any,
        previous_sandbox_error: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Feeds the triggering outage alert, live read-only catalog, and execution plan
        directly to Meta Muse Spark to formulate the indexing strategy and safe DDL.
        """
        system_prompt = (
            "You are Aegis SRE's Database Reasoning Core powered by Meta Muse Spark. "
            "You are a Principal PostgreSQL Database Reliability Engineer.\n"
            "An active production outage has triggered an alert. Using read-only database access, "
            "the agent has collected:\n"
            "1. The outage error and alert logs.\n"
            "2. The offending SQL query.\n"
            "3. The live table schema catalog and existing indexes.\n"
            "4. The raw EXPLAIN execution plan.\n"
            "5. (Optional) Error logs from a previous sandbox verification attempt.\n\n"
            "Your tasks:\n"
            "1. Diagnose the execution plan bottleneck (e.g. Seq Scan, missing index, sort spill).\n"
            "2. Formulate the optimal index column ordering (equality predicates first, sort keys next, "
            "and INCLUDE covering columns if beneficial for an Index Only Scan).\n"
            "3. Synthesize zero-downtime PostgreSQL DDL: mandate CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "prefixed with SET statement_timeout = '30s'; and SET lock_timeout = '5s';.\n\n"
            "OUTPUT STRICT JSON ONLY:\n"
            "{\n"
            '  "plan_tree_diagnosis": "Detailed technical root-cause analysis of the query bottleneck",\n'
            '  "cost_and_buffer_analysis": "Analysis of scan cost, rows scanned vs returned, and I/O impact",\n'
            '  "strategy": "COMPOSITE_COVERING_INDEX | COMPOSITE_INDEX | PARTIAL_INDEX",\n'
            '  "index_name": "idx_tablename_cols",\n'
            '  "indexed_columns": ["col1", "col2", "col3 DESC"],\n'
            '  "include_columns": ["col4"],\n'
            '  "ddl_script": "-- Safe migration SQL\\nSET statement_timeout = \'30s\';\\nSET lock_timeout = \'5s\';\\nCREATE INDEX CONCURRENTLY IF NOT EXISTS ...",\n'
            '  "expected_impact": "Predicted scan conversion and latency reduction"\n'
            "}"
        )

        user_prompt = {
            "outage_alert": outage_alert,
            "query": query,
            "table_catalog": table_catalog,
            "explain_plan": raw_explain_plan,
            "previous_sandbox_error": previous_sandbox_error
        }

        if self.api_key and self.api_key != "MOCK":
            try:
                response = self._call_live_api(system_prompt, json.dumps(user_prompt, indent=2), task_name="synthesize_database_remediation")
                is_safe, violations = DDLSafetyGuard.validate_ddl(response.get("ddl_script", ""))
                if not is_safe:
                    response["ddl_script"] = DDLSafetyGuard.enforce_safety_envelope(response.get("ddl_script", ""))
                response["cost_metrics"] = self.cost_tracker.get_task_summary()
                return response
            except Exception as e:
                raise RuntimeError(
                    f"Meta Model API call failed ({e}). Live Meta Muse Spark reasoning is required for autonomous remediation. "
                    "Please verify that META_API_KEY and META_MODEL_API_URL in .env are valid and authorized."
                ) from e

        if self.api_key == "MOCK":
            response = self._generic_sql_ast_reasoner(outage_alert, query, table_catalog, raw_explain_plan)
            p_tokens = self.cost_tracker.estimate_tokens_from_text(system_prompt + json.dumps(user_prompt))
            c_tokens = self.cost_tracker.estimate_tokens_from_text(json.dumps(response))
            self.cost_tracker.record_usage(p_tokens, c_tokens, task_name="synthesize_database_remediation")
            response["cost_metrics"] = self.cost_tracker.get_task_summary()
            return response

        raise RuntimeError(
            "META_API_KEY is not configured in .env. Live Meta Muse Spark reasoning is required for autonomous remediation."
        )

    def _call_live_api(self, system_prompt: str, user_prompt: str, task_name: str = "llm_call") -> Dict[str, Any]:
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

        masked_key = f"{self.api_key[:6]}...{self.api_key[-4:]}" if len(self.api_key) > 10 else ("None" if not self.api_key else self.api_key)
        print(f"   🧠 [Meta Model API] Dispatching live prompt to '{self.model_name}' at {self.base_url} [Key: {masked_key}] (generating reasoning & DDL)...", flush=True)
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

    def _generic_sql_ast_reasoner(
        self,
        outage_alert: Dict[str, Any],
        query: str,
        table_catalog: Dict[str, Any],
        raw_explain_plan: Any
    ) -> Dict[str, Any]:
        """
        100% generic SQL parser that inspects ANY SQL query (SELECT/FROM/WHERE/ORDER BY)
        and live table catalog to synthesize a composite covering index without hardcoded column names.
        """
        # 1. Extract table name from catalog or FROM clause
        table_name = table_catalog.get("table_name")
        if not table_name:
            m_from = re.search(r"\bFROM\s+([a-zA-Z_][a-zA-Z0-9_]*)", query, re.I)
            table_name = m_from.group(1) if m_from else "target_table"

        valid_columns = {c["column_name"].lower(): c["column_name"] for c in table_catalog.get("columns", [])}
        pk_columns = {
            c["column_name"].lower() for c in table_catalog.get("columns", []) if c.get("is_primary_key")
        }

        where_cols: List[str] = []
        order_specs: List[str] = []
        order_base_cols: List[str] = []
        include_cols: List[str] = []

        # Parse AST using sqlglot (with regex fallback)
        parsed_via_ast = False
        try:
            import sqlglot
            from sqlglot import exp
            parsed = sqlglot.parse_one(query, read="postgres")

            if not table_name:
                tables = [t.name for t in parsed.find_all(exp.Table) if t.name]
                table_name = tables[0] if tables else "target_table"

            where_node = parsed.find(exp.Where)
            if where_node:
                for col in where_node.find_all(exp.Column):
                    clower = col.name.lower()
                    if clower not in {"and", "or", "not", "null", "true", "false"}:
                        actual = valid_columns.get(clower, col.name)
                        if actual not in where_cols:
                            where_cols.append(actual)

            order_node = parsed.find(exp.Order)
            if order_node:
                for ordered in order_node.expressions:
                    col_node = ordered.this
                    cname = col_node.name if isinstance(col_node, exp.Column) else str(col_node).split(".")[-1]
                    actual = valid_columns.get(cname.lower(), cname)
                    direction = "DESC" if ordered.args.get("desc") else ""
                    if actual not in where_cols and actual not in order_base_cols:
                        order_base_cols.append(actual)
                        order_specs.append(f"{actual} {direction}".strip())

            for select_exp in parsed.selects:
                col_node = select_exp.this if hasattr(select_exp, "this") else select_exp
                cname = col_node.name if isinstance(col_node, exp.Column) else str(col_node).split(".")[-1]
                clower = cname.lower()
                if clower in valid_columns:
                    actual = valid_columns[clower]
                    if (
                        actual not in where_cols
                        and actual not in order_base_cols
                        and clower not in pk_columns
                        and actual not in include_cols
                    ):
                        include_cols.append(actual)

            parsed_via_ast = True
        except Exception:
            parsed_via_ast = False

        if not parsed_via_ast:
            # 2. Extract WHERE predicate columns dynamically via regex fallback
            where_match = re.search(r"\bWHERE\b(.*?)(?:\bORDER\s+BY\b|\bGROUP\s+BY\b|\bLIMIT\b|;|$)", query, re.I | re.S)
            if where_match:
                where_clause = where_match.group(1)
                candidates = re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*(?:=|!=|<>|<=|>=|<|>|\bIN\b|\bLIKE\b)", where_clause, re.I)
                for cand in candidates:
                    clower = cand.lower()
                    if clower not in {"and", "or", "not", "null", "true", "false"}:
                        actual_col = valid_columns.get(clower, cand)
                        if actual_col not in where_cols:
                            where_cols.append(actual_col)

            # 3. Extract ORDER BY columns and sort direction dynamically
            order_match = re.search(r"\bORDER\s+BY\b(.*?)(?:\bLIMIT\b|;|$)", query, re.I | re.S)
            if order_match:
                order_clause = order_match.group(1).strip()
                for part in order_clause.split(","):
                    tokens = part.strip().split()
                    if tokens:
                        raw_col = tokens[0].split(".")[-1]
                        actual_col = valid_columns.get(raw_col.lower(), raw_col)
                        direction = "DESC" if len(tokens) > 1 and tokens[1].upper() == "DESC" else ""
                        if actual_col not in where_cols and actual_col not in order_base_cols:
                            order_base_cols.append(actual_col)
                            order_specs.append(f"{actual_col} {direction}".strip())

            # 4. Extract SELECT projected columns to determine covering INCLUDE columns
            select_match = re.search(r"\bSELECT\b(.*?)\bFROM\b", query, re.I | re.S)
            if select_match:
                select_clause = select_match.group(1)
                for part in select_clause.split(","):
                    col_token = part.strip().split()[-1].split(".")[-1]
                    clower = col_token.lower()
                    if clower in valid_columns:
                        actual_col = valid_columns[clower]
                        if (
                            actual_col not in where_cols
                            and actual_col not in order_base_cols
                            and clower not in pk_columns
                            and actual_col not in include_cols
                        ):
                            include_cols.append(actual_col)

        # Detect joined tables and synthesize foreign key indexes for unindexed joins
        join_ddls = []
        seen_join_indexes = set()
        if parsed_via_ast:
            try:
                for join_node in parsed.find_all(exp.Join):
                    join_tbl_node = join_node.this
                    join_tbl = getattr(join_tbl_node, "name", None) or str(join_tbl_node).split()[-1].strip('"')
                    join_tbl_alias = str(getattr(join_tbl_node, "alias", "") or join_node.alias or join_tbl)
                    for col_node in join_node.find_all(exp.Column):
                        c_table = col_node.table
                        c_name = col_node.name
                        if (c_table and c_table in (join_tbl, join_tbl_alias)) or (not c_table and c_name.endswith("_id")):
                            key = (join_tbl.lower(), c_name.lower())
                            if key not in seen_join_indexes:
                                seen_join_indexes.add(key)
                                idx_name = f"idx_{join_tbl}_{c_name}".lower()
                                join_ddls.append(
                                    f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {idx_name}\nON {join_tbl} ({c_name});"
                                )
            except Exception:
                pass

        indexed_columns = where_cols + order_specs
        if not indexed_columns and valid_columns:
            indexed_columns = [next(iter(valid_columns.values()))]

        all_key_names = where_cols + order_base_cols
        index_name = f"idx_{table_name}_{'_'.join(all_key_names[:3])}".lower()

        include_clause = f"\nINCLUDE ({', '.join(include_cols)})" if include_cols else ""
        raw_ddl = (
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {index_name}\n"
            f"ON {table_name} ({', '.join(indexed_columns)}){include_clause};"
        )
        if join_ddls:
            raw_ddl += "\n\n" + "\n\n".join(join_ddls)
        safe_ddl = DDLSafetyGuard.enforce_safety_envelope(raw_ddl)

        row_count = table_catalog.get("row_count", "all")
        plan_summary = json.dumps(raw_explain_plan) if isinstance(raw_explain_plan, dict) else str(raw_explain_plan)

        plan_diagnosis = (
            f"Outage triggered by '{outage_alert.get('error_message', 'Database latency spike')}'. "
            f"Read-only inspection of '{table_name}' ({row_count} rows) and live EXPLAIN plan ({plan_summary}) "
            f"confirmed a full table scan because no existing index covers predicates ({', '.join(where_cols)}) "
            f"and sort key ({', '.join(order_specs)})."
        )

        buffer_analysis = (
            f"Full scan across {row_count} rows forces every query execution to read unindexed table pages before "
            f"filtering and sorting. Adding composite index {index_name} with covering columns ({', '.join(include_cols)}) "
            f"converts the execution plan into a direct B-Tree Index Scan."
        )

        return {
            "plan_tree_diagnosis": plan_diagnosis,
            "cost_and_buffer_analysis": buffer_analysis,
            "strategy": "COMPOSITE_COVERING_INDEX" if include_cols else "COMPOSITE_INDEX",
            "index_name": index_name,
            "indexed_columns": indexed_columns,
            "include_columns": include_cols,
            "ddl_script": safe_ddl,
            "expected_impact": "Eliminates full table scan and sort step via composite B-Tree lookup."
        }
