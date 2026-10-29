"""
Example 03: Asynchronous Scraper Resilience
Demonstrates async function healing with zero-downtime batch execution.
"""

import asyncio
import logging
from pydantic import BaseModel
from kintsugi import heal

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


class Product(BaseModel):
    name: str
    price: int


@heal(schema=Product)
async def scrape_card(html_snippet: str) -> dict:
    """Async scraper that expects legacy markup."""
    name = html_snippet.split('class="prod-name">')[1].split('<')[0].strip()
    price = int(html_snippet.split('class="prod-price">')[1].split('<')[0].strip())
    return {"name": name, "price": price}


async def main() -> None:
    catalog = [
        '<div class="box"><span class="prod-name">Mechanical Keyboard</span><span class="prod-price">750000</span></div>',
        '<div class="box"><span class="prod-name">Ergonomic Mouse</span><span class="prod-price">320000</span></div>',
        # --- Upstream website redesign shifts classes! ---
        '<div class="box"><h3 class="product-title">UltraWide Monitor</h3><p class="final-price">Rp 4.500.000</p></div>',
        '<div class="box"><h3 class="product-title">USB-C Docking Station</h3><p class="final-price">Rp 1.200.000</p></div>',
    ]

    print("Processing catalog items asynchronously...")
    for idx, snippet in enumerate(catalog, start=1):
        product = await scrape_card(snippet)
        print(f"[{idx}] {product.name} -> Rp {product.price:,}")


if __name__ == "__main__":
    asyncio.run(main())
