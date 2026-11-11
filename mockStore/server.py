import os
import subprocess
import time
import sys
import traceback
from pathlib import Path
from contextlib import asynccontextmanager
from dotenv import load_dotenv

# Load local environment variables from .env
load_dotenv(Path(__file__).resolve().parent / ".env")

from fastapi import FastAPI, HTTPException, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from typing import Optional
from pydantic import BaseModel
import psycopg2
from psycopg2 import pool
import httpx

from app.payment_client import charge_coffee_order, UpstreamContractError

DB_CONFIG = {
    "dbname": os.getenv("PGDATABASE", "postgres"),
    "user": os.getenv("PGUSER", "app_user"),
    "password": os.getenv("PGPASSWORD", "app_secret"),
    "host": os.getenv("PGHOST", "localhost"),
    "port": int(os.getenv("PGPORT", "5432"))
}

# Constrained pool: 15 connections max for application traffic
db_pool = None

def init_db_pool():
    global db_pool
    if db_pool is None:
        try:
            db_pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=15,
                **DB_CONFIG
            )
            print("Connected to PostgreSQL: ThreadedConnectionPool (1-15 slots) initialized.")
        except Exception as e:
            print(f"Warning: Could not connect to PostgreSQL ({e}). Pool will re-attempt on demand.")
            db_pool = None
    return db_pool

locust_process = None
contract_drift_enabled = False

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db_pool()
    yield
    global locust_process, db_pool
    if locust_process and locust_process.poll() is None:
        try:
            locust_process.terminate()
        except Exception:
            pass
    if db_pool:
        try:
            db_pool.closeall()
        except Exception:
            pass

app = FastAPI(title="Store Simulation API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class CheckoutRequest(BaseModel):
    customer_id: int
    product_id: int
    quantity: int
    client_source: Optional[str] = "storefront"

def get_connection(timeout: float = 3.0):
    global db_pool
    if db_pool is None:
        init_db_pool()
    if db_pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database Connection Pool Unavailable: PostgreSQL container not reachable at localhost:5432"
        )
    start_time = time.time()
    while True:
        try:
            return db_pool.getconn()
        except pool.PoolError as e:
            if time.time() - start_time >= timeout:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"Database Connection Pool Exhausted: {str(e)}"
                )
            time.sleep(0.05)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Database Connection Error: {str(e)}"
            )

@app.get("/api/v1/products")
def list_products():
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT product_id, name, price, stock FROM products ORDER BY product_id;")
        rows = cur.fetchall()
        cur.close()
        return [{"id": r[0], "name": r[1], "price": float(r[2]), "stock": r[3]} for r in rows]
    finally:
        db_pool.putconn(conn)

@app.get("/api/v1/customers/{customer_id}/orders")
def get_customer_orders(customer_id: int):
    conn = get_connection()
    try:
        cur = conn.cursor()
        # Triggers sequential table scan across 50,000 rows
        cur.execute("""
            SELECT o.order_id, o.status, i.product_id, i.quantity
            FROM orders o
            JOIN order_items i ON o.order_id = i.order_id
            WHERE o.customer_id = %s;
        """, (customer_id,))
        rows = cur.fetchall()
        cur.close()
        return {"customer_id": customer_id, "orders_count": len(rows)}
    finally:
        db_pool.putconn(conn)

# Synchronous endpoint (def) dispatched to FastAPI threadpool to simulate real concurrent DB locks & pool exhaustion
@app.post("/api/v1/orders/checkout")
def checkout_order(req: CheckoutRequest, request: Request):
    global contract_drift_enabled
    conn = get_connection()
    cur = conn.cursor()
    try:
        # 1. Deduct stock (acquires row-level exclusive lock)
        cur.execute(
            "UPDATE products SET stock = stock - %s WHERE product_id = %s RETURNING price;",
            (req.quantity, req.product_id)
        )
        row = cur.fetchone()
        price = float(row[0]) if row else 14.50

        # 2. Sequential scan lock
        cur.execute("SELECT * FROM order_items WHERE product_id = %s;", (req.product_id,))
        _ = cur.fetchall()

        # 3. Third-party payment gateway call
        order_id = f"ORD-LATTE-{int(time.time() * 1000) % 100000}"
        total_dollars = round(price * req.quantity, 2)
        street_address = "1 Infinite Loop, Cupertino, CA 95014"

        # Differentiate background swarm load (Vector A DB contention / pool exhaustion)
        # from real customer checkouts (Vector B API contract drift testing).
        user_agent = request.headers.get("user-agent", "").lower()
        is_swarm_traffic = (
            request.headers.get("x-simulation-swarm") == "true"
            or "locust" in user_agent
            or req.client_source == "swarm"
        )

        if contract_drift_enabled and not is_swarm_traffic:
            # Vector B: Test upstream RoastPay v2 contract drift on real customer checkouts
            try:
                charge_coffee_order(
                    order_id=order_id,
                    total_dollars=total_dollars,
                    street_address=street_address
                )
            except UpstreamContractError as exc:
                webhook_url = os.getenv("AEGIS_WEBHOOK_URL", "http://localhost:8080/webhooks/alert")
                if webhook_url:
                    try:
                        r = httpx.post(
                            webhook_url,
                            json={
                                "event": "checkout_failed",
                                "service": "cupertino-coffee-store",
                                "http_status": exc.status_code,
                                "endpoint": "/api/v1/orders/checkout",
                                "error_message": str(exc),
                                "traceback": traceback.format_exc(),
                            },
                            timeout=5.0
                        )
                        print(f"[mockStore] Dispatched Vector B alert to {webhook_url} (HTTP {r.status_code})")
                    except Exception as hook_err:
                        print(f"[mockStore] Notice: Alert webhook to {webhook_url} failed ({hook_err})")
                raise HTTPException(status_code=422, detail=exc.detail)
        else:
            # Vector A baseline / Swarm traffic: simulate payment roundtrip sleep inside transaction (3.5s hold)
            time.sleep(3.5)

        # 4. Finalize order
        cur.execute(
            "INSERT INTO orders (customer_id, status) VALUES (%s, 'PAID');",
            (req.customer_id,)
        )
        conn.commit()
        return {"status": "SUCCESS", "message": "Order processed", "order_id": order_id}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cur.close()
        db_pool.putconn(conn)

