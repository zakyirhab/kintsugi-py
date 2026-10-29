"""
Anthropic Native Wire Adapter for KintsugiPy.
Supports Claude 3.5 Sonnet, Claude 3.5 Haiku, Claude 3 Opus via native /v1/messages API.
"""

from typing import Optional
import httpx

from kintsugi.providers.base import LLMProvider, extract_code_block


class AnthropicNativeProvider(LLMProvider):
    """Direct Anthropic /v1/messages API adapter."""

    def __init__(
        self,
        model: str = "claude-3-5-sonnet-20241022",
        api_key: Optional[str] = None,
        base_url: Optional[str] = "https://api.anthropic.com/v1",
        timeout: float = 30.0,
    ) -> None:
        super().__init__(model=model, api_key=api_key, base_url=base_url, timeout=timeout)
        self.endpoint = f"{self.base_url}/messages"

    def _get_headers(self) -> dict:
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    def _get_payload(self, prompt: str, system_prompt: str) -> dict:
        return {
            "model": self.model,
            "max_tokens": 4096,
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.05,
        }

    def generate_patch(self, prompt: str, system_prompt: str) -> str:
        headers = self._get_headers()
        payload = self._get_payload(prompt, system_prompt)

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(self.endpoint, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            raw_content = data["content"][0]["text"]
            return extract_code_block(raw_content)

    async def agenerate_patch(self, prompt: str, system_prompt: str) -> str:
        headers = self._get_headers()
        payload = self._get_payload(prompt, system_prompt)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(self.endpoint, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            raw_content = data["content"][0]["text"]
            return extract_code_block(raw_content)
