# Post-Mortem: INC-20261028-API-01 — Upstream Gateway v2 Contract Violation (422)

**Incident ID:** INC-20261028-API-01  
**Vector Type:** VECTOR_B_API_CONTRACT  
**Service:** `client_repo`  
**Endpoint:** `POST /api/v2/payments/charge`  
**Severity:** P1 — All charge requests failing  
**Status:** Resolved — Verified Fix  
**Date:** 2026-10-28  
**Sandbox:** `sb-01M61FW9YB73R0FXBRS09X8HE6` (MODAL_CLOUD_CONTAINER)

---

## 1. Executive Summary

On 2026-10-28, `client_repo`'s payment integration began returning HTTP 422 Unprocessable Entity against the Upstream Gateway v2. The upstream OpenAPI spec introduced breaking changes requiring `amount_cents` (integer) and `billing.address.line1` (object) while removing `amount` (float) and `customer_address` (string). The downstream `PaymentClient` was not migrated and continued sending the legacy payload, causing 100% failure of `test_client_payload_against_upstream_v2_gateway`. An autonomous remediation updated the data model and payload builder to be v2-compliant while preserving backward compatibility for legacy callers. Sandbox verification confirms 1/1 tests passing.

## 2. Impact

- **Affected Service:** `client_repo` → `PaymentClient.charge_customer()` → `Upstream Gateway V2`
- **Failure Rate:** 100% of charge requests via `PaymentClient`
- **Error:** `ValueError: Upstream Gateway 422 Unprocessable Entity - Contract Violations: ['Missing required field: amount_cents (integer)', 'Missing required field: billing (object)', 'Deprecated/Removed field present: customer_address', 'Deprecated/Removed field present: amount (float)']`
- **User Impact:** No charges could be processed; downstream checkout blocked.
- **Detection:** `tests/test_payment_client.py::test_client_payload_against_upstream_v2_gateway FAILED [100%]` at `src/payment_client.py:27` → `tests/test_payment_client.py:41` in `send_charge` mock.

## 3. Timeline (UTC)

| Time | Event |
|------|-------|
| 2026-10-28 T00:00 | Upstream Gateway v2 contract deployed (breaking OpenAPI changes) |
| 2026-10-28 | Incident triggered: `client_repo` test suite fails with 422 |
| 2026-10-28 | Aegis SRE Incident Delivery Core ingests trigger log, traceback, and OpenAPI diff |
| 2026-10-28 | Diagnosis: 4 BREAKING changes identified (see §4) |
| 2026-10-28 | Verified patch generated for `src/models.py` and `src/payment_client.py` |
| 2026-10-28 | Sandbox verification `sb-01M61FW9YB73R0FXBRS09X8HE6` — `pytest tests` — **PASSED** (1.98s, exit 0) |
| 2026-10-28 | PR ready-to-merge authored |

## 4. Root Cause Analysis

### 4.1 Contract Diff (Technical Findings)

| Change Class | Type | Field | Details |
|--------------|------|-------|---------|
| BREAKING | FIELD_NEWLY_REQUIRED | `amount_cents` | `integer`, leaf `amount_cents` now strictly required |
| BREAKING | FIELD_NEWLY_REQUIRED | `billing` | `object`, leaf `billing.address.line1` now strictly required |
| BREAKING | FIELD_REMOVED | `amount` | `number` (float dollars) removed from spec |
| BREAKING | FIELD_STRUCTURALLY_NESTED | `customer_address` → `billing.address.line1` | Relocated to nested hierarchy |
| WARNING | RESPONSE_STATUS_REMOVED | `400` | No longer documented (non-blocking) |

### 4.2 Downstream Code Path

- `src/models.py` `ChargeRequest` only exposed legacy fields `amount: float` and `customer_address: str`.
- `src/payment_client.py:build_charge_payload()` constructed:
  ```json
  {
    "customer_id": "...",
    "amount": 49.99,
    "customer_address": "123 Main St",
    "currency": "USD"
  }
  ```
- `UpstreamGatewayV2MockTransport.send_charge()` validates strictly against v2 spec and rejects any payload missing `amount_cents`/`billing` or containing deprecated fields.
- No conversion logic (`amount * 100` → `amount_cents`) or nesting logic (`customer_address` → `billing.address.line1`) existed.

### 4.3 Why 422

The gateway correctly enforced the new contract. The downstream client violated all four breaking rules simultaneously, hence 4 contract violations in one response.

## 5. Resolution

