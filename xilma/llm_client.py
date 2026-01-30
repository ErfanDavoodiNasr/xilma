from __future__ import annotations

import logging
from typing import Any

from xilma.errors import ProviderError
from xilma.providers.base import BaseLLMProvider, LLMResponse


class LLMClient:
    def __init__(
        self,
        providers: dict[str, BaseLLMProvider],
        default_provider: str,
        default_model: str,
        fallback_provider: str | None = None,
        fallback_model: str | None = None,
    ) -> None:
        self._providers = providers
        self._default_provider = default_provider
        self._default_model = default_model
        self._fallback_provider = fallback_provider
        self._fallback_model = fallback_model
        self._logger = logging.getLogger("xilma.llm")

    async def start(self) -> None:
        for provider in self._providers.values():
            await provider.start()

    async def close(self) -> None:
        for provider in self._providers.values():
            await provider.close()

    async def generate_response(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str | None = None,
        provider: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
        user: str | None = None,
        reference_id: str | None = None,
    ) -> LLMResponse:
        provider_name = provider or self._default_provider
        model_name = model or self._default_model

        if provider_name not in self._providers:
            raise ProviderError(f"Unknown provider: {provider_name}")

        self._logger.info(
            "routing_request",
            extra={"provider": provider_name, "model": model_name, "reference_id": reference_id},
        )

        primary_provider = self._providers[provider_name]
        try:
            return await primary_provider.generate_response(
                messages=messages,
                model=model_name,
                temperature=temperature,
                max_tokens=max_tokens,
                top_p=top_p,
                user=user,
            )
        except ProviderError as exc:
            self._logger.error(
                "provider_error",
                extra={
                    "provider": provider_name,
                    "model": model_name,
                    "status": exc.status_code,
                    "reference_id": reference_id,
                },
            )
            if self._fallback_provider or self._fallback_model:
                fallback_provider = self._fallback_provider or provider_name
                fallback_model = self._fallback_model or model_name
                if fallback_provider in self._providers:
                    self._logger.info(
                        "routing_fallback",
                        extra={
                            "provider": fallback_provider,
                            "model": fallback_model,
                            "reference_id": reference_id,
                        },
                    )
                    fallback = self._providers[fallback_provider]
                    return await fallback.generate_response(
                        messages=messages,
                        model=fallback_model,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        top_p=top_p,
                        user=user,
                    )
            raise
