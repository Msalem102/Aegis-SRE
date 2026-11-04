# 🛡️ Aegis SRE — Autonomous Closed-Loop Site Reliability Engineering Agent

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Meta Muse Spark](https://img.shields.io/badge/Meta%20AI-Muse%20Spark%201.2-purple.svg)](https://api.meta.ai/)
[![Modal Cloud Serverless](https://img.shields.io/badge/Serverless-Modal%20Scale--to--Zero-brightgreen.svg)](https://modal.com/)
[![Tests Passing](https://img.shields.io/badge/tests-22%2F22%20passing-brightgreen.svg)](tests/)
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
            [ Pre-Flight GitHub PR Idempotency Gate ] ──> (PR already open? Skip LLM & save 100% tokens!)
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
* **Trigger:** Sequential scan surges, CPU spikes (>80%), HTTP 504 timeouts, or P99 latency breaches (>1000ms).
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
* **Anti-Truncation Surgical Patching:** Parses modified AST blocks directly into target source files, eliminating context truncation on large codebases.
* **Verification:** Runs `pytest` inside an ephemeral Modal Cloud Linux micro-container with automatic dependency discovery from `requirements.txt` or `pyproject.toml`.
* **Delivery:** Generates unified diffs, authors an incident post-mortem, and opens a GitHub PR with modified source files.

---

## 🖥️ SRE Control Plane & Real-Time Event Stream

Aegis includes an interactive, **Supabase-styled dark emerald web dashboard** (`http://localhost:8080`) built on an 8px design grid:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│  🛡️ ahmedharib's Org / [cupertino-coffee-store ▾] / master  PRODUCTION                 │
├────────────────────────────────────────────────────────────────────────────────────────┤
│  [Query SLA: Target < 1000ms]  [Telemetry Watchdog: ACTIVE]  [Remediations: Modal]    │
├────────────────────────────────────────────────────────────────────────────────────────┤
│  Autonomous Remediation Controls:                                                      │
│    [Fix Database Contention (Vector A)]  [Fix API Contract Drift (Vector B)]  [Scan DB]│
│                                                                                        │
│  Live Latency Visualizer (Production Baseline vs. Modal Ephemeral Micro-VM):           │
│  Baseline:   ████████████████████████████████████████ 242.87 ms (Seq Scan Contention) │
│  Remediated: █ 4.37 ms (-98.2% Faster / 100% Passed)                                  │
│                                                                                        │
│  Live Event Stream & Watchdog Telemetry (SSE Server-Sent Events):                      │
│  [15:12:04] [watchdog] Active unindexed sequential scan surge detected (+50000 tuples)│
│  [15:12:05] [meta]     Meta Muse Spark synthesizing zero-downtime index migration...  │
│  [15:12:09] [sandbox]  Modal Cloud micro-VM verified 98.2% latency drop in 5.11s!     │
│  [15:12:10] [delivery] Opened ready-to-merge GitHub Pull Request #33                  │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

* **Live Multi-App `.yaml` Switcher:** Seamlessly switch between microservices or create new app configurations directly via UI modal.
* **Real-Time SSE Event Stream:** Console output (`sys.stdout`/`sys.stderr`) is teed directly to the web dashboard via Server-Sent Events.
* **Interactive Post-Mortem Reports:** Inspect root causes, before/after EXPLAIN plans, and candidate diffs with 1-click links to GitHub Pull Requests.

---

## ☁️ Zero-Idle-Cost Continuous Operation (`$0.00/month` Idle)

Developers and companies **never need to run a 24/7 dedicated VPS or listener server** to keep Aegis active. Because Aegis already uses Modal Cloud for sandbox micro-VMs, [`aegis_serverless.py`](./aegis_serverless.py) deploys Aegis itself as a **Scale-to-Zero Serverless Daemon**:

1. **Scale-to-Zero HTTPS Alert Webhook (`POST /webhooks/alert`):**
   - Hosted via `@modal.asgi_app()`, sleeping at **0 running containers (`$0.00/month` idle cost)**.
   - When your app catches an upstream `422` contract failure or `504` DB timeout and `POST`s a JSON alert, Modal wakes the endpoint, spawns an asynchronous `remediate_incident_worker` cloud job in `<50ms`, verifies the fix in an isolated micro-VM, opens a GitHub PR, and scales back down to zero.
2. **Scheduled Read-Only DB Watchdog (`modal.Period(minutes=30)`):**
   - Automatically wakes up every 30 minutes on Modal Cloud, inspects `DATABASE_RO_URL` (`readonly=True`) for unindexed sequential scans breaching SLA thresholds, opens a verified SQL index PR if needed, and scales back to zero.
3. **Pre-Flight GitHub PR Idempotency Gate:**
   - Detects if an active PR is already open for the incident signature before calling the Meta model or provisioning cloud compute, saving 100% of token and compute costs on repeated alerts.

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
| **Sandbox Environment** | N/A | Modal Cloud PostgreSQL 16 Micro-VM in **5.11s** | Deterministic Cloud Verification |
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

### Step 2: Configure `.env`
Copy `.env.example` to `.env` and fill in credentials:
```bash
META_API_KEY=LLM_...
META_MODEL_API_URL=https://api.meta.ai/v1
META_MODEL_NAME=muse-spark-1.2

MODAL_TOKEN_ID=ak-...
MODAL_TOKEN_SECRET=as-...

DATABASE_RO_URL=postgresql://app_user:app_secret@localhost:5432/postgres
GITHUB_TOKEN=ghp_your_github_personal_access_token
```

Verify connectivity to all 3 core external integrations:
```bash
python aegis_cli.py verify
```

### Step 3: Run the 1-Click Interactive Demo
Launch the complete simulation (Cupertino Coffee Store on `:8000` + Aegis Control Plane on `:8080`):
```bash
# Windows
run_demo.bat
# or PowerShell
.\run_demo.ps1
```

Or start the Aegis SRE Web UI directly:
```bash
python aegis_cli.py ui --config mockstore_aegis.yaml
```

---

## 🛠️ CLI Command Reference

| Command | Purpose |
| :--- | :--- |
| `python aegis_cli.py ui [--config <path>]` | **Launches the full interactive SRE Control Plane Web Dashboard & auto-opens browser.** |
| `python aegis_cli.py check [--config <path>]` | Audits integration contract compliance (metadata, read-only mode, schema, sandbox). |
| `python aegis_cli.py init [--output <path>]` | Generates a clean, validated `aegis.yaml` starter manifest for a new repository. |
| `python aegis_cli.py run --vector [a\|b\|all]` | Runs on-demand autonomous remediation for database (A), API contracts (B), or both. |
| `python aegis_cli.py listen [--port 8080] [--watchdog]` | Runs local webhook daemon (`/webhooks/alert`) and optional direct PostgreSQL watchdog. |
| `python aegis_cli.py deploy [--config <path>]` | Deploys Aegis SRE as a scale-to-zero serverless daemon on Modal Cloud (`$0.00/mo` idle). |
| `python aegis_cli.py verify [--config <path>]` | Runs live pre-flight checks against Meta Model API, Modal Cloud, and GitHub Push access. |

---

## 🧪 Test Suite

Run the full automated verification suite:
```bash
python -m pytest tests/ -v
```

**22/22 tests passing across 5 test suites:**
* `tests/test_aegis_config.py` (5 tests): Architecture contract compliance, read-only driver enforcement, starter template roundtrips.
* `tests/test_external_blind_readiness.py` (5 tests): External repo isolation, POSIX commit keys, alert event normalization, dynamic dependency mapping, and EXPLAIN plan flattening.
* `tests/test_generalization.py` (2 tests): Unseen logistics OpenAPI specs and unseen database tables with non-destructive DDL safety policies.
* `tests/test_github_delivery.py` (6 tests): Atomic Git tree blobs, Pull Request deduplication, unified diff generation, and **Pre-Flight PR Idempotency Gate**.
* `tests/test_ui_and_api.py` (4 tests): SRE Control Plane endpoints, sandbox payload file transfer, anti-truncation AST patching, and **Live SSE Event Stream compliance**.

---

## 🏆 Hackathon Submission Highlights

1. **Meta Muse Spark Core:** Powers root-cause diagnosis, non-blocking PostgreSQL index synthesis, API contract payload reconciliation, and model-authored Pull Request post-mortems.
2. **Deterministic Sandbox Mandate:** Refuses to deliver untested code. Every SQL migration and code patch is validated in an ephemeral Modal Cloud micro-VM (PostgreSQL 16 / Linux pytest) before GitHub delivery.
3. **Pre-Flight GitHub PR Idempotency Gate:** Eliminates redundant LLM token costs and cloud compute by detecting open remediation PRs before triggering model inference.
4. **Zero-Idle-Cost Continuous Operation:** Scale-to-zero serverless daemon on Modal Cloud (`$0.00/month` idle cost).
5. **Interactive SRE Control Plane:** Supabase-styled dark emerald dashboard with real-time SSE event streaming, 8px grid alignment, and dynamic multi-app `.yaml` switcher.
6. **Domain-Agnostic Design:** Operates on unseen databases and APIs with zero hardcoded table, column, or field names.
7. **Production Safety Guarantees:** Strictly read-only production database sessions (`readonly=True`), non-destructive `CONCURRENTLY` DDL guards (`lock_timeout='5s'`), and zero-write external repository isolation.