### 5.1 Strategy
Model reconciliation + payload filtering with full backward compatibility. Legacy callers passing `amount`/`customer_address` continue to work; v2 callers passing `amount_cents`/`billing` work natively; mixed callers are synchronized with v2 taking precedence.

### 5.2 Changes

**`src/models.py` — New reconciled models:**
- Added `Address(line1: str)` and `Billing(address: Address)`
- `ChargeRequest` now exposes both v2 (`amount_cents: Optional[int]`, `billing: Optional[Billing]`) and legacy (`amount: Optional[float]`, `customer_address: Optional[str]`) fields
- `@model_validator(mode='after') reconcile_legacy_and_v2()`:
  - `amount` → `amount_cents` via `int(round(amount * 100))`
  - `amount_cents` → `amount` via `amount_cents / 100.0` with int coercion
  - `customer_address` → `billing` via `Billing(address=Address(line1=customer_address))`
  - `billing` → `customer_address` via `billing.address.line1`
  - Validates at least one amount and one address source is provided; syncs legacy to v2 when both present

**`src/payment_client.py` — v2-only payload builder:**
- `build_charge_payload()` now resolves `amount_cents` defensively (prefers `amount_cents`, falls back to `amount*100`, coerces to int)
- Resolves `billing` defensively (handles both `Billing` object and `dict` form, falls back to `customer_address`)
- Validates `billing.address.line1` presence, raises `ValueError` if missing
- Returns **only** v2 fields:
  ```json
  {
    "customer_id": "...",
    "amount_cents": 4999,
    "currency": "USD",
    "billing": {"address": {"line1": "123 Main St"}}
  }
  ```
- Drops deprecated `amount` and `customer_address` entirely

### 5.3 Verified Diff

```diff
--- a/src/models.py
+++ b/src/models.py
@@ -0,0 +1,69 @@
+"""
+Downstream Client Data Models for Payment Gateway Service.
+Updated to support OpenAPI v2 while preserving backward compatibility with v1 callers.
+"""
+
+from typing import Optional
+from pydantic import BaseModel, Field, model_validator
+
+
+class Address(BaseModel):
+    line1: str = Field(..., description="Primary address line")
+
+
+class Billing(BaseModel):
+    address: Address
+
+
+class ChargeRequest(BaseModel):
+    customer_id: str
+    currency: str = "USD"
+    # v2 contract fields (required upstream)
+    amount_cents: Optional[int] = Field(default=None, description="Charge amount in cents (e.g. 4999)")
+    billing: Optional[Billing] = Field(default=None, description="Billing object containing address")
+    # Legacy v1 fields - retained for backward compatibility
+    amount: Optional[float] = Field(default=None, description="Charge amount in dollars (e.g. 49.99) - legacy, use amount_cents")
+    customer_address: Optional[str] = Field(default=None, description="Primary customer address - legacy, use billing.address.line1")
+
+    @model_validator(mode='after')
+    def reconcile_legacy_and_v2(self):
+        # Reconcile amount <-> amount_cents
+        if self.amount_cents is None and self.amount is not None:
+            self.amount_cents = int(round(self.amount * 100))
+        elif self.amount is None and self.amount_cents is not None:
+            if not isinstance(self.amount_cents, int):
+                self.amount_cents = int(round(float(self.amount_cents)))
+            self.amount = self.amount_cents / 100.0
+        elif self.amount_cents is None and self.amount is None:
+            raise ValueError("Either 'amount' (legacy) or 'amount_cents' (v2) must be provided")
+        else:
+            if not isinstance(self.amount_cents, int):
+                self.amount_cents = int(round(float(self.amount_cents)))
+        # Reconcile customer_address <-> billing.address.line1
+        if self.billing is None and self.customer_address is not None:
+            self.billing = Billing(address=Address(line1=self.customer_address))
+        elif self.billing is not None and self.customer_address is None:
+            try:
+                self.customer_address = self.billing.address.line1
+            except Exception:
+                pass
+        elif self.billing is None and self.customer_address is None:
+            raise ValueError("Either 'customer_address' (legacy) or 'billing.address.line1' (v2) must be provided")
+        if self.billing is not None and self.customer_address is not None:
+            try:
+                v2_line1 = self.billing.address.line1
+                if v2_line1 != self.customer_address:
+                    self.customer_address = v2_line1
+            except Exception:
+                pass
+        return self
+
+
+class ChargeResponse(BaseModel):
+    charge_id: str
+    status: str

--- a/src/payment_client.py
+++ b/src/payment_client.py
@@ -0,0 +1,61 @@
+"""
+Downstream Payment Client executing HTTP charges.
+Updated to construct payloads adhering to OpenAPI v2 Specification
+while preserving backward compatibility for legacy callers.
+"""
+
+from typing import Dict, Any
+from .models import ChargeRequest, ChargeResponse
+
+
+class PaymentClient:
+    def __init__(self, base_url: str = "https://api.gateway.internal", transport=None):
+        self.base_url = base_url
+        self.transport = transport
+
+    def build_charge_payload(self, request: ChargeRequest) -> Dict[str, Any]:
+        """Constructs the outbound JSON payload for POST /api/v2/payments/charge."""
+        if request.amount_cents is not None:
+            amount_cents = request.amount_cents
+        elif request.amount is not None:
+            amount_cents = int(round(request.amount * 100))
+        else:
+            raise ValueError("Missing required field: amount_cents")
+        if not isinstance(amount_cents, int):
+            amount_cents = int(round(float(amount_cents)))
+        billing = None
+        line1 = None
+        if request.billing is not None:
+            if isinstance(request.billing, dict):
+                addr = request.billing.get("address", {})
+                line1 = addr.get("line1")
+                if line1:
+                    billing = {"address": {"line1": line1}}
+            else:
+                line1 = request.billing.address.line1
+                billing = {"address": {"line1": line1}}
+        elif request.customer_address is not None:
+            line1 = request.customer_address
+            billing = {"address": {"line1": line1}}
+        if not line1 or billing is None:
+            raise ValueError("Missing required field: billing.address.line1")
+        return {
+            "customer_id": request.customer_id,
+            "amount_cents": amount_cents,
+            "currency": request.currency,
+            "billing": billing
+        }
+
+    def charge_customer(self, request: ChargeRequest) -> ChargeResponse:
+        payload = self.build_charge_payload(request)
+        if self.transport:
+            return self.transport.send_charge(payload)
+        return ChargeResponse(charge_id="ch_mock_123", status="succeeded")
```

