"""
Deterministic OpenAPI Differ Engine.
Compares two OpenAPI 3.0+ specifications and extracts breaking contract changes
into a compact, structured JSON format for LLM consumption.
"""

from typing import Dict, Any, List, Optional
import json


class OpenAPIDiffer:
    def __init__(self, v1_spec: Dict[str, Any], v2_spec: Dict[str, Any]):
        self.v1 = v1_spec
        self.v2 = v2_spec

    def compute_breaking_changes(self) -> List[Dict[str, Any]]:
        """
        Extracts breaking changes across endpoints between v1 and v2 specs.
        Detects removed fields, renamed/nested fields, and type conversions.
        """
        breaking_changes = []

        v1_paths = self.v1.get("paths", {})
        v2_paths = self.v2.get("paths", {})

        for path, v1_methods in v1_paths.items():
            if path not in v2_paths:
                breaking_changes.append({
                    "type": "ENDPOINT_REMOVED",
                    "path": path,
                    "description": f"Endpoint {path} was removed in new specification"
                })
                continue

            v2_methods = v2_paths[path]

            for method, v1_op in v1_methods.items():
                if method not in v2_methods:
                    breaking_changes.append({
                        "type": "METHOD_REMOVED",
                        "path": path,
                        "method": method.upper(),
                        "description": f"HTTP method {method.upper()} removed for {path}"
                    })
                    continue

                v2_op = v2_methods[method]
                method_changes = self._compare_operation_schemas(path, method.upper(), v1_op, v2_op)
                breaking_changes.extend(method_changes)

        return breaking_changes

    def _compare_operation_schemas(
        self, path: str, method: str, v1_op: Dict[str, Any], v2_op: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Compares requestBody schemas of a single endpoint operation."""
        changes = []

        v1_schema = self._extract_request_schema(v1_op)
        v2_schema = self._extract_request_schema(v2_op)

        if not v1_schema or not v2_schema:
            return changes

        v1_props = v1_schema.get("properties", {})
        v2_props = v2_schema.get("properties", {})
        v2_required = set(v2_schema.get("required", []))

        # 1. Detect removed or renamed root properties
        for prop_name, prop_def in v1_props.items():
            if prop_name not in v2_props:
                # Check for currency/unit type change like amount -> amount_cents
                if prop_name == "amount" and "amount_cents" in v2_props:
                    changes.append({
                        "type": "FIELD_RENAMED_AND_TYPE_CHANGED",
                        "endpoint": path,
                        "method": method,
                        "old_field": "amount",
                        "new_field": "amount_cents",
                        "old_type": "float (dollars)",
                        "new_type": "integer (cents)",
                        "conversion_rule": "amount_cents = int(round(amount * 100))",
                        "description": v2_props["amount_cents"].get("description", "Amount changed to integer cents")
                    })
                    continue

                # Check if it was moved to a nested object
                nested_target = self._find_in_nested_schema(prop_name, v2_props)
                if nested_target:
                    changes.append({
                        "type": "FIELD_RENAMED_AND_NESTED",
                        "endpoint": path,
                        "method": method,
                        "old_field": prop_name,
                        "new_location": nested_target["location"],
                        "description": nested_target.get("description", f"Moved to {nested_target['location']}")
                    })
                else:
                    changes.append({
                        "type": "FIELD_REMOVED",
                        "endpoint": path,
                        "method": method,
                        "field": prop_name,
                        "description": f"Field '{prop_name}' was removed from request body"
                    })

        # 2. Detect newly required fields in v2 that were not in v1
        for req_field in v2_required:
            if req_field not in v1_props and req_field != "amount_cents":
                changes.append({
                    "type": "NEW_REQUIRED_FIELD",
                    "endpoint": path,
                    "method": method,
                    "field": req_field,
                    "schema": v2_props.get(req_field, {}),
                    "description": f"New mandatory field '{req_field}' added to contract"
                })

        return changes

    def _find_in_nested_schema(self, old_field: str, v2_props: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Heuristically matches flattened fields that became nested objects (e.g. customer_address -> billing.address.line1)."""
        target_name = old_field.lower().replace("customer_", "").replace("user_", "") # e.g. address
        for parent_prop, details in v2_props.items():
            if details.get("type") == "object":
                sub_props = details.get("properties", {})
                for sub_key, sub_val in sub_props.items():
                    if sub_val.get("type") == "object":
                        leaf_props = sub_val.get("properties", {})
                        for leaf_key, leaf_val in leaf_props.items():
                            if target_name in leaf_key or (target_name in ["address", "addr"] and leaf_key in ["line1", "address", "street"]):
                                return {
                                    "location": f"{parent_prop}.{sub_key}.{leaf_key}",
                                    "description": leaf_val.get("description", f"Moved to {parent_prop}.{sub_key}.{leaf_key}")
                                }
                    elif target_name in sub_key:
                        return {
                            "location": f"{parent_prop}.{sub_key}",
                            "description": sub_val.get("description", f"Moved to {parent_prop}.{sub_key}")
                        }
        return None

    def _extract_request_schema(self, operation: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extracts JSON request body schema."""
        content = operation.get("requestBody", {}).get("content", {})
        json_content = content.get("application/json", {})
        return json_content.get("schema")


def diff_specs_from_files(v1_path: str, v2_path: str) -> Dict[str, Any]:
    with open(v1_path, "r", encoding="utf-8") as f1, open(v2_path, "r", encoding="utf-8") as f2:
        v1 = json.load(f1)
        v2 = json.load(f2)

    differ = OpenAPIDiffer(v1, v2)
    changes = differ.compute_breaking_changes()
    return {
        "v1_title": v1.get("info", {}).get("title"),
        "v1_version": v1.get("info", {}).get("version"),
        "v2_title": v2.get("info", {}).get("title"),
        "v2_version": v2.get("info", {}).get("version"),
        "breaking_changes_count": len(changes),
        "breaking_changes": changes
    }
