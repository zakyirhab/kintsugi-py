"""
Demo Scraper: Real-world simulation of web scraping resilience with KintsugiPy.
"""

from pydantic import BaseModel
from kintsugi.decorator import heal
from kintsugi.providers.base import LLMProvider


class Product(BaseModel):
    title: str
    price: int


class MockScraperSurgeon(LLMProvider):
    """Simulates an LLM repairing an HTML parser that broke due to CSS class renaming."""

    def __init__(self) -> None:
        super().__init__(model="surgeon-qwen")
        self.call_count = 0

    def generate_patch(self, prompt: str, system_prompt: str) -> str:
        self.call_count += 1
        # Returns a robust implementation handling both old and new HTML selector styles
        return """
def parse_product_card(html: str) -> dict:
    import re
    # Extract title from either <h2 class="title"> or <div class="item-name">
    if 'class="title">' in html:
        title = html.split('class="title">')[1].split('<')[0].strip()
    elif 'class="item-name">' in html:
        title = html.split('class="item-name">')[1].split('<')[0].strip()
    else:
        title = "Unknown Product"

    # Extract price from either <span class="price"> or <p class="curr-val">
    if 'class="price">' in html:
        raw_price = html.split('class="price">')[1].split('<')[0]
    elif 'class="curr-val">' in html:
        raw_price = html.split('class="curr-val">')[1].split('<')[0]
    else:
        raw_price = "0"

    cleaned_price = int(re.sub(r'[^0-9]', '', raw_price))
    return {
        "title": title,
        "price": cleaned_price
    }
"""

    async def agenerate_patch(self, prompt: str, system_prompt: str) -> str:
        return self.generate_patch(prompt, system_prompt)


def test_demo_broken_scraper_healing_pipeline():
    surgeon = MockScraperSurgeon()

    @heal(schema=Product, chain=[surgeon], cache_dir=None)
    def parse_product_card(html: str) -> dict:
        # Fragile initial implementation: hardcoded to old CSS class names
        title = html.split('class="title">')[1].split('<')[0].strip()
        price_text = html.split('class="price">')[1].split('<')[0].strip()
        return {
            "title": title,
            "price": int(price_text.replace("Rp", "").replace(".", "").strip())
        }

    dataset = [
        '<div class="card"><h2 class="title">Botol Kaca 250ml</h2><span class="price">Rp 5.000</span></div>',
        '<div class="card"><h2 class="title">Tutup Ulir Hitam</h2><span class="price">Rp 1.500</span></div>',
        # --- Web redesign happens here! CSS classes shifted! ---
        '<div class="card"><div class="item-name">Plastik HDPE 100gr</div><p class="curr-val">Rp 12.000</p></div>',
        '<div class="card"><div class="item-name">Kardus Corrugated 20x20</div><p class="curr-val">Rp 8.500</p></div>',
        '<div class="card"><div class="item-name">Lakban Bening 100m</div><p class="curr-val">Rp 15.000</p></div>',
    ]

    scraped_products = []
    for raw_html in dataset:
        product = parse_product_card(raw_html)
        scraped_products.append(product)

    # 1. All 5 products must be parsed successfully
    assert len(scraped_products) == 5

    # 2. Check types
    assert all(isinstance(p, Product) for p in scraped_products)

    # 3. Check values
    assert scraped_products[0].title == "Botol Kaca 250ml"
    assert scraped_products[0].price == 5000

    assert scraped_products[2].title == "Plastik HDPE 100gr"
    assert scraped_products[2].price == 12000

    assert scraped_products[4].title == "Lakban Bening 100m"
    assert scraped_products[4].price == 15000

    # 4. LLM was invoked exactly once (at item #3) and never again for #4 and #5!
    assert surgeon.call_count == 1
    assert parse_product_card.__kintsugi_state__.is_healed
