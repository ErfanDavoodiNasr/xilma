from __future__ import annotations

import hashlib
import logging
from typing import Any
from uuid import uuid4

from telegram import Message, Update
from telegram.ext import ContextTypes


def anonymize_user_id(user_id: int) -> str:
    digest = hashlib.sha256(str(user_id).encode("utf-8")).hexdigest()
    return digest[:10]


def new_reference_id() -> str:
    return uuid4().hex


def _format_user_id(user_id: int | None, anonymize: bool) -> str | int | None:
    if user_id is None:
        return None
    return anonymize_user_id(user_id) if anonymize else user_id


def log_incoming_message(
    update: Update,
    *,
    reference_id: str | None,
    anonymize: bool,
    include_body: bool,
    include_headers: bool,
) -> None:
    if update.message is None or not (include_body or include_headers):
        return

    headers: dict[str, Any] = {}
    if include_headers:
        user_id = update.effective_user.id if update.effective_user else None
        headers = {
            "update_id": update.update_id,
            "chat_id": update.effective_chat.id if update.effective_chat else None,
            "chat_type": update.effective_chat.type if update.effective_chat else None,
            "message_id": update.message.message_id,
            "date": update.message.date.isoformat() if update.message.date else None,
            "user_id": _format_user_id(user_id, anonymize),
            "language_code": (
                update.effective_user.language_code if update.effective_user else None
            ),
        }

    body: dict[str, Any] | None = None
    if include_body:
        body = {"text": update.message.text}

    payload: dict[str, Any] = {"direction": "incoming"}
    if reference_id:
        payload["reference_id"] = reference_id
    if headers:
        payload["headers"] = headers
    if body is not None:
        payload["body"] = body

    logging.getLogger("xilma.messages").info("telegram_message", extra=payload)


def log_outgoing_message(
    message: Message | None,
    text: str,
    *,
    reference_id: str | None,
    user_id: int | None,
    anonymize: bool,
    include_body: bool,
    include_headers: bool,
    kwargs: dict[str, Any],
) -> None:
    if message is None or not (include_body or include_headers):
        return

    headers: dict[str, Any] = {}
    if include_headers:
        headers = {
            "chat_id": message.chat_id,
            "message_id": message.message_id,
            "date": message.date.isoformat() if message.date else None,
            "has_reply_markup": bool(kwargs.get("reply_markup")),
            "user_id": _format_user_id(user_id, anonymize),
        }
        if kwargs.get("parse_mode") is not None:
            headers["parse_mode"] = str(kwargs.get("parse_mode"))
        if message.reply_to_message is not None:
            headers["reply_to_message_id"] = message.reply_to_message.message_id

    body: dict[str, Any] | None = None
    if include_body:
        body = {"text": text}

    payload: dict[str, Any] = {"direction": "outgoing"}
    if reference_id:
        payload["reference_id"] = reference_id
    if headers:
        payload["headers"] = headers
    if body is not None:
        payload["body"] = body

    logging.getLogger("xilma.messages").info("telegram_message", extra=payload)


async def reply_text(
    update: Update,
    text: str,
    context: ContextTypes.DEFAULT_TYPE | None = None,
    reference_id: str | None = None,
    **kwargs,
) -> None:
    config = context.application.bot_data.get("config") if context else None
    include_body = config.data.log_message_body if config else False
    include_headers = config.data.log_message_headers if config else False
    anonymize = config.data.log_anonymize_user_ids if config else True

    sent_message: Message | None = None
    if update.message:
        sent_message = await update.message.reply_text(text, **kwargs)
    elif update.callback_query and update.callback_query.message:
        sent_message = await update.callback_query.message.reply_text(text, **kwargs)
    elif context and update.effective_chat:
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id, text=text, **kwargs
        )

    user_id = update.effective_user.id if update.effective_user else None
    log_outgoing_message(
        sent_message,
        text,
        reference_id=reference_id,
        user_id=user_id,
        anonymize=anonymize,
        include_body=include_body,
        include_headers=include_headers,
        kwargs=kwargs,
    )
