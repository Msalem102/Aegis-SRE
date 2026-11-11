from pydantic import BaseModel


class CoffeeChargePayload(BaseModel):
    """Legacy v1 checkout payload sent by Cupertino Coffee Shop."""
    order_id: str
    currency: str = "USD"
    amount: float
    customer_address: str
