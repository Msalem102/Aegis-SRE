"""
Unit & Integration Tests for Aegis SRE Web UI, Control Plane API,
File-Mounted Sandbox Payload Transfer, and Vector B Surgical Patching.
"""

import json
import os
import tempfile
from fastapi.testclient import TestClient
from core.webhooks.listener import create_webhook_app
from core.llm.muse_client import MuseSparkClient


def test_ui_and_control_plane_endpoints():
    app = create_webhook_app(config_path="mockstore_aegis.yaml", enable_db_watchdog=False)
    client = TestClient(app)

    # 1. Root dashboard route & absence of fake preset apps
    resp_root = client.get("/")
    assert resp_root.status_code == 200
    assert "text/html" in resp_root.headers.get("content-type", "")
    assert "Aegis SRE" in resp_root.text
    assert "Manrope" in resp_root.text
    assert "logistics_service_aegis.yaml" not in resp_root.text
    assert "auth-service" not in resp_root.text
    assert "inventory-lite" not in resp_root.text

    # 1b. Service worker neutralizer
    resp_sw = client.get("/sw.js")
    assert resp_sw.status_code == 200
    assert "javascript" in resp_sw.headers.get("content-type", "")
    assert "unregister" in resp_sw.text

    # 2. Static asset route
    resp_logo = client.get("/static/logo.png")
    assert resp_logo.status_code == 200
    assert "image/png" in resp_logo.headers.get("content-type", "")

    # 3. Status API
    resp_status = client.get("/api/status")
    assert resp_status.status_code == 200
    status_data = resp_status.json()
    assert status_data["status"] == "online"
    assert status_data["service"] == "cupertino-coffee-store"

    # 4. Services list API (deduplicated real .yaml manifests only)
    resp_services = client.get("/api/services")
    assert resp_services.status_code == 200
    services_data = resp_services.json()
    assert "services" in services_data
    assert len(services_data["services"]) >= 1
    filenames = [s["filename"] for s in services_data["services"]]
    assert "logistics_service_aegis.yaml" not in filenames

    # 4b. Service creation via structured fields + upstream_apis (.yaml generation)
    try:
        resp_create = client.post("/api/services/create", json={
            "service_name": "test-microservice",
            "repository": "ahmedharib/mockStore",
            "default_branch": "master",
            "db_engine": "postgres",
            "sla_latency": 600,
            "api_name": "coffee_payment_gateway",
            "spec_url": "contracts/payment_gateway_v2.json",
            "test_target": "tests/test_payment_checkout.py"
        })
        assert resp_create.status_code == 200
        create_data = resp_create.json()
        assert create_data["status"] == "CREATED"
        assert create_data["service"] == "test-microservice"
        assert create_data["filename"] == "test-microservice_aegis.yaml"
        assert os.path.exists("test-microservice_aegis.yaml")

        # 4c. Switch between .yaml manifests
        resp_switch_back = client.post("/api/services/select", json={"filename": "mockstore_aegis.yaml"})
        assert resp_switch_back.status_code == 200
        assert resp_switch_back.json()["service"] == "cupertino-coffee-store"

        resp_select = client.post("/api/services/select", json={"filename": "test-microservice_aegis.yaml"})
        assert resp_select.status_code == 200
        assert resp_select.json()["service"] == "test-microservice"

        # 4d. Delete custom .yaml service manifest via API
        resp_del = client.post("/api/services/delete", json={"filename": "test-microservice_aegis.yaml"})
        assert resp_del.status_code == 200
        assert resp_del.json()["status"] == "DELETED"
        assert not os.path.exists("test-microservice_aegis.yaml")
    finally:
        if os.path.exists("test-microservice_aegis.yaml"):
            os.remove("test-microservice_aegis.yaml")
        client.post("/api/services/select", json={"filename": "mockstore_aegis.yaml"})

    # 5. Config API
    resp_cfg = client.get("/api/config")
    assert resp_cfg.status_code == 200
    cfg_data = resp_cfg.json()
    assert cfg_data["project"]["service_name"] == "cupertino-coffee-store"
    assert "raw_yaml" in cfg_data

    # 6. Compliance validate API
    resp_val = client.post("/api/config/validate")
    assert resp_val.status_code == 200
    val_data = resp_val.json()
    assert "checks" in val_data
    assert val_data["passed"] is True

    # 7. Incidents history API
    resp_inc = client.get("/api/incidents")
    assert resp_inc.status_code == 200
    inc_data = resp_inc.json()
    assert inc_data["count"] >= 1
    assert any("PG-SEQSCAN" in inc["incident_id"] for inc in inc_data["incidents"])


