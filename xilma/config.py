from __future__ import annotations

from dataclasses import dataclass, replace
import os
import re
from typing import Any

from dotenv import load_dotenv

from xilma import texts


class ConfigValidationError(ValueError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    admin_user_id: int
    sponsor_channels: list[str]
    avalai_api_key: str | None
    avalai_base_url: str
    default_model: str
    fallback_model: str | None
    max_retries: int
    retry_backoff: float
    temperature: float | None
    max_tokens: int | None
    top_p: float | None
    max_history_messages: int
    log_level: str
    log_format: str
    log_anonymize_user_ids: bool
    log_message_body: bool
    log_message_headers: bool


@dataclass(frozen=True)
class SettingSpec:
    key: str
    attr: str
    label: str
    kind: str
    min_value: float | int | None = None
    max_value: float | int | None = None
    min_len: int | None = None
    max_len: int | None = None
    regex: str | None = None
    allowed: list[str] | None = None
    optional: bool = False
    secret: bool = False


SETTINGS_SPECS: list[SettingSpec] = [
    SettingSpec(
        key="SPONSOR_CHANNELS",
        attr="sponsor_channels",
        label="📣 Sponsor Channels",
        kind="channels",
        optional=True,
    ),
    SettingSpec(
        key="AVALAI_API_KEY",
        attr="avalai_api_key",
        label="🔑 AvalAI API Key",
        kind="string",
        min_len=10,
        max_len=200,
        regex=r"^\S+$",
        optional=True,
        secret=True,
    ),
    SettingSpec(
        key="AVALAI_BASE_URL",
        attr="avalai_base_url",
        label="🌐 AvalAI Base URL",
        kind="string",
        min_len=10,
        max_len=200,
        regex=r"^https?://\S+$",
    ),
    SettingSpec(
        key="DEFAULT_MODEL",
        attr="default_model",
        label="🧠 Default Model",
        kind="string",
        min_len=2,
        max_len=80,
        regex=r"^[A-Za-z0-9._:/-]+$",
    ),
    SettingSpec(
        key="FALLBACK_MODEL",
        attr="fallback_model",
        label="🛟 Fallback Model",
        kind="string",
        min_len=2,
        max_len=80,
        regex=r"^[A-Za-z0-9._:/-]+$",
        optional=True,
    ),
    SettingSpec(
        key="MAX_RETRIES",
        attr="max_retries",
        label="🔁 Max Retries",
        kind="int",
        min_value=0,
        max_value=5,
    ),
    SettingSpec(
        key="RETRY_BACKOFF",
        attr="retry_backoff",
        label="⏱️ Retry Backoff",
        kind="float",
        min_value=0.0,
        max_value=10.0,
    ),
    SettingSpec(
        key="TEMPERATURE",
        attr="temperature",
        label="🌡️ Temperature",
        kind="float",
        min_value=0.0,
        max_value=2.0,
        optional=True,
    ),
    SettingSpec(
        key="MAX_TOKENS",
        attr="max_tokens",
        label="🧮 Max Tokens",
        kind="int",
        min_value=1,
        max_value=8192,
        optional=True,
    ),
    SettingSpec(
        key="TOP_P",
        attr="top_p",
        label="🎛️ Top P",
        kind="float",
        min_value=0.0,
        max_value=1.0,
        optional=True,
    ),
    SettingSpec(
        key="MAX_HISTORY_MESSAGES",
        attr="max_history_messages",
        label="🗂️ Max History",
        kind="int",
        min_value=0,
        max_value=50,
    ),
    SettingSpec(
        key="LOG_LEVEL",
        attr="log_level",
        label="📈 Log Level",
        kind="enum",
        allowed=["DEBUG", "INFO", "WARNING", "ERROR"],
    ),
    SettingSpec(
        key="LOG_FORMAT",
        attr="log_format",
        label="🧾 Log Format",
        kind="enum",
        allowed=["text", "json", "both"],
    ),
    SettingSpec(
        key="LOG_ANONYMIZE_USER_IDS",
        attr="log_anonymize_user_ids",
        label="🕶️ Anonymize User IDs",
        kind="bool",
    ),
    SettingSpec(
        key="LOG_MESSAGE_BODY",
        attr="log_message_body",
        label="📝 Log Message Body",
        kind="bool",
    ),
    SettingSpec(
        key="LOG_MESSAGE_HEADERS",
        attr="log_message_headers",
        label="🧷 Log Message Headers",
        kind="bool",
    ),
]


SPEC_BY_KEY = {spec.key: spec for spec in SETTINGS_SPECS}


def _parse_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"{name} is not set")
    return value


