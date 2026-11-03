"""
Unit & Integration Tests for Aegis SRE Web UI and Control Plane API.
Verifies:
  - GET / (serves HTML single-page application dashboard)
  - GET /static/logo.png (serves brand logo asset)
  - GET /api/status (system status, watchdog state, service name)
  - GET /api/services (discovers available project manifests)
  - GET /api/config (retrieves active manifest)
  - POST /api/config/validate (runs architectural compliance linter)
  - GET /api/incidents (lists historical incidents & post-mortems)
"""

from fastapi.testclient import TestClient
from core.webhooks.listener import create_webhook_app


def test_ui_and_control_plane_endpoints():
    app = create_webhook_app(config_path="mockstore_aegis.yaml", enable_db_watchdog=False)
    client = TestClient(app)

    # 1. Root dashboard route
    resp_root = client.get("/")
    assert resp_root.status_code == 200
    assert "text/html" in resp_root.headers.get("content-type", "")
    assert "Aegis SRE" in resp_root.text
    assert "Manrope" in resp_root.text

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

    # 4. Services list API
    resp_services = client.get("/api/services")
    assert resp_services.status_code == 200
    services_data = resp_services.json()
    assert "services" in services_data
    assert len(services_data["services"]) >= 1

    # 4b. Service switching API
    resp_select = client.post("/api/services/select", json={"filename": "logistics_service_aegis.yaml"})
    assert resp_select.status_code == 200
    select_data = resp_select.json()
    assert select_data["service"] == "logistics-delivery-service"
    assert select_data["repository"] == "ahmedharib/logistics-api"

    # Switch back to mockstore
    resp_switch_back = client.post("/api/services/select", json={"filename": "mockstore_aegis.yaml"})
    assert resp_switch_back.status_code == 200
    assert resp_switch_back.json()["service"] == "cupertino-coffee-store"

    # 4c. Service creation API
    resp_create = client.post("/api/services/create", json={
        "service_name": "test-microservice",
        "repository": "ahmedharib/test-microservice",
        "default_branch": "main",
        "db_engine": "postgres",
        "sla_latency": 600
    })
    assert resp_create.status_code == 200
    create_data = resp_create.json()
    assert create_data["status"] == "CREATED"
    assert create_data["service"] == "test-microservice"

    # Clean up test created file and switch back
    import os
    if os.path.exists("test-microservice_aegis.yaml"):
        os.remove("test-microservice_aegis.yaml")
    client.post("/api/services/select", json={"filename": "mockstore_aegis.yaml"})

    # 5. Config API
    resp_cfg = client.get("/api/config")
    assert resp_cfg.status_code == 200
    cfg_data = resp_cfg.json()
    assert cfg_data["project"]["service_name"] == "cupertino-coffee-store"

    # 6. Compliance validate API
    resp_val = client.post("/api/config/validate")
    assert resp_val.status_code == 200
    val_data = resp_val.json()
    assert "checks" in val_data
    assert "passed" in val_data

    # 7. Incidents history API
    resp_inc = client.get("/api/incidents")
    assert resp_inc.status_code == 200
    inc_data = resp_inc.json()
    assert inc_data["count"] >= 1
    assert any("PG-SEQSCAN" in inc["incident_id"] for inc in inc_data["incidents"])
