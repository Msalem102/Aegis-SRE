# Post-Mortem — INC-20261104-API-5ED5D1 | RoastPay v2 Schema Drift (422 on /api/v1/orders/checkout)

**Incident ID:** INC-20261104-API-5ED5D1  
**Vector:** VECTOR_B_API_CONTRACT  
**Service:** cupertino-coffee-store  
**Endpoint:** `POST /api/v1/orders/checkout` -> upstream `POST /v1/coffee/charges`  
**Severity:** P1 — All checkouts failing (422)  
**Status:** Resolved — Verified Fix Ready to Merge  
**Date:** 2026-11-04

## 1. Executive Summary

Checkout for Cupertino Coffee Store began returning `HTTP 422 Unprocessable Entity: ROASTPAY_V2_SCHEMA_DRIFT`. Upstream RoastPay enforced v2 validation requiring integer `amount_cents` and nested `billing.address.line1`, while rejecting legacy float `amount` and flat `customer_address`. The downstream `payment_client` still built v1 payloads, causing 100% charge failure. An autonomous SRE loop diagnosed the contract diff, patched `payment_models.py` + `payment_client.py`, and verified the fix in Modal sandbox (`sb-oamVWxRLJF1TUlV6nXbMm7`) with `1 passed in 0.07s`.

## 2. Impact

- **User impact:** All `ORD-*` coffee orders (e.g., `ORD-LATTE-1042` $6.50) failed at checkout.
- **Error:** `{'error':'ROASTPAY_V2_SCHEMA_DRIFT','messages':["Field 'amount' (float) was removed in v2; send integer 'amount_cents'.", "Field 'customer_address' was removed in v2; send 'billing.address.line1'.", "Missing or non-integer required field 'amount_cents'.", "Missing required nested string field 'billing.address.line1'."]}`
- **Detection:** `tests/test_payment_checkout.py::test_coffee_order_checkout_conforms_to_roastpay_v2 FAILED` — `AssertionError: assert 'amount' not in {'order_id':'ORD-LATTE-1042','currency':'USD','amount':6.5,'customer_address':'1 Infinite Loop, Cupertino, CA 95014'}` + `app.payment_client.UpstreamContractError` from `server.py:177 checkout_order` -> `payment_client.py:59 charge_coffee_order` -> `payment_client.py:28 _simulate_roastpay_v2_gateway`.

## 3. Timeline (UTC 2026-11-04)

- **T0 Trigger:** `POST /api/v1/orders/checkout` returns 422. pytest collection `1 item`, `1 failed in 0.12s`.
- **T1 Diagnosis:** Contract diff analyzer confirms 4 BREAKING changes on `POST /v1/coffee/charges`.
- **T2 Patch:** Updated Pydantic models + builder to v2.
- **T3 Verification:** Modal cloud container re-runs target test — `1 passed in 0.07s`, exit 0, duration 4.67s.
- **T4 Ready to Merge:** This PR + post-mortem authored.

## 4. Root Cause Analysis

RoastPay v2 breaking change, no backwards compat:

| # | change_class | type | field | detail |
|---|---|---|---|---|
| 1 | BREAKING | FIELD_REMOVED | `amount` (number) | Float `amount` removed from spec. |
| 2 | BREAKING | FIELD_NEWLY_REQUIRED | `amount_cents` (integer) | Now strictly required. Must be `int(dollars*100)`. |
| 3 | BREAKING | FIELD_STRUCTURALLY_NESTED | `customer_address` -> `billing.address.line1` | Flat address relocated to nested hierarchy. |
| 4 | BREAKING | FIELD_NEWLY_REQUIRED | `billing` (object, leaf `billing.address.line1`) | Nested string required. |

Legacy code in `app/payment_models.py`:
```python
class CoffeeChargePayload(BaseModel):
    """Legacy v1 checkout payload sent by Cupertino Coffee Shop."""
    order_id: str
    currency: str = "USD"
    amount: float
    customer_address: str
```
and `app/payment_client.py::build_charge_payload` passed `amount=total_dollars, customer_address=street_address` directly, producing v1 JSON incompatible with v2 gateway.

## 5. Resolution — Verified Diff

No DDL/migration required (API contract only). Code diff applied to 2 files:

```diff
--- a/app/payment_models.py
+++ b/app/payment_models.py
@@ -1,9 +1,17 @@
 from pydantic import BaseModel
 
 
+class BillingAddress(BaseModel):
+    line1: str
+
+
+class Billing(BaseModel):
+    address: BillingAddress
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
@@ -39,12 +39,13 @@
 
 
 def build_charge_payload(order_id: str, total_dollars: float, street_address: str) -> Dict[str, Any]:
-    """Builds the outbound JSON dictionary for RoastPay."""
+    """Builds the outbound JSON dictionary for RoastPay v2."""
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

**Logic:** `int(round(total_dollars*100))` avoids float truncation (e.g., 6.5 -> 650). Pydantic v2 nesting enforces `billing.address.line1: str` type safety. `model_dump()` now emits e.g. `{'order_id':'ORD-LATTE-1042','currency':'USD','amount_cents':650,'billing':{'address':{'line1':'1 Infinite Loop, Cupertino, CA 95014'}}}`.

## 6. Sandbox Verification Proof

- **Runner:** MODAL_CLOUD_CONTAINER
- **Sandbox ID:** sb-oamVWxRLJF1TUlV6nXbMm7
- **Applied files:** `app/payment_models.py`, `app/payment_client.py`
- **Dependencies installed:** pytest, pydantic, httpx, fastapi>=0.110.0, uvicorn[standard]>=0.29.0, psycopg2-binary>=2.9.9, locust>=2.24.0
- **Test target:** `tests/test_payment_checkout.py`
- **Result:** `passed: true`, `exit_code: 0`, `duration_seconds: 4.67`, `stderr: ""`
- **Stdout:**
```
============================= test session starts ==============================
platform linux -- Python 3.12.10, pytest-9.2.0, pluggy-1.7.0 -- /usr/local/bin/python
cachedir: .pytest_cache
rootdir: /tmp/repo
plugins: anyio-4.16.0, locust-2.47.0
collecting ... collected 1 item
tests/test_payment_checkout.py::test_coffee_order_checkout_conforms_to_roastpay_v2 PASSED [100%]
============================== 1 passed in 0.07s ===============================
```

## 7. Lessons Learned & Follow-ups

- [ ] Add contract pinning / OpenAPI diff CI to catch `FIELD_REMOVED` / `FIELD_NEWLY_REQUIRED` before deploy.
- [ ] Add unit test for cents rounding edge cases (e.g., 6.555, 0.01) and empty `line1` validation.
- [ ] Monitor upstream RoastPay changelog webhook for v2.x deprecations.
- [ ] Consider idempotency key + currency minor-unit helper shared lib to avoid future float-money bugs.

## 8. PR Checklist

- [x] Conventional title `fix(contract): ...`
- [x] 2-file patch, no DB migration
- [x] Sandbox green, no stderr
- [x] Ready to merge, no manual QA blocker