def _parse_admin_id(value: str) -> int:
    if not re.fullmatch(r"[0-9]+", value):
        raise SystemExit("ADMIN_USER_ID must be digits")
    return int(value)


def _parse_optional(raw: str | None) -> str | None:
    if raw is None:
        return None
    lowered = raw.strip().lower()
    if lowered in {"", "none", "null", "unset", "-"}:
        return None
    return raw


def _parse_env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    if not re.fullmatch(r"[0-9]+", raw.strip()):
        raise SystemExit(f"{name} must be digits")
    return int(raw)


def _parse_env_float(name: str, default: float | None) -> float | None:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    if not re.fullmatch(r"[0-9]+(\.[0-9]+)?", raw.strip()):
        raise SystemExit(f"{name} must be a float number with digits")
    return float(raw)


def _validate_string(spec: SettingSpec, raw: str) -> str | None:
    value = _parse_optional(raw) if spec.optional else raw.strip()
    if value is None:
        return None
    if spec.min_len is not None and len(value) < spec.min_len:
        raise ConfigValidationError(texts.VALIDATION_TOO_SHORT)
    if spec.max_len is not None and len(value) > spec.max_len:
        raise ConfigValidationError(texts.VALIDATION_TOO_LONG)
    if spec.regex and not re.fullmatch(spec.regex, value):
        raise ConfigValidationError(texts.VALIDATION_INVALID_FORMAT)
    return value


def _validate_int(spec: SettingSpec, raw: str) -> int | None:
    value = _parse_optional(raw) if spec.optional else raw.strip()
    if value is None:
        return None
    if not re.fullmatch(r"[0-9]+", value):
        raise ConfigValidationError(texts.VALIDATION_DIGITS_ONLY)
    number = int(value)
    if spec.min_value is not None and number < spec.min_value:
        raise ConfigValidationError(texts.VALIDATION_TOO_LOW)
    if spec.max_value is not None and number > spec.max_value:
        raise ConfigValidationError(texts.VALIDATION_TOO_HIGH)
    return number


def _validate_float(spec: SettingSpec, raw: str) -> float | None:
    value = _parse_optional(raw) if spec.optional else raw.strip()
    if value is None:
        return None
    if not re.fullmatch(r"[0-9]+(\.[0-9]+)?", value):
        raise ConfigValidationError(texts.VALIDATION_FLOAT_ONLY)
    number = float(value)
    if spec.min_value is not None and number < spec.min_value:
        raise ConfigValidationError(texts.VALIDATION_TOO_LOW)
    if spec.max_value is not None and number > spec.max_value:
        raise ConfigValidationError(texts.VALIDATION_TOO_HIGH)
    return number


def _validate_enum(spec: SettingSpec, raw: str) -> str:
    value = raw.strip()
    if spec.allowed:
        if value in spec.allowed:
            return value
        lowered = value.lower()
        if lowered in spec.allowed:
            return lowered
        uppered = value.upper()
        if uppered in spec.allowed:
            return uppered
        allowed = ", ".join(spec.allowed)
        raise ConfigValidationError(texts.VALIDATION_ENUM.format(allowed=allowed))
    return value


def _validate_bool(raw: str) -> bool:
    lowered = raw.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    raise ConfigValidationError(texts.VALIDATION_BOOL)


def _normalize_channel(raw: str) -> str:
    cleaned = raw.strip()
    if cleaned.startswith("https://t.me/") or cleaned.startswith("http://t.me/"):
        cleaned = cleaned.split("t.me/", 1)[1]
    if cleaned.startswith("t.me/"):
        cleaned = cleaned.split("t.me/", 1)[1]
    if cleaned.startswith("+") or cleaned.startswith("joinchat/"):
        raise ConfigValidationError(texts.SPONSOR_INVALID)
    username = cleaned[1:] if cleaned.startswith("@") else cleaned
    if not username.replace("_", "").isalnum():
        raise ConfigValidationError(texts.SPONSOR_INVALID)
    return f"@{username}"


