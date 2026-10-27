"""
Integration Test Suite for PaymentClient against Upstream Gateway API (v2).
This test suite verifies downstream compliance with the current upstream contract.
"""

import pytest
import sys
import os

# Ensure src is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.models import ChargeRequest, ChargeResponse
from src.payment_client import PaymentClient

class UpstreamGatewayV2MockTransport:
    """Simulates the upstream gateway enforcing the OpenAPI v2 specification."""
    def send_charge(self, payload: dict) -> ChargeResponse:
        errors = []
        
        # Enforce v2 schema requirements
        if "amount_cents" not in payload:
            errors.append("Missing required field: amount_cents (integer)")
        elif not isinstance(payload["amount_cents"], int):
            errors.append(f"Field amount_cents must be integer, got {type(payload['amount_cents']).__name__}")
            
        if "billing" not in payload or not isinstance(payload.get("billing"), dict):
            errors.append("Missing required field: billing (object)")
        else:
            address = payload["billing"].get("address", {})
            if "line1" not in address or not address["line1"]:
                errors.append("Missing required field: billing.address.line1 (string)")

        # Enforce rejection of legacy/removed fields
        if "customer_address" in payload:
            errors.append("Deprecated/Removed field present: customer_address")
        if "amount" in payload:
            errors.append("Deprecated/Removed field present: amount (float)")

        if errors:
            raise ValueError(f"Upstream Gateway 422 Unprocessable Entity - Contract Violations: {errors}")

        return ChargeResponse(charge_id="ch_v2_live_998811", status="succeeded")


def test_client_payload_against_upstream_v2_gateway():
    """
    Asserts that PaymentClient properly constructs payloads acceptable by Upstream v2.
    FAILS when client uses legacy v1 payload schema.
    PASSES once client is refactored to OpenAPI v2.
    """
    transport = UpstreamGatewayV2MockTransport()
    client = PaymentClient(transport=transport)

    # Legacy request invocation
    # In legacy code, amount is 49.99 and address is passed as customer_address
    # After remediation, models and client should support v2 contract
    req = ChargeRequest(
        customer_id="cust_84920",
        amount=49.99,
        currency="USD",
        customer_address="742 Evergreen Terrace"
    )

    # When the client calls charge_customer, it must not throw a contract violation error
    response = client.charge_customer(req)
    assert response.status == "succeeded"
    assert response.charge_id.startswith("ch_v2_")
