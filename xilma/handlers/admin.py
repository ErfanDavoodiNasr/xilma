from __future__ import annotations

import math
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes, ConversationHandler

from xilma import texts
from xilma.config import (
    SETTINGS_SPECS,
    SPEC_BY_KEY,
    ConfigStore,
    ConfigValidationError,
    serialize_setting_value,
)
from xilma.ai_client import ModelInfo
from xilma.errors import APIError, UserVisibleError
from xilma.logging_setup import setup_logging
from xilma.services.sponsor import normalize_channel, parse_channels_csv
from xilma.utils import (
    format_telegram_message_chunks,
    log_incoming_message,
    log_outgoing_message,
    new_reference_id,
    reply_text,
)


ADMIN_MENU, WAITING_INPUT = range(2)
USERS_PAGE_SIZE = 10
MODELS_PAGE_SIZE = 12
DEFAULT_MODELS_PAGE_SIZE = 12
ADMIN_CHATS_PAGE_SIZE = 8
ADMIN_CHAT_MESSAGES_PAGE_SIZE = 10


def _set_sponsor_menu_active(context: ContextTypes.DEFAULT_TYPE, active: bool) -> None:
    if active:
        context.user_data["sponsor_menu_active"] = True
    else:
        context.user_data.pop("sponsor_menu_active", None)


def _build_main_menu() -> InlineKeyboardMarkup:
    keyboard: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=texts.BTN_USERS, callback_data="users:menu")]
    ]
    row: list[InlineKeyboardButton] = []
    for spec in SETTINGS_SPECS:
        row.append(InlineKeyboardButton(text=spec.label, callback_data=f"cfg:{spec.key}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton(text=texts.BTN_CLOSE, callback_data="cfg:close")])
    return InlineKeyboardMarkup(keyboard)


def _build_cancel_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(text=texts.BTN_BACK, callback_data="cfg:back")]]
    )


def _build_sponsor_menu() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton(text=texts.BTN_ADD, callback_data="sponsor:add"),
            InlineKeyboardButton(text=texts.BTN_EDIT, callback_data="sponsor:edit"),
        ],
        [
            InlineKeyboardButton(text=texts.BTN_REMOVE, callback_data="sponsor:remove"),
            InlineKeyboardButton(text=texts.BTN_BACK, callback_data="sponsor:back"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return texts.STATUS_ON if value else texts.STATUS_OFF
    if value is None or value == "":
        return "-"
    return str(value)


def _build_prompt(spec_label: str, spec_kind: str, allowed: list[str] | None, optional: bool) -> str:
    lines = [texts.ADMIN_PROMPT_VALUE.format(label=spec_label)]
    if spec_kind == "bool":
        lines.append(texts.PROMPT_BOOL)
    elif spec_kind == "enum" and allowed:
        lines.append(texts.VALIDATION_ENUM.format(allowed=", ".join(allowed)))
    elif spec_kind == "int":
        lines.append(texts.PROMPT_INT)
    elif spec_kind == "float":
        lines.append(texts.PROMPT_FLOAT)
    elif spec_kind == "channels":
        lines.append(texts.PROMPT_CHANNELS)
    if optional:
        lines.append(texts.PROMPT_OPTIONAL)
    return "\n".join(lines)


async def _persist_setting(
    config: ConfigStore, db, key: str, raw_value: str
) -> None:
    spec = SPEC_BY_KEY.get(key)
    if spec is None:
        raise ConfigValidationError(texts.CONFIG_INVALID_KEY)
    previous = config.data
    config.update(key, raw_value)
    value = getattr(config.data, spec.attr)
    db_value = serialize_setting_value(spec, value)
    try:
        await db.set_setting(key, db_value)
    except Exception:
        config._config = previous  # roll back in-memory state if persistence fails
        raise


async def _sync_sponsor_channels(config: ConfigStore, sponsor_service, db) -> None:
    channels = [channel.raw for channel in sponsor_service.list_channels()]
    csv_value = ",".join(channels)
    await _persist_setting(config, db, "SPONSOR_CHANNELS", csv_value)


def _add_sponsor_channels(sponsor_service, raw_text: str) -> None:
    channels = parse_channels_csv(raw_text)
    if not channels:
        raise UserVisibleError(texts.SPONSOR_INVALID)
    existing = {channel.chat_id for channel in sponsor_service.list_channels()}
    for channel in channels:
        if channel.chat_id in existing:
            raise UserVisibleError(texts.SPONSOR_ALREADY_EXISTS)
        existing.add(channel.chat_id)
    for channel in channels:
        sponsor_service.add_channel(channel.raw)


def _build_sponsor_select_menu(channels: list, action: str) -> InlineKeyboardMarkup:
    prefix = texts.ICON_EDIT if action == "edit" else texts.ICON_REMOVE
    keyboard: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text=f"{prefix}{channel.label}",
                callback_data=f"sponsor:{action}:{channel.label}",
            )
        ]
        for channel in channels
    ]
    keyboard.append([InlineKeyboardButton(text=texts.BTN_BACK, callback_data="sponsor:menu")])
    return InlineKeyboardMarkup(keyboard)


def _format_user_label(user: dict[str, Any]) -> str:
    user_id = user.get("telegram_id")
    username = user.get("username")
    first_name = user.get("first_name") or ""
    last_name = user.get("last_name") or ""
    name = " ".join(part for part in [first_name, last_name] if part)
    if username:
        label = f"@{username}"
    elif name:
        label = name
    else:
        label = f"User {user_id}"
    return f"{label} ({user_id})"


def _format_timestamp(value: Any) -> str:
    if not value:
        return "-"
    try:
        return value.isoformat(sep=" ", timespec="seconds")
    except TypeError:
        return str(value)


def _format_conversation_title(conversation: dict[str, Any]) -> str:
    title = conversation.get("title")
    if title:
        return title
    return f"Chat {conversation.get('id')}"


