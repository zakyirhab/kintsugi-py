"""
Example 02: Enforcing Output Contracts with Pydantic v2
Ensures AI-repaired functions strictly conform to your data model.
"""

import logging
from pydantic import BaseModel, Field
from kintsugi import heal

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


class Transaction(BaseModel):
    id: str = Field(..., description="Unique transaction ID")
    amount: float = Field(..., description="Normalized transaction amount")
    currency: str = Field(..., description="ISO 3-letter currency code")


@heal(schema=Transaction)
def process_webhook(event: dict) -> dict:
    """Fragile parser for a webhook payload."""
    return {
        "id": event["tx_id"],
        "amount": event["total_amount"],
        "currency": event["curr"],
    }


if __name__ == "__main__":
    print("--- 1. Valid Webhook Event ---")
    tx1 = process_webhook({"tx_id": "TX-101", "total_amount": 99.5, "curr": "USD"})
    print(f"Validated Model: {tx1}")
    print(f"Amount Type: {type(tx1.amount)}")

    print("\n--- 2. Mutated Webhook Event (Dirty Data) ---")
    # Upstream payment gateway changed field names and passed amount as a string
    dirty_event = {
        "transaction_number": "TX-999",
        "charge": "150.75",
        "currency_code": "EUR",
    }
    tx2 = process_webhook(dirty_event)
    print(f"Healed Model: {tx2}")
    print(f"Transaction ID: {tx2.id}, Amount: {tx2.amount} ({type(tx2.amount)}), Currency: {tx2.currency}")
