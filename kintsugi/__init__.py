"""
KintsugiPy (金継ぎ)
Self-healing Python functions powered by Universal LLMs.
Zero-downtime execution with AST safety and in-memory hot-swapping.
"""

import os
from typing import Any, Dict, List, Optional, Union

from kintsugi.decorator import heal, HealReport
from kintsugi.providers import (
    FallbackChainProvider,
    LLMProvider,
    OpenAILikeProvider,
    AnthropicNativeProvider,
    GeminiNativeProvider,
    resolve_provider,
)
from kintsugi.sandbox import SecurityViolationError

__version__ = "0.2.0"
__all__ = [
    "heal",
    "HealReport",
    "configure",
    "SecurityViolationError",
    "LLMProvider",
    "OpenAILikeProvider",
    "AnthropicNativeProvider",
    "GeminiNativeProvider",
    "FallbackChainProvider",
]

_GLOBAL_CONFIG: Dict[str, Any] = {}


def configure(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout: float = 30.0,
    chain: Optional[List[Union[dict, LLMProvider]]] = None,
) -> None:
    """Set global default configuration for KintsugiPy."""
    if provider is not None:
        os.environ["KINTSUGI_PROVIDER"] = provider
    if model is not None:
        os.environ["KINTSUGI_MODEL"] = model
    if api_key is not None:
        os.environ["KINTSUGI_API_KEY"] = api_key
    if base_url is not None:
        os.environ["KINTSUGI_BASE_URL"] = base_url

    _GLOBAL_CONFIG["provider"] = provider
    _GLOBAL_CONFIG["model"] = model
    _GLOBAL_CONFIG["api_key"] = api_key
    _GLOBAL_CONFIG["base_url"] = base_url
    _GLOBAL_CONFIG["timeout"] = timeout
    _GLOBAL_CONFIG["chain"] = chain