def _format_conversation_label(conversation: dict[str, Any]) -> str:
    title = _format_conversation_title(conversation)
    updated = _format_timestamp(conversation.get("updated_at"))
    deleted = conversation.get("deleted_at")
    error_flag = "⚠️ " if conversation.get("last_is_error") else ""
    if deleted:
        return f"🗑️ {error_flag}{title} • {updated}"
    return f"💬 {error_flag}{title} • {updated}"


def _build_users_menu(
    users: list[dict[str, Any]], page: int, pages: int
) -> InlineKeyboardMarkup:
    keyboard: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text=_format_user_label(user),
                callback_data=f"users:view:{user['telegram_id']}",
            )
        ]
        for user in users
    ]
    nav_row: list[InlineKeyboardButton] = []
    if page > 1:
        nav_row.append(
            InlineKeyboardButton(text=texts.BTN_PREV, callback_data=f"users:page:{page - 1}")
        )
    if page < pages:
        nav_row.append(
            InlineKeyboardButton(text=texts.BTN_NEXT, callback_data=f"users:page:{page + 1}")
        )
    if nav_row:
        keyboard.append(nav_row)
    keyboard.append([InlineKeyboardButton(text=texts.BTN_BACK, callback_data="users:back")])
    return InlineKeyboardMarkup(keyboard)


def _build_user_detail_menu(telegram_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(text=texts.ADMIN_USER_CHATS, callback_data=f"users:chats:{telegram_id}")],
            [InlineKeyboardButton(text=texts.BTN_BACK, callback_data="users:list")],
        ]
    )


def _build_user_chats_menu(
    conversations: list[dict[str, Any]],
    *,
    telegram_id: int,
    page: int,
    pages: int,
) -> InlineKeyboardMarkup:
    keyboard: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text=_format_conversation_label(convo),
                callback_data=f"users:chat:open:{convo['id']}",
            )
        ]
        for convo in conversations
    ]
    nav_row: list[InlineKeyboardButton] = []
    if page > 1:
        nav_row.append(
            InlineKeyboardButton(
                text=texts.BTN_PREV,
                callback_data=f"users:chats:page:{telegram_id}:{page - 1}",
            )
        )
    if page < pages:
        nav_row.append(
            InlineKeyboardButton(
                text=texts.BTN_NEXT,
                callback_data=f"users:chats:page:{telegram_id}:{page + 1}",
            )
        )
    if nav_row:
        keyboard.append(nav_row)
    keyboard.append(
        [InlineKeyboardButton(text=texts.BTN_BACK, callback_data=f"users:view:{telegram_id}")]
    )
    return InlineKeyboardMarkup(keyboard)


def _build_admin_chat_view_menu(
    *,
    telegram_id: int,
    conversation_id: int,
    page: int,
    pages: int,
) -> InlineKeyboardMarkup:
    nav_row: list[InlineKeyboardButton] = []
    if page < pages:
        nav_row.append(
            InlineKeyboardButton(
                text=texts.BTN_OLDER,
                callback_data=f"users:chat:page:{conversation_id}:{page + 1}",
            )
        )
    if page > 1:
        nav_row.append(
            InlineKeyboardButton(
                text=texts.BTN_NEWER,
                callback_data=f"users:chat:page:{conversation_id}:{page - 1}",
            )
        )
    keyboard: list[list[InlineKeyboardButton]] = []
    if nav_row:
        keyboard.append(nav_row)
    keyboard.append(
        [InlineKeyboardButton(text=texts.BTN_BACK, callback_data=f"users:chats:{telegram_id}")]
    )
    return InlineKeyboardMarkup(keyboard)


def _build_models_menu(
    models: list[ModelInfo],
    selected: set[str],
    page: int,
    pages: int,
    default_model: str,
    *,
    search_active: bool,
) -> InlineKeyboardMarkup:
    start = (page - 1) * MODELS_PAGE_SIZE
    end = start + MODELS_PAGE_SIZE
    keyboard: list[list[InlineKeyboardButton]] = []

    for idx, model in enumerate(models[start:end], start=start):
        icon = "✅" if model.model_id in selected else "⬜"
        star = " ⭐" if model.model_id == default_model else ""
        price = _format_model_price(model.price)
        label = f"{icon} {model.model_id}{star}{price}"
        keyboard.append(
            [InlineKeyboardButton(text=label, callback_data=f"models:toggle:{idx}")]
        )

    nav_row: list[InlineKeyboardButton] = []
    if page > 1:
        nav_row.append(
            InlineKeyboardButton(text=texts.BTN_PREV, callback_data=f"models:page:{page - 1}")
        )
    if page < pages:
        nav_row.append(
            InlineKeyboardButton(text=texts.BTN_NEXT, callback_data=f"models:page:{page + 1}")
        )
    if nav_row:
        keyboard.append(nav_row)

    if search_active:
        keyboard.append(
            [InlineKeyboardButton(text=texts.BTN_SEARCH_CLEAR, callback_data="models:search:clear")]
        )
    else:
        keyboard.append([InlineKeyboardButton(text=texts.BTN_SEARCH, callback_data="models:search")])

    keyboard.append(
        [
            InlineKeyboardButton(text=texts.BTN_SORT, callback_data="models:sort"),
            InlineKeyboardButton(text=texts.BTN_BACK, callback_data="models:back"),
        ]
    )
    return InlineKeyboardMarkup(keyboard)


