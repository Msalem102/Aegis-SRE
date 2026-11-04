# 🛡️ Devpost Submission: Aegis SRE

## 📌 Project Overview
* **Project Name:** Aegis SRE — Autonomous Closed-Loop Site Reliability Engineering Agent
* **Tagline:** An enterprise-grade, closed-loop SRE agent that autonomously detects database bottlenecks & API breaking changes, verifies fixes in isolated Modal Cloud micro-VMs, and delivers ready-to-merge GitHub PRs.
* **Track / Category:** Meta Global AI Developer Hackathon — Developer Tools & Enterprise Infrastructure
* **Repository:** [https://github.com/ahmedharib/meta-global-hack](https://github.com/ahmedharib/meta-global-hack)
* **Demo Video:** *[Insert YouTube / Loom Link Here]*

---

## 💡 Inspiration
Modern software systems are constantly subjected to two unpredictable failure modes:
1. **Silent Database Degradation:** An unindexed query that ran fine during staging begins sequentially scanning millions of rows in production, monopolizing CPU, exhausting connection pools, and cascading into total service collapse.
2. **Upstream API Contract Drift:** Third-party partners (payment processors, logistics APIs, identity providers) push breaking schema updates without warning, causing customer checkouts to fail with HTTP 422 Unprocessable Entity errors.

When these incidents occur at 3:00 AM, human on-call engineers face high MTTR (Mean Time to Resolution) stress. Worse, generic LLM coding assistants are dangerous in production: they hallucinate untested SQL statements that take exclusive table locks or propose code patches that fail in production.

We asked: **What if an AI Site Reliability Engineer could not only diagnose outages, but also adhere to the *Deterministic Sandbox Mandate*—proving every patch in an isolated cloud micro-VM before a single line of code ever reaches GitHub?** That is why we built **Aegis SRE**.

---

## ⚡ What It Does
Aegis SRE is an enterprise-grade, domain-agnostic autonomous SRE agent that runs continuous closed-loop remediation across two critical production failure modes:

### 1. Database Contention & Zero-Downtime Indexing
* **Telemetry Discovery:** Direct read-only inspection via `pg_stat_statements` and `pg_stat_user_tables` sequential scan analysis + AST codebase scanner.
* **Proactive Surge Detection:** Detects algorithmic $O(N)$ sequential scan surges (+50,000 tuples read per query) proactively before table volumes breach SLA thresholds.
* **Zero Production Write Risk:** Enforces strictly read-only connections at the PostgreSQL driver session level (`readonly=True`).
* **Meta Muse Spark Synthesis:** Generates optimal composite/covering index strategies (`CREATE INDEX CONCURRENTLY IF NOT EXISTS ...`) wrapped in enterprise locking guards (`lock_timeout='5s'`, `statement_timeout='30s'`).
* **Modal Ephemeral Sandbox Gate:** Provisions an isolated PostgreSQL 16 micro-VM in Modal Cloud, replicates multi-table schemas, seeds realistic synthetic data, executes the candidate migration, and evaluates median execution times across 5 runs of `EXPLAIN (ANALYZE, BUFFERS)`.
* **Empirical Delivery:** Mandates an $\ge 80\%$ latency reduction before opening an atomic GitHub Pull Request with an interactive post-mortem report.

### 2. Upstream API Contract Drift Remediation
* **Alert Ingestion:** Catches runtime HTTP 422 errors and upstream schema breaking changes via `/webhooks/alert`.
* **Tri-Mode Contract Discovery:** Operates seamlessly via (1) Two-Spec Structural AST Diffing, (2) Single-Spec Live Discovery, or (3) Pure Error-Driven Schema Inference (zero specs required).
* **AST Surgical Patching:** Traces dependencies across models and client files using Python AST, surgically applying patch blocks without file truncation.
* **Modal Ephemeral Linux Gate:** Executes the target pytest test suite inside an isolated Modal Cloud Linux micro-container with automatic dependency discovery.
* **Atomic GitHub PR:** Delivers unified diffs and incident post-mortems via atomic Git tree commits.

### 3. Pre-Flight GitHub PR Idempotency Gate
To prevent runaway token and compute costs, Aegis inspects the target GitHub repository for active remediation PRs matching the incident signature *before* invoking LLM inference or provisioning cloud containers—saving **100% of model tokens and cloud micro-VM costs** on repeated alerts.

### 4. Zero-Idle-Cost Cloud Serverless Daemon (`$0.00/month` Idle)
Via `aegis_serverless.py`, Aegis deploys onto Modal Cloud as an event-driven serverless daemon. The webhook receiver sleeps at **0 running containers**, waking in `<50ms` on inbound alerts and scaling back to zero. A scheduled cloud cron (`modal.Period(minutes=30)`) periodically inspects database health without needing a 24/7 dedicated VPS.

### 5. SRE Control Plane Web Dashboard
A Supabase-styled dark emerald web dashboard (`http://localhost:8080`) built on an 8px grid with real-time SSE (Server-Sent Events) event streaming, live before/after latency comparison bars, dynamic multi-app `.yaml` switcher, and post-mortem modal viewers.

---

## 🛠️ How We Built It
* **Reasoning Core:** **Meta Muse Spark 1.2** with structured system prompts, chain-of-thought bottleneck isolation, self-healing traceback retry loops, and automated markdown post-mortem authoring.
* **Deterministic Sandboxing:** **Modal Cloud** ephemeral micro-VMs running real PostgreSQL 16 servers and Linux Python runtime environments.
* **Telemetry & AST Engine:** Python `ast` parsing, `sqlglot` for cross-dialect query analysis, and `psycopg2` for read-only PostgreSQL catalog introspection.
* **Delivery & Version Control:** Direct GitHub REST API integration creating atomic blobs, trees, commits, and Pull Requests with zero local git write requirements.
* **Frontend Control Plane:** FastAPI, Server-Sent Events (SSE), Tailwind CSS, and custom SVG visualizers.

---

## 🧗 Challenges We Overcame
1. **Preventing Production Table Lock Cascades:** Naive index creation (`CREATE INDEX`) acquires an `AccessExclusiveLock`, queueing every subsequent read/write query and causing production outages. We engineered `DDLSafetyGuard` to strictly mandate `CREATE INDEX CONCURRENTLY` wrapped with `SET lock_timeout = '5s';` so the agent aborts if a lock cannot be acquired immediately.
2. **Local Caching vs. Production Scale:** On local developer environments, a 50,000-row table fits entirely in PostgreSQL RAM cache (`shared_buffers`), executing in ~5ms. We calibrated the watchdog to detect **sequential scan surges (`seq_tup_read`)** rather than waiting for single-query latency, catching $O(N)$ unindexed scans at the algorithmic level before they exhaust connection pools under concurrency.
3. **Anti-Truncation Surgical Code Patching:** When modifying complex client files, generative models frequently truncate surrounding code. We developed an AST-aware surgical patcher that locates the exact caller/model function block and replaces only the modified AST nodes, preserving surrounding business logic and comments.
4. **Token Economy & Debouncing:** In production outages, thousands of identical alerts flood within seconds. We implemented in-memory fingerprint debouncing combined with the **Pre-Flight GitHub PR Idempotency Gate**, eliminating redundant LLM calls.

---

## 🏆 Accomplishments That We're Proud Of
* **22/22 Automated Tests Passing:** 100% green test suite across configuration validation, external blind readiness, domain generalization, atomic GitHub delivery, and SRE Control Plane streaming.
* **Empirical -98.2% Latency Reduction:** Measured on live database workloads (reducing join latency from 242.87ms down to 4.37ms in Modal ephemeral sandboxes).
* **Zero-Write Production Safety:** Aegis can be deployed against any enterprise database with absolute peace of mind: it requires only read-only replica credentials and never modifies production tables directly.
* **100% Cloud-Native & Zero-Idle Cost:** Completely eliminates the need for expensive 24/7 listener servers.

---

## 🔬 What We Learned
* Generative AI without an empirical verification gate is fundamentally unfit for mission-critical infrastructure. The **Deterministic Sandbox Mandate** is the missing bridge between LLMs and real-world SRE.
* Deep database telemetry (`pg_stat_statements` + `pg_stat_user_tables`) contains rich semantic signals that, when paired with AST codebase analysis, allow an AI model to pinpoint bottlenecks without requiring human intervention.

---

## 🔮 What's Next for Aegis SRE
* **Vector C (Queue Saturation & Backpressure):** Autonomous diagnosis of Redis/Kafka queue consumer lag and partition rebalancing.
* **Autonomous Canary Deployments:** Triggering automated canary releases with rollback guards based on live telemetry anomaly scores.
* **eBPF Kernel Profiling:** Deep OS-level TCP socket and disk I/O contention analysis directly inside the watchdog loop.

---

## 💻 Try It Out
Clone the repository and launch the full interactive demo in one click:
```bash
git clone https://github.com/ahmedharib/meta-global-hack.git
cd meta-global-hack
# 1-Click Demo Launcher
run_demo.bat
# or via PowerShell
.\run_demo.ps1
```
*Monitored Service:* `http://localhost:8000` | *Aegis Control Plane:* `http://localhost:8080`
