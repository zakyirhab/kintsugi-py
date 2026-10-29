"""
OpenAI-Compatible Wire Adapter for KintsugiPy.
Supports: OpenAI, Groq, DeepSeek, OpenRouter, LM Studio, Ollama, vLLM, LiteLLM.
"""

from typing import Optional
import httpx

from kintsugi.providers.base import LLMProvider, extract_code_block


class OpenAILikeProvider(LLMProvider):
    """Universal OpenAI-compatible chat completions adapter."""

    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: Optional[str] = None,
        base_url: Optional[str] = "https://api.openai.com/v1",
        timeout: float = 30.0,
    ) -> None:
        super().__init__(model=model, api_key=api_key, base_url=base_url, timeout=timeout)
        self.endpoint = f"{self.base_url}/chat/completions"

    def _get_headers(self) -> dict:
        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _get_payload(self, prompt: str, system_prompt: str) -> dict:
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
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
            raw_content = data["choices"][0]["message"]["content"]
            return extract_code_block(raw_content)

    async def agenerate_patch(self, prompt: str, system_prompt: str) -> str:
        headers = self._get_headers()
        payload = self._get_payload(prompt, system_prompt)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(self.endpoint, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            raw_content = data["choices"][0]["message"]["content"]
            return extract_code_block(raw_content)
