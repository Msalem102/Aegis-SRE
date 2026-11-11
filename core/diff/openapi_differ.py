"""
Generalized OpenAPI 3.x Deterministic Differ & Live Spec Loader Engine.
Performs recursive JSON Schema tree comparison across arbitrary OpenAPI specifications.
Supports:
1. Two-Spec Structural AST Diff (baseline_spec vs spec_url — local JSON/YAML or live HTTP/HTTPS URL).
2. Single-Spec Target Contract Extraction (live spec_url without requiring a cached v1 spec).
3. Zero-Spec Pure Error-Driven Inference (when upstream API provides no OpenAPI document).
Zero domain-specific hardcoding.
"""

from typing import Dict, Any, List, Optional
import json
import os
import httpx
import yaml


def _dereference_spec(raw_spec: Dict[str, Any]) -> Dict[str, Any]:
    """Resolves internal JSON Schema `$ref` pointers cleanly via jsonref."""
    try:
        import jsonref
        return jsonref.replace_refs(raw_spec, proxies=False)
    except Exception:
        return raw_spec


def load_openapi_spec(source: str) -> Dict[str, Any]:
    """Loads an OpenAPI 3.x / Swagger specification from a live HTTP(S) URL or local JSON/YAML file."""
    if source.startswith(("http://", "https://")):
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            resp = client.get(source)
            resp.raise_for_status()
            text = resp.text
            try:
                raw = resp.json()
            except Exception:
                raw = yaml.safe_load(text)
        return _dereference_spec(raw or {})

    if not os.path.exists(source):
        raise FileNotFoundError(f"OpenAPI specification file not found: {source}")

    with open(source, "r", encoding="utf-8") as f:
        text = f.read()
        if source.lower().endswith((".yaml", ".yml")):
            raw = yaml.safe_load(text)
        else:
            try:
                raw = json.loads(text)
            except Exception:
                raw = yaml.safe_load(text)
    return _dereference_spec(raw or {})


