"""
Generalized PostgreSQL Execution Plan Tree Analyzer.
Recursively inspects any arbitrary EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) output tree.
Zero hardcoding: isolates sequential scan bottlenecks, cost hotspots, buffer cache read spills,
and extracts target filter/sort columns for indexing recommendations.
"""

from typing import Dict, Any, List, Optional
import re


class ExecutionPlanAnalyzer:
    def __init__(self, raw_explain_json: Any):
        # Format JSON returns a list of plan objects or a single dict
        if isinstance(raw_explain_json, list) and len(raw_explain_json) > 0:
            self.root = raw_explain_json[0]
        elif isinstance(raw_explain_json, dict):
            self.root = raw_explain_json
        else:
            raise ValueError("Invalid EXPLAIN JSON payload format")

        self.plan_tree = self.root.get("Plan", {})
        self.planning_time = self.root.get("Planning Time", 0.0)
        self.execution_time = self.root.get("Execution Time", 0.0)

    def analyze_plan(self) -> Dict[str, Any]:
        """Traverses the full execution plan tree and extracts structured diagnostic bottlenecks."""
        bottlenecks: List[Dict[str, Any]] = []
        table_scans: List[Dict[str, Any]] = []
        sort_nodes: List[Dict[str, Any]] = []

        total_shared_read = 0
        total_shared_hit = 0

        def traverse(node: Dict[str, Any], depth: int = 0):
            nonlocal total_shared_read, total_shared_hit

            node_type = node.get("Node Type", "Unknown")
            rel_name = node.get("Relation Name")
            actual_time = node.get("Actual Total Time", 0.0)
            actual_rows = node.get("Actual Rows", 0)
            read_blocks = node.get("Shared Read Blocks", 0)
            hit_blocks = node.get("Shared Hit Blocks", 0)

            total_shared_read += read_blocks
            total_shared_hit += hit_blocks

            # 1. Identify Sequential Scan Hotspots
            if node_type == "Seq Scan" and rel_name:
                filter_cond = node.get("Filter")
                rows_removed = node.get("Rows Removed by Filter", 0)
                extracted_cols = self._extract_columns_from_condition(filter_cond) if filter_cond else []

                scan_info = {
                    "node_type": node_type,
                    "table_name": rel_name,
                    "actual_time_ms": actual_time,
                    "actual_rows": actual_rows,
                    "rows_removed_by_filter": rows_removed,
                    "shared_read_blocks": read_blocks,
                    "shared_hit_blocks": hit_blocks,
                    "filter_condition": filter_cond,
                    "filter_columns": extracted_cols
                }
                table_scans.append(scan_info)

                if rows_removed > 1000 or actual_time > 100.0:
                    bottlenecks.append({
                        "severity": "CRITICAL",
                        "type": "EXPENSIVE_SEQUENTIAL_SCAN",
                        "table": rel_name,
                        "time_spent_ms": actual_time,
                        "rows_filtered_out": rows_removed,
                        "description": f"Sequential scan on '{rel_name}' scanned and discarded {rows_removed} rows."
                    })

            # 2. Identify Disk Buffer Read Spills
            if read_blocks > 1000:
                bottlenecks.append({
                    "severity": "HIGH",
                    "type": "BUFFER_CACHE_SPILL",
                    "table": rel_name or "unknown",
                    "read_blocks": read_blocks,
                    "description": f"Node {node_type} caused {read_blocks} physical disk page reads."
                })

            # 3. Identify In-Memory / External Sort Hotspots
            if node_type == "Sort":
                sort_keys = node.get("Sort Key", [])
                sort_method = node.get("Sort Method", "")
                sort_nodes.append({
                    "sort_keys": sort_keys,
                    "sort_method": sort_method,
                    "actual_time_ms": actual_time
                })

            # Recurse child plans
            child_plans = node.get("Plans", [])
            for child in child_plans:
                traverse(child, depth + 1)

        traverse(self.plan_tree)

        # Compute buffer cache hit ratio across whole query
        total_blocks = total_shared_read + total_shared_hit
        cache_hit_ratio = (total_shared_hit / total_blocks) if total_blocks > 0 else 1.0

        return {
            "execution_time_ms": self.execution_time,
            "planning_time_ms": self.planning_time,
            "total_shared_read_blocks": total_shared_read,
            "total_shared_hit_blocks": total_shared_hit,
            "overall_cache_hit_ratio": round(cache_hit_ratio, 4),
            "bottlenecks": bottlenecks,
            "table_scans": table_scans,
            "sort_nodes": sort_nodes,
            "is_unindexed_scan": any(s["node_type"] == "Seq Scan" for s in table_scans)
        }

    def _extract_columns_from_condition(self, condition: str) -> List[str]:
        """
        Extracts column names from arbitrary PostgreSQL condition expressions.
        Handles nested parentheses, type casts, and comparison operators.
        e.g. ((user_id = 42819) AND ((status)::text = 'completed'::text)) -> ['user_id', 'status']
        """
        # Strip PostgreSQL type casts (e.g. ::text, ::int)
        cleaned = re.sub(r"::[a-zA-Z0-9_]+", "", condition)
        # Normalize parentheses to whitespace
        cleaned = re.sub(r"[\(\)]", " ", cleaned)
        # Match identifier followed by comparison operator
        pattern = r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*(?:=|!=|<>|<=|>=|<|>|LIKE|ILIKE|IN)\s"
        matches = re.findall(pattern, cleaned, re.IGNORECASE)
        # Exclude SQL keywords
        sql_keywords = {"true", "false", "null", "and", "or", "not", "case", "when", "then"}
        return list(dict.fromkeys([m for m in matches if m.lower() not in sql_keywords]))