def test_sandbox_mounted_file_payload_transfer():
    """
    Verifies that Vector A and Vector B sandboxes stage payloads as mounted container
    files rather than passing large base64 strings via sys.argv CLI arguments.
    """
    from core.sandbox.db_sandbox import MODAL_POSTGRES_RUNNER, DatabaseSandbox
    import inspect
    from core.sandbox import modal_sandbox

    db_source = inspect.getsource(DatabaseSandbox._execute_modal_cloud_postgres_sandbox)
    assert "add_local_file" in db_source
    assert '"/root/payload.json"' in db_source

    modal_source = inspect.getsource(modal_sandbox.EphemeralSandbox._run_in_modal_cloud)
    assert "add_local_file" in modal_source
    assert '"/root/repo_bundle.zlib"' in modal_source

    # Verify MODAL_POSTGRES_RUNNER's load_sandbox_payload & split_sql_statements directly
    ns = {}
    exec(MODAL_POSTGRES_RUNNER.split("def main():")[0], ns)
    load_fn = ns["load_sandbox_payload"]
    split_sql_fn = ns["split_sql_statements"]

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tf:
        json.dump({"schema_sql": "CREATE TABLE t (id INT);", "query": "SELECT * FROM t"}, tf)
        temp_path = tf.name

    import sys
    orig_argv = sys.argv
    try:
        sys.argv = ["pg_runner.py", "--payload-file", temp_path]
        loaded = load_fn()
        assert loaded["query"] == "SELECT * FROM t"
    finally:
        sys.argv = orig_argv
        if os.path.exists(temp_path):
            os.remove(temp_path)

    # Verify PL/pgSQL DO blocks and GRANT statements are stripped cleanly
    raw_init_sql = """
    DO $do$
    BEGIN
       CREATE ROLE aegis_ro_monitor;
    END
    $do$;
    GRANT SELECT ON ALL TABLES IN SCHEMA public TO aegis_ro_monitor;
    CREATE TABLE orders (order_id SERIAL PRIMARY KEY, customer_id INT);
    """
    stmts = split_sql_fn(raw_init_sql)
    assert len(stmts) == 1
    assert "CREATE TABLE orders" in stmts[0]


def test_vector_b_surgical_patching_and_anti_truncation():
    """
    Verifies Vector B's surgical search/replace patching, unified diff application,
    large-file context slicing, and AST anti-truncation recovery.
    """
    client = MuseSparkClient(api_key="test-key")

    original_source = (
        "def helper_alpha(x: int) -> int:\n"
        "    return x + 1\n\n"
        "def build_payload(order_id: str, amount: float, currency: str) -> dict:\n"
        "    return {\n"
        "        'order_id': order_id,\n"
        "        'amount': amount,\n"
        "        'currency': currency,\n"
        "    }\n\n"
        "def helper_omega(y: str) -> str:\n"
        "    return y.strip()\n"
    )
    source_files = {"app/client.py": original_source}

    # 1. Surgical search/replace via file_patches
    parsed_response = {
        "file_patches": {
            "app/client.py": [
                {
                    "search": "        'amount': amount,",
                    "replace": "        'amount_cents': int(round(amount * 100)),"
                }
            ]
        },
        "refactored_files": {}
    }
    res1 = client.apply_surgical_patches_and_reconcile(source_files, parsed_response)
    patched = res1["refactored_files"]
    assert "'amount_cents': int(round(amount * 100))" in patched["app/client.py"]
    assert "def helper_alpha" in patched["app/client.py"]
    assert "def helper_omega" in patched["app/client.py"]
    assert res1["patch_strategy"] == "SURGICAL_PATCH"

    # 2. Anti-truncation AST guard when LLM omits unmodified top-level functions
    truncated_candidate = (
        "# ... rest of file unchanged ...\n"
        "def build_payload(order_id: str, amount: float, currency: str) -> dict:\n"
        "    return {\n"
        "        'order_id': order_id,\n"
        "        'amount_cents': int(round(amount * 100)),\n"
        "        'currency': currency,\n"
        "    }\n"
    )
    res2 = client.apply_surgical_patches_and_reconcile(
        source_files,
        {"file_patches": {}, "refactored_files": {"app/client.py": truncated_candidate}}
    )
    reconciled = res2["refactored_files"]
    assert "def helper_alpha" in reconciled["app/client.py"]
    assert "def helper_omega" in reconciled["app/client.py"]
    assert "'amount_cents': int(round(amount * 100))" in reconciled["app/client.py"]

    # 3. Large file routing to surgical mode
    large_file = "\n".join([f"def fn_{i}(x):\n    return x + {i}\n" for i in range(120)])
    views, large_files = client._prepare_prompt_file_views(
        {"app/large_module.py": large_file},
        [{"field_path": "amount_cents"}],
        {"error": "fn_50 failed"}
    )
    assert "app/large_module.py" in large_files
    assert "def fn_50" in views["app/large_module.py"]


