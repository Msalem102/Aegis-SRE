"""
Downstream Client Data Models for Payment Gateway Service.
Currently adhering to Legacy OpenAPI v1 Specification.
"""

from typing import Optional
from pydantic import BaseModel, Field


class ChargeRequest(BaseModel):
    customer_id: str
    amount: float = Field(..., description="Charge amount in dollars (e.g. 49.99)")
    currency: str = "USD"
    customer_address: str = Field(..., description="Primary customer address")


class ChargeResponse(BaseModel):
    charge_id: str
    status: str