def _build_default_models_menu(
    models: list[str],
    current_default: str,
    page: int,
    pages: int,
) -> InlineKeyboardMarkup:
    start = (page - 1) * DEFAULT_MODELS_PAGE_SIZE
    end = start + DEFAULT_MODELS_PAGE_SIZE
    keyboard: list[list[InlineKeyboardButton]] = []

    for idx, model in enumerate(models[start:end], start=start):
        icon = "✅" if model == current_default else "⬜"
        keyboard.append(
            [InlineKeyboardButton(text=f"{icon} {model}", callback_data=f"default_model:set:{idx}")]
        )

    nav_row: list[InlineKeyboardButton] = []
    if page > 1:
        nav_row.append(
            InlineKeyboardButton(
                text=texts.BTN_PREV, callback_data=f"default_model:page:{page - 1}"
            )
        )
    if page < pages:
        nav_row.append(
            InlineKeyboardButton(
                text=texts.BTN_NEXT, callback_data=f"default_model:page:{page + 1}"
            )
        )
    if nav_row:
        keyboard.append(nav_row)

    keyboard.append([InlineKeyboardButton(text=texts.BTN_BACK, callback_data="default_model:back")])
    return InlineKeyboardMarkup(keyboard)


def _build_models_sort_menu(current_mode: str) -> InlineKeyboardMarkup:
    def _label(text: str, mode: str) -> str:
        return f"✅ {text}" if current_mode == mode else text

    keyboard = [
        [
            InlineKeyboardButton(
                text=_label(texts.BTN_SORT_CHEAP, "cheap"),
                callback_data="models:sort:set:cheap",
            )
        ],
        [
            InlineKeyboardButton(
                text=_label(texts.BTN_SORT_EXPENSIVE, "expensive"),
                callback_data="models:sort:set:expensive",
            )
        ],
        [
            InlineKeyboardButton(
                text=_label(texts.BTN_SORT_DEFAULT, "name"),
                callback_data="models:sort:set:default",
            )
        ],
        [InlineKeyboardButton(text=texts.BTN_BACK, callback_data="models:sort:back")],
    ]
    return InlineKeyboardMarkup(keyboard)


def _format_allowed_models(models: list[str], limit: int = 10) -> str:
    if not models:
        return "-"
    if len(models) <= limit:
        return ", ".join(models)
    return ", ".join(models[:limit]) + " ..."


def _format_model_price(price: float | None) -> str:
    if price is None:
        return ""
    return f" (~{price:g})"


def _format_sort_mode(mode: str) -> str:
    if mode == "cheap":
        return texts.BTN_SORT_CHEAP
    if mode == "expensive":
        return texts.BTN_SORT_EXPENSIVE
    return texts.BTN_SORT_DEFAULT


def _sort_models(models: list[ModelInfo], mode: str) -> list[ModelInfo]:
    if mode == "cheap":
        return sorted(
            models,
            key=lambda m: (m.price is None, m.price if m.price is not None else 0.0, m.model_id),
        )
    if mode == "expensive":
        return sorted(
            models,
            key=lambda m: (m.price is None, -(m.price or 0.0), m.model_id),
        )
    return sorted(models, key=lambda m: m.model_id)


async def _fetch_models_from_api(
    ai_client, config: ConfigStore
) -> list[ModelInfo]:
    if not config.data.api_key:
        raise UserVisibleError(texts.ADMIN_MODELS_API_KEY_MISSING)
    try:
        return await ai_client.list_models()
    except APIError:
        raise UserVisibleError(texts.ADMIN_MODELS_FETCH_FAILED) from None


async def _show_models_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    reference_id: str,
    *,
    refresh: bool = False,
) -> None:
    config: ConfigStore | None = context.application.bot_data.get("config")
    ai_client = context.application.bot_data.get("ai_client")
    if config is None or ai_client is None:
        raise RuntimeError("Config missing")

    if refresh or "models_cache" not in context.user_data:
        try:
            models = await _fetch_models_from_api(ai_client, config)
        except UserVisibleError as exc:
            await _send_panel_message(
                update,
                context,
                text=str(exc),
                reply_markup=_build_main_menu(),
                reference_id=reference_id,
            )
            return
        context.user_data["models_cache"] = models
        context.user_data["models_page"] = 1
    else:
        models = context.user_data.get("models_cache", [])

    selected = context.user_data.get("models_selected")
    if not isinstance(selected, set):
        selected = set(config.data.allowed_models)
        context.user_data["models_selected"] = selected

    sort_mode = context.user_data.get("models_sort", "name")
    if sort_mode not in {"name", "cheap", "expensive"}:
        sort_mode = "name"
        context.user_data["models_sort"] = sort_mode
    sorted_models = _sort_models(models, sort_mode)
    context.user_data["models_view_all"] = [m.model_id for m in sorted_models]

    query = context.user_data.get("models_query", "")
    query = query.strip()
    if query:
        filtered_models = [
            model for model in sorted_models if query.lower() in model.model_id.lower()
        ]
    else:
        filtered_models = sorted_models
    context.user_data["models_view"] = [m.model_id for m in filtered_models]

    if not models:
        await _send_panel_message(
            update,
            context,
            text="\n".join([texts.ADMIN_MODELS_TITLE, texts.ADMIN_MODELS_EMPTY]),
            reply_markup=_build_main_menu(),
            reference_id=reference_id,
        )
        return

    if query and not filtered_models:
        await _send_panel_message(
            update,
            context,
            text="\n".join(
                [
                    texts.ADMIN_MODELS_TITLE,
                    texts.ADMIN_MODELS_HINT,
                    texts.ADMIN_MODELS_SEARCH_ACTIVE.format(query=query),
                    texts.ADMIN_MODELS_SEARCH_EMPTY,
                ]
            ),
            reply_markup=_build_models_menu(
                [],
                selected,
                page=1,
                pages=1,
                default_model=config.data.default_model,
                search_active=True,
            ),
            reference_id=reference_id,
        )
        return

    pages = max(1, math.ceil(len(filtered_models) / MODELS_PAGE_SIZE))
    page = context.user_data.get("models_page", 1)
    page = max(1, min(page, pages))
    context.user_data["models_page"] = page

    lines = [
        texts.ADMIN_MODELS_TITLE,
        texts.ADMIN_MODELS_HINT,
        texts.ADMIN_MODELS_SELECTED.format(count=len(selected)),
        texts.ADMIN_MODELS_SORT.format(mode=_format_sort_mode(sort_mode)),
    ]
    if query:
        lines.append(texts.ADMIN_MODELS_SEARCH_ACTIVE.format(query=query))

    if config.data.allowed_models:
        lines.append(f"{texts.MODEL_ALLOWED_LIST.format(models=_format_allowed_models(config.data.allowed_models))}")

    await _send_panel_message(
        update,
        context,
        text="\n".join(lines),
        reply_markup=_build_models_menu(
            filtered_models,
            selected,
            page,
            pages,
            config.data.default_model,
            search_active=bool(query),
        ),
        reference_id=reference_id,
    )


