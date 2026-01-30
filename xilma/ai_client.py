from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import aiohttp

from xilma.errors import APIError


@dataclass(frozen=True)
class AIResponse:
    content: str
    model: str
    usage: dict[str, Any] | None = None


class AIClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout: float,
        max_retries: int = 1,
        retry_backoff: float = 0.5,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max(0, max_retries)
        self._retry_backoff = max(0.0, retry_backoff)
        self._session: aiohttp.ClientSession | None = None
        self._logger = logging.getLogger("xilma.ai")

    async def start(self) -> None:
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=self._timeout)
            self._session = aiohttp.ClientSession(timeout=timeout)

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    def update_settings(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        max_retries: int | None = None,
        retry_backoff: float | None = None,
    ) -> None:
        if api_key is not None:
            self._api_key = api_key
        if base_url is not None:
            self._base_url = base_url.rstrip("/")
        if max_retries is not None:
            self._max_retries = max(0, max_retries)
        if retry_backoff is not None:
            self._retry_backoff = max(0.0, retry_backoff)

    async def generate_response(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
        user: str | None = None,
    ) -> AIResponse:
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
                        raise APIError(
                            f"API error {resp.status}: {text}",
                            status_code=resp.status,
                        )
                    data = await resp.json()
                break
            except APIError as exc:
                if exc.status_code in {429, 500} and attempt < self._max_retries:
                    delay = self._retry_backoff * (2**attempt)
                    self._logger.warning(
                        "request_retry",
                        extra={"attempt": attempt + 1, "status": exc.status_code, "delay": delay},
                    )
                    await asyncio.sleep(delay)
                    continue
                raise
            except (asyncio.TimeoutError, aiohttp.ClientError) as exc:
                if attempt < self._max_retries:
                    delay = self._retry_backoff * (2**attempt)
                    self._logger.warning(
                        "request_retry",
                        extra={"attempt": attempt + 1, "error": str(exc), "delay": delay},
                    )
                    await asyncio.sleep(delay)
                    continue
                raise APIError("Network error") from exc
        else:
            raise APIError("Request failed")

        try:
            choice = data["choices"][0]
            message = choice["message"]
            content = message.get("content")
            if content is None:
                raise KeyError("content missing")
        except (KeyError, IndexError, TypeError) as exc:
            raise APIError("Response format error") from exc

        return AIResponse(content=content, model=data.get("model", model), usage=data.get("usage"))
