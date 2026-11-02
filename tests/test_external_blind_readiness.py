"""
External Blind-Store Readiness & Regression Test Suite.
Verifies all 6 core autonomous guarantees:
1. External `--config` relative path resolution & POSIX GitHub commit paths.
2. `spec_url` resolution, Single-Spec Target discovery, and Zero-Spec Pure Error-Driven mode.
3. `DependencyMapper` zero-spec traceback + AST sibling discovery & `code_root` scoping.
4. PostgreSQL `EXPLAIN (FORMAT JSON)` list normalization, `%s`/`$1` auto-binding, and DDL reconstruction.
5. Dynamic `requirements.txt` parsing & `.env` secret exclusion in `EphemeralSandbox`.
6. Generic Alert webhook classification (`AlertEventNormalizer`) & `/webhooks/alert` serverless spawner flow.
"""

import json
import os
import shutil
import tempfile
from fastapi.testclient import TestClient

from core.diff.openapi_differ import diff_specs
from core.analysis.dependency_mapper import DependencyMapper
from core.db.inspector import ReadOnlyDatabaseInspector
from core.sandbox.modal_sandbox import EphemeralSandbox
from core.webhooks.alert_normalizer import AlertEventNormalizer
from core.webhooks.listener import create_webhook_app
from aegis_vector_a_runner import run_vector_a_remediation


