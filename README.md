# 🛡️ Aegis SRE — Autonomous Closed-Loop Site Reliability Engineering Agent

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Meta Muse Spark](https://img.shields.io/badge/Meta%20AI-Muse%20Spark%201.2-purple.svg)](https://api.meta.ai/)
[![Modal Cloud Serverless](https://img.shields.io/badge/Serverless-Modal%20Scale--to--Zero-brightgreen.svg)](https://modal.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Hackathon: Meta Global AI](https://img.shields.io/badge/Hackathon-Meta%20Global%20AI%20Developer-orange.svg)](https://metaglobalai.devpost.com/)

**Aegis SRE** is an enterprise-grade, closed-loop Site Reliability Engineering agent built for the **Meta Global AI Developer Hackathon**. Powered by **Meta Muse Spark** reasoning and **Modal Cloud serverless micro-VMs**, Aegis autonomously detects production database bottlenecks and API contract breaking changes, synthesizes self-healing fixes, and deterministically validates every patch in isolated cloud sandboxes before opening ready-to-merge GitHub Pull Requests with full post-mortem reports.

---

## 🚀 The Core Philosophy: The Deterministic Sandbox Mandate

Most AI coding assistants propose untested code and hope for the best. In production infrastructure, this causes secondary outages, table lock cascades, and broken dependencies.

Aegis SRE operates under the **Deterministic Sandbox Mandate**:
> **No patch or SQL migration is EVER delivered to GitHub without passing an isolated ephemeral cloud micro-VM verification gate with exit code 0 or deterministic $\ge$80% query latency reduction.**

Offline simulations and local SQLite fallbacks have been permanently removed. Aegis executes 100% cloud-native verification against real PostgreSQL 16 servers and Linux micro-containers.

```
       [ Production Alert Webhook OR Live PostgreSQL Watchdog Surge ]
                                     │
                                     ▼
            [ Read-Only Telemetry & Catalog ] (readonly=True, ZERO prod write risk)
                                     │
                                     ▼
                   [ Meta Muse Spark Reasoning Core ] (AST Analysis & Patch Synthesis)
                                     │
                                     ▼
                        [ Production Safety Gate ] (Enforces lock_timeout & CONCURRENTLY)
                                     │
                                     ▼
  ┌─────────────────────────────────────────────────────────────────────┐
  │            ☁️ Modal Cloud Ephemeral Sandbox Micro-VM                │
  │  • Spawns clean PostgreSQL 16 / Linux micro-VM in cloud             │
  │  • Replicates schema + seeds realistic synthetic rows               │
  │  • Executes candidate DDL / runs target pytest suite                │
  │  • Measures EXPLAIN (ANALYZE, BUFFERS) speedup ratio                │
  └─────────────────────────────────────────────────────────────────────┘
                                     │
                         Gate Passed? (>=80% speedup / Exit Code 0)
                         ├── ❌ NO  ──> Feed traceback back to Muse Spark (Self-Healing Loop)
                         └── ✅ YES ──> Open Ready-to-Merge Atomic GitHub PR + Post-Mortem Report
```

---

## ⚡ Two Remediation Vectors

### 1. Vector A: Database Performance & Zero-Downtime Indexing
* **Trigger:** Sequential scan saturation, CPU spikes (>80%), HTTP 504 timeouts, or P99 latency breaches (>1000ms).
* **Detection:** Direct read-only inspection via `pg_stat_statements` and `pg_stat_user_tables` sequential scan analysis + AST code scanner.
* **Autonomous Query Discovery:** Aegis scans target Python codebases via AST to locate the offending `SELECT ... FROM ... WHERE ...` queries (zero hardcoded SQL).
* **Safety:** Strictly read-only connection enforced at driver session level (`readonly=True`).
* **Synthesis:** Meta Muse Spark identifies missing composite/covering indexes and predicate ordering (equality $\rightarrow$ sort keys $\rightarrow$ `INCLUDE` covering columns).
* **Safety Envelope:** `DDLSafetyGuard` mandates:
  - `SET statement_timeout = '30s';`
  - `SET lock_timeout = '5s';` (prevents table lock queues behind long transactions)
  - `CREATE INDEX CONCURRENTLY IF NOT EXISTS ...`
* **Verification:** Provisions an ephemeral Modal Cloud micro-VM running PostgreSQL 16, replicates multi-table schemas, seeds tens of thousands of rows with realistic cardinality, executes the migration, and evaluates median execution times across 5 runs of `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`.
* **Delivery:** Generates a timestamped SQL migration artifact, authors a Markdown incident post-mortem, and opens an atomic GitHub Pull Request.

### 2. Vector B: Upstream API Contract Drift Remediation
* **Trigger:** HTTP 400/422 Unprocessable Entity errors, inbound JSON alert webhooks (`/webhooks/alert`), or failing verification test suites.
* **Discovery:** Supports 3 contract modes seamlessly:
  1. *Two-Spec Structural AST Diff:* Computes exact breaking changes between `baseline_spec` and `spec_url`.
  2. *Single-Spec Live Discovery:* Ingests active upstream OpenAPI contract without requiring a baseline.
  3. *Pure Error-Driven Schema Inference:* Operates with zero spec files, inferring payload requirements directly from HTTP 422 error messages and stack traces.
* **Dependency Mapping:** `DependencyMapper` uses Python AST to trace caller files, data models, and serializers across the codebase.
* **Verification:** Runs `pytest` inside an ephemeral Modal Cloud Linux micro-container with automatic dependency discovery from `requirements.txt` or `pyproject.toml`.
* **Delivery:** Generates unified diffs, authors an incident post-mortem, and opens a GitHub PR with modified source files.

---

## ☁️ Zero-Idle-Cost Continuous Operation (`$0.00/month` Idle)

Developers and companies **never need to run a 24/7 dedicated VPS or listener server** to keep Aegis active. Because Aegis already uses Modal Cloud for sandbox micro-VMs, [`aegis_serverless.py`](./aegis_serverless.py) deploys Aegis itself as a **Scale-to-Zero Serverless Daemon**:

1. **Scale-to-Zero HTTPS Alert Webhook (`POST /webhooks/alert`):**
   - Hosted via `@modal.asgi_app()`, sleeping at **0 running containers (`$0.00/month` idle cost)**.
   - When your app catches an upstream `422` contract failure or `504` DB timeout and `POST`s a JSON alert, Modal wakes the endpoint, spawns an asynchronous `remediate_incident_worker` cloud job in `<50ms`, verifies the fix in an isolated micro-VM, opens a GitHub PR, and scales back down to zero.
2. **Scheduled Read-Only DB Watchdog (`modal.Period(minutes=30)`):**
   - Automatically wakes up every 30 minutes on Modal Cloud, inspects `DATABASE_RO_URL` (`readonly=True`) for unindexed sequential scans breaching SLA thresholds, opens a verified SQL index PR if needed, and scales back to zero.
3. **Optional GitHub Actions Scheduled Audit (Zero Extra Accounts):**
   - Teams can also run `python aegis_cli.py run --vector all` on a GitHub Actions `schedule` cron or CI failure trigger.

Deploy serverless in one command:
```bash
python aegis_cli.py deploy --config aegis.yaml
```

---

## 📊 Live Verification Benchmark

During end-to-end testing against the live `cupertino-coffee-store` production database (multi-table join over `orders` and `order_items` with 19,405 rows):

| Metric | Before Remediation | After Remediation | Autonomous Impact |
| :--- | :--- | :--- | :--- |
| **Execution Plan** | `Hash Join (Seq Scan orders + Seq Scan order_items)` | `Nested Loop (Bitmap Index Scan idx_orders_customer_id + Index Only Scan idx_order_items_order_id)` | **100% Sequential Scan Elimination** |
| **Execution Latency** | **242.87 ms** | **4.37 ms** | **-98.2% Latency Reduction** |
| **Host CPU Utilization** | ~94.2% | ~9.1% | **-90.3% CPU Relief** |
| **Table Lock Impact** | N/A | **0 ms Lock Wait** | Zero Downtime via `CONCURRENTLY` + `lock_timeout='5s'` |
| **Sandbox Environment** | N/A | Modal Cloud PostgreSQL 16 Micro-VM (`sb-qd3aPZffOWJpvoAEJ20N4K`) in **5.11s** | Deterministic Cloud Verification |
| **Meta Model Speed** | N/A | DDL Synthesis: **9.32s** \| Post-Mortem Report: **13.25s** | Real-time Live Token Generation |
| **Deterministic Gate** | N/A | **PASSED** (required $\ge$ 80%) | Auto-Approved for Pull Request |

---

## 🧭 Getting Started in 5 Minutes

### Step 1: Clone & Install Dependencies
```bash
git clone https://github.com/your-org/aegis-sre.git
cd aegis-sre
python -m venv .venv
# Windows: .venv\Scripts\activate | macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

### Step 2: Create Read-Only PostgreSQL Credentials (Zero Production Write Risk)
Run once on your PostgreSQL database (Supabase, Neon, RDS, or self-hosted) so Aegis can inspect query plans and catalog stats without write permissions:
```sql
CREATE ROLE aegis_ro WITH LOGIN PASSWORD 'strong_readonly_password';
GRANT CONNECT ON DATABASE your_db TO aegis_ro;
GRANT USAGE ON SCHEMA public TO aegis_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO aegis_ro;
GRANT pg_read_all_stats TO aegis_ro;
```

### Step 3: Configure `.env`
Copy `.env.example` to `.env` and fill in credentials:
```bash
META_API_KEY=LLM_...
META_MODEL_API_URL=https://api.meta.ai/v1
META_MODEL_NAME=muse-spark-1.2

MODAL_TOKEN_ID=ak-...
MODAL_TOKEN_SECRET=as-...

DATABASE_RO_URL=postgresql://aegis_ro:strong_readonly_password@your-db-host:5432/your_db
GITHUB_TOKEN=ghp_your_github_personal_access_token
```

Verify connectivity:
```bash
python verify_meta_api.py   # Verifies Meta Muse Spark API
python verify_modal.py      # Verifies Modal Cloud micro-VM provisioning
```

### Step 4: Initialize & Audit `aegis.yaml`
Generate a starter `aegis.yaml` manifest for your service and run the architectural contract audit:
```bash
python aegis_cli.py init --output aegis.yaml
python aegis_cli.py check --config aegis.yaml
```

Example `aegis.yaml`:
```yaml
version: "1.0"

project:
  service_name: "cupertino-coffee-store"
  repository: "meta-sre/cupertino-coffee"
  default_branch: "main"

observability:
  provider: "direct"
  watchdog_interval_seconds: 60

database:
  engine: "postgres"
  read_only_connection_env: "DATABASE_RO_URL"
  require_read_only_mode: true
  schema_path: "auto"        # Introspects live PostgreSQL catalog metadata
  telemetry_source: "auto"   # Discovers slow queries via pg_stat_user_tables delta reads
  migration_output_dir: "migrations"
  sla_thresholds:
    p99_latency_ms: 1000.0
    max_cpu_percent: 80.0
    min_sandbox_speedup_percent: 80.0

upstream_apis:
  - name: "coffee_payment_gateway"
    spec_url: "contracts/payment_gateway_v2.json"
    client_repo_root: "."
    code_root: "app"
    test_target: "tests"
    max_healing_retries: 3

sandbox:
  provider: "modal"
  app_name: "aegis-sre"
  timeout_seconds: 120
```

### Step 5: Run Aegis SRE
* **Option A — Run Local Listener with Direct DB Watchdog:**
  ```bash
  python aegis_cli.py listen --config aegis.yaml --port 8080 --watchdog
  ```
* **Option B — Deploy Serverless Scale-to-Zero Daemon to Modal Cloud:**
  ```bash
  python aegis_cli.py deploy --config aegis.yaml
  ```
* **Option C — Trigger On-Demand CLI Remediation:**
  ```bash
  python aegis_cli.py run --vector a --config aegis.yaml
  python aegis_cli.py run --vector b --config aegis.yaml
  python aegis_cli.py run --vector all --config aegis.yaml
  ```

---

## 🛠️ CLI Command Reference

| Command | Purpose |
| :--- | :--- |
| `python aegis_cli.py check [--config <path>]` | Audits integration contract compliance (metadata, read-only mode, schema, sandbox). |
| `python aegis_cli.py init [--output <path>]` | Generates a clean, validated `aegis.yaml` starter manifest for a new repository. |
| `python aegis_cli.py run --vector [a\|b\|all]` | Runs on-demand autonomous remediation for database (A), API contracts (B), or both. |
| `python aegis_cli.py listen [--port 8080] [--watchdog]` | Runs local webhook daemon (`/webhooks/alert`) and optional direct PostgreSQL watchdog. |
| `python aegis_cli.py deploy [--config <path>]` | Deploys Aegis SRE as a scale-to-zero serverless daemon on Modal Cloud (`$0.00/mo` idle). |

---

## 🧪 Test Suite

Run the full automated verification suite:
```bash
python -m pytest tests/ -v
```

16/16 tests passing:
* `test_aegis_config.py`: Architecture compliance, read-only enforcement, starter manifest roundtrip.
* `test_external_blind_readiness.py`: External repository isolation, POSIX commit paths, alert normalization, dynamic dependency mapping.
* `test_generalization.py`: Unseen logistics schemas, unseen database tables, non-destructive DDL safety policies.
* `test_github_delivery.py`: Atomic Git tree, blob, commit, and Pull Request creation with unified diffs.

---

## 🏆 Hackathon Submission Highlights

1. **Meta Muse Spark Core:** Powers deep root-cause diagnosis, non-blocking PostgreSQL index synthesis, API contract payload reconciliation, and model-authored Pull Request post-mortems.
2. **Modal Cloud Infrastructure:** Powers both ephemeral verification micro-VMs (PostgreSQL 16 + Linux pytest sandboxes) and Aegis's own scale-to-zero continuous serverless daemon (`$0.00/month` idle cost).
3. **Domain-Agnostic Design:** Operates on unseen databases and APIs with zero hardcoded table, column, or field names.
4. **Safety First:** Strictly read-only production database sessions (`readonly=True`), non-destructive `CONCURRENTLY` DDL guards, and zero-write external repository isolation.
