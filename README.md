# Aegis Mobile — MTM4681 Milestone 1

**Student:** Mohamed Salem — **25058911**

**External contributor (outside the university):** Ahmed Harib 

## Mobile project submission

- [Design justification (PDF)](milestone/docs/DESIGN_JUSTIFICATION.pdf)
- [Illustrated user flow (PDF)](milestone/docs/USER_FLOW.pdf)
- [Architecture and protocols (PDF)](milestone/docs/ARCHITECTURE_AND_PROTOCOLS.pdf)
- [Editable wireframes](https://www.figma.com/design/3zM5YkkarvApLs90BDiHmi?node-id=4-195)
- [Approved mockups](https://www.figma.com/design/3zM5YkkarvApLs90BDiHmi?node-id=20-116)
- [Interactive prototype](https://www.figma.com/proto/3zM5YkkarvApLs90BDiHmi?node-id=20-117&starting-point-node-id=20%3A117)
- [Milestone overview and approved screen exports](milestone/README.md)

The mobile interface is a design prototype over the imported Aegis SRE backend. Authentication and agent chat are proposed features. A verified candidate or PR does not imply a production deployment. Prototype navigation and instructor viewing access were confirmed by Mohamed Salem.

The original backend documentation and attribution are preserved below.

---

# Aegis SRE

**Autonomous Closed-Loop Site Reliability Engineering Agent**

[![Python Version](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg)](https://www.python.org/)
[![Model Core](https://img.shields.io/badge/Reasoning%20Core-Meta%20Muse%20Spark-purple.svg)](https://api.meta.ai/)
[![Sandbox Runtime](https://img.shields.io/badge/Verification-Modal%20Cloud%20Micro--VMs-brightgreen.svg)](https://modal.com/)
[![Test Suite](https://img.shields.io/badge/tests-23%2F23%20passing-brightgreen.svg)](tests/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Aegis SRE is an autonomous, closed-loop Site Reliability Engineering agent designed to detect, diagnose, and remediate production performance bottlenecks and breaking API changes. 

Unlike traditional generative AI coding tools that output unverified code snippets directly to developers, Aegis enforces a **Deterministic Sandbox Mandate**: no SQL migration or code patch is ever delivered to a production repository without passing empirical verification inside an isolated, cloud-hosted micro-VM.

---

## Table of Contents

- [Overview & Architecture](#overview--architecture)
- [Core Capabilities](#core-capabilities)
  - [Database Performance & Non-Blocking Indexing](#database-performance--non-blocking-indexing)
  - [Upstream API Contract Drift Remediation](#upstream-api-contract-drift-remediation)
  - [Pre-Flight PR Idempotency Gate](#pre-flight-pr-idempotency-gate)
- [Prerequisites](#prerequisites)
- [PostgreSQL Telemetry Setup (`pg_stat_statements`)](#postgresql-telemetry-setup-pg_stat_statements)
- [Quickstart Guide](#quickstart-guide)
  - [Option 1: 1-Click Interactive Demo (Recommended)](#option-1-1-click-interactive-demo-recommended)
  - [Option 2: Step-by-Step Manual Setup](#option-2-step-by-step-manual-setup)
- [SRE Control Plane & Telemetry Dashboard](#sre-control-plane--telemetry-dashboard)
- [Serverless Deployment (Modal Cloud)](#serverless-deployment-modal-cloud)
- [CLI Reference](#cli-reference)
- [Automated Test Suite](#automated-test-suite)
- [Live Pull Request Showcase](#live-pull-request-showcase)
- [License](#license)

---

## Overview & Architecture

Modern cloud architectures suffer from two frequent failure modes:
1. **Unindexed Database Query Contention:** A query with missing indexes triggers full sequential scans across millions of rows, saturating host CPU and exhausting application connection pools.
2. **Upstream API Contract Drift:** Third-party services push backward-incompatible schema updates, causing runtime HTTP 422 Unprocessable Entity exceptions during live user requests.

Aegis monitors services continuously, synthesizes minimal corrective changes using **Meta Muse Spark**, deterministically verifies candidates inside ephemeral **Modal Cloud micro-VMs**, and delivers atomic Pull Requests containing unified diffs and incident post-mortems.

```
       [ PostgreSQL Telemetry Surge OR Inbound Alert Webhook ]
                                  │
                                  ▼
           [ Pre-Flight GitHub PR Idempotency Gate ]
           (Detects existing open PRs -> skips compute/tokens)
                                  │
                                  ▼
           [ Read-Only Telemetry & Catalog Introspection ]
           (Session enforced: SET TRANSACTION READ ONLY)
                                  │
                                  ▼
              [ Meta Muse Spark Reasoning Engine ]
           (AST Dependency Analysis & Patch Synthesis)
                                  │
                                  ▼
              [ DDL & Safe Patch Verification Gate ]
           (Enforces lock_timeout = 5s & CONCURRENTLY)
                                  │
                                  ▼
   ┌─────────────────────────────────────────────────────────────┐
   │             Modal Cloud Ephemeral Micro-VM                  │
   │  • Spawns dedicated PostgreSQL 16 or Linux container        │
   │  • Replicates schema + seeds realistic dataset cardinality   │
   │  • Executes migration or runs targeted pytest suite         │
   │  • Benchmarks EXPLAIN (ANALYZE, BUFFERS) speedup ratio      │
   └─────────────────────────────────────────────────────────────┘
                                  │
                  Verification Threshold Satisfied?
                   ├── NO  ──> Feedback Loop to Muse Spark (Self-Healing)
                   └── YES ──> Open Atomic GitHub Pull Request + Post-Mortem
```

---

## Core Capabilities

### Database Performance & Non-Blocking Indexing
* **Telemetry Monitoring:** Continuously tracks read-only metrics using PostgreSQL's `pg_stat_statements` and `pg_stat_user_tables`.
* **Proactive Sequential Scan Detection:** Rather than waiting for local queries to breach absolute latency thresholds, the watchdog detects sequential scan surges (`seq_tup_read` deltas), catching $O(N)$ table scans before they cause connection pool exhaustion under concurrent load.
* **Autonomous Query Discovery:** Discovers the offending SQL queries by cross-referencing runtime database statistics with Python codebase AST scans (zero hardcoded queries).
* **Production Safety Envelope:** All synthesized index migrations are wrapped in strict transaction guards:
  ```sql
  SET statement_timeout = '30s';
  SET lock_timeout = '5s';
  CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_name ON table(column);
  ```
  This prevents index builds from blocking concurrent reads and writes or waiting behind long-running transactions.
* **Empirical Speedup Verification:** Spawns an isolated PostgreSQL 16 micro-VM in Modal Cloud, executes 5 warm runs of `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`, and verifies an $\ge 80\%$ latency reduction before delivery.

### Upstream API Contract Drift Remediation
* **Alert Ingestion:** Catches runtime HTTP 422 errors and contract validation failures through a standardized webhook (`POST /webhooks/alert`).
* **Multi-Mode Schema Discovery:** Supports two-spec AST diffing (`baseline_spec` vs `spec_url`), single-spec discovery, or pure runtime error inference (extracting requirements directly from error messages and tracebacks).
* **Surgical AST Code Patching:** Uses Python AST traversal to isolate models, serializers, and client methods, replacing only the affected AST nodes while preserving surrounding code, comments, and imports.
* **Automated Cloud Test Gate:** Executes the target repository's pytest test suite in a clean Modal Linux container to verify complete contract conformance.

### Pre-Flight PR Idempotency Gate
When recurring alerts flood during an incident, Aegis inspects the target repository for active remediation Pull Requests matching the incident signature. If a PR is already open, Aegis short-circuits the pipeline—saving 100% of LLM token costs and cloud compute resources.

---

## Prerequisites

Before running Aegis SRE, ensure you have:

1. **Python 3.11+** installed locally.
2. **Docker** installed and running (for local PostgreSQL telemetry testing).
3. **External Credentials:**
   * **Meta Model API Key:** Access to Meta Muse Spark (`META_API_KEY`).
   * **Modal Cloud Credentials:** `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET` (from [modal.com](https://modal.com)).
   * **GitHub Token:** Personal Access Token with `repo` scope for creating branches and Pull Requests.

---

## PostgreSQL Telemetry Setup (`pg_stat_statements`)

To enable Aegis to monitor database performance without third-party APM SaaS agents, PostgreSQL must have the official `pg_stat_statements` extension enabled.

### 1. Enable Extension at Server Startup
PostgreSQL requires `pg_stat_statements` to be preloaded in shared memory.

#### Using Docker:
Start PostgreSQL with the extension configured in the command parameters:
```bash
docker run -d \
  --name pg-sim \
  -e POSTGRES_PASSWORD=secret \
  -e POSTGRES_DB=postgres \
  -p 5432:5432 \
  postgres:16 \
  -c shared_preload_libraries=pg_stat_statements \
  -c pg_stat_statements.track=all \
  -c max_connections=25
```

#### In `postgresql.conf` (Self-Hosted / Managed RDS / Neon / Supabase):
```ini
shared_preload_libraries = 'pg_stat_statements'
pg_stat_statements.track = all
pg_stat_statements.max = 10000
```
*(Requires a database server restart if newly added).*

### 2. Initialize Extension in Database
Connect to your PostgreSQL database as a superuser (`postgres`) and create the extension:
```sql
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
```

### 3. Create a Least-Privilege Read-Only User
Aegis requires strictly read-only access. It never writes directly to your production database:
```sql
-- Create read-only role
CREATE ROLE aegis_ro WITH LOGIN PASSWORD 'strong_readonly_password';
GRANT CONNECT ON DATABASE postgres TO aegis_ro;
GRANT USAGE ON SCHEMA public TO aegis_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO aegis_ro;

-- Grant access to query statistics
GRANT pg_read_all_stats TO aegis_ro;
GRANT EXECUTE ON FUNCTION pg_stat_statements_reset() TO aegis_ro;
```

---

## Quickstart Guide

> [!IMPORTANT]
> **First-Time Setup Required for Live Cloud Execution:**
> Because API keys and private tokens are excluded from Git repositories for security, fresh clones require creating a `.env` file before executing live cloud micro-VMs and Pull Requests:
> 1. Copy `.env.example` to `.env`: `cp .env.example .env` (or on Windows: `copy .env.example .env`)
> 2. Populate your credentials: `META_API_KEY`, `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`, and `GITHUB_TOKEN`.
> 3. Test connectivity across all 3 cloud providers in one command:
>    ```bash
>    python aegis_cli.py verify
>    ```
> Once verified, proceed to either option below.

### Option 1: 1-Click Interactive Demo (Recommended)

The monitored microservice (`mockStore`) is bundled directly inside this repository—no secondary cloning is needed. The repository provides a single-command turnkey launcher for Windows, macOS, and Linux:

```bash
# On Windows (Command Prompt):
run_demo.bat

# On Windows (PowerShell):
.\run_demo.ps1

# On macOS / Linux:
chmod +x run_demo.sh
./run_demo.sh
```

This script automatically:
1. Verifies or boots the PostgreSQL container (`pg-sim`) on port `5432` with `pg_stat_statements` enabled.
2. Starts the monitored service (`Cupertino Coffee Store`) on `http://localhost:8000`.
3. Launches the Aegis SRE Control Plane on `http://localhost:8080`.
4. Opens both applications in your default browser.

---

### Option 2: Step-by-Step Manual Setup

#### Step 1: Clone and Setup Virtual Environment
```bash
git clone https://github.com/ahmedharib/Aegis-SRE.git
cd Aegis-SRE

python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On Linux / macOS:
source .venv/bin/activate

pip install -r requirements.txt
```

#### Step 2: Configure Environment Variables
Copy `.env.example` to `.env` and fill in your credentials:
```bash
cp .env.example .env
```

Edit `.env`:
```ini
# Meta AI Reasoning Core
META_API_KEY=LLM_...
META_MODEL_API_URL=https://api.meta.ai/v1
META_MODEL_NAME=muse-spark-1.2

# Modal Cloud Ephemeral Sandboxes
MODAL_TOKEN_ID=ak-...
MODAL_TOKEN_SECRET=as-...

# Target PostgreSQL Read-Only Telemetry Connection
DATABASE_RO_URL=postgresql://app_user:app_secret@localhost:5432/postgres

# GitHub Integration
GITHUB_TOKEN=ghp_...
GITHUB_REPOSITORY=ahmedharib/mockStore
```

#### Step 3: Verify Integrations
Run the pre-flight connectivity check across the Meta Model API, Modal Cloud, and GitHub:
```bash
python aegis_cli.py verify
```

#### Step 4: Launch the SRE Control Plane
```bash
python aegis_cli.py ui --config mockstore_aegis.yaml
```
Access the dashboard at `http://localhost:8080`.

---

## SRE Control Plane & Telemetry Dashboard

The Aegis Web Dashboard (`http://localhost:8080`) provides real-time operational visibility:

```
+---------------------------------------------------------------------------------------+
|  Aegis SRE  |  Target: cupertino-coffee-store  |  Branch: master  |  Status: ONLINE   |
+---------------------------------------------------------------------------------------+
|  [Query SLA: < 1000ms]   [Telemetry Watchdog: ACTIVE]   [Sandbox Gate: Modal Ready]   |
+---------------------------------------------------------------------------------------+
|  Autonomous Controls:                                                                 |
|    [ Fix Database Contention ]              [ Fix API Contract Drift ]                 |
|                                                                                       |
|  Execution Latency Benchmark:                                                         |
|    Baseline:   [========================================] 242.87 ms (Seq Scan)        |
|    Remediated: [==] 4.37 ms (-98.2% Latency Reduction)                                |
|                                                                                       |
|  Live Event Stream & Watchdog Telemetry (SSE):                                        |
|    [15:02:11] [watchdog] Unindexed sequential scan surge detected (+50000 tuples read)|
|    [15:02:12] [meta]     Meta Muse Spark synthesizing non-blocking index DDL...       |
|    [15:02:16] [sandbox]  Modal micro-VM verified 98.2% speedup across 5 warm runs.    |
|    [15:02:17] [delivery] Atomic GitHub Pull Request #34 opened with post-mortem report|
+---------------------------------------------------------------------------------------+
```

* **Live Telemetry Stream:** Emits real-time diagnostic output from standard output and the database watchdog directly to the browser via Server-Sent Events (SSE).
* **Latency Visualizer:** Displays proportional execution time comparisons between production baselines and remediated plans.
* **Service Switcher:** Dynamically load or create new application contracts (`service_aegis.yaml`) on demand.

---

## Serverless Deployment (Modal Cloud)

To operate continuously without maintaining a 24/7 listener server, deploy Aegis as a zero-idle-cost serverless daemon via Modal:

```bash
python aegis_cli.py deploy --config aegis.yaml
```

* **Scale-to-Zero Webhook (`POST /webhooks/alert`):** Wakes up in `<50ms` upon receiving an alert, spawns an asynchronous cloud remediation worker, and scales back down to zero ($0.00/month idle cost).
* **Scheduled DB Watchdog (`modal.Period(minutes=30)`):** Periodically polls remote PostgreSQL replicas for unindexed sequential scans without requiring dedicated compute instances.

---

## CLI Reference

Aegis includes a unified CLI (`aegis_cli.py`) for local workflows, CI/CD pipelines, and cloud deployments:

| Command | Arguments | Description |
| :--- | :--- | :--- |
| `ui` | `[--config <path>] [--port <int>] [--no-browser]` | Launches the interactive web control plane and starts the telemetry stream. |
| `verify` | `[--config <path>]` | Validates live authentication with the Meta Model API, Modal Cloud, and GitHub. |
| `check` | `[--config <path>]` | Audits an `aegis.yaml` manifest against architectural compliance rules. |
| `init` | `[--output <path>] [--force]` | Generates a valid starter `aegis.yaml` contract for a new service. |
| `run` | `--vector <a\|b\|all> [--config <path>]` | Dispatches on-demand autonomous remediation for database, API, or both. |
| `listen` | `[--port <int>] [--watchdog]` | Runs the headless webhook daemon and optional direct database watchdog. |
| `deploy` | `[--config <path>]` | Deploys Aegis as a scale-to-zero serverless application to Modal Cloud. |

---

## Automated Test Suite

Aegis includes comprehensive unit and integration test coverage:

```bash
# Run full test suite
python -m pytest tests/ -v
```

**23/23 Tests Passing:**
* **`tests/test_aegis_config.py`** (5 tests): Manifest schema validation, read-only driver enforcement, and template roundtrips.
* **`tests/test_external_blind_readiness.py`** (5 tests): External repository isolation, POSIX path sanitization, alert payload normalization, dynamic dependency mapping, and EXPLAIN plan parsing.
* **`tests/test_generalization.py`** (2 tests): Validation against unseen logistics schemas and arbitrary database tables.
* **`tests/test_github_delivery.py`** (6 tests): Atomic Git tree blobs, commit deduplication, unified diff creation, and pre-flight PR idempotency verification.
* **`tests/test_ui_and_api.py`** (5 tests): Control plane endpoints, sandbox payload transfer integrity, anti-truncation AST patching, live SSE event stream conformance, and manual control button pre-flight bypass.

---

## Live Pull Request Showcase

Explore the dedicated [`pull_requests/`](pull_requests/) directory to inspect the actual Pull Requests autonomously opened by Aegis on GitHub during live test runs against the monitored service:

* **[PR #58 — Database Contention](https://github.com/ahmedharib/mockStore/pull/58):** Synthesized covering B-tree indexes with `CONCURRENTLY` and safe timeouts, achieving a **-98.46% latency reduction** inside Modal Cloud PostgreSQL 16 micro-VMs. Full artifacts in [`pull_requests/PR_58_DATABASE_CONTENTION/`](pull_requests/PR_58_DATABASE_CONTENTION/).
* **[PR #56 — API Contract Drift](https://github.com/ahmedharib/mockStore/pull/56):** Surgically patched Pydantic models and payment client builders for RoastPay v2, achieving a **100% pytest pass (1/1 in 0.07s)** in Modal Cloud Linux micro-containers. Full artifacts in [`pull_requests/PR_56_API_CONTRACT_DRIFT/`](pull_requests/PR_56_API_CONTRACT_DRIFT/).

---

## License

Aegis SRE is open-source software licensed under the [MIT License](LICENSE).
