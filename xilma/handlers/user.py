from __future__ import annotations

import logging
import math
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from xilma import texts
from xilma.config import ConfigStore
from xilma.errors import UserVisibleError
from xilma.ai_client import ModelInfo
from xilma.utils import (
    anonymize_user_id,
    format_telegram_message_chunks,
    log_incoming_message,
    log_outgoing_message,
    new_reference_id,
    reply_text,
)


logger = logging.getLogger("xilma.handlers.user")
USER_MODELS_PAGE_SIZE = 12


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


def _format_allowed_models(models: list[str], limit: int = 10) -> str:
    if not models:
        return "-"
    if len(models) <= limit:
        return ", ".join(models)
    return ", ".join(models[:limit]) + " ..."


def _sort_allowed_models(
    allowed: list[str],
    models_info: list[ModelInfo],
    mode: str,
) -> list[tuple[str, float | None]]:
    price_map = {model.model_id: model.price for model in models_info}
    items = [(model_id, price_map.get(model_id)) for model_id in allowed]
    if mode == "cheap":
        return sorted(
            items,
            key=lambda item: (item[1] is None, item[1] if item[1] is not None else 0.0, item[0]),
        )
    if mode == "expensive":
        return sorted(
            items,
            key=lambda item: (item[1] is None, -(item[1] or 0.0), item[0]),
        )
    return items


def _format_models_with_price(items: list[tuple[str, float | None]]) -> str:
    lines = []
    for model_id, price in items:
        if price is None:
            lines.append(f"- {model_id}")
        else:
            lines.append(f"- {model_id} (~{price:g})")
    return "\n".join(lines)


def _format_sort_mode_label(mode: str) -> str:
    if mode == "cheap":
        return texts.BTN_SORT_CHEAP
    if mode == "expensive":
        return texts.BTN_SORT_EXPENSIVE
    return texts.BTN_SORT_DEFAULT


def _format_user_display(user) -> str:
    if user is None:
        return "-"
    name = " ".join(part for part in [user.first_name, user.last_name] if part)
    if name:
        return name
    if user.username:
        return f"@{user.username}"
    return "-"


def _build_user_panel_menu() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton(text=texts.BTN_USER_NEW_CHAT, callback_data="user:new"),
            InlineKeyboardButton(text=texts.BTN_USER_MODEL, callback_data="user:model"),
        ],
        [InlineKeyboardButton(text=texts.BTN_USERS_INFO, callback_data="user:info")],
    ]
    return InlineKeyboardMarkup(keyboard)


def _build_user_models_menu(
    models: list[str],
    current_model: str,
    default_model: str,
    page: int,
    pages: int,
) -> InlineKeyboardMarkup:
    start = (page - 1) * USER_MODELS_PAGE_SIZE
    end = start + USER_MODELS_PAGE_SIZE
    keyboard: list[list[InlineKeyboardButton]] = []

    for idx, model in enumerate(models[start:end], start=start):
        icon = "✅" if model == current_model else "⬜"
        star = " ⭐" if model == default_model else ""
        keyboard.append(
            [InlineKeyboardButton(text=f"{icon} {model}{star}", callback_data=f"user:model:set:{idx}")]
        )

    nav_row: list[InlineKeyboardButton] = []
    if page > 1:
        nav_row.append(
            InlineKeyboardButton(text=texts.BTN_PREV, callback_data=f"user:model:page:{page - 1}")
        )
    if page < pages:
        nav_row.append(
            InlineKeyboardButton(text=texts.BTN_NEXT, callback_data=f"user:model:page:{page + 1}")
        )
    if nav_row:
        keyboard.append(nav_row)

    keyboard.append([InlineKeyboardButton(text=texts.BTN_BACK, callback_data="user:panel")])
    return InlineKeyboardMarkup(keyboard)


async def _send_user_panel_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    text: str,
    reply_markup: InlineKeyboardMarkup | None,
    reference_id: str,
) -> None:
    config: ConfigStore | None = context.application.bot_data.get("config")
    include_body = config.data.log_message_body if config else False
    include_headers = config.data.log_message_headers if config else False
    anonymize = config.data.log_anonymize_user_ids if config else True
    user_id = update.effective_user.id if update.effective_user else None

    if update.callback_query and update.callback_query.message:
        try:
            message = await update.callback_query.message.edit_text(
                text,
                reply_markup=reply_markup,
            )
        except BadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise
            return
        log_outgoing_message(
            message,
            text,
            reference_id=reference_id,
            user_id=user_id,
            anonymize=anonymize,
            include_body=include_body,
            include_headers=include_headers,
            kwargs={"reply_markup": reply_markup},
        )
    else:
        await reply_text(update, text, context, reference_id=reference_id, reply_markup=reply_markup)


