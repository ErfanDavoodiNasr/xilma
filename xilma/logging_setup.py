from __future__ import annotations

import json
import logging
from datetime import datetime, timezone


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
        for key, value in record.__dict__.items():
            if key in {
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
            }:
                continue
            payload[key] = value
        return json.dumps(payload, ensure_ascii=False)


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
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        handlers.append(text_handler)

    root.handlers.clear()
    for handler in handlers:
        root.addHandler(handler)
