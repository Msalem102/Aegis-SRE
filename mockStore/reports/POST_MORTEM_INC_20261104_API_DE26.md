# Post-Mortem: INC-20261104-API-DE26 — RoastPay v2 Schema Drift (422 on /api/v1/orders/checkout)

**Incident ID:** INC-20261104-API-DE26  
**Vector:** VECTOR_B_API_CONTRACT  
**Service:** cupertino-coffee-store  
**Endpoint:** POST /api/v1/orders/checkout -> POST /v1/coffee/charges (RoastPay)  
**Severity:** P1 - Checkout Blocked (HTTP 422)  
**Date:** 2026-11-04  
**Status:** Resolved - Verified in Sandbox  
**Author:** Aegis SRE Incident Delivery Core

## 1. Executive Summary

Checkout for Cupertino Coffee Store failed conformance with RoastPay v2, returning HTTP 422 `ROASTPAY_V2_SCHEMA_DRIFT`. The downstream payload still used v1 fields `amount` (float dollars) and `customer_address` (flat string), both removed in v2. Upstream now strictly requires integer `amount_cents` and nested `billing.address.line1`. Autonomous remediation migrated `CoffeeChargePayload` and `build_charge_payload()` to v2 schema. Sandbox verification confirms `tests/test_payment_checkout.py::test_coffee_order_checkout_conforms_to_roastpay_v2` now PASSED.

## 2. Impact

- **User Impact:** All coffee order checkouts via `/api/v1/orders/checkout` rejected (example order `ORD-LATTE-1042`, $6.50).
- **Error Signature:** `AssertionError: assert 'amount' not in {'order_id': 'ORD-LATTE-1042', 'currency': 'USD', 'amount': 6.5, 'customer_address': '1 Infinite Loop, Cupertino, CA 95014'}`
- **Upstream Code:** 422 ROASTPAY_V2_SCHEMA_DRIFT
- **Scope:** 100% of RoastPay charge requests using legacy builder.

## 3. Timeline

- **T0 - Detection:** pytest `tests/test_payment_checkout.py::test_coffee_order_checkout_conforms_to_roastpay_v2 FAILED [100%]` in 0.10s.
- **T1 - Diagnosis:** Contract diff analysis identified 4 BREAKING changes (2x FIELD_NEWLY_REQUIRED, 1x FIELD_REMOVED, 1x FIELD_STRUCTURALLY_NESTED).
- **T2 - Patch:** Updated `app/payment_models.py` and `app/payment_client.py` to v2 schema.
- **T3 - Verification:** Modal sandbox `sb-Bsx3tF1tdveVt3Ur1HPkJj` - 1 passed in 0.10s (total duration 4.11s, exit_code 0).

## 4. Root Cause Analysis

Legacy v1 model:

```python
class CoffeeChargePayload(BaseModel):
    order_id: str
    currency: str = "USD"
    amount: float
    customer_address: str
```

v2 contract removes float `amount` to eliminate floating-point rounding risk, requiring integer minor units `amount_cents`. It also normalizes address handling by nesting flat `customer_address` into `billing.address.line1` object for extensibility (line2, city, zip, country). Downstream was not migrated, causing missing required leaves `amount_cents`, `billing.address.line1` and presence of forbidden `amount`.

Technical findings:

| # | Change Class | Type | Field | Detail |
|---|---|---|---|---|
| 1 | BREAKING | FIELD_NEWLY_REQUIRED | `amount_cents: integer` | Now strictly required on POST /v1/coffee/charges |
| 2 | BREAKING | FIELD_NEWLY_REQUIRED | `billing: object` | Required leaf `billing.address.line1` |
| 3 | BREAKING | FIELD_REMOVED | `amount: number` | Removed from spec |
| 4 | BREAKING | FIELD_STRUCTURALLY_NESTED | `customer_address` -> `billing.address.line1` | Relocated to nested hierarchy |

## 5. Resolution - Verified Diff

Applied files: `app/payment_models.py`, `app/payment_client.py`

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
@@ -1,5 +1,5 @@
 from typing import Dict, Any
-from app.payment_models import CoffeeChargePayload
+from app.payment_models import CoffeeChargePayload, Billing, BillingAddress
 
 
 class UpstreamContractError(Exception):
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
+        billing=Billing(address=BillingAddress(line1=street_address)),
     )
     return model.model_dump()
```

Key logic: `amount_cents = int(round(total_dollars * 100))` ensures $6.5 -> 650 correctly; `Billing(address=BillingAddress(line1=street_address))` satisfies nested requirement.

## 6. Sandbox Verification Proof

- **Runner:** MODAL_CLOUD_CONTAINER
- **Sandbox ID:** sb-Bsx3tF1tdveVt3Ur1HPkJj
- **Passed:** true, exit_code 0, duration 4.11s
- **Test Target:** tests/test_payment_checkout.py
- **Dependencies:** pytest, pydantic, httpx, fastapi>=0.110.0, uvicorn[standard]>=0.29.0, psycopg2-binary>=2.9.9, locust>=2.24.0

stdout:

```text
============================= test session starts ==============================
platform linux -- Python 3.12.10, pytest-9.2.0, pluggy-1.7.0 -- /usr/local/bin/python
cachedir: .pytest_cache
rootdir: /tmp/repo
plugins: anyio-4.16.0, locust-2.47.0
collecting ... collected 1 item
tests/test_payment_checkout.py::test_coffee_order_checkout_conforms_to_roastpay_v2 PASSED [100%]
============================== 1 passed in 0.10s ===============================
```

stderr: (empty)

Before fix, same test FAILED with `assert 'amount' not in payload` on identical payload. After fix, PASSED.

## 7. Action Items

- [x] Merge this PR to migrate to RoastPay v2
- [ ] Add contract pinning / OpenAPI diff check in CI to catch FIELD_REMOVED / FIELD_NEWLY_REQUIRED early
- [ ] Add unit test for dollars->cents edge cases (e.g., 6.555 -> 656, 0.01 -> 1)
- [ ] Audit other RoastPay callers for v1 field usage
- [ ] Monitor 422 rate on /api/v1/orders/checkout post-deploy

## 8. Risk Assessment

Low risk. Change is isolated to payload builder, strictly typed via Pydantic, backward-compatible with v2 only (v1 deprecated). No DB migration required. Verified in clean sandbox.