async def _show_user_panel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    reference_id: str,
) -> None:
    config: ConfigStore | None = context.application.bot_data.get("config")
    if config is None:
        raise RuntimeError("Config missing")

    lines = [
        texts.USER_PANEL_HEADER,
        "━━━━━━━━━━━━━━━━━━━━",
        texts.USER_PANEL_WELCOME,
        texts.USER_PANEL_SUBTITLE,
        texts.USER_PANEL_ACTIONS,
        "",
        texts.USER_PANEL_HINT,
        texts.USER_PANEL_START_HINT,
    ]

    await _send_user_panel_message(
        update,
        context,
        text="\n".join(lines),
        reply_markup=_build_user_panel_menu(),
        reference_id=reference_id,
    )


async def _show_user_info(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    reference_id: str,
) -> None:
    config: ConfigStore | None = context.application.bot_data.get("config")
    if config is None:
        raise RuntimeError("Config missing")

    user = update.effective_user
    current_model = context.user_data.get("model", config.data.default_model)
    if config.data.allowed_models and current_model not in config.data.allowed_models:
        current_model = config.data.allowed_models[0]
        context.user_data["model"] = current_model

    lines = [
        f"✦ {texts.USER_INFO_TITLE}",
        "━━━━━━━━━━━━━━━━━━━━",
        f"👤 {texts.USER_PANEL_USER}: {_format_user_display(user)}",
        f"🔖 {texts.USER_PANEL_USERNAME}: @{user.username}"
        if user and user.username
        else f"🔖 {texts.USER_PANEL_USERNAME}: -",
        f"🆔 {texts.USER_PANEL_ID}: {user.id if user else '-'}",
        "",
        f"🧠 {texts.USER_PANEL_MODEL.format(model=current_model)}",
        f"⭐ {texts.USER_PANEL_DEFAULT.format(model=config.data.default_model)}",
    ]
    if config.data.allowed_models:
        lines.append(
            f"🧩 {texts.USER_PANEL_ALLOWED.format(models=_format_allowed_models(config.data.allowed_models))}"
        )
    lines.extend(["", texts.USER_INFO_HINT])

    await _send_user_panel_message(
        update,
        context,
        text="\n".join(lines),
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton(text=texts.BTN_BACK, callback_data="user:panel")]]
        ),
        reference_id=reference_id,
    )


async def _show_user_models_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    reference_id: str,
) -> None:
    config: ConfigStore | None = context.application.bot_data.get("config")
    if config is None:
        raise RuntimeError("Config missing")

    allowed = list(config.data.allowed_models)
    if not allowed:
        await _send_user_panel_message(
            update,
            context,
            text=texts.USER_MODELS_EMPTY,
            reply_markup=_build_user_panel_menu(),
            reference_id=reference_id,
        )
        return

    page = context.user_data.get("user_models_page", 1)
    pages = max(1, math.ceil(len(allowed) / USER_MODELS_PAGE_SIZE))
    page = max(1, min(page, pages))
    context.user_data["user_models_page"] = page
    context.user_data["user_models_view"] = allowed

    current_model = context.user_data.get("model", config.data.default_model)
    if current_model not in allowed:
        current_model = allowed[0]
        context.user_data["model"] = current_model

    await _send_user_panel_message(
        update,
        context,
        text="\n".join(
            [
                texts.USER_MODELS_TITLE,
                texts.USER_MODELS_HINT,
                texts.USER_PANEL_MODEL.format(model=current_model),
            ]
        ),
        reply_markup=_build_user_models_menu(
            allowed,
            current_model,
            config.data.default_model,
            page,
            pages,
        ),
        reference_id=reference_id,
    )


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
    await _show_user_panel(update, context, reference_id)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    reference_id = new_reference_id()
    if not await _log_and_check_membership(update, context, reference_id):
        return
    await reply_text(update, texts.HELP_MESSAGE, context, reference_id=reference_id)


async def models_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    reference_id = new_reference_id()
    if not await _log_and_check_membership(update, context, reference_id):
        return

    config: ConfigStore | None = context.application.bot_data.get("config")
    ai_client = context.application.bot_data.get("ai_client")
    if config is None or ai_client is None:
        raise RuntimeError("Config missing")

    allowed = list(config.data.allowed_models)
    if not allowed:
        await reply_text(
            update,
            texts.MODEL_ALLOWED_LIST.format(models="-"),
            context,
            reference_id=reference_id,
        )
        return

    mode = (context.args[0].strip().lower() if context.args else "name")
    if mode not in {"name", "cheap", "expensive"}:
        mode = "name"

    models_info: list[ModelInfo] = []
    if mode in {"cheap", "expensive"}:
        try:
            models_info = await ai_client.list_models()
        except Exception:  # noqa: BLE001
            models_info = []

    sorted_items = _sort_allowed_models(allowed, models_info, mode)
    lines = [
        texts.MODELS_LIST_TITLE,
        texts.MODELS_SORT_HINT.format(mode=_format_sort_mode_label(mode)),
        "",
        _format_models_with_price(sorted_items),
    ]
    if mode in {"cheap", "expensive"} and not models_info:
        lines.extend(["", texts.MODELS_SORT_FAILED])
    lines.extend(["", texts.MODELS_SORT_USAGE])
    await reply_text(update, "\n".join(lines), context, reference_id=reference_id)


