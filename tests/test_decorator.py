import shutil
from pathlib import Path
import pytest
from pydantic import BaseModel

from kintsugi.decorator import heal
from kintsugi.providers.base import LLMProvider


class MockLLMProvider(LLMProvider):
    """Predictable mock provider that yields predefined repair code."""

    def __init__(self, patch_code: str) -> None:
        super().__init__(model="mock-surgeon")
        self.patch_code = patch_code
        self.call_count = 0

    def generate_patch(self, prompt: str, system_prompt: str) -> str:
        self.call_count += 1
        return self.patch_code

    async def agenerate_patch(self, prompt: str, system_prompt: str) -> str:
        self.call_count += 1
        return self.patch_code


class ItemModel(BaseModel):
    name: str
    price: int


TEST_CACHE_DIR = ".test_kintsugi_cache"


@pytest.fixture(autouse=True)
def cleanup_test_cache():
    shutil.rmtree(TEST_CACHE_DIR, ignore_errors=True)
    yield
    shutil.rmtree(TEST_CACHE_DIR, ignore_errors=True)


def test_healthy_function_zero_overhead():
    mock_llm = MockLLMProvider("def add_numbers(a, b): return a + b")

    @heal(provider="mock", chain=[mock_llm], cache_dir=TEST_CACHE_DIR)
    def add_numbers(a: int, b: int) -> int:
        return a + b

    # Executes natively
    assert add_numbers(5, 7) == 12
    assert add_numbers(10, 20) == 30
    # LLM was never called
    assert mock_llm.call_count == 0
    assert not add_numbers.__kintsugi_state__.is_healed


def test_sync_function_healing_and_hotswap():
    # Repaired version handles both 'price' and 'cost', and parses string to int
    repaired_code = """
def parse_price(data: dict) -> int:
    val = data.get("price") if "price" in data else data.get("cost", 0)
    if isinstance(val, str):
        val = int(val.replace("$", "").strip())
    return val
"""
    mock_llm = MockLLMProvider(repaired_code)

    @heal(provider="mock", chain=[mock_llm], cache_dir=TEST_CACHE_DIR)
    def parse_price(data: dict) -> int:
        # Fragile code expects int 'price' key
        return data["price"]

    # 1. Normal call passes
    assert parse_price({"price": 100}) == 100
    assert mock_llm.call_count == 0

    # 2. Crash call triggers healing: key changed to "cost" with string "$250"
    repaired_result = parse_price({"cost": "$250"})
    assert repaired_result == 250
    assert mock_llm.call_count == 1
    assert parse_price.__kintsugi_state__.is_healed

    # 3. Subsequent calls now use the hot-swapped function in memory WITHOUT calling the LLM!
    assert parse_price({"cost": "$500"}) == 500
    assert parse_price({"price": 300}) == 300
    # Call count remains 1
    assert mock_llm.call_count == 1


@pytest.mark.asyncio
async def test_async_function_healing():
    repaired_code = """
async def fetch_record(data: dict) -> str:
    return data.get("name") or data.get("title", "Unknown")
"""
    mock_llm = MockLLMProvider(repaired_code)

    @heal(provider="mock", chain=[mock_llm], cache_dir=TEST_CACHE_DIR)
    async def fetch_record(data: dict) -> str:
        return data["name"]

    # Fails and recovers
    res = await fetch_record({"title": "Autonomous Drone"})
    assert res == "Autonomous Drone"
    assert mock_llm.call_count == 1
    assert fetch_record.__kintsugi_state__.is_healed

    # Subsequent async call uses memory patch without LLM
    res2 = await fetch_record({"title": "Quantum Sensor"})
    assert res2 == "Quantum Sensor"
    assert mock_llm.call_count == 1


def test_pydantic_schema_enforcement():
    repaired_code = """
def get_item(data: dict) -> dict:
    return {
        "name": data.get("title", "item"),
        "price": int(data.get("price_raw", 0))
    }
"""
    mock_llm = MockLLMProvider(repaired_code)

    @heal(schema=ItemModel, provider="mock", chain=[mock_llm], cache_dir=TEST_CACHE_DIR)
    def get_item(data: dict):
        return {"name": data["title"], "price": data["price_raw"]}

    # Raw input has string "150", schema coerces to ItemModel with int price 150
    result = get_item({"title": "Keyboard", "price_raw": "150"})
    assert isinstance(result, ItemModel)
    assert result.name == "Keyboard"
    assert result.price == 150


def test_cold_start_cache_rehydration():
    repaired_code = """
def parse_val(x: str) -> int:
    return int(x.replace("px", "").strip())
"""
    mock_llm = MockLLMProvider(repaired_code)

    @heal(provider="mock", chain=[mock_llm], cache_dir=TEST_CACHE_DIR)
    def parse_val(x: str) -> int:
        return int(x)

    # Trigger healing on string with suffix "42px" which raises ValueError in original func
    assert parse_val("42px") == 42
    assert mock_llm.call_count == 1

    # Verify file was written to disk
    cache_files = list(Path(TEST_CACHE_DIR).glob("*.py"))
    assert len(cache_files) == 1

    # Re-instantiate a fresh wrapper on the original broken function with same cache_dir
    fresh_mock_llm = MockLLMProvider("def parse_val(x): return -1")

    @heal(provider="mock", chain=[fresh_mock_llm], cache_dir=TEST_CACHE_DIR)
    def parse_val(x: str) -> int:
        return int(x)

    # Should be instantly healed via disk cache without touching fresh_mock_llm
    assert parse_val.__kintsugi_state__.is_healed
    assert parse_val("99px") == 99
    assert fresh_mock_llm.call_count == 0