def test_live_event_stream_and_telemetry():
    """
    Verifies that the Aegis SRE live event stream captures process runner output,
    exposes real-time logs via /api/logs, supports clearing, and streams events via SSE.
    """
    from core.webhooks.listener import get_global_stream_manager, enable_stream_capture

    app = create_webhook_app(config_path="mockstore_aegis.yaml", enable_db_watchdog=False)
    client = TestClient(app)

    # 1. Clear existing logs
    resp_clear = client.post("/api/logs/clear")
    assert resp_clear.status_code == 200
    assert resp_clear.json()["status"] == "CLEARED"

    resp_logs = client.get("/api/logs")
    assert resp_logs.status_code == 200
    data = resp_logs.json()
    assert data["count"] == 1
    assert "cleared" in data["logs"][0]["message"].lower()

    # 2. Log an event directly through the stream manager
    mgr = get_global_stream_manager()
    mgr.log("🚨 [Contention] Unindexed sequential scan surge detected on orders (+50000 reads)", log_type="surge", source="watchdog")
    mgr.log("[Vector A] Beginning sandbox execution in Modal Cloud...", log_type="step", source="vector_a")

    resp_logs_after = client.get("/api/logs")
    assert resp_logs_after.status_code == 200
    logs = resp_logs_after.json()["logs"]
    assert len(logs) >= 2
    assert any("sequential scan surge" in l["message"] and l["type"] == "surge" for l in logs)
    assert any("Vector A" in l["message"] for l in logs)

    # 3. Test since_id filter
    first_id = logs[0]["id"]
    resp_filtered = client.get(f"/api/logs?since_id={first_id}")
    assert resp_filtered.status_code == 200
    filtered_logs = resp_filtered.json()["logs"]
    assert all(l["id"] > first_id for l in filtered_logs)

    # 4. Test sys.stdout / sys.stderr tee capture & stream attribute compliance
    enable_stream_capture(mgr)
    import sys
    assert hasattr(sys.stdout, "encoding")
    assert isinstance(sys.stdout.encoding, str)
    assert hasattr(sys.stdout, "errors")
    assert hasattr(sys.stdout, "reconfigure")
    sys.stdout.reconfigure(encoding="utf-8")
    assert sys.stdout.writable() is True

    test_line = "[Vector B] Running pytest suite in container: test_payment_checkout.py"
    print(test_line)

    resp_logs_tee = client.get("/api/logs")
    assert resp_logs_tee.status_code == 200
    tee_logs = resp_logs_tee.json()["logs"]
    assert any("Running pytest suite in container" in l["message"] for l in tee_logs)

    # 5. Test SSE stream headers and initial backlog delivery
    with client.stream("GET", "/api/stream/events") as stream_resp:
        assert stream_resp.status_code == 200
        assert "text/event-stream" in stream_resp.headers.get("content-type", "")
        lines = []
        for line in stream_resp.iter_lines():
            if line:
                lines.append(line)
                if len(lines) >= 2:
                    break
        assert any("data:" in l for l in lines)