async def _show_default_model_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    reference_id: str,
) -> None:
    config: ConfigStore | None = context.application.bot_data.get("config")
    if config is None:
        raise RuntimeError("Config missing")

    allowed = list(config.data.allowed_models)
    if not allowed:
        await _send_panel_message(
            update,
            context,
            text=texts.ADMIN_MODELS_DEFAULT_EMPTY,
            reply_markup=_build_main_menu(),
            reference_id=reference_id,
        )
        return

    page = context.user_data.get("default_models_page", 1)
    pages = max(1, math.ceil(len(allowed) / DEFAULT_MODELS_PAGE_SIZE))
    page = max(1, min(page, pages))
    context.user_data["default_models_page"] = page
    context.user_data["default_models_view"] = allowed

    await _send_panel_message(
        update,
        context,
        text="\n".join([texts.ADMIN_MODELS_DEFAULT_TITLE, texts.ADMIN_MODELS_DEFAULT_HINT]),
        reply_markup=_build_default_models_menu(
            allowed, config.data.default_model, page, pages
        ),
        reference_id=reference_id,
    )


async def _send_panel_message(
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

    await reply_text(
        update,
        text,
        context,
        reference_id=reference_id,
        reply_markup=reply_markup,
    )


def _log_admin_request(update: Update, context: ContextTypes.DEFAULT_TYPE, reference_id: str) -> None:
    config: ConfigStore | None = context.application.bot_data.get("config")
    if config is None or update.message is None:
        return
    log_incoming_message(
        update,
        reference_id=reference_id,
        anonymize=config.data.log_anonymize_user_ids,
        include_body=config.data.log_message_body,
        include_headers=config.data.log_message_headers,
    )


def _is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.effective_user is None:
        return False
    config: ConfigStore | None = context.application.bot_data.get("config")
    if config is None:
        return False
    return update.effective_user.id == config.data.admin_user_id


async def _show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, reference_id: str) -> None:
    config: ConfigStore | None = context.application.bot_data.get("config")
    if config is None:
        raise RuntimeError("Config missing")

    _set_sponsor_menu_active(context, False)
    snapshot = config.snapshot(masked=True)
    lines = [
        f"✦ {texts.ADMIN_MENU_TITLE}",
        "━━━━━━━━━━━━━━━━━━━━",
        texts.ADMIN_MENU_HINT,
        "",
        texts.ADMIN_SETTINGS_CURRENT,
    ]
    for spec in SETTINGS_SPECS:
        lines.append(f"- {spec.label}: {_format_value(snapshot.get(spec.key))}")

    await _send_panel_message(
        update,
        context,
        text="\n".join(lines),
        reply_markup=_build_main_menu(),
        reference_id=reference_id,
    )


async def _show_sponsor_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, reference_id: str) -> None:
    sponsor_service = context.application.bot_data.get("sponsor_service")
    if sponsor_service is None:
        raise RuntimeError("Sponsor service missing")

    _set_sponsor_menu_active(context, True)
    lines = [texts.ADMIN_SPONSOR_TITLE, texts.ADMIN_SPONSOR_HINT, ""]
    channels = sponsor_service.list_channels()
    if not channels:
        lines.append(texts.SPONSOR_LIST_EMPTY)
    else:
        lines.extend(f"- {channel.label}" for channel in channels)

    await _send_panel_message(
        update,
        context,
        text="\n".join(lines),
        reply_markup=_build_sponsor_menu(),
        reference_id=reference_id,
    )


async def _show_sponsor_select_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    reference_id: str,
    action: str,
) -> None:
    sponsor_service = context.application.bot_data.get("sponsor_service")
    if sponsor_service is None:
        raise RuntimeError("Sponsor service missing")

    channels = sponsor_service.list_channels()
    if not channels:
        await _show_sponsor_menu(update, context, reference_id)
        return

    prompt = (
        texts.ADMIN_PROMPT_SPONSOR_EDIT_SELECT
        if action == "edit"
        else texts.ADMIN_PROMPT_SPONSOR_REMOVE_SELECT
    )
    _set_sponsor_menu_active(context, False)
    await _send_panel_message(
        update,
        context,
        text="\n".join([texts.ADMIN_SPONSOR_TITLE, prompt]),
        reply_markup=_build_sponsor_select_menu(channels, action),
        reference_id=reference_id,
    )


async def _show_users_page(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    reference_id: str,
    page: int,
) -> None:
    db = context.application.bot_data.get("db")
    if db is None:
        raise RuntimeError("DB missing")
    _set_sponsor_menu_active(context, False)

    total = await db.get_user_count()
    if total == 0:
        await _send_panel_message(
            update,
            context,
            text="\n".join(
                [
                    texts.ADMIN_USERS_TITLE,
                    texts.ADMIN_USERS_TOTAL.format(count=0),
                    "",
                    texts.ADMIN_USERS_EMPTY,
                ]
            ),
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(text=texts.BTN_BACK, callback_data="users:back")]]
            ),
            reference_id=reference_id,
        )
        return

    pages = max(1, math.ceil(total / USERS_PAGE_SIZE))
    page = max(1, min(page, pages))
    offset = (page - 1) * USERS_PAGE_SIZE
    users = await db.list_users(limit=USERS_PAGE_SIZE, offset=offset)
    context.user_data["users_page"] = page

    lines = [
        texts.ADMIN_USERS_TITLE,
        texts.ADMIN_USERS_TOTAL.format(count=total),
        texts.ADMIN_USERS_PAGE.format(page=page, pages=pages),
        "",
    ]
    for user in users:
        lines.append(f"- {_format_user_label(user)}")
    lines.extend(["", texts.ADMIN_USERS_PROMPT])

    await _send_panel_message(
        update,
        context,
        text="\n".join(lines),
        reply_markup=_build_users_menu(users, page, pages),
        reference_id=reference_id,
    )