async def new_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    reference_id = new_reference_id()
    if not await _log_and_check_membership(update, context, reference_id):
        return
    context.user_data["history"] = []
    await reply_text(update, texts.CHAT_RESET, context, reference_id=reference_id)
    await _show_user_panel(update, context, new_reference_id())


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
        if config.data.allowed_models:
            allowed_line = texts.MODEL_ALLOWED_LIST.format(
                models=_format_allowed_models(config.data.allowed_models)
            )
            message = f"{texts.MODEL_CURRENT.format(model=current)}\n{allowed_line}"
        else:
            message = texts.MODEL_CURRENT.format(model=current)
        await reply_text(update, message, context, reference_id=reference_id)
        return

    model = context.args[0].strip()
    if not model:
        raise UserVisibleError(texts.MODEL_USAGE)

    if config.data.allowed_models and model not in config.data.allowed_models:
        raise UserVisibleError(
            texts.MODEL_NOT_ALLOWED.format(
                models=_format_allowed_models(config.data.allowed_models)
            )
        )

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
    selected_model = model_override or config.data.default_model
    if config.data.allowed_models:
        if model_override and model_override not in config.data.allowed_models:
            raise UserVisibleError(
                texts.MODEL_NOT_ALLOWED.format(
                    models=_format_allowed_models(config.data.allowed_models)
                )
            )
        if selected_model not in config.data.allowed_models:
            selected_model = config.data.allowed_models[0]
            context.user_data["model"] = selected_model
            logger.warning(
                "default_model_not_allowed",
                extra={"reference_id": reference_id, "fallback": selected_model},
            )

    response = await ai_client.generate_response(
        messages=messages,
        model=selected_model,
        temperature=config.data.temperature,
        max_tokens=config.data.max_tokens,
        top_p=config.data.top_p,
        user=str(user_id) if user_id else None,
    )

    for formatted_text, parse_mode in format_telegram_message_chunks(response.content):
        await reply_text(
            update,
            formatted_text,
            context,
            reference_id=reference_id,
            parse_mode=parse_mode,
        )

    history.append({"role": "user", "content": update.message.text})
    history.append({"role": "assistant", "content": response.content})
    max_messages = max(config.data.max_history_messages, 0)
    if max_messages <= 0:
        history = []
    else:
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


async def handle_user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    reference_id = new_reference_id()
    await _track_user(update, context)
    if not await _ensure_sponsor_membership(update, context, reference_id):
        return

    data = update.callback_query.data or ""
    if data == "user:panel":
        await update.callback_query.answer()
        await _show_user_panel(update, context, reference_id)
        return

    if data == "user:model":
        await update.callback_query.answer()
        await _show_user_models_menu(update, context, reference_id)
        return

    if data == "user:info":
        await update.callback_query.answer()
        await _show_user_info(update, context, reference_id)
        return

    if data == "user:new":
        context.user_data["history"] = []
        await update.callback_query.answer(texts.CHAT_RESET)
        await _show_user_panel(update, context, reference_id)
        return

    if data.startswith("user:model:page:"):
        try:
            page = int(data.split(":", 3)[3])
        except ValueError:
            return
        context.user_data["user_models_page"] = page
        await update.callback_query.answer()
        await _show_user_models_menu(update, context, reference_id)
        return

    if data.startswith("user:model:set:"):
        config: ConfigStore | None = context.application.bot_data.get("config")
        if config is None:
            raise RuntimeError("Config missing")
        try:
            idx = int(data.split(":", 3)[3])
        except ValueError:
            return
        models_view = context.user_data.get("user_models_view", [])
        if not isinstance(models_view, list) or idx < 0 or idx >= len(models_view):
            return
        model_id = models_view[idx]
        if config.data.allowed_models and model_id not in config.data.allowed_models:
            await update.callback_query.answer(
                texts.MODEL_NOT_ALLOWED.format(
                    models=_format_allowed_models(config.data.allowed_models)
                ),
                show_alert=True,
            )
            return
        context.user_data["model"] = model_id
        await update.callback_query.answer(texts.USER_MODEL_UPDATED)
        await _show_user_models_menu(update, context, reference_id)
        return


async def command_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    reference_id = new_reference_id()
    if not await _log_and_check_membership(update, context, reference_id):
        return
    await reply_text(update, texts.USER_COMMAND_FALLBACK, context, reference_id=reference_id)
    await _show_user_panel(update, context, new_reference_id())
