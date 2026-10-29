import pytest
from kintsugi.decorator import heal
from kintsugi.providers.base import LLMProvider


class MockPredicateSurgeon(LLMProvider):
    def __init__(self, patch: str) -> None:
        super().__init__(model="pred-surgeon")
        self.patch = patch
        self.calls = 0

    def generate_patch(self, prompt: str, system_prompt: str) -> str:
        self.calls += 1
        return self.patch

    async def agenerate_patch(self, prompt: str, system_prompt: str) -> str:
        self.calls += 1
        return self.patch


def test_custom_validate_predicate_catches_empty_results():
    # Original scraper returns empty list [] because selector failed quietly
    repaired_code = """
def scrape_items(html: str) -> list:
    if 'item' in html:
        return [html.split('item">')[1].split('<')[0]]
    elif 'product' in html:
        return [html.split('product">')[1].split('<')[0]]
    return []
"""
    surgeon = MockPredicateSurgeon(repaired_code)

    @heal(
        validate=lambda items: isinstance(items, list) and len(items) > 0,
        chain=[surgeon],
        cache_dir=None,
    )
    def scrape_items(html: str) -> list:
        # Broken selector returns empty list instead of crashing
        if 'class="item">' in html:
            return [html.split('class="item">')[1].split('<')[0]]
        return []

    # 1. Normal call with old class passes predicate
    res1 = scrape_items('<div class="item">Keyboard</div>')
    assert res1 == ["Keyboard"]
    assert surgeon.calls == 0

    # 2. Website redesign: class is now 'product'. Original function returns []
    # But validate predicate rejects [] and triggers autonomous healing!
    res2 = scrape_items('<div class="product">Mouse</div>')
    assert res2 == ["Mouse"]
    assert surgeon.calls == 1
    assert scrape_items.__kintsugi_state__.is_healed

    # 3. Subsequent call uses healed function without LLM
    res3 = scrape_items('<div class="product">Headset</div>')
    assert res3 == ["Headset"]
    assert surgeon.calls == 1


def test_predicate_exception_treated_as_validation_failure():
    # If function returns an int (0) and predicate tries len(x), TypeError occurs.
    # Kintsugi must handle TypeError gracefully as failure, trigger healing, and succeed.
    repaired_code = """
def get_tags(d: dict) -> list:
    return ["tag1", "tag2"]
"""
    surgeon = MockPredicateSurgeon(repaired_code)

    @heal(
        validate=lambda x: len(x) > 0,  # len(0) will raise TypeError
        chain=[surgeon],
        cache_dir=None,
    )
    def get_tags(d: dict):
        return 0  # Invalid int instead of container

    # Must heal gracefully without blowing up on TypeError
    res = get_tags({})
    assert res == ["tag1", "tag2"]
    assert surgeon.calls == 1
