# Post-Mortem — INC-20261104-API-C46E | RoastPay v2 Schema Drift (422 on /api/v1/orders/checkout)

**Incident ID:** INC-20261104-API-C46E  
**Vector:** VECTOR_B_API_CONTRACT  
**Service:** cupertino-coffee-store  
**Endpoint:** POST /api/v1/orders/checkout  
**Severity:** P1 - Checkout blocked (HTTP 422)  
**Date (UTC):** 2026-11-04  
**Status:** Resolved — Verified in sandbox  
**Sandbox:** sb-o0dRmcLHj9eWO4dSJY6WiE (MODAL_CLOUD_CONTAINER, 4.85s, exit 0)

## 1. Executive Summary

Checkout for Cupertino Coffee Store began returning `422 ROASTPAY_V2_SCHEMA_DRIFT` after RoastPay enforced v2 contract. Autonomous SRE diagnosed v1-to-v2 drift, migrated `CoffeeChargePayload` and `build_charge_payload` to v2 shape, and verified with `test_coffee_order_checkout_conforms_to_roastpay_v2` PASSED. No caller signature change required.

## 2. Impact

- **User impact:** All coffee order checkouts via `/api/v1/orders/checkout` rejected (e.g., `ORD-LATTE-1042`, $6.50).
- **Error:** `AssertionError: assert 'amount' not in {'order_id': 'ORD-LATTE-1042', 'currency': 'USD', 'amount': 6.5, 'customer_address': '1 Infinite Loop, Cupertino, CA 95014'}`
- **Upstream:** `POST /v1/coffee/charges` returns 422 `ROASTPAY_V2_SCHEMA_DRIFT`.

## 3. Timeline

- **Trigger:** pytest `tests/test_payment_checkout.py::test_coffee_order_checkout_conforms_to_roastpay_v2 FAILED [100%]` in 0.12s.
- **Diagnosis:** Identified RoastPay v2 breaking change: float `amount` removed for integer `amount_cents`, flat `customer_address` relocated to nested `billing.address.line1`.
- **Patch:** Updated `app/payment_models.py` + `app/payment_client.py`.
- **Verification:** Sandbox `sb-o0dRmcLHj9eWO4dSJY6WiE` — 1 passed in 0.14s.

## 4. Root Cause Analysis

Upstream contract diff (4 BREAKING changes):

| Change Class | Type | Field | Detail |
|---|---|---|---|
| BREAKING | FIELD_NEWLY_REQUIRED | `amount_cents: integer` | Now strictly required on POST /v1/coffee/charges |
| BREAKING | FIELD_NEWLY_REQUIRED | `billing: object` | Required leaf `billing.address.line1` |
| BREAKING | FIELD_REMOVED | `amount: number` | Removed from spec |
| BREAKING | FIELD_STRUCTURALLY_NESTED | `customer_address` -> `billing.address.line1` | Relocated to nested hierarchy |

Legacy `CoffeeChargePayload(order_id, currency, amount: float, customer_address: str)` and `build_charge_payload()` emitted v1 JSON, failing v2 validator checks for `amount` presence, missing `amount_cents` int, and missing `billing.address.line1` string.

## 5. Resolution (Verified Patch)

Migrated models to v2, added `Address`/`Billing`, converted dollars to cents with `int(round(total_dollars * 100))`, preserved `build_charge_payload(order_id: str, total_dollars: float, street_address: str)` signature for backward compatibility.

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
@@ -1,5 +1,5 @@
 from typing import Dict, Any
-from app.payment_models import CoffeeChargePayload
+from app.payment_models import CoffeeChargePayload, Billing, Address
 
 
 class UpstreamContractError(Exception):
@@ -18,18 +18,15 @@
         errors.append("Field 'customer_address' was removed in v2; send 'billing.address.line1'.")
     if not isinstance(payload.get("amount_cents"), int):
         errors.append("Missing or non-integer required field 'amount_cents'.")
-
     billing = payload.get("billing")
     line1 = billing.get("address", {}).get("line1") if isinstance(billing, dict) else None
     if not isinstance(line1, str) or not line1.strip():
         errors.append("Missing required nested string field 'billing.address.line1'.")
-
     if errors:
         raise UpstreamContractError(
             status_code=422,
             detail={"error": "ROASTPAY_V2_SCHEMA_DRIFT", "messages": errors},
         )
-
     return {
         "status": "authorized",
         "gateway_version": "2.0",
@@ -39,12 +36,13 @@
 
 
 def build_charge_payload(order_id: str, total_dollars: float, street_address: str) -> Dict[str, Any]:
-    """Builds the outbound JSON dictionary for RoastPay."""
+    """Builds the outbound JSON dictionary for RoastPay v2. Keeps v1 caller signature for backward compatibility."""
+    amount_cents = int(round(total_dollars * 100))
     model = CoffeeChargePayload(
         order_id=order_id,
         currency="USD",
-        amount=total_dollars,
-        customer_address=street_address,
+        amount_cents=amount_cents,
+        billing=Billing(address=Address(line1=street_address)),
     )
     return model.model_dump()
```

**Files changed:** `app/payment_models.py`, `app/payment_client.py`

## 6. Sandbox Verification Proof

- **Runner:** MODAL_CLOUD_CONTAINER
- **Sandbox ID:** sb-o0dRmcLHj9eWO4dSJY6WiE
- **Passed:** true, Exit 0, Duration 4.85s
- **Test target:** tests/test_payment_checkout.py
- **Dependencies:** pytest, pydantic, httpx, fastapi>=0.110.0, uvicorn[standard]>=0.29.0, psycopg2-binary>=2.9.9, locust>=2.24.0

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

stderr: (empty)

## 7. Lessons Learned & Action Items

- [ ] Add contract-diff CI gate to detect `FIELD_REMOVED` / `FIELD_NEWLY_REQUIRED` before upstream enforcement.
- [ ] Prefer integer minor units (`amount_cents`) for all money fields to avoid float drift.
- [ ] Add Pact/OpenAPI snapshot test for `billing.address.line1` nesting.
- [ ] Monitor 422 `ROASTPAY_V2_SCHEMA_DRIFT` rate post-deploy.

## 8. PR Readiness

Ready to merge. Backward-compatible caller signature, Pydantic-enforced v2 schema, sandbox green. Conventional title: `fix(contract): migrate checkout payload to RoastPay v2 schema`.
