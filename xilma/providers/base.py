from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LLMResponse:
    content: str
    model: str
    usage: dict[str, Any] | None = None


class BaseLLMProvider:
    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

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
        raise NotImplementedError
