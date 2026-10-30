import pytest
from kintsugi.privacy import (
    map_and_replace_secrets,
    restore_mapped_secrets,
)
from kintsugi.inspector import build_repair_prompt
from kintsugi.decorator import heal
from kintsugi.providers.base import LLMProvider


def test_map_and_replace_secrets_basic():
    code = 'API_KEY = "sk-1234567890abcdef1234567890"\nauth = "Bearer mytoken1234567890abcdef"\n'
    masked, s_map = map_and_replace_secrets(code)

    assert "sk-1234567890abcdef1234567890" not in masked
    assert "__KINTSUGI_SECRET_0__" in masked
    assert "__KINTSUGI_SECRET_1__" in masked
    assert s_map["__KINTSUGI_SECRET_0__"] == "sk-1234567890abcdef1234567890"

    # Restoration recovers original secrets
    restored = restore_mapped_secrets(masked, s_map)
    assert restored == code


def test_restore_mapped_secrets_rejects_unmapped_redacted():
    patch_with_unmapped = 'def foo(): return "[REDACTED_API_KEY]"'
    with pytest.raises(ValueError, match="unmapped '\\[REDACTED\\]' placeholder"):
        restore_mapped_secrets(patch_with_unmapped, {})


class MockSecretSurgeon(LLMProvider):
    def __init__(self, patch: str) -> None:
        super().__init__(model="secret-surgeon")
        self.patch = patch
        self.last_user_prompt = ""

    def generate_patch(self, prompt: str, system_prompt: str) -> str:
        self.last_user_prompt = prompt
        return self.patch

    async def agenerate_patch(self, prompt: str, system_prompt: str) -> str:
        self.last_user_prompt = prompt
        return self.patch


def test_end_to_end_secret_reversibility_in_heal():
    # A function with a hardcoded secret in source
    raw_secret = "sk-production_live_token_987654321012345"

    # LLM receives placeholder and preserves placeholder in its patch
    llm_returned_patch = """
def authenticate_client(payload: dict) -> dict:
    key = "__KINTSUGI_SECRET_0__"
    return {"status": "ok", "auth": key, "client": payload.get("client_id", "default")}
"""
    surgeon = MockSecretSurgeon(llm_returned_patch)

    @heal(chain=[surgeon], cache_dir=None)
    def authenticate_client(payload: dict) -> dict:
        key = "sk-production_live_token_987654321012345"
        # Crashes on missing key
        return {"auth": key, "client": payload["client_id"]}

    # First call crashes, heals, restores secret
    res = authenticate_client({})
    assert res["status"] == "ok"
    assert res["client"] == "default"
    # Secret must be restored in the hot-swapped function!
    assert res["auth"] == raw_secret

    # Verify that the prompt sent to LLM did NOT contain raw secret
    assert raw_secret not in surgeon.last_user_prompt
    assert "__KINTSUGI_SECRET_0__" in surgeon.last_user_prompt
