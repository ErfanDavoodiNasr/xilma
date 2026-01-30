from __future__ import annotations

import json
import logging
from datetime import datetime, timezone


STANDARD_RECORD_ATTRS = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
}


def _extract_extras(record: logging.LogRecord) -> dict[str, object]:
    extras: dict[str, object] = {}
    for key, value in record.__dict__.items():
        if key in STANDARD_RECORD_ATTRS:
            continue
        extras[key] = value
    return extras


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        payload.update(_extract_extras(record))
        return json.dumps(payload, ensure_ascii=False)


class TextExtrasFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = _extract_extras(record)
        if extras:
            extra_json = json.dumps(extras, ensure_ascii=False)
            return f"{base} | extra={extra_json}"
        return base


def _parse_formats(fmt: str) -> list[str]:
    lowered = fmt.strip().lower()
    if lowered in {"both", "all"}:
        return ["text", "json"]
    if "," in lowered:
        return [item.strip() for item in lowered.split(",") if item.strip()]
    return [lowered]


def setup_logging(level: str, fmt: str) -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())

    formats = _parse_formats(fmt)
    handlers: list[logging.Handler] = []

    if "json" in formats:
        json_handler = logging.StreamHandler()
        json_handler.setFormatter(JsonFormatter())
        handlers.append(json_handler)

    if "text" in formats or not handlers:
        text_handler = logging.StreamHandler()
        text_handler.setFormatter(
            TextExtrasFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        handlers.append(text_handler)

    root.handlers.clear()
    for handler in handlers:
        root.addHandler(handler)
