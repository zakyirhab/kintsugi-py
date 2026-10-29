import pytest
from kintsugi.decorator import heal, HealReport, ProposedPatchError
from kintsugi.providers.base import LLMProvider


class MockProposeSurgeon(LLMProvider):
    def __init__(self, patch: str) -> None:
        super().__init__(model="propose-surgeon")
        self.patch = patch
        self.calls = 0

    def generate_patch(self, prompt: str, system_prompt: str) -> str:
        self.calls += 1
        return self.patch

    async def agenerate_patch(self, prompt: str, system_prompt: str) -> str:
        self.calls += 1
        return self.patch


def test_mode_propose_does_not_hotswap():
    repaired_code = """
def parse_id(data: dict) -> int:
    return int(data.get("id") or data.get("uuid", 0))
"""
    surgeon = MockProposeSurgeon(repaired_code)
    captured_proposals = []

    def on_proposal(report: HealReport):
        captured_proposals.append(report)

    @heal(mode="propose", chain=[surgeon], on_heal=on_proposal, cache_dir=None)
    def parse_id(data: dict) -> int:
        return data["id"]

    # In mode="propose", a crash generates the patch, fires on_heal, but raises ProposedPatchError!
    with pytest.raises(ProposedPatchError) as exc_info:
        parse_id({"uuid": 42})

    # 1. Report was created and emitted
    assert len(captured_proposals) == 1
    assert captured_proposals[0].func_name == "parse_id"
    assert "+++ b/parse_id.py" in captured_proposals[0].diff

    # 2. Function is NOT hot-swapped in memory
    assert not parse_id.__kintsugi_state__.is_healed
    assert parse_id.__kintsugi_state__.active_func == parse_id.__kintsugi_state__.original_func

    # 3. Subsequent calls with missing 'id' still fail in original function
    with pytest.raises(ProposedPatchError):
        parse_id({"uuid": 99})


@pytest.mark.asyncio
async def test_async_mode_propose():
    repaired_code = """
async def async_fetch(d: dict) -> str:
    return d.get("val", "healed")
"""
    surgeon = MockProposeSurgeon(repaired_code)
    captured = []

    async def async_cb(report: HealReport):
        captured.append(report)

    @heal(mode="propose", chain=[surgeon], on_heal=async_cb, cache_dir=None)
    async def async_fetch(d: dict) -> str:
        return d["val"]

    with pytest.raises(ProposedPatchError):
        await async_fetch({"other": "xyz"})

    assert len(captured) == 1
    assert captured[0].func_name == "async_fetch"
    assert not async_fetch.__kintsugi_state__.is_healed