async def _show_user_details(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    reference_id: str,
    telegram_id: int,
) -> None:
    db = context.application.bot_data.get("db")
    if db is None:
        raise RuntimeError("DB missing")
    _set_sponsor_menu_active(context, False)

    user = await db.get_user_by_telegram_id(telegram_id)
    if user is None:
        await _send_panel_message(
            update,
            context,
            text=texts.ADMIN_USERS_NOT_FOUND,
            reply_markup=_build_user_detail_menu(telegram_id),
            reference_id=reference_id,
        )
        return

    first_name = user.get("first_name") or ""
    last_name = user.get("last_name") or ""
    full_name = " ".join(part for part in [first_name, last_name] if part) or "-"
    username = f"@{user['username']}" if user.get("username") else "-"

    lines = [
        texts.ADMIN_USER_DETAILS_TITLE,
        f"Telegram ID: {user.get('telegram_id', '-')}",
        f"Name: {full_name}",
        f"Username: {username}",
        f"Language: {user.get('language_code') or '-'}",
        f"Is bot: {'yes' if user.get('is_bot') else 'no'}",
        f"First seen: {_format_timestamp(user.get('first_seen'))}",
        f"Last seen: {_format_timestamp(user.get('last_seen'))}",
        f"Created at: {_format_timestamp(user.get('created_at'))}",
        f"Updated at: {_format_timestamp(user.get('updated_at'))}",
    ]

    await _send_panel_message(
        update,
        context,
        text="\n".join(lines),
        reply_markup=_build_user_detail_menu(telegram_id),
        reference_id=reference_id,
    )


async def _show_user_chats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    reference_id: str,
    *,
    telegram_id: int,
    page: int,
) -> None:
    db = context.application.bot_data.get("db")
    if db is None:
        raise RuntimeError("DB missing")

    total = await db.count_conversations(telegram_id=telegram_id, include_deleted=True)
    if total == 0:
        await _send_panel_message(
            update,
            context,
            text=texts.ADMIN_USER_CHATS_EMPTY,
            reply_markup=_build_user_detail_menu(telegram_id),
            reference_id=reference_id,
        )
        return

    pages = max(1, math.ceil(total / ADMIN_CHATS_PAGE_SIZE))
    page = max(1, min(page, pages))
    conversations = await db.list_conversations_with_last_message(
        telegram_id=telegram_id,
        include_deleted=True,
        limit=ADMIN_CHATS_PAGE_SIZE,
        offset=(page - 1) * ADMIN_CHATS_PAGE_SIZE,
    )

    lines = [
        texts.ADMIN_USER_CHATS_TITLE,
        texts.ADMIN_USER_CHATS_PAGE.format(page=page, pages=pages),
        texts.ADMIN_CHAT_USER.format(user_id=telegram_id),
        "",
    ]
    for convo in conversations:
        lines.append(f"- {_format_conversation_label(convo)}")

    await _send_panel_message(
        update,
        context,
        text="\n".join(lines),
        reply_markup=_build_user_chats_menu(
            conversations,
            telegram_id=telegram_id,
            page=page,
            pages=pages,
        ),
        reference_id=reference_id,
    )


