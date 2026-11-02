"""
Aegis SRE Project Integration Contract (`aegis.yaml`) Parser & Compliance Validator.
Enables any external repository or service to onboard onto Aegis SRE:
1. Database Layer: Read-Only Database Inspection access (`mode=ro`) + SLA thresholds.
   Supports live PostgreSQL catalog introspection & slow-query discovery or local schema/telemetry files.
2. API Layer: Autonomous codebase scanning (no manual client file listing required) +
   live OpenAPI spec URL, local spec file, or pure error-driven inference from HTTP 4xx/5xx logs.
3. Continuous Monitoring Layer: Scale-to-zero Modal Serverless Alert Webhooks & Direct Read-Only DB Watchdog.
"""

from typing import List, Dict, Any, Optional
import os
import json
import yaml
from pydantic import BaseModel, Field


LIVE_TELEMETRY_MODES = {"auto", "webhook", "pg_stat_statements"}
LIVE_SCHEMA_MODES = {"auto", "live", "information_schema"}


class SLAThresholdsConfig(BaseModel):
    p99_latency_ms: float = Field(default=1500.0, gt=0)
    max_cpu_percent: float = Field(default=80.0, gt=0, le=100.0)
    min_sandbox_speedup_percent: float = Field(default=80.0, gt=0, le=100.0)


class DatabaseIntegrationConfig(BaseModel):
    engine: str = Field(default="postgres", description="Database engine: postgres or sqlite")
    read_only_connection_env: str = Field(default="DATABASE_RO_URL")
    connection_url: Optional[str] = Field(default=None, description="Direct database connection URL (or use read_only_connection_env)")
    require_read_only_mode: bool = Field(default=True)
    schema_path: Optional[str] = Field(
        default="auto",
        description="Optional path to schema.sql, or 'auto' to introspect live PostgreSQL catalog via read-only connection"
    )
    live_db_path: Optional[str] = Field(
        default=None,
        description="Optional SQLite database file path when inspecting an external SQLite database"
    )
    telemetry_source: Optional[str] = Field(
        default="auto",
        description="Telemetry source: 'auto' (live pg_stat_statements / pg_stat_user_tables), 'webhook', or path to JSON alert"
    )
    migration_output_dir: str = Field(default="migrations")
    sla_thresholds: SLAThresholdsConfig = Field(default_factory=SLAThresholdsConfig)
    max_healing_retries: int = Field(default=3, ge=1, le=5)


class UpstreamAPIContractConfig(BaseModel):
    name: str = Field(description="Identifier for the upstream API dependency")
    spec_url: Optional[str] = Field(
        default=None,
        description="Remote URL or path to upstream OpenAPI spec. If omitted, Aegis uses pure error-driven inference from HTTP 4xx/5xx logs."
    )
    baseline_spec: Optional[str] = Field(
        default=None,
        description="Optional URL or path to cached baseline OpenAPI spec"
    )
    target_spec: Optional[str] = Field(
        default=None,
        description="Alias for spec_url (backward compatibility)"
    )
    client_repo_root: str = Field(
        default=".",
        description="Root directory of the downstream service repository"
    )
    code_root: Optional[str] = Field(
        default=None,
        description="Subdirectory to scan for API callers (e.g. 'src', 'app'). If omitted, scans client_repo_root."
    )
    isolated_client_modules: Optional[List[str]] = Field(
        default=None,
        description="Optional list of client files. If omitted, DependencyMapper autonomously scans code_root."
    )
    test_target: str = Field(default="tests", description="Test directory or file for sandbox verification")
    max_healing_retries: int = Field(default=3, ge=1, le=5)

    def get_effective_spec(self) -> Optional[str]:
        return self.spec_url or self.target_spec


class ObservabilityConfig(BaseModel):
    provider: str = Field(default="direct", description="Monitoring mode: direct (PostgreSQL catalog & alert webhook) or webhook")
    watchdog_interval_seconds: int = Field(default=60, ge=5, le=3600)


class SandboxConfig(BaseModel):
    provider: str = Field(default="modal", description="Execution provider: modal (Modal Cloud micro-VMs) or postgres (dedicated PostgreSQL URL)")
    app_name: str = Field(default="aegis-sre")
    timeout_seconds: int = Field(default=120, ge=10, le=600)


class ProjectMetadataConfig(BaseModel):
    service_name: str = Field(default="cupertino-coffee-store")
    repository: str = Field(default="meta-sre/cupertino-coffee")
    default_branch: str = Field(default="main")
    code_dir: Optional[str] = Field(default=None, description="Path to target project directory when config is stored externally")
    read_only_source: bool = Field(default=False, description="When True, Aegis will never write reports or migrations to code_dir; outputs are saved to workspace artifacts")


