# Post-Mortem: INC-20261104-API-941D — RoastPay v2 Schema Drift (422 on /api/v1/orders/checkout)

**Incident ID:** INC-20261104-API-941D  
**Vector:** VECTOR_B_API_CONTRACT  
**Service:** cupertino-coffee-store  
**Endpoint:** POST /api/v1/orders/checkout -> POST /v1/coffee/charges (RoastPay)  
**Severity:** SEV-2 (checkout blocked, HTTP 422)  
**Date (UTC):** 2026-11-04  
**Status:** Resolved — Ready to Merge  
**Authors:** Aegis SRE Incident Delivery Core (Meta Muse Spark)

## Executive Summary

Checkout began returning HTTP 422 `ROASTPAY_V2_SCHEMA_DRIFT` after RoastPay enforced v2 contract. The app still sent v1 fields `amount` (float dollars) and flat `customer_address`, both removed in v2. V2 requires integer `amount_cents` and nested `billing.address.line1`. Autonomous agent diagnosed 4 breaking changes, patched `app/payment_models.py` and `app/payment_client.py` with backward-compatible migration, and verified in Modal sandbox with 1/1 tests passing.

## Impact

- **User impact:** All coffee order checkouts via `/api/v1/orders/checkout` rejected (e.g., `ORD-LATTE-1042`, $6.50, `1 Infinite Loop, Cupertino, CA 95014`).
- **Error:** `422` + `AssertionError: assert 'amount' not in {'order_id': 'ORD-LATTE-1042', 'currency': 'USD', 'amount': 6.5, 'customer_address': ...}`
- **Scope:** 100% of RoastPay charge attempts using legacy builder.
- **Duration:** From v2 enforcement until patch merge.

## Timeline (UTC 2026-11-04)

- **T0 - Trigger:** `pytest tests/test_payment_checkout.py::test_coffee_order_checkout_conforms_to_roastpay_v2 FAILED` in 0.12s.
- **T1 - Triage:** Captured raw traceback, confirmed legacy payload contains forbidden `amount` key.
- **T2 - Diagnosis:** Diffed v1 vs v2 OpenAPI; identified 4 BREAKING changes (2x FIELD_NEWLY_REQUIRED, 1x FIELD_REMOVED, 1x FIELD_STRUCTURALLY_NESTED).
- **T3 - Patch:** Updated `CoffeeChargePayload` to v2 + added `_migrate_legacy_fields` validator; updated `build_charge_payload()` to compute `amount_cents` and nest billing.
- **T4 - Verification:** Modal sandbox `sb-Gjp0yXuc1hy4pt42JMdkC0` — `1 passed in 0.10s`, exit 0, duration 4.47s.
- **T5 - Delivery:** PR + post-mortem authored for merge.

## Root Cause Analysis

Downstream strictly sent RoastPay v1 shape. V2 removed `amount: number` and `customer_address: string`, requiring `amount_cents: integer` and `billing: object { address: { line1: string } }`. Gateway uses strict schema (additionalProperties: false / required enforcement), so any legacy key triggers `422 ROASTPAY_V2_SCHEMA_DRIFT`. Float dollars also risk rounding errors; cents as int is canonical. No migration shim existed in Pydantic model or client builder.

### Technical Findings

| # | Change Class | Type | Method / Endpoint | Field | Detail |
|---|--------------|------|-------------------|-------|--------|
| 1 | BREAKING | FIELD_NEWLY_REQUIRED | POST /v1/coffee/charges | `amount_cents: integer` | Leaf `amount_cents` now strictly required. |
| 2 | BREAKING | FIELD_NEWLY_REQUIRED | POST /v1/coffee/charges | `billing: object` | Leaf `billing.address.line1` now strictly required. |
| 3 | BREAKING | FIELD_REMOVED | POST /v1/coffee/charges | `amount: number` | Removed; presence causes 422. |
| 4 | BREAKING | FIELD_STRUCTURALLY_NESTED | POST /v1/coffee/charges | `customer_address` -> `billing.address.line1` | Relocated to nested hierarchy. |

Example failing payload:
```json
{
  "order_id": "ORD-LATTE-1042",
  "currency": "USD",
  "amount": 6.5,
  "customer_address": "1 Infinite Loop, Cupertino, CA 95014"
}
```
Expected v2 payload:
```json
{
  "order_id": "ORD-LATTE-1042",
  "currency": "USD",
  "amount_cents": 650,
  "billing": { "address": { "line1": "1 Infinite Loop, Cupertino, CA 95014" } }
}
```

## Resolution (Verified Patch)

**Files changed:** `app/payment_models.py`, `app/payment_client.py`

