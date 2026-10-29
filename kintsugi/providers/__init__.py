"""
Universal Provider Resolver and Auto-Detection for KintsugiPy.
"""

import os
from typing import List, Optional, Union

from kintsugi.providers.base import LLMProvider
from kintsugi.providers.openai_like import OpenAILikeProvider
from kintsugi.providers.anthropic_native import AnthropicNativeProvider
from kintsugi.providers.gemini_native import GeminiNativeProvider


class FallbackChainProvider(LLMProvider):
    """Orchestrates sequential fallback across multiple providers."""

    def __init__(self, providers: List[LLMProvider]) -> None:
        if not providers:
            raise ValueError("FallbackChainProvider requires at least one provider.")
        self.providers = providers
        super().__init__(
            model=providers[0].model,
            api_key=providers[0].api_key,
            base_url=providers[0].base_url,
            timeout=providers[0].timeout,
        )

    def generate_patch(self, prompt: str, system_prompt: str) -> str:
        errors = []
        for p in self.providers:
            try:
                return p.generate_patch(prompt, system_prompt)
            except Exception as e:
                errors.append(f"{p.__class__.__name__} ({p.model}): {str(e)}")
        raise RuntimeError(f"All providers in fallback chain failed: {'; '.join(errors)}")

    async def agenerate_patch(self, prompt: str, system_prompt: str) -> str:
        errors = []
        for p in self.providers:
            try:
                return await p.agenerate_patch(prompt, system_prompt)
            except Exception as e:
                errors.append(f"{p.__class__.__name__} ({p.model}): {str(e)}")
        raise RuntimeError(f"All providers in fallback chain failed: {'; '.join(errors)}")


def resolve_provider(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout: float = 30.0,
    chain: Optional[List[Union[dict, LLMProvider]]] = None,
) -> LLMProvider:
    """Resolve and instantiate the appropriate LLMProvider based on params or environment."""
    
    # 1. If explicit chain is given
    if chain:
        chain_instances: List[LLMProvider] = []
        for item in chain:
            if isinstance(item, LLMProvider):
                chain_instances.append(item)
            elif isinstance(item, dict):
                chain_instances.append(resolve_provider(**item))
        return FallbackChainProvider(chain_instances)

    # 2. Extract from environment variables if not provided
    prov = (provider or os.getenv("KINTSUGI_PROVIDER", "")).lower().strip()
    key = api_key or os.getenv("KINTSUGI_API_KEY", "")
    url = base_url or os.getenv("KINTSUGI_BASE_URL", "")
    mdl = model or os.getenv("KINTSUGI_MODEL", "")

    # 3. Provider detection logic
    # Anthropic
    if prov in ("anthropic", "claude") or (not prov and key.startswith("sk-ant-")) or (not prov and os.getenv("ANTHROPIC_API_KEY")):
        actual_key = key or os.getenv("ANTHROPIC_API_KEY", "")
        actual_model = mdl or "claude-3-5-sonnet-20241022"
        actual_url = url or "https://api.anthropic.com/v1"
        return AnthropicNativeProvider(model=actual_model, api_key=actual_key, base_url=actual_url, timeout=timeout)

    # Gemini
    if prov in ("gemini", "google") or (not prov and key.startswith("AIza")) or (not prov and os.getenv("GEMINI_API_KEY")):
        actual_key = key or os.getenv("GEMINI_API_KEY", "")
        actual_model = mdl or "gemini-1.5-flash"
        actual_url = url or "https://generativelanguage.googleapis.com/v1beta"
        return GeminiNativeProvider(model=actual_model, api_key=actual_key, base_url=actual_url, timeout=timeout)

    # Groq
    if prov == "groq" or (not prov and key.startswith("gsk_")) or (not prov and os.getenv("GROQ_API_KEY")):
        actual_key = key or os.getenv("GROQ_API_KEY", "")
        actual_model = mdl or "llama-3.3-70b-versatile"
        actual_url = url or "https://api.groq.com/openai/v1"
        return OpenAILikeProvider(model=actual_model, api_key=actual_key, base_url=actual_url, timeout=timeout)

    # OpenRouter
    if prov == "openrouter" or (not prov and key.startswith("sk-or-")) or (not prov and os.getenv("OPENROUTER_API_KEY")):
        actual_key = key or os.getenv("OPENROUTER_API_KEY", "")
        actual_model = mdl or "anthropic/claude-3.5-sonnet"
        actual_url = url or "https://openrouter.ai/api/v1"
        return OpenAILikeProvider(model=actual_model, api_key=actual_key, base_url=actual_url, timeout=timeout)

    # DeepSeek
    if prov == "deepseek" or (not prov and os.getenv("DEEPSEEK_API_KEY")):
        actual_key = key or os.getenv("DEEPSEEK_API_KEY", "")
        actual_model = mdl or "deepseek-chat"
        actual_url = url or "https://api.deepseek.com/v1"
        return OpenAILikeProvider(model=actual_model, api_key=actual_key, base_url=actual_url, timeout=timeout)

    # OpenAI
    if prov == "openai" or (not prov and key.startswith("sk-") and not url) or (not prov and os.getenv("OPENAI_API_KEY")):
        actual_key = key or os.getenv("OPENAI_API_KEY", "")
        actual_model = mdl or "gpt-4o"
        actual_url = url or "https://api.openai.com/v1"
        return OpenAILikeProvider(model=actual_model, api_key=actual_key, base_url=actual_url, timeout=timeout)

    # Local Engine (LM Studio, Ollama, vLLM) or Custom URL
    actual_url = url or "http://localhost:1234/v1"
    actual_model = mdl or "qwen2.5-coder-14b-instruct"
    return OpenAILikeProvider(model=actual_model, api_key=key, base_url=actual_url, timeout=timeout)