# --- Direct Vector B Checkout Route (for Webhook / Plan Section 4) ---
@app.post("/api/checkout")
def direct_checkout_endpoint(order_id: str = "ORD-LATTE-1042", total_dollars: float = 6.50):
    try:
        return charge_coffee_order(
            order_id=order_id,
            total_dollars=total_dollars,
            street_address="1 Infinite Loop, Cupertino, CA 95014",
        )
    except UpstreamContractError as exc:
        webhook_url = os.getenv("AEGIS_WEBHOOK_URL", "http://localhost:8080/webhooks/alert")
        if webhook_url:
            try:
                r = httpx.post(
                    webhook_url,
                    json={
                        "event": "checkout_failed",
                        "service": "cupertino-coffee-store",
                        "http_status": exc.status_code,
                        "endpoint": "/api/checkout",
                        "error_message": str(exc),
                        "traceback": traceback.format_exc(),
                    },
                    timeout=5.0
                )
                print(f"[mockStore] Dispatched Vector B alert to {webhook_url} (HTTP {r.status_code})")
            except Exception as hook_err:
                print(f"[mockStore] Notice: Alert webhook to {webhook_url} failed ({hook_err})")
        raise HTTPException(status_code=422, detail=exc.detail)

# Helper to find locust executable regardless of which python was launched
def get_locust_cmd():
    # Prefer .venv if it exists, otherwise sys.executable
    venv_py = Path(__file__).resolve().parent / ".venv" / "Scripts" / "python.exe"
    py_exec = str(venv_py) if venv_py.exists() else sys.executable
    return [
        py_exec, "-m", "locust",
        "-f", "locustfile.py",
        "--headless",
        "-u", "25",
        "-r", "5",
        "--host", "http://127.0.0.1:8000"
    ]

# --- Swarm Controls (Vector A) ---
@app.post("/api/admin/start-swarm")
def start_swarm():
    global locust_process
    if locust_process is None or locust_process.poll() is not None:
        cmd = get_locust_cmd()
        locust_process = subprocess.Popen(cmd)
        return {"status": "Swarm launched", "users": 25, "spawn_rate": 5, "pid": locust_process.pid}
    return {"status": "Swarm already active", "pid": locust_process.pid}

@app.post("/api/admin/stop-swarm")
def stop_swarm():
    global locust_process
    if locust_process and locust_process.poll() is None:
        locust_process.terminate()
        locust_process = None
        return {"status": "Swarm stopped"}
    locust_process = None
    return {"status": "No active swarm"}

@app.get("/api/admin/swarm-status")
def swarm_status():
    global locust_process
    is_running = locust_process is not None and locust_process.poll() is None
    return {
        "is_running": is_running,
        "pid": locust_process.pid if is_running else None
    }

# --- Contract Drift Controls (Vector B) ---
@app.get("/api/admin/drift-status")
def drift_status():
    global contract_drift_enabled
    return {"drift_enabled": contract_drift_enabled}

@app.post("/api/admin/toggle-contract-drift")
def toggle_contract_drift():
    global contract_drift_enabled
    contract_drift_enabled = not contract_drift_enabled
    return {
        "status": "success",
        "drift_enabled": contract_drift_enabled,
        "message": f"Contract drift set to {contract_drift_enabled}"
    }

@app.get("/api/admin/pool-status")
def pool_status():
    global db_pool
    if not db_pool:
        return {
            "connected": False,
            "max_connections": 15,
            "used_connections": 0,
            "available_connections": 0,
            "exhausted": False
        }
    try:
        used = len(db_pool._used) if hasattr(db_pool, "_used") else 0
        avail = len(db_pool._pool) if hasattr(db_pool, "_pool") else 0
        return {
            "connected": True,
            "max_connections": 15,
            "used_connections": used,
            "available_connections": avail,
            "exhausted": used >= 15
        }
    except Exception as e:
        return {"connected": False, "error": str(e), "max_connections": 15, "used_connections": 0}

# Serve frontend & static assets directly
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
def serve_index():
    index_file = BASE_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Store Simulation API is running. index.html not found."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
