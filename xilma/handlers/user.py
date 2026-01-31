from __future__ import annotations

import logging
import math
import time
from typing import Any
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from xilma import texts
from xilma.config import ConfigStore
from xilma.errors import APIError, UserVisibleError
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
CHAT_RATE_LIMIT_SECONDS = 1.0
USER_CHATS_PAGE_SIZE = 8
USER_CHAT_MESSAGES_PAGE_SIZE = 10


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


def _format_timestamp(value) -> str:
    if not value:
        return "-"
    try:
        return value.isoformat(sep=" ", timespec="minutes")
    except TypeError:
        return str(value)


def _truncate_title(text: str, limit: int = 40) -> str:
    cleaned = " ".join(text.strip().split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


def _format_conversation_title(conversation: dict) -> str:
    title = conversation.get("title")
    if title:
        return title
    return texts.USER_CHAT_UNTITLED.format(chat_id=conversation.get("id"))


def _format_conversation_label(conversation: dict, active_id: int | None) -> str:
    title = _format_conversation_title(conversation)
    updated = _format_timestamp(conversation.get("updated_at"))
    marker = "⭐ " if active_id and conversation.get("id") == active_id else ""
    error_flag = "⚠️ " if conversation.get("last_is_error") else ""
    return f"{marker}{error_flag}{title} • {updated}"


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
        [
            InlineKeyboardButton(text=texts.BTN_USERS_INFO, callback_data="user:info"),
            InlineKeyboardButton(text=texts.BTN_USER_CHATS, callback_data="user:chats"),
        ],
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

    keyboard.append([InlineKeyboardButton(text=texts.BTN_USER_NEW_CHAT, callback_data="user:new")])
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
        chunks = format_telegram_message_chunks(text)
        if len(chunks) == 1:
            formatted_text, parse_mode = chunks[0]
            try:
                message = await update.callback_query.message.edit_text(
                    formatted_text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                )
            except BadRequest as exc:
                if "message is not modified" not in str(exc).lower():
                    raise
                return
            log_outgoing_message(
                message,
                formatted_text,
                reference_id=reference_id,
                user_id=user_id,
                anonymize=anonymize,
                include_body=include_body,
                include_headers=include_headers,
                kwargs={"reply_markup": reply_markup, "parse_mode": parse_mode},
            )
            return

        for idx, (chunk, parse_mode) in enumerate(chunks):
            chunk_markup = reply_markup if idx == len(chunks) - 1 else None
            await reply_text(
                update,
                chunk,
                context,
                reference_id=reference_id,
                reply_markup=chunk_markup,
                parse_mode=parse_mode,
            )
        return

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


async def _ensure_active_conversation(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    db = context.application.bot_data.get("db")
    if db is None:
        raise RuntimeError("DB missing")
    if update.effective_user is None:
        raise RuntimeError("User missing")

    conversation_id = context.user_data.get("conversation_id")
    if isinstance(conversation_id, int):
        existing = await db.get_conversation(
            telegram_id=update.effective_user.id,
            conversation_id=conversation_id,
            include_deleted=False,
        )
        if existing:
            return conversation_id

    conversation_id = await db.create_conversation(telegram_id=update.effective_user.id)
    context.user_data["conversation_id"] = conversation_id
    context.user_data["history"] = []
    return conversation_id


async def _start_new_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = context.application.bot_data.get("db")
    if db is None:
        raise RuntimeError("DB missing")
    if update.effective_user is None:
        raise RuntimeError("User missing")
    new_conversation_id = await db.create_conversation(telegram_id=update.effective_user.id)
    context.user_data["conversation_id"] = new_conversation_id
    context.user_data["history"] = []


async def _load_history_for_conversation(
    db,
    *,
    conversation_id: int,
    max_messages: int,
) -> list[dict[str, str]]:
    if max_messages <= 0:
        return []
    total = await db.count_messages(conversation_id=conversation_id)
    offset = max(total - max_messages, 0)
    rows = await db.list_messages(
        conversation_id=conversation_id,
        limit=max_messages,
        offset=offset,
    )
    history: list[dict[str, str]] = []
    for row in rows:
        if row.get("is_error"):
            continue
        role = row.get("role")
        content = row.get("content")
        if role and content is not None:
            history.append({"role": role, "content": content})
    return history


async def _set_active_conversation(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    conversation_id: int,
    config: ConfigStore,
) -> None:
    db = context.application.bot_data.get("db")
    if db is None:
        raise RuntimeError("DB missing")
    if update.effective_user is None:
        raise RuntimeError("User missing")
    convo = await db.get_conversation(
        telegram_id=update.effective_user.id,
        conversation_id=conversation_id,
        include_deleted=False,
    )
    if not convo:
        raise UserVisibleError(texts.USER_CHAT_NOT_FOUND)
    history = await _load_history_for_conversation(
        db,
        conversation_id=conversation_id,
        max_messages=max(config.data.max_history_messages, 0),
    )
    context.user_data["conversation_id"] = conversation_id
    context.user_data["history"] = history


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


def _build_user_chats_menu(
    conversations: list[dict[str, Any]],
    *,
    active_id: int | None,
    page: int,
    pages: int,
) -> InlineKeyboardMarkup:
    keyboard: list[list[InlineKeyboardButton]] = []
    for convo in conversations:
        label = _format_conversation_label(convo, active_id)
        keyboard.append(
            [InlineKeyboardButton(text=label, callback_data=f"user:chat:open:{convo['id']}")]
        )

    nav_row: list[InlineKeyboardButton] = []
    if page > 1:
        nav_row.append(
            InlineKeyboardButton(
                text=texts.BTN_PREV, callback_data=f"user:chats:page:{page - 1}"
            )
        )
    if page < pages:
        nav_row.append(
            InlineKeyboardButton(
                text=texts.BTN_NEXT, callback_data=f"user:chats:page:{page + 1}"
            )
        )
    if nav_row:
        keyboard.append(nav_row)

    keyboard.append([InlineKeyboardButton(text=texts.BTN_BACK, callback_data="user:panel")])
    return InlineKeyboardMarkup(keyboard)


def _build_user_chat_view_menu(
    *,
    page: int,
    pages: int,
    conversation_id: int,
) -> InlineKeyboardMarkup:
    nav_row: list[InlineKeyboardButton] = []
    if page < pages:
        nav_row.append(
            InlineKeyboardButton(
                text=texts.BTN_OLDER, callback_data=f"user:chat:page:{conversation_id}:{page + 1}"
            )
        )
    if page > 1:
        nav_row.append(
            InlineKeyboardButton(
                text=texts.BTN_NEWER, callback_data=f"user:chat:page:{conversation_id}:{page - 1}"
            )
        )
    keyboard: list[list[InlineKeyboardButton]] = []
    if nav_row:
        keyboard.append(nav_row)
    keyboard.append(
        [InlineKeyboardButton(text=texts.BTN_DELETE_CHAT, callback_data=f"user:chat:delete:{conversation_id}")]
    )
    keyboard.append([InlineKeyboardButton(text=texts.BTN_BACK, callback_data="user:chats")])
    return InlineKeyboardMarkup(keyboard)


async def _show_user_chats_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    reference_id: str,
    *,
    page: int,
) -> None:
    if update.effective_user is None:
        raise RuntimeError("User missing")
    db = context.application.bot_data.get("db")
    if db is None:
        raise RuntimeError("DB missing")

    total = await db.count_conversations(
        telegram_id=update.effective_user.id, include_deleted=False
    )
    if total == 0:
        await _send_user_panel_message(
            update,
            context,
            text=texts.USER_CHATS_EMPTY,
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton(text=texts.BTN_USER_NEW_CHAT, callback_data="user:new")],
                    [InlineKeyboardButton(text=texts.BTN_BACK, callback_data="user:panel")],
                ]
            ),
            reference_id=reference_id,
        )
        return

    pages = max(1, math.ceil(total / USER_CHATS_PAGE_SIZE))
    page = max(1, min(page, pages))
    context.user_data["user_chats_page"] = page
    conversations = await db.list_conversations_with_last_message(
        telegram_id=update.effective_user.id,
        include_deleted=False,
        limit=USER_CHATS_PAGE_SIZE,
        offset=(page - 1) * USER_CHATS_PAGE_SIZE,
    )

    active_id = context.user_data.get("conversation_id")
    lines = [
        texts.USER_CHATS_TITLE,
        texts.USER_CHATS_PAGE.format(page=page, pages=pages),
        "",
    ]
    for convo in conversations:
        lines.append(f"- {_format_conversation_label(convo, active_id)}")
    lines.extend(["", texts.USER_CHATS_HINT])

    await _send_user_panel_message(
        update,
        context,
        text="\n".join(lines),
        reply_markup=_build_user_chats_menu(
            conversations, active_id=active_id if isinstance(active_id, int) else None, page=page, pages=pages
        ),
        reference_id=reference_id,
    )


