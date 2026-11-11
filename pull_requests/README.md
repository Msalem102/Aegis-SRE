# 📦 Autonomous Pull Requests Created by Aegis SRE

This directory contains the actual production-ready Pull Requests autonomously synthesized, verified in cloud micro-VM sandboxes, and opened on GitHub by **Aegis SRE** during live end-to-end incident test runs against [`cupertino-coffee-store`](https://github.com/ahmedharib/mockStore).

---

## 📋 Live GitHub Pull Requests

| PR # | Incident Vector | Title & GitHub Link | Sandbox Speedup / Conformance | Target Repository |
| :---: | :--- | :--- | :---: | :--- |
| **#58** | **Database Contention** | [**perf(db): add covering indexes on orders.customer_id and order_items.order_id**](https://github.com/ahmedharib/mockStore/pull/58) | **-98.46% Latency Reduction**<br>*(240.0ms → 3.69ms in Modal micro-VM)* | [`ahmedharib/mockStore`](https://github.com/ahmedharib/mockStore) |
| **#56** | **API Contract Drift** | [**fix(contract): migrate checkout payload to RoastPay v2 schema**](https://github.com/ahmedharib/mockStore/pull/56) | **100% Pytest Pass (1/1)**<br>*(Modal Linux Container Gate: 0.07s)* | [`ahmedharib/mockStore`](https://github.com/ahmedharib/mockStore) |

---

## 📁 Directory Structure

```
pull_requests/
├── README.md                                  # This overview & summary of live PRs
├── PR_58_DATABASE_CONTENTION/                 # Actual PR #58 (Database Contention)
│   ├── PR_METADATA.json                       # Live GitHub PR metadata & URLs
│   ├── INCIDENT_POST_MORTEM.md                # Full post-mortem report authored by Meta Muse Spark
│   ├── migration.sql                          # Zero-downtime DDL with CONCURRENTLY & lock guards
│   ├── changes.patch                          # Unified git diff committed to the branch
│   └── sandbox_verification.json              # Modal Cloud PostgreSQL 16 micro-VM benchmark proof
└── PR_56_API_CONTRACT_DRIFT/                  # Actual PR #56 (API Contract Drift)
    ├── PR_METADATA.json                       # Live GitHub PR metadata & URLs
    ├── INCIDENT_POST_MORTEM.md                # Full post-mortem report authored by Meta Muse Spark
    ├── payment_models.py                      # Patched Pydantic v2 data models
    ├── payment_client.py                      # Patched client builder logic
    ├── changes.patch                          # Unified git diff committed to the branch
    └── sandbox_verification.json              # Modal Cloud Linux micro-container test proof
```

---

## 🔍 Pull Request Highlights

### 1. Database Contention ([PR #58](https://github.com/ahmedharib/mockStore/pull/58))
* **Detection:** Proactive sequential scan surge detected on `orders` and `order_items` during high customer checkout volume (+50,000 tuples read per query).
* **Synthesis:** Meta Muse Spark analyzed PostgreSQL `EXPLAIN` query plans and Python codebase ASTs, generating covering composite indexes with `INCLUDE` clauses to allow Index-Only Scans.
* **Production Safety Guard:** Mandated `CREATE INDEX CONCURRENTLY` and wrapped with strict session lock guards (`SET statement_timeout = '30s'; SET lock_timeout = '5s';`).
* **Modal Sandbox Benchmark:** Spawns an ephemeral PostgreSQL 16 micro-VM, clones schema, populates dataset cardinality, and records 5 warm benchmark runs:
  * **Baseline Latency:** `240.0 ms` (Sequential Scan Hash Join)
  * **Remediated Latency:** `3.69 ms` (Nested Loop Index-Only Scan)
  * **Empirical Speedup:** **-98.46% Latency Reduction** | **-90.55% CPU Reduction**
* **Delivery:** Authors the complete Incident Post-Mortem and opens an atomic Pull Request directly against the monitored repository.

### 2. API Contract Drift ([PR #56](https://github.com/ahmedharib/mockStore/pull/56))
* **Detection:** Catches runtime `HTTP 422 Unprocessable Entity: ROASTPAY_V2_SCHEMA_DRIFT` alerts when the third-party payment gateway enforces OpenAPI v2.
* **Diagnosis:** AST structural schema diffing isolates 4 breaking changes (removal of float `amount`, required integer `amount_cents`, and migration of `customer_address` to nested `billing.address.line1`).
* **Surgical AST Patching:** Surgically patches `app/payment_models.py` and `app/payment_client.py` without truncating comments or existing codebase logic.
* **Modal Cloud Test Gate:** Executes the target repository's pytest test suite inside an ephemeral Modal Linux container (`tests/test_payment_checkout.py` passes 100% in 0.07s).
* **Delivery:** Delivers atomic Pull Request with unified diff and post-mortem breakdown.
