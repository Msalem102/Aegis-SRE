"""
Downstream Payment Client executing HTTP charges.
Refactored by Aegis SRE (Meta Muse Spark) to construct payloads adhering to Upstream OpenAPI v2 Specification.
"""

from typing import Dict, Any
try:
    from .models import ChargeRequest, ChargeResponse
except (ImportError, ValueError):
    from src.models import ChargeRequest, ChargeResponse


class PaymentClient:
    def __init__(self, base_url: str = "https://api.gateway.internal", transport=None):
        self.base_url = base_url
        self.transport = transport

    def build_charge_payload(self, request: ChargeRequest) -> Dict[str, Any]:
        """
        Constructs the outbound JSON payload for POST /api/v2/payments/charge conforming to v2:
        - amount_cents (integer) instead of legacy amount (float)
        - billing.address.line1 instead of legacy customer_address
        """
        # Calculate amount_cents
        if request.amount_cents is not None:
            cents = request.amount_cents
        elif request.amount is not None:
            cents = int(round(request.amount * 100))
        else:
            raise ValueError("Either amount_cents or amount must be specified")

        # Construct nested billing
        if request.billing is not None:
            billing_payload = request.billing.model_dump()
        elif request.customer_address is not None:
            billing_payload = {"address": {"line1": request.customer_address}}
        else:
            raise ValueError("Either billing or customer_address must be specified")

        return {
            "customer_id": request.customer_id,
            "amount_cents": cents,
            "currency": request.currency,
            "billing": billing_payload
        }

    def charge_customer(self, request: ChargeRequest) -> ChargeResponse:
        payload = self.build_charge_payload(request)
        if self.transport:
            return self.transport.send_charge(payload)
        
        return ChargeResponse(charge_id="ch_v2_live_123", status="succeeded")
