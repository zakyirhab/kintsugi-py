"""
Abstract Base Provider for KintsugiPy LLM Connectors.
"""

from abc import ABC, abstractmethod
import re
from typing import Optional


def extract_code_block(raw_text: str) -> str:
    """Extract python source code from markdown fences or raw LLM output."""
    clean_text = raw_text.strip()
    
    # Match ```python ... ``` or ``` ... ```
    pattern = r"```(?:python)?\s*([\s\S]*?)```"
    match = re.search(pattern, clean_text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    
    # If no fences found, return clean text
    return clean_text


class LLMProvider(ABC):
    """Abstract interface for LLM backends in KintsugiPy."""

    def __init__(
        self,
        model: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
    ) -> None:
        self.model = model
        self.api_key = api_key or ""
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.timeout = timeout

    @abstractmethod
    def generate_patch(self, prompt: str, system_prompt: str) -> str:
        """Synchronously request a patch from the model."""
        pass

    @abstractmethod
    async def agenerate_patch(self, prompt: str, system_prompt: str) -> str:
        """Asynchronously request a patch from the model."""
        pass
