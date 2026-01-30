from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from xilma.errors import ProviderError
from xilma.providers.base import BaseLLMProvider, LLMResponse


class AvalAIProvider(BaseLLMProvider):
    def __init__(
        self,
        api_key: str,
        base_url: str,
        timeout: float,
        max_retries: int = 1,
        retry_backoff: float = 0.5,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff
        self._session: aiohttp.ClientSession | None = None
        self._logger = logging.getLogger("xilma.providers.avalai")

    async def start(self) -> None:
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=self._timeout)
            self._session = aiohttp.ClientSession(timeout=timeout)

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def generate_response(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
        user: str | None = None,
    ) -> LLMResponse:
        if self._session is None:
            await self.start()

        payload: dict[str, Any] = {"model": model, "messages": messages}
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if top_p is not None:
            payload["top_p"] = top_p
        if user is not None:
            payload["user"] = user

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        url = f"{self._base_url}/v1/chat/completions"
        for attempt in range(self._max_retries + 1):
            try:
                async with self._session.post(url, json=payload, headers=headers) as resp:
                    if resp.status >= 400:
                        text = await resp.text()
                        raise ProviderError(
                            f"AvalAI error {resp.status}: {text}",
                            status_code=resp.status,
                        )
                    data = await resp.json()
                break
            except ProviderError as exc:
                if (
                    exc.status_code in {429, 500}
                    and attempt < self._max_retries
                ):
                    delay = self._retry_backoff * (2**attempt)
                    self._logger.warning(
                        "avalai_retry",
                        extra={
                            "attempt": attempt + 1,
                            "status": exc.status_code,
                            "delay": delay,
                        },
                    )
                    await asyncio.sleep(delay)
                    continue
                raise
            except (asyncio.TimeoutError, aiohttp.ClientError) as exc:
                if attempt < self._max_retries:
                    delay = self._retry_backoff * (2**attempt)
                    self._logger.warning(
                        "avalai_retry",
                        extra={
                            "attempt": attempt + 1,
                            "error": str(exc),
                            "delay": delay,
                        },
                    )
                    await asyncio.sleep(delay)
                    continue
                raise ProviderError("AvalAI network error") from exc
        else:
            raise ProviderError("AvalAI request failed")

        try:
            choice = data["choices"][0]
            message = choice["message"]
            content = message.get("content")
            if content is None:
                raise KeyError("content missing")
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("AvalAI response format error") from exc

        return LLMResponse(content=content, model=data.get("model", model), usage=data.get("usage"))
