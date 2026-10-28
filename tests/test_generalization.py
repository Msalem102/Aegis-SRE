"""
Generalization Verification Suite.
Proves that Aegis SRE's Vector A (Database) and Vector B (API Contract) pipelines
work on completely unseen schemas, tables, queries, and OpenAPI specifications
with zero domain-specific hardcoding.
"""

import os
import tempfile
import pytest

from core.diff.openapi_differ import GeneralizedOpenAPIDiffer
from core.db.inspector import ReadOnlyDatabaseInspector
from core.db.safety_guard import DDLSafetyGuard
from core.llm.muse_db_client import MuseDBClient
from core.sandbox.db_sandbox import DatabaseSandbox


def test_vector_b_differ_on_unseen_logistics_api():
    """Tests GeneralizedOpenAPIDiffer on an unseen Logistics / Shipment API."""
    v1_spec = {
        "openapi": "3.0.3",
        "info": {"title": "Global Logistics API", "version": "1.0.0"},
        "paths": {
            "/v1/shipments/dispatch": {
                "post": {
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["shipment_id", "warehouse_code", "weight_kg"],
                                    "properties": {
                                        "shipment_id": {"type": "string"},
                                        "warehouse_code": {"type": "string"},
                                        "weight_kg": {"type": "number", "format": "float"}
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    v2_spec = {
        "openapi": "3.0.3",
        "info": {"title": "Global Logistics API", "version": "2.0.0"},
        "paths": {
            "/v1/shipments/dispatch": {
                "post": {
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["shipment_id", "origin", "weight_grams"],
                                    "properties": {
                                        "shipment_id": {"type": "string"},
                                        "weight_grams": {"type": "integer"},
                                        "origin": {
                                            "type": "object",
                                            "required": ["warehouse"],
                                            "properties": {
                                                "warehouse": {
                                                    "type": "object",
                                                    "required": ["code"],
                                                    "properties": {
                                                        "code": {"type": "string"}
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    differ = GeneralizedOpenAPIDiffer(v1_spec, v2_spec)
    changes = differ.compute_breaking_changes()

    change_types = {c["type"] for c in changes}
    assert "FIELD_STRUCTURALLY_NESTED" in change_types
    assert "FIELD_NEWLY_REQUIRED" in change_types
    assert "FIELD_REMOVED" in change_types

    nested_change = next(c for c in changes if c["type"] == "FIELD_STRUCTURALLY_NESTED")
    assert nested_change["old_field_path"] == "warehouse_code"
    assert nested_change["new_field_path"] == "origin.warehouse.code"


def test_vector_a_pipeline_on_unseen_security_audit_table():
    """
    Tests ReadOnlyDatabaseInspector, MuseDBClient, DDLSafetyGuard, and DatabaseSandbox
    on a completely unseen 'security_audit_logs' table and query.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        schema_path = os.path.join(tmp_dir, "audit_schema.sql")
        db_path = os.path.join(tmp_dir, "audit_live.db")

        with open(schema_path, "w", encoding="utf-8") as f:
            f.write("""
            CREATE TABLE IF NOT EXISTS security_audit_logs (
                event_id BIGSERIAL PRIMARY KEY,
                tenant_id BIGINT NOT NULL,
                event_status VARCHAR(32) NOT NULL,
                payload_amount NUMERIC(10, 2) NOT NULL,
                logged_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                actor_ip TEXT
            );
            """)

        query = (
            "SELECT event_id, tenant_id, event_status, payload_amount, logged_at "
            "FROM security_audit_logs "
            "WHERE tenant_id = $1 AND event_status = $2 "
            "ORDER BY logged_at DESC LIMIT $3"
        )
        params = [42819, "completed", 25]

        # 1. Read-Only Inspection
        inspector = ReadOnlyDatabaseInspector(schema_sql_path=schema_path, row_count=30000)
        inspector.ensure_database_initialized(db_path)
        inspection = inspector.inspect_outage_context(query, sample_params=params)

        assert inspection["read_only_verified"] is True
        assert inspection["table_catalog"]["table_name"] == "security_audit_logs"
        assert inspection["explain_plan"]["is_sequential_scan"] is True

        # 2. DDL Synthesis on unseen table
        muse_db = MuseDBClient()
        synthesis = muse_db.synthesize_database_remediation(
            outage_alert={"error_message": "P99 timeout on security_audit_logs"},
            query=inspection["executable_query"],
            table_catalog=inspection["table_catalog"],
            raw_explain_plan=inspection["explain_plan"]
        )

        assert "security_audit_logs" in synthesis["index_name"]
        assert "tenant_id" in synthesis["indexed_columns"]
        assert "event_status" in synthesis["indexed_columns"]
        assert any("logged_at" in col for col in synthesis["indexed_columns"])
        assert "payload_amount" in synthesis["include_columns"]

        # 3. Safety Gate Validation
        is_safe, violations = DDLSafetyGuard.validate_ddl(synthesis["ddl_script"])
        assert is_safe is True, f"Unexpected violations: {violations}"

        # 4. Real Ephemeral DB Sandbox Execution
        sandbox = DatabaseSandbox(source_db_path=db_path)
        sb_result = sandbox.verify_ddl_and_replay_query(
            ddl_script=synthesis["ddl_script"],
            executable_query=inspection["executable_query"],
            baseline_inspection=inspection
        )

        assert sb_result["deterministic_gate_passed"] is True
        assert sb_result["converted_to_index_scan"] is True
        assert sb_result["latency_reduction_percent"] >= 80.0