async def _show_admin_chat_view(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    reference_id: str,
    *,
    conversation_id: int,
    page: int,
) -> None:
    db = context.application.bot_data.get("db")
    if db is None:
        raise RuntimeError("DB missing")

    convo = await db.get_conversation_by_id(conversation_id)
    if not convo:
        await _send_panel_message(
            update,
            context,
            text=texts.ADMIN_USERS_NOT_FOUND,
            reply_markup=_build_main_menu(),
            reference_id=reference_id,
        )
        return

    telegram_id = int(convo.get("telegram_id"))
    total = await db.count_messages(conversation_id=conversation_id)
    if total == 0:
        await _send_panel_message(
            update,
            context,
            text=texts.ADMIN_CHAT_EMPTY,
            reply_markup=_build_admin_chat_view_menu(
                telegram_id=telegram_id,
                conversation_id=conversation_id,
                page=1,
                pages=1,
            ),
            reference_id=reference_id,
        )
        return

    pages = max(1, math.ceil(total / ADMIN_CHAT_MESSAGES_PAGE_SIZE))
    page = max(1, min(page, pages))
    start = max(total - (page * ADMIN_CHAT_MESSAGES_PAGE_SIZE), 0)
    limit = min(ADMIN_CHAT_MESSAGES_PAGE_SIZE, total - start)
    messages = await db.list_messages(
        conversation_id=conversation_id,
        limit=limit,
        offset=start,
    )

    deleted_flag = texts.ADMIN_CHAT_DELETED if convo.get("deleted_at") else "-"
    lines = [
        texts.ADMIN_CHAT_TITLE.format(title=_format_conversation_title(convo)),
        texts.ADMIN_CHAT_PAGE.format(page=page, pages=pages),
        texts.ADMIN_CHAT_USER.format(user_id=telegram_id),
        f"{texts.ADMIN_CHAT_DELETED}: {deleted_flag}",
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
            lines.append(texts.ADMIN_CHAT_MODEL.format(model=model))
        lines.append(str(message.get("content", "")).strip())
        lines.append("")

    await _send_panel_message(
        update,
        context,
        text="\n".join(lines).strip(),
        reply_markup=_build_admin_chat_view_menu(
            telegram_id=telegram_id,
            conversation_id=conversation_id,
            page=page,
            pages=pages,
        ),
        reference_id=reference_id,
    )


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    reference_id = new_reference_id()
    _log_admin_request(update, context, reference_id)
    if not _is_admin(update, context):
        await reply_text(update, texts.NOT_AUTHORIZED, context, reference_id=reference_id)
        return ConversationHandler.END

    context.user_data.pop("config_pending", None)
    await _show_main_menu(update, context, reference_id)
    return ADMIN_MENU


async def handle_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query is None:
        return ConversationHandler.END

    reference_id = new_reference_id()
    if not _is_admin(update, context):
        await update.callback_query.answer(texts.NOT_AUTHORIZED, show_alert=True)
        return ConversationHandler.END

    await update.callback_query.answer()

    data = update.callback_query.data or ""
    if data == "cfg:close":
        context.user_data.pop("config_pending", None)
        _set_sponsor_menu_active(context, False)
        await _send_panel_message(
            update,
            context,
            text=texts.ADMIN_PANEL_CLOSED,
            reply_markup=None,
            reference_id=reference_id,
        )
        return ConversationHandler.END

    if data == "cfg:back":
        context.user_data.pop("config_pending", None)
        _set_sponsor_menu_active(context, False)
        await _show_main_menu(update, context, reference_id)
        return ADMIN_MENU

    if data == "sponsor:back":
        context.user_data.pop("config_pending", None)
        _set_sponsor_menu_active(context, False)
        await _show_main_menu(update, context, reference_id)
        return ADMIN_MENU

    if data == "sponsor:menu":
        context.user_data.pop("config_pending", None)
        await _show_sponsor_menu(update, context, reference_id)
        return ADMIN_MENU

    if data == "models:back":
        context.user_data.pop("config_pending", None)
        context.user_data.pop("models_page", None)
        await _show_main_menu(update, context, reference_id)
        return ADMIN_MENU

    if data == "models:sort":
        sort_mode = context.user_data.get("models_sort", "name")
        if sort_mode not in {"name", "cheap", "expensive"}:
            sort_mode = "name"
            context.user_data["models_sort"] = sort_mode
        await _send_panel_message(
            update,
            context,
            text="\n".join(
                [
                    texts.ADMIN_MODELS_SORT_MENU,
                    texts.ADMIN_MODELS_SORT.format(mode=_format_sort_mode(sort_mode)),
                ]
            ),
            reply_markup=_build_models_sort_menu(sort_mode),
            reference_id=reference_id,
        )
        return ADMIN_MENU

    if data == "models:sort:back":
        await _show_models_menu(update, context, reference_id)
        return ADMIN_MENU

    if data.startswith("models:sort:set:"):
        selected_mode = data.split(":", 3)[3]
        if selected_mode == "default":
            selected_mode = "name"
        if selected_mode in {"name", "cheap", "expensive"}:
            context.user_data["models_sort"] = selected_mode
        await _show_models_menu(update, context, reference_id)
        return ADMIN_MENU

    if data == "models:search":
        context.user_data["config_pending"] = {"type": "models_search"}
        await _send_panel_message(
            update,
            context,
            text=texts.ADMIN_MODELS_SEARCH_PROMPT,
            reply_markup=_build_cancel_menu(),
            reference_id=reference_id,
        )
        return WAITING_INPUT

    if data == "models:search:clear":
        context.user_data.pop("models_query", None)
        await _show_models_menu(update, context, reference_id)
        return ADMIN_MENU

    if data.startswith("models:page:"):
        try:
            page = int(data.split(":", 2)[2])
        except ValueError:
            return ADMIN_MENU
        context.user_data["models_page"] = page
        await _show_models_menu(update, context, reference_id)
        return ADMIN_MENU

    if data.startswith("models:toggle:"):
        config: ConfigStore | None = context.application.bot_data.get("config")
        db = context.application.bot_data.get("db")
        if config is None or db is None:
            raise RuntimeError("Config missing")
        try:
            idx = int(data.split(":", 2)[2])
        except ValueError:
            return ADMIN_MENU
        models_view = context.user_data.get("models_view", [])
        if not isinstance(models_view, list) or idx < 0 or idx >= len(models_view):
            return ADMIN_MENU
        selected = context.user_data.get("models_selected")
        if not isinstance(selected, set):
            selected = set()
        model_id = models_view[idx]
        if model_id in selected:
            selected.remove(model_id)
        else:
            selected.add(model_id)
        context.user_data["models_selected"] = selected

        models_view_all = context.user_data.get("models_view_all", [])
        if isinstance(selected, set) and isinstance(models_view_all, list):
            selected_list = [model for model in models_view_all if model in selected]
        else:
            selected_list = []
        raw_value = ",".join(selected_list) if selected_list else "unset"
        await _persist_setting(config, db, "ALLOWED_MODELS", raw_value)

        if selected_list and config.data.default_model not in selected_list:
            new_default = selected_list[0]
            await _persist_setting(config, db, "DEFAULT_MODEL", new_default)
        await _show_models_menu(update, context, reference_id)
        return ADMIN_MENU

    if data == "sponsor:add":
        context.user_data["config_pending"] = {"type": "sponsor_add"}
        _set_sponsor_menu_active(context, False)
        await _send_panel_message(
            update,
            context,
            text=texts.ADMIN_PROMPT_SPONSOR_ADD,
            reply_markup=_build_cancel_menu(),
            reference_id=reference_id,
        )
        return WAITING_INPUT

    if data == "sponsor:remove":
        context.user_data.pop("config_pending", None)
        await _show_sponsor_select_menu(update, context, reference_id, "remove")
        return ADMIN_MENU

    if data == "sponsor:edit":
        context.user_data.pop("config_pending", None)
        await _show_sponsor_select_menu(update, context, reference_id, "edit")
        return ADMIN_MENU

    if data.startswith("sponsor:remove:"):
        sponsor_service = context.application.bot_data.get("sponsor_service")
        config: ConfigStore | None = context.application.bot_data.get("config")
        db = context.application.bot_data.get("db")
        if sponsor_service is None or config is None or db is None:
            raise RuntimeError("Config missing")
        channel = data.split(":", 2)[2]
        try:
            sponsor_service.remove_channel(channel)
            await _sync_sponsor_channels(config, sponsor_service, db)
        except UserVisibleError as exc:
            await update.callback_query.answer(str(exc), show_alert=True)
            return ADMIN_MENU
        await _show_sponsor_menu(update, context, reference_id)
        return ADMIN_MENU

    if data.startswith("sponsor:edit:"):
        channel = data.split(":", 2)[2]
        context.user_data["config_pending"] = {"type": "sponsor_edit", "target": channel}
        _set_sponsor_menu_active(context, False)
        await _send_panel_message(
            update,
            context,
            text=texts.ADMIN_PROMPT_SPONSOR_EDIT,
            reply_markup=_build_cancel_menu(),
            reference_id=reference_id,
        )
        return WAITING_INPUT

    if data == "users:menu":
        context.user_data.pop("config_pending", None)
        await _show_users_page(update, context, reference_id, page=1)
        return ADMIN_MENU

    if data == "users:list":
        context.user_data.pop("config_pending", None)
        page = context.user_data.get("users_page", 1)
        await _show_users_page(update, context, reference_id, page=page)
        return ADMIN_MENU

    if data.startswith("users:chats:page:"):
        parts = data.split(":", 4)
        if len(parts) < 5:
            return ADMIN_MENU
        try:
            telegram_id = int(parts[3])
            page = int(parts[4])
        except ValueError:
            return ADMIN_MENU
        await _show_user_chats(update, context, reference_id, telegram_id=telegram_id, page=page)
        return ADMIN_MENU

    if data.startswith("users:chats:"):
        try:
            telegram_id = int(data.split(":", 2)[2])
        except ValueError:
            return ADMIN_MENU
        await _show_user_chats(update, context, reference_id, telegram_id=telegram_id, page=1)
        return ADMIN_MENU

    if data.startswith("users:chat:open:"):
        try:
            conversation_id = int(data.split(":", 3)[3])
        except ValueError:
            return ADMIN_MENU
        await _show_admin_chat_view(
            update,
            context,
            reference_id,
            conversation_id=conversation_id,
            page=1,
        )
        return ADMIN_MENU

    if data.startswith("users:chat:page:"):
        parts = data.split(":", 4)
        if len(parts) < 5:
            return ADMIN_MENU
        try:
            conversation_id = int(parts[3])
            page = int(parts[4])
        except ValueError:
            return ADMIN_MENU
        await _show_admin_chat_view(
            update,
            context,
            reference_id,
            conversation_id=conversation_id,
            page=page,
        )
        return ADMIN_MENU

    if data == "users:back":
        context.user_data.pop("config_pending", None)
        context.user_data.pop("users_page", None)
        await _show_main_menu(update, context, reference_id)
        return ADMIN_MENU

    if data == "default_model:back":
        context.user_data.pop("default_models_page", None)
        await _show_main_menu(update, context, reference_id)
        return ADMIN_MENU

    if data.startswith("default_model:page:"):
        try:
            page = int(data.split(":", 2)[2])
        except ValueError:
            return ADMIN_MENU
        context.user_data["default_models_page"] = page
        await _show_default_model_menu(update, context, reference_id)
        return ADMIN_MENU

    if data.startswith("default_model:set:"):
        config: ConfigStore | None = context.application.bot_data.get("config")
        db = context.application.bot_data.get("db")
        if config is None or db is None:
            raise RuntimeError("Config missing")
        try:
            idx = int(data.split(":", 2)[2])
        except ValueError:
            return ADMIN_MENU
        models_view = context.user_data.get("default_models_view", [])
        if not isinstance(models_view, list) or idx < 0 or idx >= len(models_view):
            return ADMIN_MENU
        model_id = models_view[idx]
        await _persist_setting(config, db, "DEFAULT_MODEL", model_id)
        await _show_default_model_menu(update, context, reference_id)
        return ADMIN_MENU

    if data.startswith("users:page:"):
        context.user_data.pop("config_pending", None)
        try:
            page = int(data.split(":", 2)[2])
        except ValueError:
            return ADMIN_MENU
        await _show_users_page(update, context, reference_id, page=page)
        return ADMIN_MENU

    if data.startswith("users:view:"):
        context.user_data.pop("config_pending", None)
        try:
            telegram_id = int(data.split(":", 2)[2])
        except ValueError:
            return ADMIN_MENU
        await _show_user_details(update, context, reference_id, telegram_id)
        return ADMIN_MENU

    if data.startswith("cfg:"):
        key = data.split(":", 1)[1]
        spec = next((item for item in SETTINGS_SPECS if item.key == key), None)
        if spec is None:
            await _send_panel_message(
                update,
                context,
                text=texts.CONFIG_INVALID_KEY,
                reply_markup=_build_main_menu(),
                reference_id=reference_id,
            )
            return ADMIN_MENU

        if spec.key == "SPONSOR_CHANNELS":
            await _show_sponsor_menu(update, context, reference_id)
            return ADMIN_MENU
        if spec.key == "ALLOWED_MODELS":
            await _show_models_menu(update, context, reference_id, refresh=True)
            return ADMIN_MENU
        if spec.key == "DEFAULT_MODEL":
            context.user_data.pop("config_pending", None)
            await _show_default_model_menu(update, context, reference_id)
            return ADMIN_MENU

        context.user_data["config_pending"] = {"key": spec.key}
        await _send_panel_message(
            update,
            context,
            text=_build_prompt(spec.label, spec.kind, spec.allowed, spec.optional),
            reply_markup=_build_cancel_menu(),
            reference_id=reference_id,
        )
        return WAITING_INPUT

    return ADMIN_MENU


async def handle_admin_menu_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return ADMIN_MENU

    reference_id = new_reference_id()
    config: ConfigStore | None = context.application.bot_data.get("config")
    sponsor_service = context.application.bot_data.get("sponsor_service")
    db = context.application.bot_data.get("db")
    if config is None or sponsor_service is None or db is None:
        raise RuntimeError("Config missing")

    log_incoming_message(
        update,
        reference_id=reference_id,
        anonymize=config.data.log_anonymize_user_ids,
        include_body=config.data.log_message_body,
        include_headers=config.data.log_message_headers,
    )

    if not _is_admin(update, context):
        await reply_text(update, texts.NOT_AUTHORIZED, context, reference_id=reference_id)
        return ConversationHandler.END

    if not context.user_data.get("sponsor_menu_active"):
        await reply_text(update, texts.ADMIN_USE_BUTTONS, context, reference_id=reference_id)
        return ADMIN_MENU

    raw_text = update.message.text.strip()
    if not raw_text:
        await reply_text(update, texts.SPONSOR_INVALID, context, reference_id=reference_id)
        return ADMIN_MENU

    try:
        _add_sponsor_channels(sponsor_service, raw_text)
        await _sync_sponsor_channels(config, sponsor_service, db)
    except UserVisibleError as exc:
        await reply_text(
            update,
            f"{str(exc)}\n{texts.ADMIN_PROMPT_SPONSOR_QUICK}",
            context,
            reference_id=reference_id,
        )
        await _show_sponsor_menu(update, context, new_reference_id())
        return ADMIN_MENU

    await reply_text(update, texts.CONFIG_UPDATED, context, reference_id=reference_id)
    await _show_sponsor_menu(update, context, new_reference_id())
    return ADMIN_MENU


async def handle_admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return ADMIN_MENU

    pending = context.user_data.get("config_pending")
    if not pending:
        return ADMIN_MENU

    reference_id = new_reference_id()
    config: ConfigStore | None = context.application.bot_data.get("config")
    ai_client = context.application.bot_data.get("ai_client")
    sponsor_service = context.application.bot_data.get("sponsor_service")
    db = context.application.bot_data.get("db")
    if config is None or ai_client is None or sponsor_service is None or db is None:
        raise RuntimeError("Config missing")

    settings = config.data
    include_body = settings.log_message_body
    if pending.get("key") == "API_KEY":
        include_body = False
    log_incoming_message(
        update,
        reference_id=reference_id,
        anonymize=settings.log_anonymize_user_ids,
        include_body=include_body,
        include_headers=settings.log_message_headers,
    )

    if not _is_admin(update, context):
        await reply_text(update, texts.NOT_AUTHORIZED, context, reference_id=reference_id)
        return ConversationHandler.END

    raw_text = update.message.text.strip()
    pending_type = pending.get("type")
    key = pending.get("key")
    if not key and pending_type not in {"sponsor_add", "sponsor_edit", "models_search"}:
        raise UserVisibleError(texts.CONFIG_INVALID_KEY)

    try:
        if pending_type == "models_search":
            if raw_text:
                context.user_data["models_query"] = raw_text
            else:
                context.user_data.pop("models_query", None)
            context.user_data["models_page"] = 1
            context.user_data.pop("config_pending", None)
            await _show_models_menu(update, context, reference_id)
            return ADMIN_MENU
        if pending_type in {"sponsor_add", "sponsor_edit"}:
            if pending_type == "sponsor_add":
                _add_sponsor_channels(sponsor_service, raw_text)
            else:
                target = pending.get("target")
                if not target:
                    raise UserVisibleError(texts.SPONSOR_NOT_FOUND)
                try:
                    new_channel = normalize_channel(raw_text)
                    target_channel = normalize_channel(target)
                except ValueError as exc:
                    raise UserVisibleError(texts.SPONSOR_INVALID) from exc
                existing = {channel.chat_id for channel in sponsor_service.list_channels()}
                if (
                    new_channel.chat_id in existing
                    and new_channel.chat_id != target_channel.chat_id
                ):
                    raise UserVisibleError(texts.SPONSOR_ALREADY_EXISTS)
                if new_channel.chat_id != target_channel.chat_id:
                    sponsor_service.remove_channel(target_channel.chat_id)
                    sponsor_service.add_channel(new_channel.raw)
            await _sync_sponsor_channels(config, sponsor_service, db)
        else:
            await _persist_setting(config, db, key, raw_text)
    except (ConfigValidationError, UserVisibleError) as exc:
        if pending_type in {"sponsor_add", "sponsor_edit"}:
            prompt = (
                texts.ADMIN_PROMPT_SPONSOR_ADD
                if pending_type == "sponsor_add"
                else texts.ADMIN_PROMPT_SPONSOR_EDIT
            )
        else:
            spec = next((item for item in SETTINGS_SPECS if item.key == key), None)
            prompt = _build_prompt(
                spec.label if spec else key,
                spec.kind if spec else "string",
                spec.allowed if spec else None,
                spec.optional if spec else False,
            )
        message = exc.message if isinstance(exc, ConfigValidationError) else str(exc)
        await reply_text(
            update,
            f"{message}\n{prompt}",
            context,
            reference_id=reference_id,
            reply_markup=_build_cancel_menu(),
        )
        return WAITING_INPUT

    # Apply runtime changes
    updated = config.data
    ai_client.update_settings(
        api_key=updated.api_key or "",
        base_url=updated.base_url,
        max_retries=updated.max_retries,
        retry_backoff=updated.retry_backoff,
    )

    if key in {"LOG_LEVEL", "LOG_FORMAT"}:
        setup_logging(updated.log_level, updated.log_format)

    context.user_data.pop("config_pending", None)
    await reply_text(update, texts.CONFIG_UPDATED, context, reference_id=reference_id)
    if pending_type in {"sponsor_add", "sponsor_edit"}:
        await _show_sponsor_menu(update, context, new_reference_id())
    else:
        await _show_main_menu(update, context, new_reference_id())
    return ADMIN_MENU