class GeneralizedOpenAPIDiffer:
    def __init__(self, v1_spec: Dict[str, Any], v2_spec: Dict[str, Any]):
        self.v1 = _dereference_spec(v1_spec)
        self.v2 = _dereference_spec(v2_spec)

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
                    "endpoint": path,
                    "path": path,
                    "description": f"Endpoint '{path}' was removed in newer specification."
                })
                continue

            v2_methods = v2_paths[path]

            # 2. HTTP Method comparisons
            for method, v1_operation in v1_methods.items():
                if not isinstance(v1_operation, dict):
                    continue
                if method.lower() not in [m.lower() for m in v2_methods.keys()]:
                    changes.append({
                        "change_class": "BREAKING",
                        "type": "METHOD_REMOVED",
                        "endpoint": path,
                        "path": path,
                        "method": method.upper(),
                        "description": f"HTTP method '{method.upper()}' removed from endpoint '{path}'."
                    })
                    continue

                # Find matching v2 operation case-insensitively
                v2_op_key = next(k for k in v2_methods.keys() if k.lower() == method.lower())
                v2_operation = v2_methods[v2_op_key]
                if not isinstance(v2_operation, dict):
                    continue

                # Diff Request Body
                req_changes = self._diff_request_body(path, method.upper(), v1_operation, v2_operation)
                changes.extend(req_changes)

                # Diff Response Schemas
                res_changes = self._diff_responses(path, method.upper(), v1_operation, v2_operation)
                changes.extend(res_changes)

        return changes

    def extract_target_contract_summary(self) -> List[Dict[str, Any]]:
        """
        Extracts active endpoint schemas from `v2_spec` when no baseline `v1_spec` is provided
        (Single-Spec Live Discovery Mode).
        """
        contracts: List[Dict[str, Any]] = []
        v2_paths = self.v2.get("paths", {})
        for path, methods in v2_paths.items():
            if not isinstance(methods, dict):
                continue
            for method, operation in methods.items():
                if method.lower() not in {"get", "post", "put", "patch", "delete"} or not isinstance(operation, dict):
                    continue
                req_schema = self._extract_json_schema(operation.get("requestBody", {}))
                if req_schema:
                    leaf_paths = self._collect_required_leaf_paths(req_schema, "")
                    clean_leaves = [lp.lstrip(".") for lp in leaf_paths if lp.lstrip(".")]
                    contracts.append({
                        "change_class": "TARGET_SCHEMA",
                        "type": "ACTIVE_UPSTREAM_CONTRACT",
                        "endpoint": path,
                        "method": method.upper(),
                        "required_fields": req_schema.get("required", []),
                        "required_leaf_paths": clean_leaves,
                        "request_schema": req_schema,
                        "description": (
                            f"Active upstream contract for {method.upper()} {path} requires fields: "
                            f"{clean_leaves or list(req_schema.get('properties', {}).keys())}"
                        )
                    })
        return contracts

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
            req_schema = v2_props.get(req_field, {})
            leaf_paths = self._collect_required_leaf_paths(req_schema, full_path)
            changes.append({
                "change_class": "BREAKING",
                "type": "FIELD_NEWLY_REQUIRED",
                "endpoint": endpoint,
                "method": method,
                "field_path": full_path,
                "required_leaf_paths": leaf_paths,
                "new_type": req_schema.get("type", "unknown"),
                "description": f"Field '{full_path}' (leaf paths: {leaf_paths}) is now strictly required by upstream contract."
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

    def _collect_required_leaf_paths(self, schema_node: Dict[str, Any], prefix: str) -> List[str]:
        """Recursively collects all required leaf property paths under a schema node."""
        if schema_node.get("type") != "object":
            return [prefix] if prefix else []
        props = schema_node.get("properties", {})
        reqs = schema_node.get("required", list(props.keys()))
        leaves = []
        for r in reqs:
            child_node = props.get(r, {})
            next_prefix = f"{prefix}.{r}" if prefix else r
            leaves.extend(self._collect_required_leaf_paths(child_node, next_prefix))
        return leaves or ([prefix] if prefix else [])

    def _search_field_in_nested_objects(
        self, target_name: str, parent_props: Dict[str, Any], current_path: str = ""
    ) -> Optional[str]:
        """
        Generic search for a relocated field across nested object definitions.
        Matches if the field name or its underscore tokens match a nested object or leaf property.
        """
        target_tokens = [t for t in target_name.lower().split("_") if len(t) > 2]

        for prop_name, prop_def in parent_props.items():
            if prop_def.get("type") == "object":
                child_props = prop_def.get("properties", {})
                new_path = f"{current_path}.{prop_name}" if current_path else prop_name

                # Direct match on leaf
                if target_name in child_props:
                    return f"{new_path}.{target_name}"

                for child_key, child_val in child_props.items():
                    child_full = f"{new_path}.{child_key}"
                    if child_val.get("type") == "object":
                        deep_match = self._search_field_in_nested_objects(
                            target_name, {child_key: child_val}, current_path=new_path
                        )
                        if deep_match:
                            return deep_match
                        # If the nested object key itself matches a token of target_name, resolve to its primary required leaf
                        if child_key.lower() in target_tokens:
                            leaves = self._collect_required_leaf_paths(child_val, child_full)
                            if leaves:
                                return leaves[0]
                    elif child_key.lower() in target_tokens or target_name.lower() in child_key.lower():
                        return child_full

        return None

    def _extract_json_schema(self, content_container: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        content = content_container.get("content", {})
        for content_type, details in content.items():
            if "json" in content_type.lower() and isinstance(details, dict):
                return details.get("schema")
        return None


def diff_specs(v1_source: Optional[str] = None, v2_source: Optional[str] = None) -> Dict[str, Any]:
    """
    Universal contract discovery entrypoint:
    - If both v1_source and v2_source exist -> computes exact structural AST diff (TWO_SPEC_DIFF).
    - If only v2_source exists -> extracts active target schemas from live URL/file (SINGLE_TARGET_SPEC).
    - If neither exists -> returns clean Pure Error-Driven Inference context (PURE_ERROR_INFERENCE).
    """
    if v1_source and v2_source:
        v1 = load_openapi_spec(v1_source)
        v2 = load_openapi_spec(v2_source)
        differ = GeneralizedOpenAPIDiffer(v1, v2)
        changes = differ.compute_breaking_changes()
        return {
            "mode": "TWO_SPEC_DIFF",
            "v1_title": v1.get("info", {}).get("title", "Baseline Spec"),
            "v1_version": v1.get("info", {}).get("version", "v1"),
            "v2_title": v2.get("info", {}).get("title", "Target Spec"),
            "v2_version": v2.get("info", {}).get("version", "v2"),
            "breaking_changes_count": len(changes),
            "breaking_changes": changes
        }

    if v2_source:
        v2 = load_openapi_spec(v2_source)
        differ = GeneralizedOpenAPIDiffer({}, v2)
        contracts = differ.extract_target_contract_summary()
        return {
            "mode": "SINGLE_TARGET_SPEC",
            "v1_title": None,
            "v1_version": None,
            "v2_title": v2.get("info", {}).get("title", "Upstream OpenAPI"),
            "v2_version": v2.get("info", {}).get("version", "latest"),
            "breaking_changes_count": len(contracts),
            "breaking_changes": contracts
        }

    return {
        "mode": "PURE_ERROR_INFERENCE",
        "v1_title": None,
        "v1_version": None,
        "v2_title": None,
        "v2_version": None,
        "breaking_changes_count": 0,
        "breaking_changes": []
    }


def diff_specs_from_files(v1_path: str, v2_path: str) -> Dict[str, Any]:
    """Backward-compatible wrapper around `diff_specs`."""
    return diff_specs(v1_path, v2_path)
