from __future__ import annotations

from dataclasses import dataclass, replace
import os
import re
from typing import Any

from xilma import texts
from xilma.services.sponsor import normalize_channel


class ConfigValidationError(ValueError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    admin_user_id: int
    sponsor_channels: list[str]
    api_key: str | None
    base_url: str
    default_model: str
    allowed_models: list[str]
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
        key="API_KEY",
        attr="api_key",
        label="🔑 API Key",
        kind="string",
        min_len=10,
        max_len=200,
        regex=r"^\S+$",
        optional=True,
        secret=True,
    ),
    SettingSpec(
        key="BASE_URL",
        attr="base_url",
        label="🌐 Base URL",
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
        key="ALLOWED_MODELS",
        attr="allowed_models",
        label="🧩 Allowed Models",
        kind="models",
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


DEFAULT_SETTINGS: dict[str, Any] = {
    "SPONSOR_CHANNELS": [],
    "API_KEY": None,
    "BASE_URL": "https://api.avalai.ir",
    "DEFAULT_MODEL": "gpt-4o",
    "ALLOWED_MODELS": [],
    "MAX_RETRIES": 1,
    "RETRY_BACKOFF": 0.5,
    "TEMPERATURE": None,
    "MAX_TOKENS": None,
    "TOP_P": None,
    "MAX_HISTORY_MESSAGES": 12,
    "LOG_LEVEL": "INFO",
    "LOG_FORMAT": "both",
    "LOG_ANONYMIZE_USER_IDS": True,
    "LOG_MESSAGE_BODY": True,
    "LOG_MESSAGE_HEADERS": True,
}


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
    try:
        channel = normalize_channel(raw)
    except ValueError as exc:
        raise ConfigValidationError(texts.SPONSOR_INVALID) from exc
    return channel.label


def _validate_channels(raw: str, optional: bool) -> list[str]:
    if optional and _parse_optional(raw) is None:
        return []
    items = [item.strip() for item in raw.split(",") if item.strip()]
    channels: list[str] = []
    for item in items:
        normalized = _normalize_channel(item)
        if normalized not in channels:
            channels.append(normalized)
    return channels


def _validate_models(raw: str, optional: bool) -> list[str]:
    if optional and _parse_optional(raw) is None:
        return []
    items = [item.strip() for item in raw.split(",") if item.strip()]
    models: list[str] = []
    for item in items:
        if not re.fullmatch(r"[A-Za-z0-9._:/-]+", item):
            raise ConfigValidationError(texts.VALIDATION_INVALID_FORMAT)
        if item not in models:
            models.append(item)
    return models


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
        elif spec.kind == "models":
            value = _validate_models(raw_value, spec.optional)
        else:
            raise ConfigValidationError(texts.CONFIG_INVALID_KEY)

        self._config = replace(self._config, **{spec.attr: value})

    def snapshot(self, masked: bool = True) -> dict[str, Any]:
        data = {}
        for spec in SETTINGS_SPECS:
            value = getattr(self._config, spec.attr)
        if spec.kind == "channels":
            value = ", ".join(value) if value else "-"
        if spec.kind == "models":
            value = ", ".join(value) if value else "-"
        if masked and spec.secret and value:
            value = f"{str(value)[:3]}***{str(value)[-3:]}"
            data[spec.key] = value
        return data


def load_env_credentials() -> tuple[str, int]:
    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN")
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set")
    admin_user_id = _parse_admin_id(_parse_required_env("ADMIN_USER_ID"))
    return token, admin_user_id


def serialize_setting_value(spec: SettingSpec, value: Any) -> str | None:
    if value is None:
        return None
    if spec.kind == "bool":
        return "true" if value else "false"
    if spec.kind == "int":
        return str(int(value))
    if spec.kind == "float":
        return str(float(value))
    if spec.kind == "channels":
        channels = list(value) if value else []
        return ",".join(channels) if channels else None
    if spec.kind == "models":
        models = list(value) if value else []
        return ",".join(models) if models else None
    return str(value)


def default_settings_raw() -> dict[str, str | None]:
    defaults: dict[str, str | None] = {}
    for spec in SETTINGS_SPECS:
        if spec.key not in DEFAULT_SETTINGS:
            continue
        defaults[spec.key] = serialize_setting_value(spec, DEFAULT_SETTINGS[spec.key])
    return defaults


def env_settings_raw() -> dict[str, str]:
    settings: dict[str, str] = {}
    for spec in SETTINGS_SPECS:
        raw = os.getenv(spec.key)
        if raw is None:
            continue
        settings[spec.key] = raw
    return settings


def apply_env_overrides(
    *,
    settings: dict[str, str | None],
    defaults: dict[str, str | None],
) -> tuple[dict[str, str | None], dict[str, str | None]]:
    env_settings = env_settings_raw()
    if not env_settings:
        return settings, {}
    merged = dict(settings)
    updates: dict[str, str | None] = {}
    for key, raw in env_settings.items():
        if not raw.strip():
            continue
        current = merged.get(key)
        default = defaults.get(key)
        if current is None or current == default:
            merged[key] = raw
            updates[key] = raw
    return merged, updates


def build_config_store(
    *,
    telegram_bot_token: str,
    admin_user_id: int,
    settings: dict[str, str | None],
) -> ConfigStore:
    config = Config(
        telegram_bot_token=telegram_bot_token,
        admin_user_id=admin_user_id,
        sponsor_channels=list(DEFAULT_SETTINGS["SPONSOR_CHANNELS"]),
        api_key=DEFAULT_SETTINGS["API_KEY"],
        base_url=DEFAULT_SETTINGS["BASE_URL"],
        default_model=DEFAULT_SETTINGS["DEFAULT_MODEL"],
        allowed_models=list(DEFAULT_SETTINGS["ALLOWED_MODELS"]),
        max_retries=DEFAULT_SETTINGS["MAX_RETRIES"],
        retry_backoff=DEFAULT_SETTINGS["RETRY_BACKOFF"],
        temperature=DEFAULT_SETTINGS["TEMPERATURE"],
        max_tokens=DEFAULT_SETTINGS["MAX_TOKENS"],
        top_p=DEFAULT_SETTINGS["TOP_P"],
        max_history_messages=DEFAULT_SETTINGS["MAX_HISTORY_MESSAGES"],
        log_level=DEFAULT_SETTINGS["LOG_LEVEL"],
        log_format=DEFAULT_SETTINGS["LOG_FORMAT"],
        log_anonymize_user_ids=DEFAULT_SETTINGS["LOG_ANONYMIZE_USER_IDS"],
        log_message_body=DEFAULT_SETTINGS["LOG_MESSAGE_BODY"],
        log_message_headers=DEFAULT_SETTINGS["LOG_MESSAGE_HEADERS"],
    )

    store = ConfigStore(config)
    for spec in SETTINGS_SPECS:
        raw = settings.get(spec.key)
        if raw is None:
            continue
        try:
            store.update(spec.key, raw)
        except ConfigValidationError as exc:
            raise SystemExit(f"Invalid {spec.key} in database: {exc.message}") from exc
    return store