async def _show_user_chat_view(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    reference_id: str,
    *,
    conversation_id: int,
    page: int,
) -> None:
    if update.effective_user is None:
        raise RuntimeError("User missing")
    db = context.application.bot_data.get("db")
    if db is None:
        raise RuntimeError("DB missing")

    convo = await db.get_conversation(
        telegram_id=update.effective_user.id,
        conversation_id=conversation_id,
        include_deleted=False,
    )
    if not convo:
        await _show_user_chats_menu(update, context, reference_id, page=1)
        return

    total = await db.count_messages(conversation_id=conversation_id)
    if total == 0:
        await _send_user_panel_message(
            update,
            context,
            text=texts.USER_CHAT_EMPTY,
            reply_markup=_build_user_chat_view_menu(page=1, pages=1, conversation_id=conversation_id),
            reference_id=reference_id,
        )
        return

    pages = max(1, math.ceil(total / USER_CHAT_MESSAGES_PAGE_SIZE))
    page = max(1, min(page, pages))
    start = max(total - (page * USER_CHAT_MESSAGES_PAGE_SIZE), 0)
    limit = min(USER_CHAT_MESSAGES_PAGE_SIZE, total - start)
    messages = await db.list_messages(
        conversation_id=conversation_id,
        limit=limit,
        offset=start,
    )

    lines = [
        texts.USER_CHAT_TITLE.format(title=_format_conversation_title(convo)),
        texts.USER_CHAT_PAGE.format(page=page, pages=pages),
        "",
    ]
    for message in messages:
        role = message.get("role")
        if message.get("is_error"):
            prefix = "⚠️"
        else:
            prefix = "👤" if role == "user" else "🤖" if role == "assistant" else "⚙️"
        created = _format_timestamp(message.get("created_at"))
        lines.append(f"{prefix} ({created})")
        model = message.get("model")
        if model:
            lines.append(texts.USER_CHAT_MODEL.format(model=model))
        if message.get("is_error"):
            lines.append(texts.USER_CHAT_ERROR)
        else:
            lines.append(str(message.get("content", "")).strip())
        lines.append("")

    await _send_user_panel_message(
        update,
        context,
        text="\n".join(lines).strip(),
        reply_markup=_build_user_chat_view_menu(
            page=page,
            pages=pages,
            conversation_id=conversation_id,
        ),
        reference_id=reference_id,
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
    for chunk, parse_mode in format_telegram_message_chunks("\n".join(lines)):
        await reply_text(
            update,
            chunk,
            context,
            reference_id=reference_id,
            parse_mode=parse_mode,
        )


async def new_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    reference_id = new_reference_id()
    if not await _log_and_check_membership(update, context, reference_id):
        return
    await _start_new_conversation(update, context)
    await reply_text(update, texts.USER_CHAT_CREATED, context, reference_id=reference_id)
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

    last_ts = context.user_data.get("last_chat_ts")
    now = time.monotonic()
    if isinstance(last_ts, (int, float)) and now - last_ts < CHAT_RATE_LIMIT_SECONDS:
        await reply_text(update, texts.RATE_LIMITED, context, reference_id=reference_id)
        return
    context.user_data["last_chat_ts"] = now

    if not config.data.api_key:
        raise UserVisibleError(texts.API_KEY_MISSING)

    db = context.application.bot_data.get("db")
    if db is None:
        raise RuntimeError("DB missing")

    conversation_id = await _ensure_active_conversation(update, context)
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

    await db.insert_message(
        conversation_id=conversation_id,
        role="user",
        content=update.message.text,
    )
    await db.update_conversation_title(
        conversation_id=conversation_id,
        title=_truncate_title(update.message.text),
    )

    try:
        response = await ai_client.generate_response(
            messages=messages,
            model=selected_model,
            temperature=config.data.temperature,
            max_tokens=config.data.max_tokens,
            top_p=config.data.top_p,
            user=str(user_id) if user_id else None,
        )
    except APIError as exc:
        await db.insert_message(
            conversation_id=conversation_id,
            role="assistant",
            content=f"API_ERROR: {exc.message}",
            is_error=True,
            model=selected_model,
        )
        raise UserVisibleError(texts.GENERIC_ERROR) from exc
    except Exception as exc:  # noqa: BLE001
        await db.insert_message(
            conversation_id=conversation_id,
            role="assistant",
            content=f"ERROR: {str(exc)}",
            is_error=True,
            model=selected_model,
        )
        raise

    await db.insert_message(
        conversation_id=conversation_id,
        role="assistant",
        content=response.content,
        model=selected_model,
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
        await _start_new_conversation(update, context)
        await update.callback_query.answer(texts.USER_CHAT_CREATED)
        await _show_user_panel(update, context, reference_id)
        return

    if data == "user:chats":
        await update.callback_query.answer()
        await _show_user_chats_menu(update, context, reference_id, page=1)
        return

    if data.startswith("user:chats:page:"):
        try:
            page = int(data.split(":", 3)[3])
        except ValueError:
            return
        await update.callback_query.answer()
        await _show_user_chats_menu(update, context, reference_id, page=page)
        return

    if data.startswith("user:chat:open:"):
        try:
            conversation_id = int(data.split(":", 3)[3])
        except ValueError:
            return
        config: ConfigStore | None = context.application.bot_data.get("config")
        if config is None:
            raise RuntimeError("Config missing")
        await _set_active_conversation(
            update,
            context,
            conversation_id=conversation_id,
            config=config,
        )
        await update.callback_query.answer(texts.USER_CHAT_SELECTED)
        await _show_user_chat_view(
            update,
            context,
            reference_id,
            conversation_id=conversation_id,
            page=1,
        )
        return

    if data.startswith("user:chat:page:"):
        parts = data.split(":", 4)
        if len(parts) < 5:
            return
        try:
            conversation_id = int(parts[3])
            page = int(parts[4])
        except ValueError:
            return
        await update.callback_query.answer()
        await _show_user_chat_view(
            update,
            context,
            reference_id,
            conversation_id=conversation_id,
            page=page,
        )
        return

    if data.startswith("user:chat:delete:"):
        try:
            conversation_id = int(data.split(":", 3)[3])
        except ValueError:
            return
        db = context.application.bot_data.get("db")
        if db is None or update.effective_user is None:
            raise RuntimeError("DB missing")
        await db.soft_delete_conversation(
            telegram_id=update.effective_user.id,
            conversation_id=conversation_id,
        )
        if context.user_data.get("conversation_id") == conversation_id:
            context.user_data.pop("conversation_id", None)
            context.user_data["history"] = []
        await update.callback_query.answer(texts.USER_CHAT_DELETED)
        await _show_user_chats_menu(update, context, reference_id, page=1)
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
