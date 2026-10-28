"""
Unit & Integration Tests for the Aegis Project Integration Contract (`aegis.yaml`).
Verifies schema parsing, architectural compliance checks (Read-Only DB mode,
Autonomous codebase scanning, and spec discovery).
"""

import os
import tempfile
from core.config.aegis_config import (
    AegisConfigLoader,
    AegisContractManifest,
    DatabaseIntegrationConfig,
    UpstreamAPIContractConfig,
    ProjectMetadataConfig
)


def test_load_and_validate_root_aegis_yaml():
    """Asserts that the repository's root `aegis.yaml` loads cleanly and passes 100% of contract checks."""
    manifest = AegisConfigLoader.load("aegis.yaml")
    assert manifest.version == "1.0"
    assert manifest.project.service_name == "novacart-ecommerce"
    assert manifest.database is not None
    assert manifest.database.require_read_only_mode is True
    assert len(manifest.upstream_apis) == 1
    assert manifest.upstream_apis[0].get_effective_spec() is not None
    assert manifest.upstream_apis[0].code_root == "src"

    report = AegisConfigLoader.validate_project_compliance(manifest, base_dir=".")
    assert report["passed"] is True, f"Expected root aegis.yaml to pass compliance, got errors: {report['errors']}"
    assert len(report["errors"]) == 0


def test_detects_read_only_database_violation():
    """Asserts that disabling read-only mode triggers a strict contract compliance failure."""
    manifest = AegisContractManifest(
        project=ProjectMetadataConfig(service_name="unsafe-app", repository="org/unsafe-app"),
        database=DatabaseIntegrationConfig(require_read_only_mode=False)
    )
    report = AegisConfigLoader.validate_project_compliance(manifest, base_dir=".")
    assert report["passed"] is False
    assert any("require_read_only_mode" in err for err in report["errors"])


def test_supports_pure_error_driven_inference_mode():
    """Asserts that projects can onboard with zero external spec URL (pure error inference)."""
    manifest = AegisContractManifest(
        project=ProjectMetadataConfig(service_name="pure-error-app", repository="org/pure-error-app"),
        upstream_apis=[
            UpstreamAPIContractConfig(
                name="third_party_opaque_api",
                spec_url=None,
                client_repo_root="scenarios/vector_b_contract/client_repo",
                code_root="src",
                test_target="tests"
            )
        ]
    )
    report = AegisConfigLoader.validate_project_compliance(manifest, base_dir=".")
    assert report["passed"] is True
    check_item = next(c for c in report["checks"] if "Upstream Contract Discovery" in c["name"])
    assert "Pure Error-Driven Schema Inference" in check_item["detail"]


def test_detects_test_file_isolation_violation():
    """Asserts that marking a test file as an editable client module is flagged as a violation."""
    manifest = AegisContractManifest(
        project=ProjectMetadataConfig(service_name="bad-client-app", repository="org/bad-client-app"),
        upstream_apis=[
            UpstreamAPIContractConfig(
                name="broken_gateway",
                spec_url="scenarios/vector_b_contract/upstream/openapi_v2_breaking.json",
                client_repo_root="scenarios/vector_b_contract/client_repo",
                isolated_client_modules=["tests/test_payment_client.py"],
                test_target="tests"
            )
        ]
    )
    report = AegisConfigLoader.validate_project_compliance(manifest, base_dir=".")
    assert report["passed"] is False
    assert any("Architectural violation" in err for err in report["errors"])


def test_starter_template_roundtrip():
    """Asserts that the generated starter template parses into a valid AegisContractManifest."""
    template_str = AegisConfigLoader.generate_starter_template()
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as tmp:
        tmp.write(template_str)
        tmp_path = tmp.name

    try:
        loaded = AegisConfigLoader.load(tmp_path)
        assert loaded.version == "1.0"
        assert loaded.database.require_read_only_mode is True
        assert len(loaded.upstream_apis) == 1
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