class AegisContractManifest(BaseModel):
    version: str = Field(default="1.0")
    project: ProjectMetadataConfig = Field(default_factory=ProjectMetadataConfig)
    database: Optional[DatabaseIntegrationConfig] = None
    upstream_apis: List[UpstreamAPIContractConfig] = Field(default_factory=list)
    observability: Optional[ObservabilityConfig] = None
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)


class AegisConfigLoader:
    """Loads, parses, and validates `aegis.yaml` project integration manifests."""

    DEFAULT_MANIFEST_PATH = "aegis.yaml"

    @staticmethod
    def resolve_path(base_dir: str, path_or_url: Optional[str]) -> Optional[str]:
        """Resolves a manifest-relative path against `aegis.yaml`'s directory, preserving URLs & live mode keywords."""
        if not path_or_url:
            return None
        stripped = path_or_url.strip()
        if stripped.lower() in (LIVE_TELEMETRY_MODES | LIVE_SCHEMA_MODES):
            return stripped
        if stripped.startswith(("http://", "https://")):
            return stripped
        if os.path.isabs(stripped):
            return os.path.normpath(stripped)
        return os.path.normpath(os.path.join(base_dir, stripped))

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> AegisContractManifest:
        path = config_path or cls.DEFAULT_MANIFEST_PATH
        if not os.path.exists(path):
            raise FileNotFoundError(f"Aegis contract manifest not found at: {path}")

        with open(path, "r", encoding="utf-8") as f:
            raw_data = yaml.safe_load(f) or {}

        return AegisContractManifest(**raw_data)

    @classmethod
    def load_or_default(cls, config_path: Optional[str] = None) -> AegisContractManifest:
        path = config_path or cls.DEFAULT_MANIFEST_PATH
        if os.path.exists(path):
            try:
                return cls.load(path)
            except Exception:
                pass
        return AegisContractManifest(
            database=DatabaseIntegrationConfig(
                schema_path="auto",
                telemetry_source="auto",
            )
        )

    @classmethod
    def validate_project_compliance(
        cls,
        manifest: AegisContractManifest,
        base_dir: str = "."
    ) -> Dict[str, Any]:
        """
        Verifies that the target project satisfies all Aegis SRE architectural contracts:
        1. Read-Only DB access mandate (`require_read_only_mode=True`) and valid schema/telemetry configuration.
        2. Autonomous API discovery (verifies code_root exists with source files, no forced client file micromanagement).
        3. Spec resolution (supports live spec URL, local spec path, or zero-spec error-driven inference).
        """
        checks: List[Dict[str, Any]] = []
        errors: List[str] = []

        if manifest.project.code_dir:
            base_dir = cls.resolve_path(base_dir, manifest.project.code_dir) or base_dir

        # 1. Project Metadata Check
        if manifest.project.service_name and "/" in manifest.project.repository:
            checks.append({
                "category": "PROJECT_METADATA",
                "name": f"Service '{manifest.project.service_name}' ({manifest.project.repository})",
                "passed": True,
                "detail": f"Target branch: {manifest.project.default_branch}"
            })
        else:
            msg = "Project repository must follow 'owner/repo' format."
            errors.append(msg)
            checks.append({
                "category": "PROJECT_METADATA",
                "name": "Repository Format",
                "passed": False,
                "detail": msg
            })

        # 2. Database Integration Contract Checks
        if manifest.database:
            db = manifest.database
            if not db.require_read_only_mode:
                msg = "Database integration contract requires 'require_read_only_mode: true' to guarantee zero production write risk."
                errors.append(msg)
                checks.append({
                    "category": "DATABASE_CONTRACT",
                    "name": "Strict Read-Only Mode (mode=ro)",
                    "passed": False,
                    "detail": msg
                })
            else:
                checks.append({
                    "category": "DATABASE_CONTRACT",
                    "name": "Strict Read-Only Mode (mode=ro)",
                    "passed": True,
                    "detail": f"Enforced via env '{db.read_only_connection_env}' ({db.engine})"
                })

            if not db.schema_path or db.schema_path.strip().lower() in LIVE_SCHEMA_MODES:
                checks.append({
                    "category": "DATABASE_CONTRACT",
                    "name": "Database Schema Definition",
                    "passed": True,
                    "detail": "Live Read-Only Catalog Introspection enabled (information_schema / pg_indexes)"
                })
            else:
                schema_full = cls.resolve_path(base_dir, db.schema_path)
                if schema_full and os.path.exists(schema_full):
                    checks.append({
                        "category": "DATABASE_CONTRACT",
                        "name": "Database Schema Definition",
                        "passed": True,
                        "detail": f"Found {db.schema_path}"
                    })
                else:
                    msg = f"Database schema file missing: {db.schema_path}"
                    errors.append(msg)
                    checks.append({
                        "category": "DATABASE_CONTRACT",
                        "name": "Database Schema Definition",
                        "passed": False,
                        "detail": msg
                    })

            if not db.telemetry_source or db.telemetry_source.strip().lower() in LIVE_TELEMETRY_MODES:
                mode_label = db.telemetry_source or "auto"
                checks.append({
                    "category": "DATABASE_CONTRACT",
                    "name": "Observability Telemetry Hook",
                    "passed": True,
                    "detail": (
                        f"Live telemetry discovery enabled ({mode_label}) "
                        f"(SLAs: P99 <= {db.sla_thresholds.p99_latency_ms}ms, CPU <= {db.sla_thresholds.max_cpu_percent}%)"
                    )
                })
            else:
                telemetry_full = cls.resolve_path(base_dir, db.telemetry_source)
                if telemetry_full and os.path.exists(telemetry_full):
                    checks.append({
                        "category": "DATABASE_CONTRACT",
                        "name": "Observability Telemetry Hook",
                        "passed": True,
                        "detail": (
                            f"Found {db.telemetry_source} "
                            f"(SLAs: P99 <= {db.sla_thresholds.p99_latency_ms}ms, CPU <= {db.sla_thresholds.max_cpu_percent}%)"
                        )
                    })
                else:
                    msg = f"Database telemetry source missing: {db.telemetry_source}"
                    errors.append(msg)
                    checks.append({
                        "category": "DATABASE_CONTRACT",
                        "name": "Observability Telemetry Hook",
                        "passed": False,
                        "detail": msg
                    })

        # 3. Autonomous API Contract Checks
        for api in manifest.upstream_apis:
            repo_full = cls.resolve_path(base_dir, api.client_repo_root) or base_dir
            if not os.path.isdir(repo_full):
                msg = f"[{api.name}] Client repository root directory not found: {api.client_repo_root}"
                errors.append(msg)
                checks.append({
                    "category": "API_CONTRACT",
                    "name": f"API Repository Root ({api.name})",
                    "passed": False,
                    "detail": msg
                })
                continue

            # Check Code Root & Autonomous Discovery
            scan_target_rel = api.code_root or "."
            scan_target_full = os.path.join(repo_full, scan_target_rel)
            if os.path.exists(scan_target_full):
                py_files = []
                for root, dirs, files in os.walk(scan_target_full):
                    dirs[:] = [d for d in dirs if d not in {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules"}]
                    for f in files:
                        if f.endswith(".py"):
                            py_files.append(os.path.relpath(os.path.join(root, f), repo_full))
                checks.append({
                    "category": "API_CONTRACT",
                    "name": f"{api.name} - Autonomous Codebase Scanning",
                    "passed": True,
                    "detail": f"Targeting '{scan_target_rel}' ({len(py_files)} source files discovered for AST mapping, zero manual file listing required)"
                })
            else:
                msg = f"[{api.name}] Code root directory not found: {scan_target_rel}"
                errors.append(msg)
                checks.append({
                    "category": "API_CONTRACT",
                    "name": f"{api.name} - Autonomous Codebase Scanning",
                    "passed": False,
                    "detail": msg
                })

            # Check Spec Resolution Mode (URL, local file, or pure error inference)
            effective_spec = api.get_effective_spec()
            if effective_spec:
                if effective_spec.startswith(("http://", "https://")):
                    checks.append({
                        "category": "API_CONTRACT",
                        "name": f"{api.name} - Upstream Contract Discovery",
                        "passed": True,
                        "detail": f"Live spec subscription configured: {effective_spec}"
                    })
                else:
                    spec_full = cls.resolve_path(base_dir, effective_spec)
                    if spec_full and os.path.exists(spec_full):
                        try:
                            with open(spec_full, "r", encoding="utf-8") as sf:
                                spec_obj = json.load(sf) if spec_full.endswith(".json") else yaml.safe_load(sf)
                            ver = spec_obj.get("info", {}).get("version", "unknown")
                            checks.append({
                                "category": "API_CONTRACT",
                                "name": f"{api.name} - Upstream Contract Discovery",
                                "passed": True,
                                "detail": f"OpenAPI specification verified (v{ver}) at {effective_spec}"
                            })
                        except Exception as e:
                            msg = f"[{api.name}] Failed to parse spec at {effective_spec}: {e}"
                            errors.append(msg)
                            checks.append({
                                "category": "API_CONTRACT",
                                "name": f"{api.name} - Upstream Contract Discovery",
                                "passed": False,
                                "detail": msg
                            })
                    else:
                        msg = f"[{api.name}] Spec file not found: {effective_spec}"
                        errors.append(msg)
                        checks.append({
                            "category": "API_CONTRACT",
                            "name": f"{api.name} - Upstream Contract Discovery",
                            "passed": False,
                            "detail": msg
                        })
            else:
                checks.append({
                    "category": "API_CONTRACT",
                    "name": f"{api.name} - Upstream Contract Discovery",
                    "passed": True,
                    "detail": "Pure Error-Driven Schema Inference enabled (no external spec URL required)"
                })

            # Check Optional Isolated Modules (only if explicitly specified)
            if api.isolated_client_modules:
                for mod_rel in api.isolated_client_modules:
                    if "test" in os.path.basename(mod_rel).lower():
                        msg = f"[{api.name}] Architectural violation: Test file '{mod_rel}' cannot be listed as an editable client module."
                        errors.append(msg)
                        checks.append({
                            "category": "API_CONTRACT",
                            "name": f"{api.name} - Client Isolation Rule",
                            "passed": False,
                            "detail": msg
                        })

            # Check Test Suite Target
            test_full = os.path.join(repo_full, api.test_target)
            if os.path.exists(test_full):
                checks.append({
                    "category": "API_CONTRACT",
                    "name": f"{api.name} - Verification Test Suite",
                    "passed": True,
                    "detail": f"Found test suite target '{api.test_target}'"
                })
            else:
                msg = f"[{api.name}] Verification test target '{api.test_target}' not found in {api.client_repo_root}"
                errors.append(msg)
                checks.append({
                    "category": "API_CONTRACT",
                    "name": f"{api.name} - Verification Test Suite",
                    "passed": False,
                    "detail": msg
                })

        return {
            "passed": len(errors) == 0,
            "manifest_version": manifest.version,
            "service_name": manifest.project.service_name,
            "checks": checks,
            "errors": errors
        }

    @classmethod
    def generate_starter_template(cls) -> str:
        """Returns a documented starter `aegis.yaml` template for onboarding new projects."""
        return """# =============================================================================
# Aegis SRE — Project Integration Contract Manifest (aegis.yaml)
# =============================================================================
# Any service adhering to this manifest can be autonomously monitored, diagnosed,
# sandboxed, and remediated by Aegis SRE (powered by Meta Muse Spark & Modal).

version: "1.0"

project:
  service_name: "my-production-service"
  repository: "your-org/your-repo"
  default_branch: "main"

# -----------------------------------------------------------------------------
# Continuous Monitoring & Direct Watchdog
# -----------------------------------------------------------------------------
observability:
  provider: "direct"
  watchdog_interval_seconds: 60

# -----------------------------------------------------------------------------
# Vector A: Database Performance & Zero-Downtime Indexing Contract
# Requirement: PostgreSQL with strictly Read-Only inspection access
# -----------------------------------------------------------------------------
database:
  engine: "postgres"
  read_only_connection_env: "DATABASE_RO_URL"
  require_read_only_mode: true
  # Set to 'auto' to introspect live Postgres schema & pg_stat_statements directly:
  schema_path: "auto"
  telemetry_source: "auto"
  migration_output_dir: "migrations"
  max_healing_retries: 3
  sla_thresholds:
    p99_latency_ms: 1500.0
    max_cpu_percent: 80.0
    min_sandbox_speedup_percent: 80.0

# -----------------------------------------------------------------------------
# Vector B: Upstream API Contract Drift Auto-Remediation
# Requirement: Autonomous AST mapping across code_root (no manual file listing)
# -----------------------------------------------------------------------------
upstream_apis:
  - name: "upstream_gateway"
    # Live OpenAPI spec URL, local file, or omit to infer drift purely from 4xx error logs:
    spec_url: "https://api.gateway.internal/openapi.json"
    client_repo_root: "."
    code_root: "app"
    test_target: "tests"
    max_healing_retries: 3

# -----------------------------------------------------------------------------
# Ephemeral Sandbox Verification Gate (Modal Cloud Serverless Micro-VMs)
# -----------------------------------------------------------------------------
sandbox:
  provider: "modal"
  app_name: "aegis-sre"
  timeout_seconds: 120
"""
