# 🎬 Aegis SRE — 3-Minute Video Walkthrough Script

This script is structured for a high-impact, professional 2.5 to 3-minute video recording for the **Meta Global AI Developer Hackathon**.

---

## ⏱️ Video Timeline Overview

| Timestamp | Segment | Visual on Screen | Key Narration Focus |
| :--- | :--- | :--- | :--- |
| **0:00 - 0:35** | **The Hook & Problem** | Slide / Code editor + Terminal | Why AI coding bots fail in production & The Deterministic Sandbox Mandate |
| **0:35 - 1:25** | **Vector A: DB Contention** | Split Screen: Coffee Store (:8000) & Aegis Control Plane (:8080) | Sequential scan surge, Modal Cloud verification, GitHub PR with -98% latency |
| **1:25 - 2:05** | **Vector B: API Contract Drift** | Coffee Store (:8000) & Aegis Live Event Stream | Upstream 422 alert, AST diff, Modal Linux micro-VM pytest, GitHub PR |
| **2:05 - 2:35** | **Architecture & Safety** | SRE UI + Serverless Architecture Diagram | Pre-flight idempotency gate, `readonly=True` safety, scale-to-zero on Modal |
| **2:35 - 3:00** | **Conclusion & Call to Action** | SRE Control Plane & GitHub PR list | 22/22 tests passing, open source, 1-click launcher |

---

## 🎙️ Step-by-Step Recording Script

### [0:00 - 0:35] Part 1: The Hook & The Problem
* **Visual:** Show code editor with an unindexed SQL query or terminal.
* **Narration:**
  > *"When production databases grind to a halt at 3:00 AM, or an upstream payment gateway unexpectedly breaks backward compatibility, on-call engineers face high MTTR and stressful outages.*
  >
  > *Most AI coding assistants are dangerous here—they hallucinate untested SQL that locks production tables, or generate patches that fail in production.*
  >
  > *Meet **Aegis SRE**—an autonomous, closed-loop Site Reliability Engineering agent built for the Meta Global AI Hackathon. Aegis operates under the **Deterministic Sandbox Mandate**: zero code reaches GitHub without passing an isolated cloud micro-VM verification gate."*

---

### [0:35 - 1:25] Part 2: Vector A Demo (Database Contention)
* **Visual:** Open browser with two side-by-side tabs: `Cupertino Coffee Store` (`:8000`) on the left, and `Aegis SRE Control Plane` (`:8080`) on the right.
* **Action:**
  1. On the left tab (`mockStore`), click **"Start Swarm"**.
  2. Point to the right tab (`Aegis Control Plane`).
* **Narration:**
  > *"Here on the left is our production service: Cupertino Coffee Store. We launch a Locust swarm simulating 25 concurrent users. Notice what happens: 50,000 unindexed tuples are scanned on every single checkout.*
  >
  > *Immediately, on the right, Aegis SRE's Direct PostgreSQL Watchdog detects the sequential scan surge in real time—without needing third-party APM agents.*
  >
  > *Aegis dispatches **Meta Muse Spark**, which analyzes the AST, recognizes the missing covering index, and synthesizes a non-blocking `CREATE INDEX CONCURRENTLY` wrapped in a 5-second lock timeout.*
  >
  > *Before opening a PR, Aegis provisions an ephemeral PostgreSQL 16 micro-VM in Modal Cloud, seeds realistic rows, and measures the speedup. As you can see on the visualizer, query latency dropped from **242 milliseconds to just 4.3 milliseconds—a 98.2% latency reduction**!*
  >
  > *With verification passed, Aegis automatically opened this ready-to-merge GitHub Pull Request with a comprehensive incident post-mortem report."*

---

### [1:25 - 2:05] Part 3: Vector B Demo (API Contract Drift)
* **Visual:** Switch focus to Cupertino Coffee Store (`:8000`).
* **Action:**
  1. Click **"Contract Drift"** (turns amber/active).
  2. Click **"Checkout Bag"** (an HTTP 422 error appears in the cart).
  3. Look at the Aegis Live Event Stream.
* **Narration:**
  > *"Now, let's test Vector B: Upstream API Contract Drift. Our payment processor, RoastPay, just upgraded to v2, breaking backward compatibility by requiring `amount_cents` instead of float `amount`.*
  >
  > *When a customer clicks 'Checkout Bag', the application throws an HTTP 422 error and fires a webhook into Aegis.*
  >
  > *Aegis ingests the error, diffs the OpenAPI specification, and uses Meta Muse Spark to perform surgical AST code patching on `payment_client.py`.*
  >
  > *Aegis spins up a clean Linux micro-VM in Modal Cloud, installs dependencies, and runs the target pytest suite. 100% of tests pass! Aegis then opens an atomic GitHub Pull Request containing the exact unified diff."*

---

### [2:05 - 2:35] Part 4: Enterprise Safety & Zero-Idle-Cost
* **Visual:** Aegis Control Plane showing the Pre-Flight Idempotency Gate log and Settings/Config tab.
* **Narration:**
  > *"What makes Aegis enterprise-ready?*
  >
  > *First, **Cost Efficiency**: Aegis features a **Pre-Flight GitHub PR Idempotency Gate**. If another alert fires for the same incident while a PR is already open, Aegis skips the LLM and cloud sandboxes, saving 100% of token and compute costs.*
  >
  > *Second, **Zero Production Write Risk**: The watchdog uses strictly read-only connections (`readonly=True`). It never executes DDL against your production database.*
  >
  > *Third, **Scale-to-Zero Continuous Operation**: Using Modal, Aegis sleeps at 0 running containers when idle—costing **$0.00/month** until an alert arrives."*

---

### [2:35 - 3:00] Part 5: Conclusion & Wrap-Up
* **Visual:** Terminal showing `pytest tests/ -v` (22 passed) and the GitHub repository.
* **Narration:**
  > *"Aegis SRE comes with a complete suite of 22 automated tests passing, a full CLI, a 1-click demo launcher, and support for multi-app YAML manifests.*
  >
  > *By combining **Meta Muse Spark** reasoning with **Modal Cloud's Deterministic Sandboxes**, Aegis SRE brings true autonomous self-healing to modern cloud infrastructure.*
  >
  > *Check out the repository on GitHub, and thank you for watching!"*
