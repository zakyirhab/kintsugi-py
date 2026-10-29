"""
Example 01: Quickstart Self-Healing Function
Demonstrates basic exception handling and in-memory hot-swapping.
"""

import logging
from kintsugi import heal

# Enable logging to observe Kintsugi's internal healing cycle
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


@heal()
def parse_price_tag(payload: dict) -> int:
    """Brittle function expecting a strict integer under 'price'."""
    return payload["price"]


if __name__ == "__main__":
    print("--- 1. Calling with expected payload ---")
    res1 = parse_price_tag({"price": 15000})
    print(f"Result 1: {res1}")

    print("\n--- 2. Calling with unexpected broken payload ---")
    # Upstream data structure changed: key is now 'cost' with a string currency!
    # Kintsugi catches KeyError, calls your configured LLM, hot-swaps the function in-memory.
    res2 = parse_price_tag({"cost": "Rp 25.000"})
    print(f"Result 2: {res2}")

    print("\n--- 3. Calling again with new structure ---")
    # Future calls run the hot-swapped function natively with 0ms LLM latency!
    res3 = parse_price_tag({"cost": "Rp 40.000"})
    print(f"Result 3: {res3}")
