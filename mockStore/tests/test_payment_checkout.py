from app.payment_client import build_charge_payload, charge_coffee_order


def test_coffee_order_checkout_conforms_to_roastpay_v2():
    """Verifies $6.50 Oat Latte order converts to 650 cents and nested billing.address.line1."""
    payload = build_charge_payload(
        order_id="ORD-LATTE-1042",
        total_dollars=6.50,
        street_address="1 Infinite Loop, Cupertino, CA 95014",
    )

    assert "amount" not in payload
    assert "customer_address" not in payload
    assert payload["amount_cents"] == 650
    assert isinstance(payload["amount_cents"], int)
    assert payload["billing"]["address"]["line1"] == "1 Infinite Loop, Cupertino, CA 95014"

    receipt = charge_coffee_order(
        order_id="ORD-LATTE-1042",
        total_dollars=6.50,
        street_address="1 Infinite Loop, Cupertino, CA 95014",
    )
    assert receipt["status"] == "authorized"
    assert receipt["charged_cents"] == 650
