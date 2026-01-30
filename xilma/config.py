from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Iterable

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    admin_user_ids: set[int]
    avalai_api_key: str
    avalai_base_url: str
    default_provider: str
    default_model: str
    fallback_provider: str | None
    fallback_model: str | None
    request_timeout: float
    max_retries: int
    retry_backoff: float
    temperature: float | None
    max_tokens: int | None
    top_p: float | None
    max_history_messages: int
    sponsor_channels: list[str]
    sponsor_channels_file: str
    log_level: str
    log_format: str
    anonymize_user_ids: bool


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    parts = [item.strip() for item in value.split(",")]
    return [item for item in parts if item]


def _parse_admin_ids(primary: str | None, additional: str | None) -> set[int]:
    raw_values: list[str] = []
    if primary:
        raw_values.append(primary)
    raw_values.extend(_split_csv(additional))

    admin_ids: set[int] = set()
    for raw in raw_values:
        try:
            admin_ids.add(int(raw))
        except ValueError as exc:
            raise SystemExit("ADMIN_USER_ID(S) must be integers") from exc
    return admin_ids


def _get_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError as exc:
        raise SystemExit(f"Invalid float value: {value}") from exc


def _get_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise SystemExit(f"Invalid integer value: {value}") from exc


def _get_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_settings() -> Settings:
    load_dotenv()

    telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set")

    admin_user_ids = _parse_admin_ids(
        os.getenv("ADMIN_USER_ID"),
        os.getenv("ADMIN_USER_IDS"),
    )

    avalai_api_key = os.getenv("AVALAI_API_KEY")
    if not avalai_api_key:
        raise SystemExit("AVALAI_API_KEY is not set")

    avalai_base_url = os.getenv("AVALAI_BASE_URL", "https://api.avalai.ir")

    default_provider = os.getenv("DEFAULT_PROVIDER", "avalai")
    default_model = os.getenv("DEFAULT_MODEL", "gpt-4o")
    fallback_provider = os.getenv("FALLBACK_PROVIDER") or None
    fallback_model = os.getenv("FALLBACK_MODEL") or None

    request_timeout = float(os.getenv("REQUEST_TIMEOUT", "30"))
    max_retries = max(0, int(os.getenv("MAX_RETRIES", "1")))
    retry_backoff = max(0.0, float(os.getenv("RETRY_BACKOFF", "0.5")))

    temperature = _get_float(os.getenv("TEMPERATURE"))
    max_tokens = _get_int(os.getenv("MAX_TOKENS"))
    top_p = _get_float(os.getenv("TOP_P"))

    max_history_messages = max(0, int(os.getenv("MAX_HISTORY_MESSAGES", "12")))

    sponsor_channels = _split_csv(os.getenv("SPONSOR_CHANNELS"))
    sponsor_channels_file = os.getenv("SPONSOR_CHANNELS_FILE", "sponsors.json")

    log_level = os.getenv("LOG_LEVEL", "INFO")
    log_format = os.getenv("LOG_FORMAT", "json")
    anonymize_user_ids = _get_bool(os.getenv("LOG_ANONYMIZE_USER_IDS"), True)

    return Settings(
        telegram_bot_token=telegram_bot_token,
        admin_user_ids=admin_user_ids,
        avalai_api_key=avalai_api_key,
        avalai_base_url=avalai_base_url,
        default_provider=default_provider,
        default_model=default_model,
        fallback_provider=fallback_provider,
        fallback_model=fallback_model,
        request_timeout=request_timeout,
        max_retries=max_retries,
        retry_backoff=retry_backoff,
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=top_p,
        max_history_messages=max_history_messages,
        sponsor_channels=sponsor_channels,
        sponsor_channels_file=sponsor_channels_file,
        log_level=log_level,
        log_format=log_format,
        anonymize_user_ids=anonymize_user_ids,
    )
