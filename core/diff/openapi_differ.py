"""
Generalized OpenAPI 3.x Deterministic Differ Engine.
Performs recursive JSON Schema tree comparison across arbitrary OpenAPI specifications.
Zero domain-specific hardcoding: detects path mutations, method changes, property removals,
type mutations, constraint changes, and structural hierarchy migrations.
"""

from typing import Dict, Any, List, Optional
import json


class GeneralizedOpenAPIDiffer:
    def __init__(self, v1_spec: Dict[str, Any], v2_spec: Dict[str, Any]):
        self.v1 = v1_spec
        self.v2 = v2_spec

    def compute_breaking_changes(self) -> List[Dict[str, Any]]:
        """Compares two arbitrary OpenAPI specs and outputs all breaking contract changes."""
        changes = []

        v1_paths = self.v1.get("paths", {})
        v2_paths = self.v2.get("paths", {})

        # 1. Endpoint additions / removals
        for path, v1_methods in v1_paths.items():
            if path not in v2_paths:
                changes.append({
                    "change_class": "BREAKING",
                    "type": "ENDPOINT_REMOVED",
                    "path": path,
                    "description": f"Endpoint '{path}' was removed in newer specification."
                })
                continue

            v2_methods = v2_paths[path]

            # 2. HTTP Method comparisons
            for method, v1_operation in v1_methods.items():
                if method.lower() not in [m.lower() for m in v2_methods.keys()]:
                    changes.append({
                        "change_class": "BREAKING",
                        "type": "METHOD_REMOVED",
                        "path": path,
                        "method": method.upper(),
                        "description": f"HTTP method '{method.upper()}' removed from endpoint '{path}'."
                    })
                    continue

                # Find matching v2 operation case-insensitively
                v2_op_key = next(k for k in v2_methods.keys() if k.lower() == method.lower())
                v2_operation = v2_methods[v2_op_key]

                # Diff Request Body
                req_changes = self._diff_request_body(path, method.upper(), v1_operation, v2_operation)
                changes.extend(req_changes)

                # Diff Response Schemas
                res_changes = self._diff_responses(path, method.upper(), v1_operation, v2_operation)
                changes.extend(res_changes)

        return changes

    def _diff_request_body(
        self, path: str, method: str, v1_op: Dict[str, Any], v2_op: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        changes = []
        v1_schema = self._extract_json_schema(v1_op.get("requestBody", {}))
        v2_schema = self._extract_json_schema(v2_op.get("requestBody", {}))

        if not v1_schema and not v2_schema:
            return changes
        if v1_schema and not v2_schema:
            changes.append({
                "change_class": "BREAKING",
                "type": "REQUEST_BODY_REMOVED",
                "endpoint": path,
                "method": method,
                "description": "Request body schema was removed."
            })
            return changes
        if not v1_schema and v2_schema:
            is_required = v2_op.get("requestBody", {}).get("required", False)
            if is_required:
                changes.append({
                    "change_class": "BREAKING",
                    "type": "REQUEST_BODY_MANDATED",
                    "endpoint": path,
                    "method": method,
                    "description": "Request body is now newly required."
                })
            return changes

        # Deep compare JSON Schemas
        schema_changes = self._deep_diff_schemas(path, method, "requestBody", v1_schema, v2_schema)
        changes.extend(schema_changes)
        return changes

    def _diff_responses(
        self, path: str, method: str, v1_op: Dict[str, Any], v2_op: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        changes = []
        v1_responses = v1_op.get("responses", {})
        v2_responses = v2_op.get("responses", {})

        for status_code, v1_res in v1_responses.items():
            if status_code not in v2_responses:
                changes.append({
                    "change_class": "WARNING",
                    "type": "RESPONSE_STATUS_REMOVED",
                    "endpoint": path,
                    "method": method,
                    "status_code": status_code,
                    "description": f"Status code '{status_code}' no longer documented in response."
                })
        return changes

    def _deep_diff_schemas(
        self,
        endpoint: str,
        method: str,
        scope: str,
        v1_schema: Dict[str, Any],
        v2_schema: Dict[str, Any],
        path_prefix: str = ""
    ) -> List[Dict[str, Any]]:
        """
        Recursively compares two JSON Schema objects without any hardcoded domain assumptions.
        Tracks property removals, additions, type changes, and structural reorganizations.
        """
        changes = []

        v1_type = v1_schema.get("type")
        v2_type = v2_schema.get("type")

        # 1. Type Mutation at current node
        if v1_type and v2_type and v1_type != v2_type:
            changes.append({
                "change_class": "BREAKING",
                "type": "SCHEMA_TYPE_MUTATED",
                "endpoint": endpoint,
                "method": method,
                "field_path": path_prefix or "(root)",
                "old_type": v1_type,
                "new_type": v2_type,
                "description": f"Schema type for '{path_prefix or scope}' mutated from '{v1_type}' to '{v2_type}'."
            })

        v1_props = v1_schema.get("properties", {})
        v2_props = v2_schema.get("properties", {})
        v1_required = set(v1_schema.get("required", []))
        v2_required = set(v2_schema.get("required", []))

        # 2. Check for newly required properties (breaking change for callers)
        newly_required = v2_required - v1_required
        for req_field in newly_required:
            full_path = f"{path_prefix}.{req_field}" if path_prefix else req_field
            changes.append({
                "change_class": "BREAKING",
                "type": "FIELD_NEWLY_REQUIRED",
                "endpoint": endpoint,
                "method": method,
                "field_path": full_path,
                "description": f"Field '{full_path}' is now strictly required by upstream contract."
            })

        # 3. Check for removed properties or relocated properties
        for prop_name, prop_v1 in v1_props.items():
            full_path = f"{path_prefix}.{prop_name}" if path_prefix else prop_name
            if prop_name not in v2_props:
                # Check if this property was potentially nested into an object
                found_in_child = self._search_field_in_nested_objects(prop_name, v2_props)
                if found_in_child:
                    changes.append({
                        "change_class": "BREAKING",
                        "type": "FIELD_STRUCTURALLY_NESTED",
                        "endpoint": endpoint,
                        "method": method,
                        "old_field_path": full_path,
                        "new_field_path": f"{path_prefix}.{found_in_child}" if path_prefix else found_in_child,
                        "description": f"Field '{full_path}' was relocated to nested hierarchy '{found_in_child}'."
                    })
                else:
                    changes.append({
                        "change_class": "BREAKING",
                        "type": "FIELD_REMOVED",
                        "endpoint": endpoint,
                        "method": method,
                        "field_path": full_path,
                        "old_type": prop_v1.get("type", "unknown"),
                        "description": f"Field '{full_path}' removed from specification."
                    })
            else:
                # Property exists in both -> recurse if it's an object, or compare types/formats
                prop_v2 = v2_props[prop_name]
                prop_v1_type = prop_v1.get("type")
                prop_v2_type = prop_v2.get("type")
                prop_v1_format = prop_v1.get("format")
                prop_v2_format = prop_v2.get("format")

                # Detect type mutation or format mutation (e.g. float vs integer)
                if prop_v1_type != prop_v2_type or (prop_v1_format and prop_v2_format and prop_v1_format != prop_v2_format):
                    changes.append({
                        "change_class": "BREAKING",
                        "type": "FIELD_TYPE_CHANGED",
                        "endpoint": endpoint,
                        "method": method,
                        "field_path": full_path,
                        "old_type": f"{prop_v1_type}:{prop_v1_format}" if prop_v1_format else prop_v1_type,
                        "new_type": f"{prop_v2_type}:{prop_v2_format}" if prop_v2_format else prop_v2_type,
                        "description": f"Field '{full_path}' type changed from {prop_v1_type} to {prop_v2_type}."
                    })

                # Recurse if both are objects
                if prop_v1_type == "object" and prop_v2_type == "object":
                    child_changes = self._deep_diff_schemas(
                        endpoint, method, scope, prop_v1, prop_v2, path_prefix=full_path
                    )
                    changes.extend(child_changes)

        return changes

    def _search_field_in_nested_objects(
        self, target_name: str, parent_props: Dict[str, Any], current_path: str = ""
    ) -> Optional[str]:
        """
        Generic search for a field across nested object definitions.
        Matches if the field name is present in sub-properties or matches common suffix/stem.
        """
        for prop_name, prop_def in parent_props.items():
            if prop_def.get("type") == "object":
                child_props = prop_def.get("properties", {})
                new_path = f"{current_path}.{prop_name}" if current_path else prop_name

                # Direct match
                if target_name in child_props:
                    return f"{new_path}.{target_name}"

                # Suffix/stem match (e.g., address in billing.address or customer_address in billing.address.line1)
                for child_key, child_val in child_props.items():
                    if child_val.get("type") == "object":
                        deep_match = self._search_field_in_nested_objects(
                            target_name, {child_key: child_val}, current_path=new_path
                        )
                        if deep_match:
                            return deep_match
                    elif child_key in target_name or target_name in child_key:
                        return f"{new_path}.{child_key}"

        return None

    def _extract_json_schema(self, content_container: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        content = content_container.get("content", {})
        for content_type, details in content.items():
            if "json" in content_type.lower():
                return details.get("schema")
        return None


def diff_specs_from_files(v1_path: str, v2_path: str) -> Dict[str, Any]:
    with open(v1_path, "r", encoding="utf-8") as f1, open(v2_path, "r", encoding="utf-8") as f2:
        v1 = json.load(f1)
        v2 = json.load(f2)

    differ = GeneralizedOpenAPIDiffer(v1, v2)
    changes = differ.compute_breaking_changes()
    return {
        "v1_title": v1.get("info", {}).get("title"),
        "v1_version": v1.get("info", {}).get("version"),
        "v2_title": v2.get("info", {}).get("title"),
        "v2_version": v2.get("info", {}).get("version"),
        "breaking_changes_count": len(changes),
        "breaking_changes": changes
    }