## 6. Verification

**Sandbox:** MODAL_CLOUD_CONTAINER `sb-01M61FW9YB73R0FXBRS09X8HE6`  
**Applied Files:** `src/models.py`, `src/payment_client.py`  
**Test Target:** `tests`  
**Result:** PASSED — Exit Code 0 — Duration 1.98s

**Stdout:**
```
============================= test session starts ==============================
platform linux -- Python 3.12.10, pytest-9.2.0, pluggy-1.7.0 -- /usr/local/bin/python
cachedir: .pytest_cache
rootdir: /tmp/repo
collecting ... collected 1 item

tests/test_payment_client.py::test_client_payload_against_upstream_v2_gateway PASSED [100%]

============================== 1 passed in 0.07s ===============================
```
**Stderr:** (empty)

The previously failing `test_client_payload_against_upstream_v2_gateway` now passes, confirming the payload no longer contains deprecated fields and satisfies all required v2 fields with correct types.

## 7. Lessons Learned

- Breaking OpenAPI changes (type change `float`→`int`, structural nesting) must be treated as major version bumps with downstream codemods.
- Strict mock transports that validate `required` + `deprecated` fields are effective at catching contract drift early in CI.
- Backward compatibility via model validators reduces migration risk for internal callers still using legacy fields.
- Amount handling requires explicit rounding (`round(amount*100)`) to avoid floating-point truncation errors.

## 8. Action Items

| Action | Owner | Priority |
|--------|-------|----------|
| Add contract-testing CI job that diffs OpenAPI spec on every upstream release | Platform | High |
| Deprecate `amount`/`customer_address` with warnings and schedule removal in next major | Payments Team | Medium |
| Add unit tests for edge cases: `amount=0.01`, `amount_cents` as float string, `billing` as dict | Payments Team | Medium |
| Monitor gateway 422 rate post-deploy | SRE | High |
| Update API documentation and client SDK changelog for v2 migration | Docs | Low |

## 9. Appendix

- **Incident Trigger:** `ValueError: Upstream Gateway 422 Unprocessable Entity - Contract Violations: ['Missing required field: amount_cents (integer)', 'Missing required field: billing (object)', 'Deprecated/Removed field present: customer_address', 'Deprecated/Removed field present: amount (float)']` at `src/payment_client.py:27` / `tests/test_payment_client.py:41`
- **Diagnosis Source:** OpenAPI diff analysis (4 BREAKING, 1 WARNING)
- **Rollback Plan:** Revert to legacy gateway v1 if v2 verification fails (not needed — verification passed)
