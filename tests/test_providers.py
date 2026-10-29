import pytest
from kintsugi.providers.base import extract_code_block, LLMProvider
from kintsugi.providers.openai_like import OpenAILikeProvider
from kintsugi.providers.anthropic_native import AnthropicNativeProvider
from kintsugi.providers.gemini_native import GeminiNativeProvider
from kintsugi.providers import resolve_provider, FallbackChainProvider


def test_extract_code_block_with_markdown_fences():
    text = """Here is the repaired function:
```python
def fix_me(x):
    return x * 2
```
Hope this helps!"""
    assert extract_code_block(text) == "def fix_me(x):\n    return x * 2"


def test_extract_code_block_raw():
    text = "def fix_me(x):\n    return x + 1"
    assert extract_code_block(text) == text


def test_resolve_provider_groq_auto_detection():
    prov = resolve_provider(api_key="gsk_1234567890abcdef")
    assert isinstance(prov, OpenAILikeProvider)
    assert "groq.com" in prov.endpoint
    assert prov.model == "llama-3.3-70b-versatile"


def test_resolve_provider_anthropic_auto_detection():
    prov = resolve_provider(api_key="sk-ant-api03-123456")
    assert isinstance(prov, AnthropicNativeProvider)
    assert prov.endpoint == "https://api.anthropic.com/v1/messages"


def test_resolve_provider_gemini_auto_detection():
    prov = resolve_provider(api_key="AIzaSy1234567890")
    assert isinstance(prov, GeminiNativeProvider)
    assert "generativelanguage.googleapis.com" in prov.endpoint


def test_resolve_provider_openrouter():
    prov = resolve_provider(provider="openrouter", api_key="sk-or-v1-12345")
    assert isinstance(prov, OpenAILikeProvider)
    assert prov.endpoint == "https://openrouter.ai/api/v1/chat/completions"


def test_resolve_provider_deepseek():
    prov = resolve_provider(provider="deepseek", api_key="sk-deepseek-123")
    assert isinstance(prov, OpenAILikeProvider)
    assert prov.endpoint == "https://api.deepseek.com/v1/chat/completions"


def test_resolve_provider_default_local(monkeypatch):
    for k in [
        "KINTSUGI_PROVIDER",
        "KINTSUGI_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GROQ_API_KEY",
        "DEEPSEEK_API_KEY",
        "OPENROUTER_API_KEY",
    ]:
        monkeypatch.delenv(k, raising=False)
    prov = resolve_provider()
    assert isinstance(prov, OpenAILikeProvider)
    assert prov.base_url == "http://localhost:1234/v1"
    assert prov.model == "qwen2.5-coder-14b-instruct"


class DummyFailingProvider(LLMProvider):
    def generate_patch(self, prompt: str, system_prompt: str) -> str:
        raise ConnectionError("Server unreachable")

    async def agenerate_patch(self, prompt: str, system_prompt: str) -> str:
        raise ConnectionError("Server unreachable")


class DummySuccessfulProvider(LLMProvider):
    def generate_patch(self, prompt: str, system_prompt: str) -> str:
        return "def dummy(): pass"

    async def agenerate_patch(self, prompt: str, system_prompt: str) -> str:
        return "def dummy(): pass"


def test_fallback_chain():
    p1 = DummyFailingProvider(model="local-m1")
    p2 = DummySuccessfulProvider(model="cloud-m2")

    chain = FallbackChainProvider([p1, p2])
    result = chain.generate_patch("test", "test")
    assert result == "def dummy(): pass"


@pytest.mark.asyncio
async def test_async_fallback_chain():
    p1 = DummyFailingProvider(model="local-m1")
    p2 = DummySuccessfulProvider(model="cloud-m2")

    chain = FallbackChainProvider([p1, p2])
    result = await chain.agenerate_patch("test", "test")
    assert result == "def dummy(): pass"
