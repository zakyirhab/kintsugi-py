"""
Google Gemini Native Wire Adapter for KintsugiPy.
Supports Gemini 1.5 Pro, Gemini 1.5 Flash, Gemini 2.0 via Google AI Studio API.
"""

from typing import Optional
import httpx

from kintsugi.providers.base import LLMProvider, extract_code_block


class GeminiNativeProvider(LLMProvider):
    """Direct Google Gemini REST API adapter."""

    def __init__(
        self,
        model: str = "gemini-1.5-pro",
        api_key: Optional[str] = None,
        base_url: Optional[str] = "https://generativelanguage.googleapis.com/v1beta",
        timeout: float = 30.0,
    ) -> None:
        super().__init__(model=model, api_key=api_key, base_url=base_url, timeout=timeout)
        self.endpoint = f"{self.base_url}/models/{self.model}:generateContent"

    def _get_params(self) -> dict:
        params = {}
        if self.api_key:
            params["key"] = self.api_key
        return params

    def _get_payload(self, prompt: str, system_prompt: str) -> dict:
        return {
            "systemInstruction": {
                "parts": [{"text": system_prompt}]
            },
            "contents": [
                {
                    "parts": [{"text": prompt}]
                }
            ],
            "generationConfig": {
                "temperature": 0.05
            }
        }

    def generate_patch(self, prompt: str, system_prompt: str) -> str:
        params = self._get_params()
        payload = self._get_payload(prompt, system_prompt)

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(self.endpoint, params=params, json=payload)
            resp.raise_for_status()
            data = resp.json()
            raw_content = data["candidates"][0]["content"]["parts"][0]["text"]
            return extract_code_block(raw_content)

    async def agenerate_patch(self, prompt: str, system_prompt: str) -> str:
        params = self._get_params()
        payload = self._get_payload(prompt, system_prompt)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(self.endpoint, params=params, json=payload)
            resp.raise_for_status()
            data = resp.json()
            raw_content = data["candidates"][0]["content"]["parts"][0]["text"]
            return extract_code_block(raw_content)
