"""
Concurrency & Thundering Herd Prevention Tests for KintsugiPy.
"""

import asyncio
import pytest
from kintsugi.decorator import heal
from kintsugi.providers.base import LLMProvider


class SlowMockLLM(LLMProvider):
    """Simulates an LLM with network latency to thoroughly stress test concurrency."""

    def __init__(self, patch_code: str, latency: float = 0.05) -> None:
        super().__init__(model="mock-surgeon")
        self.patch_code = patch_code
        self.latency = latency
        self.call_count = 0

    def generate_patch(self, prompt: str, system_prompt: str) -> str:
        self.call_count += 1
        return self.patch_code

    async def agenerate_patch(self, prompt: str, system_prompt: str) -> str:
        self.call_count += 1
        await asyncio.sleep(self.latency)
        return self.patch_code


@pytest.mark.asyncio
async def test_async_thundering_herd_prevention():
    """Verify that 50 concurrent coroutines failing simultaneously trigger exactly 1 LLM repair."""
    repaired_code = """
async def parse_concurrent(item: dict) -> int:
    return item.get("val") or item.get("value", 0)
"""
    mock_llm = SlowMockLLM(repaired_code, latency=0.03)

    @heal(provider="mock", chain=[mock_llm], cache_dir=None)
    async def parse_concurrent(item: dict) -> int:
        # Fragile function: expects 'val'
        return item["val"]

    # 50 concurrent requests with the new schema key 'value'
    tasks = [
        parse_concurrent({"value": i * 10})
        for i in range(1, 51)
    ]

    # Execute all 50 tasks simultaneously in an asyncio event loop
    results = await asyncio.gather(*tasks)

    # 1. All 50 tasks must succeed
    assert len(results) == 50
    assert results[0] == 10
    assert results[49] == 500

    # 2. Critical: LLM must have been summoned EXACTLY ONCE!
    assert mock_llm.call_count == 1
    assert parse_concurrent.__kintsugi_state__.is_healed
