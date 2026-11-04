# Café Cupertino (`mockStore`)

> **Apple HIG Coffee Roastery Testbed for Autonomous SRE & Self-Healing Evaluation (Aegis)**

[![FastAPI](https://img.shields.io/badge/FastAPI-0.110.0-009688.svg?logo=fastapi)](https://fastapi.tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791.svg?logo=postgresql)](https://www.postgresql.org)
[![Aegis SRE](https://img.shields.io/badge/Aegis-Autonomous%20SRE-black.svg)](mockstore_aegis.yaml)
[![Apple Design](https://img.shields.io/badge/Design-Apple%20HIG%208px-gray.svg)](#apple-hig-design-system)

`mockStore` is a full-stack, single-page specialty coffee roastery web application. Behind its polished Cupertino storefront, `mockStore` serves as a dual-vector chaos and contract-drift testbed engineered specifically to benchmark and demonstrate **Aegis** — an autonomous AI Site Reliability Engineer that detects, verifies, and patches production failures.

---

##  Architecture & How mockStore Works With Aegis

```
                           +-------------------------------------------------------------+
                           |                      Café Cupertino                         |
                           |       (Single-Page Apple HIG Storefront + FastAPI)          |
                           +-------------------------------------------------------------+
                                       |                                    |
                    [Vector A: Pool Starvation]                  [Vector B: Contract Drift]
                                       |                                    |
                           Locust Swarm (25 users)              RoastPay v2 (Breaking Changes)
                                       |                                    |
                           15-Slot PostgreSQL Pool               HTTP 422 Unprocessable Entity
                                       |                                    |
                           HTTP 503 Pool Exhausted              Dispatches Webhook Alert Payload
                                                                            |
                                                                            v
+---------------------------------------------------------------------------------------------------------+
|                                              AEGIS SRE                                                  |
|                                                                                                         |
|  1. Webhook Ingestion        Receives incident payload (endpoint, status 422, stack trace)             |
|  2. Spec Diffing             Diffs contracts/payment_gateway_v1.json vs payment_gateway_v2.json        |
|  3. AST Code Mapping         Discovers app/payment_client.py & app/payment_models.py dependencies       |
|  4. LLM Synthesis            Synthesizes atomic Pydantic v2 model & payload adapter patch              |
|  5. Modal Micro-VM Gate      Runs `pytest tests/test_payment_checkout.py` in isolated cloud sandbox    |
|  6. Autonomous PR            Exit code 0 -> Commits branch and opens Pull Request on mockStore         |
+---------------------------------------------------------------------------------------------------------+
```

### Aegis Closed-Loop Self-Healing Flow
1. **Zero-Touch Incident Detection**: When upstream contract drift is triggered, `mockStore`'s checkout endpoint catches `UpstreamContractError` and asynchronously notifies `AEGIS_WEBHOOK_URL` (local daemon or deployed Modal cloud webhook).
2. **Contract Configuration (`mockstore_aegis.yaml`)**: Aegis reads the repository's configuration file to identify the upstream API baseline (`v1`) versus current specification (`v2`), the target code root (`app/`), and the deterministic verification gate (`tests/test_payment_checkout.py`).
3. **AST Dependency Mapping**: Aegis recursively inspects the Abstract Syntax Tree (AST) starting from `payment_client.py`, automatically resolving imported models in `payment_models.py` without requiring manual file listings.
4. **Isolated Micro-VM Verification**: Aegis spins up a secure, ephemeral Modal Cloud Linux container, applies the synthesized code patch, and runs the test suite. Aegis **never** alters test files.
5. **Atomic Pull Request**: Only when `pytest` exits with code `0` does Aegis commit the patch and open a clean GitHub Pull Request against the repository.

---

## 🔬 Test Vectors

Both test vectors can be controlled independently using the top navigation bar inside the running application:

### Vector A: PostgreSQL Connection Pool Starvation (`HTTP 503`)
* **Trigger**: Click **"Start Swarm"** in the top navigation bar.
* **Mechanism**:
  - Launches headless Locust workers (25 concurrent users at 5 users/sec) targeting `POST /api/v1/orders/checkout`.
  - The PostgreSQL connection pool is strictly capped at **15 connections** via `ThreadedConnectionPool(minconn=1, maxconn=15)`.
  - Each checkout acquires an exclusive row lock (`SELECT stock FROM products ... FOR UPDATE`) and holds the connection hostage in an `idle in transaction` state with a 3.5-second processing delay.
* **Observed Failure**:
  - Within 8–12 seconds, all 15 pool slots are fully saturated.
  - Subsequent storefront operations (browsing, fetching past orders, customer checkout) immediately fail with:
    ```json
    {
      "detail": "Database Connection Pool Exhausted: connection pool exhausted"
    }
    ```
* **Recovery**: Click **"Stop Swarm"** to terminate the background Locust process; connections drain and the pool recovers automatically.

---

### Vector B: Upstream Payment Gateway Contract Drift (`HTTP 422`)
* **Trigger**: Click **"Contract Drift: Off"** in the top bar to toggle it to **"Contract Drift: Active (v2 422)"**.
* **Mechanism**:
  - The upstream provider **RoastPay** deployed breaking changes in OpenAPI contract v2:
    | Field | RoastPay v1 (Legacy) | RoastPay v2 (Breaking) |
    | :--- | :--- | :--- |
    | **Order Amount** | `amount` (float dollars, e.g. `6.50`) | `amount_cents` (integer cents, e.g. `650`) |
    | **Customer Address** | `customer_address` (flat string) | `billing.address.line1` (nested JSON object) |
  - `mockStore`'s `app/payment_models.py` and `app/payment_client.py` still transmit the legacy v1 schema.
* **Observed Failure**:
  - Any customer checkout fails with `422 Unprocessable Entity`:
    ```json
    {
      "detail": {
        "error": "ROASTPAY_V2_SCHEMA_DRIFT",
        "messages": [
          "Field 'amount' (float) was removed in v2; send integer 'amount_cents'.",
          "Field 'customer_address' was removed in v2; send 'billing.address.line1'."
        ]
      }
    }
    ```
  - An incident alert is automatically dispatched to Aegis via `AEGIS_WEBHOOK_URL`.
* **Verification Gate**:
  - `pytest tests/test_payment_checkout.py` tests conversion of dollar amounts to integer cents and nested billing structures.
  - In baseline state, this test fails with `AssertionError: assert 'amount' not in payload`.
  - Once Aegis heals the code, the test passes with exit code `0`.

---

## 📁 Repository Structure

```text
mockStore/
├── .env.example                     # Environment template (PostgreSQL & Aegis webhook URL)
├── .gitignore                       # Git exclusion rules (venv, cache, env, IDEs)
├── docker-compose.yml               # Containerized PostgreSQL 16 (max_connections=25)
├── init.sql                         # Database schema & seed data (50k order items)
├── mockstore_aegis.yaml             # Aegis SRE upstream API configuration
├── requirements.txt                 # Python dependencies (FastAPI, uvicorn, psycopg2, locust, httpx, pytest)
├── server.py                        # FastAPI backend with dual-vector controls & webhook alerts
├── locustfile.py                    # Locust load generator for Vector A
├── index.html                       # Apple HIG Storefront (Coffee UI + independent vector controls)
├── contracts/
│   ├── payment_gateway_v1.json      # Baseline RoastPay OpenAPI 3.0 specification
│   └── payment_gateway_v2.json      # Upstream breaking RoastPay v2 OpenAPI specification
├── app/
│   ├── __init__.py
│   ├── payment_models.py            # Legacy v1 Pydantic checkout payload model
│   └── payment_client.py            # RoastPay client + deterministic v2 contract validator
└── tests/
    ├── __init__.py
    └── test_payment_checkout.py     # Modal Cloud verification gate (pytest)
```

---

## 🚀 Quick Start

### 1. Prerequisites
- [Docker & Docker Compose](https://www.docker.com/)
- [Python 3.10+](https://www.python.org/)

### 2. Environment Setup
```powershell
# Clone the repository
git clone <repo-url> mockStore
cd mockStore

# Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Copy environment variables
Copy-Item .env.example .env
```

### 3. Start Database
```powershell
docker compose up -d
```
> PostgreSQL 16 will start on `localhost:5432` and automatically execute `init.sql`, populating the catalog and 50,000 historical order records.

### 4. Run Application Server
```powershell
.\.venv\Scripts\python.exe -m uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```

Open `http://localhost:8000` in your web browser.

---

## 🧪 Testing with Aegis SRE

### Running the Modal Verification Test Manually
You can verify the current state of the payment gateway contract at any time:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_payment_checkout.py -v
```

* **Before Aegis Healing**:
  ```text
  FAILED tests/test_payment_checkout.py::test_coffee_order_checkout_conforms_to_roastpay_v2
  AssertionError: assert 'amount' not in {'amount': 6.5, 'currency': 'USD', 'customer_address': '1 Infinite Loop...'}
  ```
* **After Aegis Healing**:
  ```text
  PASSED tests/test_payment_checkout.py::test_coffee_order_checkout_conforms_to_roastpay_v2
  1 passed in 0.04s
  ```

### Autonomous Webhook Integration
When Aegis is running locally or in Modal Cloud:
1. Ensure `AEGIS_WEBHOOK_URL` in `.env` points to the listener (e.g. `http://localhost:8080/webhooks/alert`).
2. Toggle **Contract Drift: Active** in the storefront navigation bar.
3. Add any coffee item to your bag and click **Checkout Bag**.
4. The storefront reports `422 Unprocessable Entity` and `server.py` posts the stack trace to Aegis, initiating the autonomous repair pipeline.

---

## 🎨 Apple HIG Design System

The storefront adheres strictly to Apple's Human Interface Guidelines:
- **8pt Grid System**: All margins, padding, and layout bounds are multiples of 8px (`8px`, `16px`, `24px`, `32px`).
- **Warm Coffee Palette**: Cupertino Oat (`#FDFBF7`), Flat White Card (`#FFFFFF`), Roasted Bean (`#2D1B11`), Espresso Muted (`#7D6B5D`), and Crema Border (`#EFE8E1`).
- **Clean Typography**: Apple SF Pro system stack with standard weight hierarchies (`600` titles, `400` body).
- **Zero Distracting Gimmicks**: Free of excessive neon gradients, pulse glows, or artificial sci-fi aesthetic.
