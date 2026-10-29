"""
Observability and Telemetry Hook Tests for KintsugiPy.
"""

import pytest
from kintsugi.decorator import heal, HealReport
from kintsugi.providers.base import LLMProvider


class SimpleMockLLM(LLMProvider):
    def __init__(self, patch_code: str) -> None:
        super().__init__(model="mock-surgeon")
        self.patch_code = patch_code

    def generate_patch(self, prompt: str, system_prompt: str) -> str:
        return self.patch_code

    async def agenerate_patch(self, prompt: str, system_prompt: str) -> str:
        return self.patch_code


def test_sync_on_heal_receives_heal_report():
    repaired_code = """
def sample_task(d: dict) -> str:
    return d.get("user", "guest")
"""
    mock_llm = SimpleMockLLM(repaired_code)
    captured_reports = []

    def handle_report(report: HealReport):
        captured_reports.append(report)

    @heal(provider="mock", chain=[mock_llm], on_heal=handle_report, cache_dir=None)
    def sample_task(d: dict) -> str:
        return d["user"]

    # Fails and triggers healing
    res = sample_task({})
    assert res == "guest"
    assert len(captured_reports) == 1

    report = captured_reports[0]
    assert isinstance(report, HealReport)
    assert report.func_name == "sample_task"
    assert report.error_type == "KeyError"
    assert "user" in report.error_message
    assert "sample_task" in report.original_code
    assert "guest" in report.healed_code
    assert "--- a/sample_task.py" in report.diff
    assert "+++ b/sample_task.py" in report.diff
    assert report.attempts == 1


@pytest.mark.asyncio
async def test_async_on_heal_coroutine_callback():
    repaired_code = """
async def async_sample(d: dict) -> int:
    return d.get("count", 0)
"""
    mock_llm = SimpleMockLLM(repaired_code)
    async_captured = []

    async def async_notifier(report: HealReport):
        async_captured.append(report)

    @heal(provider="mock", chain=[mock_llm], on_heal=async_notifier, cache_dir=None)
    async def async_sample(d: dict) -> int:
        return d["count"]

    res = await async_sample({"qty": 42})
    assert res == 0
    assert len(async_captured) == 1
    assert async_captured[0].func_name == "async_sample"
    assert async_captured[0].error_type == "KeyError"


def test_legacy_2_arg_on_heal_backwards_compatible():
    repaired_code = """
def legacy_task(x: int) -> int:
    return x * 10
"""
    mock_llm = SimpleMockLLM(repaired_code)
    legacy_calls = []

    def legacy_handler(name: str, code: str):
        legacy_calls.append((name, code))

    @heal(provider="mock", chain=[mock_llm], on_heal=legacy_handler, cache_dir=None)
    def legacy_task(x: int) -> int:
        raise ValueError("Invalid state")

    res = legacy_task(5)
    assert res == 50
    assert len(legacy_calls) == 1
    assert legacy_calls[0][0] == "legacy_task"
    assert "return x * 10" in legacy_calls[0][1]
