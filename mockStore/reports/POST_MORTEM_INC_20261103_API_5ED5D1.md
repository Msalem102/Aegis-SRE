# Post-Mortem: INC-20261103-API-5ED5D1 - RoastPay v2 Schema Drift (422 on Checkout)

**Incident ID:** INC-20261103-API-5ED5D1  
**Vector:** VECTOR_B_API_CONTRACT  
**Service:** cupertino-coffee-store  
**Endpoint:** POST /api/v1/orders/checkout  
**Severity:** SEV-1 (Checkout 100% failure - 422)  
**Date:** 2026-11-03  
**Status:** Resolved - Ready to Merge  
**Author:** Aegis SRE Incident Delivery Core (Meta Muse Spark)

## 1. Executive Summary

On 2026-11-03, `cupertino-coffee-store` checkout began failing with `HTTP 422 Unprocessable Entity: ROASTPAY_V2_SCHEMA_DRIFT`. Upstream RoastPay v2 removed `amount (float)` and `customer_address (flat string)` in favor of `amount_cents (int)` and `billing.address.line1 (nested string)`. The downstream client was still emitting v1. Autonomous diagnosis and sandbox-verified patch migrated the contract with zero caller-signature breakage. Verification: 1/1 tests passed in Modal sandbox.

## 2. Impact

- **User impact:** All coffee order checkouts via `/api/v1/orders/checkout` rejected (e.g., `ORD-LATTE-1042`, $6.50).
- **Error:** `UpstreamContractError: HTTP 422 ... ROASTPAY_V2_SCHEMA_DRIFT` from `app/payment_client.py:28` in `_simulate_roastpay_v2_gateway`.
- **Scope:** VECTOR_B_API_CONTRACT - downstream payload non-conformant to upstream v2.
- **Duration:** Until patch merge.

## 3. Timeline

- **Trigger:** `POST /api/v1/orders/checkout` -> 422 with messages: `Field 'amount' (float) was removed in v2; send integer 'amount_cents'.`, `Field 'customer_address' was removed in v2; send 'billing.address.line1'.`, `Missing or non-integer required field 'amount_cents'.`, `Missing required nested string field 'billing.address.line1'.`
- **Test failure observed:** `tests/test_payment_checkout.py::test_coffee_order_checkout_conforms_to_roastpay_v2 FAILED` - `AssertionError: assert 'amount' not in {'order_id': 'ORD-LATTE-1042', 'currency': 'USD', 'amount': 6.5, 'customer_address': '1 Infinite Loop, Cupertino, CA 95014'}`
- **Traceback:** `server.py:161 checkout_order` -> `app/payment_client.py:59 charge_coffee_order` -> `app/payment_client.py:28 _simulate_roastpay_v2_gateway` raises `UpstreamContractError`.
- **Diagnosis:** Confirmed v1 emission in `CoffeeChargePayload` and `build_charge_payload`.
- **Patch applied:** `app/payment_models.py`, `app/payment_client.py`.
- **Verification:** Modal sandbox `sb-2YJ5SSsKOgTZH8RVeo9Nzm` - PASSED.

## 4. Root Cause Analysis

RoastPay v2 breaking change:
- `amount: float (dollars)` **removed**. Must send `amount_cents: integer`. Prevents float rounding issues; requires `int(round(dollars * 100))`.
- `customer_address: string (flat)` **relocated** to `billing.address.line1: string (nested)`. Requires new `Billing { address: Address { line1: str } }` object hierarchy.

Downstream `CoffeeChargePayload(BaseModel)` still defined legacy fields:
```python
class CoffeeChargePayload(BaseModel):
    order_id: str
    currency: str = "USD"
    amount: float
    customer_address: str
```
and `build_charge_payload(order_id, total_dollars, street_address)` passed them through verbatim, triggering all 4 validation errors upstream.

### Technical Findings (Upstream Diff)

| Change Class | Type | Field | Details |
|---|---|---|---|
| BREAKING | FIELD_REMOVED | `amount` (number) | Removed from spec |
| BREAKING | FIELD_NEWLY_REQUIRED | `amount_cents` (integer) | Now strictly required |
| BREAKING | FIELD_STRUCTURALLY_NESTED | `customer_address` -> `billing.address.line1` | Relocated to nested hierarchy |
| BREAKING | FIELD_NEWLY_REQUIRED | `billing` (object) | Leaf `billing.address.line1` required |

Endpoint: `POST /v1/coffee/charges`

## 5. Resolution - Verified Diff

No SQL DDL required (contract-only fix). Preserved backward-compatible function signature.

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
@@ -39,12 +39,18 @@
 
 
 def build_charge_payload(order_id: str, total_dollars: float, street_address: str) -> Dict[str, Any]:
-    """Builds the outbound JSON dictionary for RoastPay."""
+    """Builds the outbound JSON dictionary for RoastPay v2.
+
+    Preserves backward-compatible signature (order_id, total_dollars, street_address)
+    while converting to v2 contract: dollars float -> amount_cents int,
+    flat customer_address -> billing.address.line1.
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

**Files changed:** `app/payment_models.py`, `app/payment_client.py`

## 6. Sandbox Verification Proof

- **Runner:** MODAL_CLOUD_CONTAINER
- **Sandbox ID:** sb-2YJ5SSsKOgTZH8RVeo9Nzm
- **Passed:** true, Exit Code: 0, Duration: 4.15s
- **Test Target:** tests/test_payment_checkout.py
- **Dependencies:** pytest, pydantic, httpx, fastapi>=0.110.0, uvicorn[standard]>=0.29.0, psycopg2-binary>=2.9.9, locust>=2.24.0
- **Applied Files:** app/payment_models.py, app/payment_client.py

```
============================= test session starts ==============================
platform linux -- Python 3.12.10, pytest-9.2.0, pluggy-1.7.0 -- /usr/local/bin/python
cachedir: .pytest_cache
rootdir: /tmp/repo
plugins: anyio-4.16.0, locust-2.47.0
collecting ... collected 1 item
tests/test_payment_checkout.py::test_coffee_order_checkout_conforms_to_roastpay_v2 PASSED [100%]
============================== 1 passed in 0.11s ===============================
```
STDERR: (empty)

Before fix: 1 failed. After fix: 1 passed. No regressions.

## 7. Lessons Learned

- Upstream versioned contracts need schema pinning and CI conformance tests - this test caught drift correctly.
- Float money fields are fragile; integer cents is correct.
- Flat-to-nested migrations break silently without contract diff monitoring.

## 8. Action Items

- [ ] Merge this PR to restore checkout.
- [ ] Add Pydantic strict validation (`strict=True`, `extra='forbid'`) to fail fast on removed fields.
- [ ] Add unit test for cents rounding edge cases (e.g., 6.555 -> 656, 0.01 -> 1).
- [ ] Subscribe to RoastPay changelog / OpenAPI diff CI check.
- [ ] Audit other callers of `CoffeeChargePayload` for v1 assumptions.

## Appendix

- Raw incident error: `HTTP 422 Unprocessable Entity: {'error': 'ROASTPAY_V2_SCHEMA_DRIFT', ...}`
- Repro payload: `{'order_id': 'ORD-LATTE-1042', 'currency': 'USD', 'amount': 6.5, 'customer_address': '1 Infinite Loop, Cupertino, CA 95014'}`
- Expected v2 payload: `{'order_id': 'ORD-LATTE-1042', 'currency': 'USD', 'amount_cents': 650, 'billing': {'address': {'line1': '1 Infinite Loop, Cupertino, CA 95014'}}}`
