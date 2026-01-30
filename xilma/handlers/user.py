from __future__ import annotations

import logging
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from xilma import texts
from xilma.errors import UserVisibleError
from xilma.handlers.common import ensure_sponsor_membership
from xilma.utils import (
    anonymize_user_id,
    log_incoming_message,
    new_reference_id,
    reply_text,
)


logger = logging.getLogger("xilma.handlers.user")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    reference_id = new_reference_id()
    if update.message:
        settings = context.application.bot_data.get("settings")
        if settings:
            log_incoming_message(
                update,
                reference_id=reference_id,
                anonymize=settings.anonymize_user_ids,
                include_body=settings.log_message_body,
                include_headers=settings.log_message_headers,
            )
    if not await ensure_sponsor_membership(update, context, reference_id):
        return
    await reply_text(update, texts.START_MESSAGE, context, reference_id=reference_id)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    reference_id = new_reference_id()
    if update.message:
        settings = context.application.bot_data.get("settings")
        if settings:
            log_incoming_message(
                update,
                reference_id=reference_id,
                anonymize=settings.anonymize_user_ids,
                include_body=settings.log_message_body,
                include_headers=settings.log_message_headers,
            )
    if not await ensure_sponsor_membership(update, context, reference_id):
        return
    await reply_text(update, texts.HELP_MESSAGE, context, reference_id=reference_id)


async def new_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    reference_id = new_reference_id()
    if update.message:
        settings = context.application.bot_data.get("settings")
        if settings:
            log_incoming_message(
                update,
                reference_id=reference_id,
                anonymize=settings.anonymize_user_ids,
                include_body=settings.log_message_body,
                include_headers=settings.log_message_headers,
            )
    if not await ensure_sponsor_membership(update, context, reference_id):
        return
    context.user_data["history"] = []
    await reply_text(update, texts.CHAT_RESET, context, reference_id=reference_id)


async def set_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    reference_id = new_reference_id()
    if update.message:
        settings = context.application.bot_data.get("settings")
        if settings:
            log_incoming_message(
                update,
                reference_id=reference_id,
                anonymize=settings.anonymize_user_ids,
                include_body=settings.log_message_body,
                include_headers=settings.log_message_headers,
            )
    if not await ensure_sponsor_membership(update, context, reference_id):
        return

    settings = context.application.bot_data.get("settings")
    if settings is None:
        raise RuntimeError("App not configured")

    if not context.args:
        current = context.user_data.get("model", settings.default_model)
        await reply_text(
            update,
            texts.MODEL_CURRENT.format(model=current),
            context,
            reference_id=reference_id,
        )
        return

    model = context.args[0].strip()
    if not model:
        raise UserVisibleError(texts.MODEL_USAGE)

    context.user_data["model"] = model
    await reply_text(update, texts.MODEL_SET, context, reference_id=reference_id)


async def unsupported(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    reference_id = new_reference_id()
    if update.message:
        settings = context.application.bot_data.get("settings")
        if settings:
            log_incoming_message(
                update,
                reference_id=reference_id,
                anonymize=settings.anonymize_user_ids,
                include_body=settings.log_message_body,
                include_headers=settings.log_message_headers,
            )
    if not await ensure_sponsor_membership(update, context, reference_id):
        return
    await reply_text(update, texts.CHAT_ONLY_TEXT, context, reference_id=reference_id)


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    reference_id = new_reference_id()

    if update.message is None or not update.message.text:
        raise UserVisibleError(texts.CHAT_ONLY_TEXT)

    settings = context.application.bot_data.get("settings")
    llm_client = context.application.bot_data.get("llm_client")
    if settings is None or llm_client is None:
        raise RuntimeError("App not configured")

    log_incoming_message(
        update,
        reference_id=reference_id,
        anonymize=settings.anonymize_user_ids,
        include_body=settings.log_message_body,
        include_headers=settings.log_message_headers,
    )

    if not await ensure_sponsor_membership(update, context, reference_id):
        return

    history: list[dict[str, str]] = context.user_data.get("history", [])
    system_prompt = {"role": "system", "content": texts.SYSTEM_PROMPT}
    messages = [system_prompt, *history, {"role": "user", "content": update.message.text}]

    user_id = update.effective_user.id if update.effective_user else 0
    log_user = (
        anonymize_user_id(user_id)
        if user_id and settings.anonymize_user_ids
        else str(user_id)
    )
    logger.info(
        "user_message",
        extra={
            "reference_id": reference_id,
            "user_id": log_user,
            "length": len(update.message.text),
        },
    )
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    model_override = context.user_data.get("model")
    response = await llm_client.generate_response(
        messages=messages,
        model=model_override or settings.default_model,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
        top_p=settings.top_p,
        user=str(user_id) if user_id else None,
        reference_id=reference_id,
    )

    await reply_text(update, response.content, context, reference_id=reference_id)

    history.append({"role": "user", "content": update.message.text})
    history.append({"role": "assistant", "content": response.content})
    max_messages = max(settings.max_history_messages, 0)
    if max_messages:
        history = history[-max_messages:]
    context.user_data["history"] = history


async def check_membership(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    reference_id = new_reference_id()
    await update.callback_query.answer()
    if await ensure_sponsor_membership(update, context, reference_id):
        await reply_text(update, texts.MEMBERSHIP_OK, context, reference_id=reference_id)