- Added `Address(line1: str)` and `Billing(address: Address)` models.
- Replaced `CoffeeChargePayload.amount: float` + `customer_address: str` with `amount_cents: int` + `billing: Billing`.
- Added `@model_validator(mode="before") _migrate_legacy_fields` for backward compat: converts v1 `amount` to cents, nests `customer_address`, strips legacy keys.
- Updated `build_charge_payload()` to compute `int(round(total_dollars*100))` and emit v2 JSON.

### Diff / DDL

```diff
--- a/app/payment_models.py
+++ b/app/payment_models.py
@@ -1,9 +1,38 @@
-from pydantic import BaseModel
+from typing import Any
+from pydantic import BaseModel, model_validator
+
+
+class Address(BaseModel):
+    line1: str
+
+
+class Billing(BaseModel):
+    address: Address
 
 
 class CoffeeChargePayload(BaseModel):
-    """Legacy v1 checkout payload sent by Cupertino Coffee Shop."""
+    """RoastPay v2 checkout payload sent by Cupertino Coffee Shop."""
     order_id: str
     currency: str = "USD"
-    amount: float
-    customer_address: str
+    amount_cents: int
+    billing: Billing
+
+    @model_validator(mode="before")
+    @classmethod
+    def _migrate_legacy_fields(cls, data: Any) -> Any:
+        """Backward-compat: migrate v1 `amount`/`customer_address` to v2."""
+        if isinstance(data, dict):
+            migrated = dict(data)
+            if "amount_cents" not in migrated and "amount" in migrated:
+                try:
+                    migrated["amount_cents"] = int(round(float(migrated.pop("amount")) * 100))
+                except (TypeError, ValueError):
+                    pass
+            elif "amount" in migrated:
+                migrated.pop("amount", None)
+            if "billing" not in migrated and "customer_address" in migrated:
+                migrated["billing"] = {"address": {"line1": migrated.pop("customer_address")}}
+            elif "customer_address" in migrated:
+                migrated.pop("customer_address", None)
+            return migrated
+        return data

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

## Sandbox Verification Proof

- **Runner:** MODAL_CLOUD_CONTAINER
- **Sandbox ID:** sb-Gjp0yXuc1hy4pt42JMdkC0
- **Applied files:** `app/payment_models.py`, `app/payment_client.py`
- **Dependencies:** pytest, pydantic, httpx, fastapi>=0.110.0, uvicorn[standard]>=0.29.0, psycopg2-binary>=2.9.9, locust>=2.24.0
- **Test target:** `tests/test_payment_checkout.py`
- **Result:** PASSED = true, exit_code = 0, duration = 4.47s
- **stdout:**
```
============================= test session starts ==============================
platform linux -- Python 3.12.10, pytest-9.2.0, pluggy-1.7.0 -- /usr/local/bin/python
cachedir: .pytest_cache
rootdir: /tmp/repo
plugins: anyio-4.16.0, locust-2.47.0
collecting ... collected 1 item
tests/test_payment_checkout.py::test_coffee_order_checkout_conforms_to_roastpay_v2 PASSED [100%]
============================== 1 passed in 0.10s ===============================
```
- **stderr:** (empty)
- **Before fix:** `1 failed in 0.12s` with `AssertionError: assert 'amount' not in {...}`
- **After fix:** `1 passed in 0.10s` — confirms no legacy `amount` key, correct `amount_cents` + `billing.address.line1`.

## Lessons Learned

1. Upstream contract drift without version pinning breaks strict gateways — need OpenAPI diff in CI.
2. Float money fields are fragile; integer cents should have been adopted earlier.
3. Flat address strings do not survive nesting migrations — validators must handle relocation.
4. Backward-compat validators allow safe rollout for in-flight v1 callers/queues.

## Action Items

| Owner | Action | Priority |
|-------|--------|----------|
| Backend | Merge this PR; deploy cupertino-coffee-store; monitor 422 rate -> 0 | P0 |
| SRE | Add RoastPay OpenAPI contract test + breaking-change alert to CI | P1 |
| Backend | Audit other RoastPay callers for `amount`/`customer_address` usage; backfill logs | P1 |
| QA | Add edge tests: rounding (e.g., 6.555 -> 656), empty address, both v1+v2 present | P2 |
| Product | Subscribe to RoastPay changelog / versioned SDK | P2 |

## Appendix

- Incident trigger: `tests/test_payment_checkout.py::test_coffee_order_checkout_conforms_to_roastpay_v2 FAILED [100%] | E AssertionError: assert 'amount' not in {...}`
- Diagnosis: Downstream still sends v1 fields, v2 requires `amount_cents` + `billing.address.line1`, gateway rejects legacy keys with 422.
- Rollback: Safe — validator accepts both v1 and v2 inputs; no DB migration required.
