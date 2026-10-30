import pytest
from kintsugi.decorator import heal
from kintsugi.providers.base import LLMProvider


class MockFilterSurgeon(LLMProvider):
    def __init__(self, patch: str) -> None:
        super().__init__(model="filter-surgeon")
        self.patch = patch
        self.calls = 0

    def generate_patch(self, prompt: str, system_prompt: str) -> str:
        self.calls += 1
        return self.patch

    async def agenerate_patch(self, prompt: str, system_prompt: str) -> str:
        self.calls += 1
        return self.patch


def test_network_and_system_errors_bypass_healing():
    repaired_code = """
def fetch_api(url: str) -> str:
    return "ok"
"""
    surgeon = MockFilterSurgeon(repaired_code)

    @heal(chain=[surgeon], cache_dir=None)
    def fetch_api(url: str) -> str:
        raise ConnectionError("Host unreachable: 192.168.1.1")

    # ConnectionError is an environmental/infrastructure error, NOT in heal_on
    with pytest.raises(ConnectionError, match="Host unreachable"):
        fetch_api("http://api.internal")

    # LLM must NOT be called for network errors!
    assert surgeon.calls == 0
    assert not fetch_api.__kintsugi_state__.is_healed


def test_timeout_error_bypasses_healing():
    repaired_code = """
def slow_task() -> str:
    return "done"
"""
    surgeon = MockFilterSurgeon(repaired_code)

    @heal(chain=[surgeon], cache_dir=None)
    def slow_task() -> str:
        raise TimeoutError("Socket timed out after 30s")

    with pytest.raises(TimeoutError, match="Socket timed out"):
        slow_task()

    assert surgeon.calls == 0


def test_custom_heal_on_selective_trigger():
    repaired_code = """
def parse_record(val: str, d: dict) -> int:
    return 0
"""
    surgeon = MockFilterSurgeon(repaired_code)

    # Only heal ValueError; ignore KeyError
    @heal(heal_on=(ValueError,), chain=[surgeon], cache_dir=None)
    def parse_record(val: str, d: dict) -> int:
        if not val:
            return d["missing_key"]  # KeyError
        return int(val)  # ValueError

    # 1. KeyError must NOT be healed
    with pytest.raises(KeyError):
        parse_record("", {})
    assert surgeon.calls == 0

    # 2. ValueError IS in heal_on and MUST be healed
    res = parse_record("not_a_number", {})
    assert res == 0
    assert surgeon.calls == 1


def test_idempotent_false_does_not_execute_dry_run():
    # Verify that when idempotent=False (default), candidate_fn is NOT executed
    # with live arguments during dry_run validation.
    side_effects = []

    repaired_code = """
def mutate_account(acc_id: str) -> str:
    # Healed version
    return f"processed_{acc_id}"
"""
    surgeon = MockFilterSurgeon(repaired_code)

    @heal(idempotent=False, chain=[surgeon], cache_dir=None)
    def mutate_account(acc_id: str) -> str:
        side_effects.append(f"run_{acc_id}")
        if len(side_effects) == 1:
            raise KeyError("acc_id missing")
        return f"processed_{acc_id}"

    # First call crashes, heals, and then runs once (NOT twice via dry-run)
    res = mutate_account("acc_99")
    assert res == "processed_acc_99"
    # mutate_account was executed once for the initial crash; dry-run was skipped.
    assert surgeon.calls == 1
