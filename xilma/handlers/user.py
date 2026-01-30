from __future__ import annotations

import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from xilma import texts
from xilma.config import ConfigStore
from xilma.errors import UserVisibleError
from xilma.utils import anonymize_user_id, log_incoming_message, new_reference_id, reply_text


logger = logging.getLogger("xilma.handlers.user")


def _log_incoming_if_config(
    update: Update, config: ConfigStore | None, reference_id: str
) -> None:
    if config and update.message:
        log_incoming_message(
            update,
            reference_id=reference_id,
            anonymize=config.data.log_anonymize_user_ids,
            include_body=config.data.log_message_body,
            include_headers=config.data.log_message_headers,
        )


def _log_user_message(update: Update, config: ConfigStore, reference_id: str) -> None:
    user_id = update.effective_user.id if update.effective_user else 0
    log_user = (
        anonymize_user_id(user_id)
        if user_id and config.data.log_anonymize_user_ids
        else str(user_id)
    )
    logger.info(
        "user_message",
        extra={
            "reference_id": reference_id,
            "user_id": log_user,
            "length": len(update.message.text) if update.message else 0,
        },
    )


def _is_admin(update: Update, config: ConfigStore) -> bool:
    if update.effective_user is None:
        return False
    return update.effective_user.id == config.data.admin_user_id


async def _track_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = context.application.bot_data.get("db")
    user = update.effective_user
    if db is None or user is None:
        return
    await db.upsert_user(
        telegram_id=user.id,
        first_name=user.first_name,
        last_name=user.last_name,
        username=user.username,
        language_code=user.language_code,
        is_bot=user.is_bot,
    )


def _build_sponsor_markup(context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup | None:
    sponsor_service = context.application.bot_data.get("sponsor_service")
    if sponsor_service is None:
        return None
    buttons = sponsor_service.build_buttons()
    if not buttons:
        return None
    buttons.append(
        [InlineKeyboardButton(text=texts.CHECK_MEMBERSHIP, callback_data="check_membership")]
    )
    return InlineKeyboardMarkup(buttons)


async def _ensure_sponsor_membership(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    reference_id: str,
) -> bool:
    config: ConfigStore | None = context.application.bot_data.get("config")
    sponsor_service = context.application.bot_data.get("sponsor_service")
    if config is None or sponsor_service is None:
        return True

    if _is_admin(update, config):
        return True

    if update.effective_user is None:
        return False

    if await sponsor_service.is_member(context.bot, update.effective_user.id):
        return True

    markup = _build_sponsor_markup(context)
    await reply_text(
        update,
        texts.SPONSOR_REQUIRED,
        context,
        reference_id=reference_id,
        reply_markup=markup,
    )
    return False


async def _log_and_check_membership(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    reference_id: str,
) -> bool:
    await _track_user(update, context)
    config: ConfigStore | None = context.application.bot_data.get("config")
    _log_incoming_if_config(update, config, reference_id)
    return await _ensure_sponsor_membership(update, context, reference_id)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    reference_id = new_reference_id()
    if not await _log_and_check_membership(update, context, reference_id):
        return
    await reply_text(update, texts.START_MESSAGE, context, reference_id=reference_id)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    reference_id = new_reference_id()
    if not await _log_and_check_membership(update, context, reference_id):
        return
    await reply_text(update, texts.HELP_MESSAGE, context, reference_id=reference_id)


async def new_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    reference_id = new_reference_id()
    if not await _log_and_check_membership(update, context, reference_id):
        return
    context.user_data["history"] = []
    await reply_text(update, texts.CHAT_RESET, context, reference_id=reference_id)


async def set_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    reference_id = new_reference_id()
    await _track_user(update, context)
    config: ConfigStore | None = context.application.bot_data.get("config")
    _log_incoming_if_config(update, config, reference_id)

    if config is None:
        raise RuntimeError("Config missing")

    if not await _ensure_sponsor_membership(update, context, reference_id):
        return

    if not context.args:
        current = context.user_data.get("model", config.data.default_model)
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
    if not await _log_and_check_membership(update, context, reference_id):
        return
    await reply_text(update, texts.CHAT_ONLY_TEXT, context, reference_id=reference_id)


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    reference_id = new_reference_id()
    if update.message is None or not update.message.text:
        raise UserVisibleError(texts.CHAT_ONLY_TEXT)
    await _track_user(update, context)

    config: ConfigStore | None = context.application.bot_data.get("config")
    ai_client = context.application.bot_data.get("ai_client")
    if config is None or ai_client is None:
        raise RuntimeError("App not configured")

    _log_user_message(update, config, reference_id)
    log_incoming_message(
        update,
        reference_id=reference_id,
        anonymize=config.data.log_anonymize_user_ids,
        include_body=config.data.log_message_body,
        include_headers=config.data.log_message_headers,
    )

    if not await _ensure_sponsor_membership(update, context, reference_id):
        return

    if not config.data.api_key:
        raise UserVisibleError(texts.API_KEY_MISSING)

    history: list[dict[str, str]] = context.user_data.get("history", [])
    system_prompt = {"role": "system", "content": texts.SYSTEM_PROMPT}
    messages = [system_prompt, *history, {"role": "user", "content": update.message.text}]

    user_id = update.effective_user.id if update.effective_user else 0

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    model_override = context.user_data.get("model")
    response = await ai_client.generate_response(
        messages=messages,
        model=model_override or config.data.default_model,
        temperature=config.data.temperature,
        max_tokens=config.data.max_tokens,
        top_p=config.data.top_p,
        user=str(user_id) if user_id else None,
    )

    await reply_text(update, response.content, context, reference_id=reference_id)

    history.append({"role": "user", "content": update.message.text})
    history.append({"role": "assistant", "content": response.content})
    max_messages = max(config.data.max_history_messages, 0)
    if max_messages:
        history = history[-max_messages:]
    context.user_data["history"] = history


async def check_membership(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    reference_id = new_reference_id()
    await _track_user(update, context)
    await update.callback_query.answer()
    if await _ensure_sponsor_membership(update, context, reference_id):
        await reply_text(update, texts.MEMBERSHIP_OK, context, reference_id=reference_id)
