# Post-Mortem — INC-20261104-API-5ED5D1: RoastPay v2 Schema Drift

**Incident ID:** INC-20261104-API-5ED5D1  
**Vector Type:** VECTOR_B_API_CONTRACT  
**Service:** cupertino-coffee-store  
**Endpoint:** `POST /api/v1/orders/checkout` -> upstream `POST /v1/coffee/charges` (RoastPay)  
**Severity:** P1 — Checkout fully blocked (HTTP 422 Unprocessable Entity)  
**Date:** 2026-11-04  
**Status:** Resolved — Ready to Merge, Sandbox Verified

## Executive Summary
On 2026-11-04, all checkout calls to `/api/v1/orders/checkout` failed with `HTTP 422 ROASTPAY_V2_SCHEMA_DRIFT`. Upstream RoastPay enforced v2 contract: float `amount` removed in favor of integer `amount_cents`, and flat `customer_address` relocated to nested `billing.address.line1`. The autonomous SRE core diagnosed the drift, migrated `CoffeeChargePayload` and `build_charge_payload`, and verified the fix in a Modal cloud sandbox (1 passed, exit 0).

## Impact
- **User impact:** 100% of coffee order checkouts (e.g. `ORD-LATTE-1042`, $6.50) rejected upstream.
- **Error:** `{'error': 'ROASTPAY_V2_SCHEMA_DRIFT', 'messages': ["Field 'amount' (float) was removed in v2; send integer 'amount_cents'.", "Field 'customer_address' was removed in v2; send 'billing.address.line1'.", "Missing or non-integer required field 'amount_cents'.", "Missing required nested string field 'billing.address.line1'."]}`
- **Duration:** Until patch merge; no data loss, no partial charges (fail-closed at gateway validation).

## Timeline (UTC 2026-11-04)
- **Trigger:** `test_coffee_order_checkout_conforms_to_roastpay_v2 FAILED` — `assert 'amount' not in {'order_id': 'ORD-LATTE-1042', 'currency': 'USD', 'amount': 6.5, 'customer_address': '1 Infinite Loop, Cupertino, CA 95014'}`
- **Trace:** `server.py:166 checkout_order` -> `app/payment_client.py:59 charge_coffee_order` -> `app/payment_client.py:28 _simulate_roastpay_v2_gateway` raises `UpstreamContractError: HTTP 422`
- **Diagnosis:** Contract diff identified 4 BREAKING changes on `POST /v1/coffee/charges`.
- **Patch applied:** `app/payment_models.py`, `app/payment_client.py`
- **Verification:** Modal sandbox `sb-3KXyBCgGkbRUUPeUyvsr5w` — 1 passed in 0.14s (total 4.62s), exit 0.

## Root Cause Analysis
RoastPay v2 breaking change:
1. **FIELD_REMOVED `amount` (number):** Float dollars (e.g. 6.5) removed to eliminate floating-point errors.
2. **FIELD_NEWLY_REQUIRED `amount_cents` (integer):** Now strictly required, leaf path `['amount_cents']`.
3. **FIELD_NEWLY_REQUIRED `billing` (object):** Now strictly required, leaf path `['billing.address.line1']`.
4. **FIELD_STRUCTURALLY_NESTED `customer_address` -> `billing.address.line1`:** Flat string relocated to nested hierarchy.

Downstream `CoffeeChargePayload(BaseModel)` still defined `amount: float` + `customer_address: str`, and `build_charge_payload(order_id, total_dollars, street_address)` emitted v1 JSON verbatim. Gateway v2 validator therefore returned 4 errors and 422.

## Resolution — Verified Diff / DDL
No DDL required (API contract fix only). Code diff:

```diff
--- a/app/payment_models.py
+++ b/app/payment_models.py
@@ -1,9 +1,17 @@
 from pydantic import BaseModel
 
 
+class Address(BaseModel):
+    line1: str
+
+
+class Billing(BaseModel):
+    address: Address
+
+
 class CoffeeChargePayload(BaseModel):
-    """Legacy v1 checkout payload sent by Cupertino Coffee Shop."""
+    """RoastPay v2 checkout payload."""
     order_id: str
     currency: str = "USD"
-    amount: float
-    customer_address: str
+    amount_cents: int
+    billing: Billing

--- a/app/payment_client.py
+++ b/app/payment_client.py
@@ -39,12 +39,17 @@
 
 
 def build_charge_payload(order_id: str, total_dollars: float, street_address: str) -> Dict[str, Any]:
-    """Builds the outbound JSON dictionary for RoastPay."""
+    """Builds the outbound JSON dictionary for RoastPay v2.
+
+    Preserves backward-compatible signature (total_dollars, street_address)
+    while emitting v2 contract: integer amount_cents + billing.address.line1.
+    """
+    amount_cents = int(round(total_dollars * 100))
     model = CoffeeChargePayload(
         order_id=order_id,
         currency="USD",
-        amount=total_dollars,
-        customer_address=street_address,
+        amount_cents=amount_cents,
+        billing={"address": {"line1": street_address}},
     )
     return model.model_dump()
```

**Design notes:**
- Preserves caller signature `(order_id, total_dollars, street_address)` for zero-call-site churn.
- `int(round(total_dollars * 100))` ensures correct cents conversion (6.5 -> 650).
- Pydantic `Address`/`Billing` enforce `billing.address.line1` as required non-empty string and `amount_cents` as int.

## Sandbox Verification Proof
- **Runner:** MODAL_CLOUD_CONTAINER
- **Sandbox ID:** sb-3KXyBCgGkbRUUPeUyvsr5w
- **Passed:** true, **Exit Code:** 0, **Duration:** 4.62s
- **Applied Files:** `app/payment_models.py`, `app/payment_client.py`
- **Test Target:** `tests/test_payment_checkout.py`
- **Dependencies:** pytest, pydantic, httpx, fastapi>=0.110.0, uvicorn[standard]>=0.29.0, psycopg2-binary>=2.9.9, locust>=2.24.0
- **stdout:**
```
============================= test session starts ==============================
platform linux -- Python 3.12.10, pytest-9.2.0, pluggy-1.7.0 -- /usr/local/bin/python
cachedir: .pytest_cache
rootdir: /tmp/repo
plugins: anyio-4.16.0, locust-2.47.0
collecting ... collected 1 item
tests/test_payment_checkout.py::test_coffee_order_checkout_conforms_to_roastpay_v2 PASSED [100%]
============================== 1 passed in 0.14s ===============================
```
- **stderr:** (empty)

## Action Items
- [ ] Add contract pin + OpenAPI diff check in CI for RoastPay spec changes.
- [ ] Add unit test for cents rounding edge cases (e.g. 6.555, 0.01, 0.00).
- [ ] Audit other services still emitting v1 `amount` / `customer_address`.
- [ ] Consider webhook / changelog subscription for RoastPay v2/v3 announcements.

## Appendix — Raw Trigger
- **HTTP Status:** 422 on `/api/v1/orders/checkout`
- **Trace excerpt:** `app.payment_client.UpstreamContractError: HTTP 422 Unprocessable Entity: {'error': 'ROASTPAY_V2_SCHEMA_DRIFT', ...}` at `server.py:166` / `payment_client.py:59` / `payment_client.py:28`.
