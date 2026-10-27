"""
Downstream Payment Client executing HTTP charges.
Currently constructs payloads adhering to Legacy OpenAPI v1 Specification.
"""

from typing import Dict, Any
from .models import ChargeRequest, ChargeResponse


class PaymentClient:
    def __init__(self, base_url: str = "https://api.gateway.internal", transport=None):
        self.base_url = base_url
        self.transport = transport

    def build_charge_payload(self, request: ChargeRequest) -> Dict[str, Any]:
        """Constructs the outbound JSON payload for POST /api/v2/payments/charge."""
        return {
            "customer_id": request.customer_id,
            "amount": request.amount,
            "currency": request.currency,
            "customer_address": request.customer_address
        }

    def charge_customer(self, request: ChargeRequest) -> ChargeResponse:
        payload = self.build_charge_payload(request)
        if self.transport:
            return self.transport.send_charge(payload)
        
        return ChargeResponse(charge_id="ch_mock_123", status="succeeded")
