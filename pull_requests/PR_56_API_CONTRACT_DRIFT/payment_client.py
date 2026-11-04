from typing import Dict, Any
from app.payment_models import CoffeeChargePayload


class UpstreamContractError(Exception):
    def __init__(self, status_code: int, detail: Dict[str, Any]):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"HTTP {status_code} Unprocessable Entity: {detail}")


def _simulate_roastpay_v2_gateway(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Enforces RoastPay v2 OpenAPI contract strictly."""
    errors = []
    if "amount" in payload:
        errors.append("Field 'amount' (float) was removed in v2; send integer 'amount_cents'.")
    if "customer_address" in payload:
        errors.append("Field 'customer_address' was removed in v2; send 'billing.address.line1'.")
    if not isinstance(payload.get("amount_cents"), int):
        errors.append("Missing or non-integer required field 'amount_cents'.")

    billing = payload.get("billing")
    line1 = billing.get("address", {}).get("line1") if isinstance(billing, dict) else None
    if not isinstance(line1, str) or not line1.strip():
        errors.append("Missing required nested string field 'billing.address.line1'.")

    if errors:
        raise UpstreamContractError(
            status_code=422,
            detail={"error": "ROASTPAY_V2_SCHEMA_DRIFT", "messages": errors},
        )

    return {
        "status": "authorized",
        "gateway_version": "2.0",
        "order_id": payload["order_id"],
        "charged_cents": payload["amount_cents"],
    }


def build_charge_payload(order_id: str, total_dollars: float, street_address: str) -> Dict[str, Any]:
    """Builds the outbound JSON dictionary for RoastPay v2."""
    amount_cents = int(round(total_dollars * 100))
    model = CoffeeChargePayload(
        order_id=order_id,
        currency="USD",
        amount_cents=amount_cents,
        billing={"address": {"line1": street_address}},
    )
    return model.model_dump()


def charge_coffee_order(order_id: str, total_dollars: float, street_address: str) -> Dict[str, Any]:
    """Executes payment authorization for a Cupertino Coffee Shop order."""
    payload = build_charge_payload(
        order_id=order_id,
        total_dollars=total_dollars,
        street_address=street_address,
    )
    return _simulate_roastpay_v2_gateway(payload)