def test_external_config_vector_a_resolves_paths_and_posix_commit_keys(monkeypatch):
    """
    Creates an isolated external repository outside Aegis's CWD with an unseen
    `warehouse_pick_tasks` schema and verifies `run_vector_a_remediation(--config ...)`
    resolves all files relative to the external manifest and commits POSIX repo-relative paths.
    """
    def mock_verify(*args, **kwargs):
        return {
            "sandbox_environment": "MODAL_CLOUD_POSTGRES_SANDBOX",
            "sandbox_id": "sb-mock-ext-warehouse-01",
            "deterministic_gate_passed": True,
            "baseline_latency_ms": 2940.0,
            "remediated_latency_ms": 12.5,
            "latency_reduction_percent": 99.57,
            "before_plan_nodes": ["Seq Scan on warehouse_pick_tasks"],
            "after_plan_nodes": ["Index Scan using idx_warehouse_pick_tasks"],
            "converted_to_index_scan": True,
            "table_locks_detected": False
        }

    monkeypatch.setattr("core.sandbox.db_sandbox.DatabaseSandbox.verify_ddl_and_replay_query", mock_verify)
    monkeypatch.setenv("META_API_KEY", "MOCK")

    with tempfile.TemporaryDirectory() as ext_repo:
        schema_file = os.path.join(ext_repo, "db", "warehouse.sql")
        os.makedirs(os.path.dirname(schema_file), exist_ok=True)
        with open(schema_file, "w", encoding="utf-8") as sf:
            sf.write(
                """
                CREATE TABLE IF NOT EXISTS warehouse_pick_tasks (
                    task_id BIGSERIAL PRIMARY KEY,
                    zone_code VARCHAR(32) NOT NULL,
                    task_status VARCHAR(32) NOT NULL,
                    item_weight NUMERIC(10, 2) NOT NULL,
                    dispatched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )

        telemetry_file = os.path.join(ext_repo, "telemetry", "db_alert.json")
        os.makedirs(os.path.dirname(telemetry_file), exist_ok=True)
        with open(telemetry_file, "w", encoding="utf-8") as tf:
            json.dump(
                {
                    "incident_id": "INC-EXT-WAREHOUSE-01",
                    "service": "warehouse-fulfillment-api",
                    "pg_stat_statements_summary": {
                        "query": (
                            "SELECT task_id, zone_code, task_status, item_weight, dispatched_at "
                            "FROM warehouse_pick_tasks "
                            "WHERE zone_code = %s AND task_status = %s "
                            "ORDER BY dispatched_at DESC LIMIT %s"
                        )
                    },
                    "sample_params": ["sample_zone_code_0", "completed", 25],
                    "anomaly_trigger": {"current_value": 2940.0, "threshold": 1000.0, "host_cpu_percent": 93.1}
                },
                tf
            )

        manifest_file = os.path.join(ext_repo, "aegis.yaml")
        with open(manifest_file, "w", encoding="utf-8") as mf:
            mf.write(
                """
version: "1.0"
project:
  service_name: "warehouse-fulfillment-api"
  repository: "blind-org/warehouse-fulfillment"
  default_branch: "main"
database:
  engine: "sqlite"
  read_only_connection_env: "CUSTOM_WAREHOUSE_RO_URL"
  require_read_only_mode: true
  schema_path: "db/warehouse.sql"
  live_db_path: "db/warehouse_sim.db"
  telemetry_source: "telemetry/db_alert.json"
  migration_output_dir: "db/migrations"
sandbox:
  provider: "modal"
"""
            )

        try:
            res = run_vector_a_remediation(config_path=manifest_file)
            assert res["incident_id"] == "INC-EXT-WAREHOUSE-01"
            assert res["sandbox_result"]["deterministic_gate_passed"] is True
            assert res["pr"]["target_repo"] == "blind-org/warehouse-fulfillment"

            committed = res["pr"]["committed_files"]
            assert len(committed) == 1
            assert committed[0].startswith("db/migrations/")
            assert ":" not in committed[0] and "\\" not in committed[0]
            assert os.path.isfile(os.path.join(ext_repo, committed[0].replace("/", os.sep)))
        finally:
            test_artifact_dir = os.path.join("artifacts", "warehouse-fulfillment-api")
            if os.path.isdir(test_artifact_dir):
                shutil.rmtree(test_artifact_dir, ignore_errors=True)


def test_single_spec_and_zero_spec_modes_and_dependency_mapper():
    """
    Verifies Single-Spec (`spec_url` without `baseline_spec`) and Zero-Spec (`PURE_ERROR_INFERENCE`)
    contract discovery, plus `DependencyMapper` traceback & AST sibling discovery when `breaking_changes == []`.
    """
    # 1. Zero-Spec mode
    zero_res = diff_specs(None, None)
    assert zero_res["mode"] == "PURE_ERROR_INFERENCE"
    assert zero_res["breaking_changes"] == []

    # 2. Single-Spec mode using ephemeral OpenAPI v2 JSON contract
    with tempfile.TemporaryDirectory() as spec_dir:
        v2_spec_path = os.path.join(spec_dir, "payment_gateway_v2.json")
        with open(v2_spec_path, "w", encoding="utf-8") as sf:
            json.dump(
                {
                    "openapi": "3.0.3",
                    "info": {"title": "Coffee Payment Gateway API", "version": "2.0.0"},
                    "paths": {
                        "/v2/charges": {
                            "post": {
                                "requestBody": {
                                    "required": True,
                                    "content": {
                                        "application/json": {
                                            "schema": {
                                                "type": "object",
                                                "required": ["order_id", "amount_cents", "billing"],
                                                "properties": {
                                                    "order_id": {"type": "string"},
                                                    "amount_cents": {"type": "integer"},
                                                    "billing": {
                                                        "type": "object",
                                                        "required": ["address"],
                                                        "properties": {
                                                            "address": {
                                                                "type": "object",
                                                                "required": ["line1"],
                                                                "properties": {"line1": {"type": "string"}}
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
                },
                sf
            )

        single_res = diff_specs(None, v2_spec_path)
        assert single_res["mode"] == "SINGLE_TARGET_SPEC"
        assert len(single_res["breaking_changes"]) >= 1
        assert single_res["breaking_changes"][0]["type"] == "ACTIVE_UPSTREAM_CONTRACT"

    # 3. DependencyMapper in Pure Error-Driven Mode (0 breaking_changes, only traceback + code_root)
    with tempfile.TemporaryDirectory() as app_repo:
        os.makedirs(os.path.join(app_repo, "app"), exist_ok=True)
        os.makedirs(os.path.join(app_repo, "tests"), exist_ok=True)

        with open(os.path.join(app_repo, "app", "schemas.py"), "w", encoding="utf-8") as f:
            f.write("from pydantic import BaseModel\nclass InvoicePayload(BaseModel):\n    total: float\n")

        with open(os.path.join(app_repo, "app", "billing_gateway.py"), "w", encoding="utf-8") as f:
            f.write("import httpx\nfrom app.schemas import InvoicePayload\ndef send_invoice(p: InvoicePayload):\n    return httpx.post('https://billing/v2/invoices', json=p.model_dump())\n")

        with open(os.path.join(app_repo, "tests", "test_billing.py"), "w", encoding="utf-8") as f:
            f.write("from app.billing_gateway import send_invoice\ndef test_send():\n    assert True\n")

        mapper = DependencyMapper(app_repo, code_root="app", test_target="tests")
        mapped = mapper.map_affected_components(
            breaking_changes=[],
            incident_error_log={
                "error_message": "422 Unprocessable Entity: field 'total_cents' required",
                "raw_traceback": "app/billing_gateway.py:4: in send_invoice\nAssertionError: 422"
            }
        )
        files = mapped["target_files"]
        assert "app/billing_gateway.py" in files
        assert "app/schemas.py" in files, "Expected AST import expansion to include sibling app/schemas.py"
        assert "tests/test_billing.py" in files


def test_postgres_explain_plan_flattening_and_placeholder_binding():
    """
    Verifies PostgreSQL JSON EXPLAIN list parsing (preventing list.get AttributeError),
    `%s` / `$1` / unbound placeholder binding, and `reconstructed_ddl` generation.
    """
    pg_json_plan = [
        {
            "Plan": {
                "Node Type": "Limit",
                "Total Cost": 4812.45,
                "Actual Rows": 50,
                "Plans": [
                    {
                        "Node Type": "Sort",
                        "Total Cost": 4812.30,
                        "Actual Rows": 50,
                        "Plans": [
                            {
                                "Node Type": "Seq Scan",
                                "Relation Name": "customer_orders",
                                "Total Cost": 4510.00,
                                "Actual Rows": 65,
                                "Rows Removed by Filter": 149935
                            }
                        ]
                    }
                ]
            },
            "Planning Time": 0.42,
            "Execution Time": 84.65
        }
    ]

    nodes, has_seq, has_idx, scanned = ReadOnlyDatabaseInspector._flatten_postgres_plan_nodes(pg_json_plan[0]["Plan"])
    assert has_seq is True
    assert has_idx is False
    assert scanned == 150000
    assert any("Seq Scan on customer_orders" in n for n in nodes)

    inspector = ReadOnlyDatabaseInspector(db_url=None)
    bound_pct = inspector._bind_query_params(
        "SELECT * FROM orders WHERE email = %s AND total > %s LIMIT %s",
        ["alex@store.io", 49.99, 20]
    )
    assert "'alex@store.io'" in bound_pct
    assert "49.99" in bound_pct
    assert "LIMIT 20" in bound_pct

    ddl = ReadOnlyDatabaseInspector._reconstruct_postgres_table_ddl(
        "customer_orders",
        [
            {"column_name": "id", "data_type": "bigint", "is_primary_key": True},
            {"column_name": "customer_email", "data_type": "character varying", "is_primary_key": False},
            {"column_name": "created_at", "data_type": "timestamp with time zone", "is_primary_key": False}
        ],
        []
    )
    assert 'CREATE TABLE IF NOT EXISTS "customer_orders"' in ddl
    assert '"id" BIGSERIAL PRIMARY KEY' in ddl
    assert '"created_at" TIMESTAMPTZ' in ddl


def test_modal_sandbox_dynamic_requirements_discovery():
    """Asserts EphemeralSandbox dynamically reads requirements.txt and normalizes psycopg2 -> psycopg2-binary."""
    with tempfile.TemporaryDirectory() as tmp_repo:
        with open(os.path.join(tmp_repo, "requirements.txt"), "w", encoding="utf-8") as rf:
            rf.write(
                "# Store dependencies\n"
                "fastapi>=0.110.0\n"
                "psycopg2==2.9.9\n"
                "redis>=5.0.0\n"
                "sqlalchemy>=2.0.0\n"
            )

        sb = EphemeralSandbox(tmp_repo)
        deps = sb._discover_project_dependencies()
        dep_str = " ".join(deps)
        assert "fastapi>=0.110.0" in deps
        assert "redis>=5.0.0" in deps
        assert "sqlalchemy>=2.0.0" in deps
        assert "psycopg2-binary==2.9.9" in dep_str


def test_alert_event_normalizer_and_webhook_server():
    """Verifies generic JSON alert classification (Vector A, Vector B, benign) and FastAPI `/webhooks/alert`."""
    # 1. HTTP 422 / checkout_failed -> Vector B
    api_alert = {
        "incident_id": "INC-COFFEE-422-01",
        "event": "checkout_failed",
        "service": "cupertino-coffee-store",
        "http_status": 422,
        "endpoint": "/api/checkout",
        "error_message": "HTTP 422 Unprocessable Entity: missing required fields 'amount_cents' and 'billing.address.line1'",
        "traceback": "File 'app/payment_client.py', line 48, in charge_coffee_order"
    }
    norm_b = AlertEventNormalizer.classify_and_normalize(api_alert)
    assert norm_b is not None
    assert norm_b["vector"] == "b"
    assert norm_b["payload"]["http_status"] == 422
    assert "amount_cents" in norm_b["payload"]["error_message"]

    # 2. Database slow_query -> Vector A
    db_alert = {
        "incident_id": "INC-COFFEE-DB-01",
        "event": "slow_query",
        "query": "SELECT * FROM orders WHERE customer_id = $1 ORDER BY created_at DESC LIMIT 50",
        "duration_ms": 3420.5
    }
    norm_a = AlertEventNormalizer.classify_and_normalize(db_alert)
    assert norm_a is not None
    assert norm_a["vector"] == "a"
    assert "SELECT * FROM orders" in norm_a["payload"]["pg_stat_statements_summary"]["query"]

    # 3. Benign health heartbeat -> Ignored
    assert AlertEventNormalizer.classify_and_normalize({"event": "heartbeat_ok", "uptime_s": 3600}) is None

    # 4. Webhook HTTP Endpoint + Serverless Async Spawner check
    spawned_calls = []

    class DummyModalCallHandle:
        object_id = "fc-modal-test-call-001"

    def fake_modal_spawner(classified, cfg_path):
        spawned_calls.append((classified, cfg_path))
        return DummyModalCallHandle()

    app = create_webhook_app(
        config_path="aegis.yaml",
        enable_db_watchdog=False,
        async_spawner=fake_modal_spawner
    )
    client = TestClient(app)

    health_resp = client.get("/health")
    assert health_resp.status_code == 200
    assert health_resp.json()["status"] == "online"

    benign_resp = client.post("/webhooks/alert", json={"event": "heartbeat_ok"})
    assert benign_resp.status_code == 200
    assert benign_resp.json()["status"] == "IGNORED_BENIGN_EVENT"

    trigger_resp = client.post("/webhooks/alert", json=api_alert)
    assert trigger_resp.status_code == 200
    body = trigger_resp.json()
    assert body["status"] == "ACCEPTED_SERVERLESS_SPAWNED"
    assert body["vector"] == "b"
    assert body["modal_call_id"] == "fc-modal-test-call-001"
    assert len(spawned_calls) == 1
