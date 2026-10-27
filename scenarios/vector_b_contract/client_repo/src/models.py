"""
Downstream Client Data Models for Payment Gateway Service.
Refactored by Aegis SRE (Meta Muse Spark) to adhere to Upstream OpenAPI v2 Specification.
"""

from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, model_validator


class BillingAddress(BaseModel):
    line1: str = Field(..., description="Primary street address")


class BillingDetails(BaseModel):
    address: BillingAddress


class ChargeRequest(BaseModel):
    customer_id: str
    amount: Optional[float] = Field(default=None, description="Legacy charge amount in dollars (e.g. 49.99)")
    amount_cents: Optional[int] = Field(default=None, description="v2 charge amount strictly in integer cents")
    currency: str = "USD"
    customer_address: Optional[str] = Field(default=None, description="Legacy primary customer address")
    billing: Optional[BillingDetails] = Field(default=None, description="v2 nested billing details")

    @model_validator(mode="before")
    @classmethod
    def reconcile_v1_and_v2_fields(cls, values: Any) -> Any:
        if isinstance(values, dict):
            # Convert legacy dollars to integer cents if amount_cents not provided
            if values.get("amount_cents") is None and values.get("amount") is not None:
                values["amount_cents"] = int(round(float(values["amount"]) * 100))
            
            # Convert legacy customer_address to nested billing.address.line1
            if values.get("billing") is None and values.get("customer_address") is not None:
                values["billing"] = {
                    "address": {
                        "line1": values["customer_address"]
                    }
                }
        return values


class ChargeResponse(BaseModel):
    charge_id: str
    status: str