def _validate_channels(raw: str, optional: bool) -> list[str]:
    if optional and raw.strip().lower() in {"", "unset", "none", "null", "-"}:
        return []
    items = [item.strip() for item in raw.split(",") if item.strip()]
    channels: list[str] = []
    for item in items:
        normalized = _normalize_channel(item)
        if normalized not in channels:
            channels.append(normalized)
    return channels


class ConfigStore:
    def __init__(self, config: Config) -> None:
        self._config = config

    @property
    def data(self) -> Config:
        return self._config

    def update(self, key: str, raw_value: str) -> None:
        spec = SPEC_BY_KEY.get(key)
        if spec is None:
            raise ConfigValidationError(texts.CONFIG_INVALID_KEY)

        if spec.kind == "string":
            value = _validate_string(spec, raw_value)
        elif spec.kind == "int":
            value = _validate_int(spec, raw_value)
        elif spec.kind == "float":
            value = _validate_float(spec, raw_value)
        elif spec.kind == "enum":
            value = _validate_enum(spec, raw_value)
        elif spec.kind == "bool":
            value = _validate_bool(raw_value)
        elif spec.kind == "channels":
            value = _validate_channels(raw_value, spec.optional)
        else:
            raise ConfigValidationError(texts.CONFIG_INVALID_KEY)

        self._config = replace(self._config, **{spec.attr: value})

    def snapshot(self, masked: bool = True) -> dict[str, Any]:
        data = {}
        for spec in SETTINGS_SPECS:
            value = getattr(self._config, spec.attr)
            if spec.kind == "channels":
                value = ", ".join(value) if value else "-"
            if masked and spec.secret and value:
                value = f"{str(value)[:3]}***{str(value)[-3:]}"
            data[spec.key] = value
        return data


def load_config() -> ConfigStore:
    load_dotenv()

    telegram_bot_token = _parse_required_env("TELEGRAM_BOT_TOKEN")
    admin_user_id = _parse_admin_id(_parse_required_env("ADMIN_USER_ID"))

    config = Config(
        telegram_bot_token=telegram_bot_token,
        admin_user_id=admin_user_id,
        sponsor_channels=[],
        avalai_api_key=os.getenv("AVALAI_API_KEY"),
        avalai_base_url=os.getenv("AVALAI_BASE_URL", "https://api.avalai.ir"),
        default_model=os.getenv("DEFAULT_MODEL", "gpt-4o"),
        fallback_model=os.getenv("FALLBACK_MODEL") or None,
        max_retries=max(0, _parse_env_int("MAX_RETRIES", 1)),
        retry_backoff=max(0.0, _parse_env_float("RETRY_BACKOFF", 0.5) or 0.5),
        temperature=_parse_env_float("TEMPERATURE", None),
        max_tokens=_parse_env_int("MAX_TOKENS", 0) or None,
        top_p=_parse_env_float("TOP_P", None),
        max_history_messages=max(0, _parse_env_int("MAX_HISTORY_MESSAGES", 12)),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        log_format=os.getenv("LOG_FORMAT", "both"),
        log_anonymize_user_ids=os.getenv("LOG_ANONYMIZE_USER_IDS", "true").lower()
        in {"1", "true", "yes", "on"},
        log_message_body=os.getenv("LOG_MESSAGE_BODY", "true").lower()
        in {"1", "true", "yes", "on"},
        log_message_headers=os.getenv("LOG_MESSAGE_HEADERS", "true").lower()
        in {"1", "true", "yes", "on"},
    )

    store = ConfigStore(config)
    for spec in SETTINGS_SPECS:
        raw = os.getenv(spec.key)
        if raw is None:
            continue
        try:
            store.update(spec.key, raw)
        except ConfigValidationError as exc:
            raise SystemExit(f"Invalid {spec.key}: {exc.message}") from exc
    return store
