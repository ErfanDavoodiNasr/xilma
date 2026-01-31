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
from xilma.errors import UserVisibleError
from xilma.logging_setup import setup_logging
from xilma.services.sponsor import normalize_channel, parse_channels_csv
from xilma.utils import log_incoming_message, log_outgoing_message, new_reference_id, reply_text


ADMIN_MENU, WAITING_INPUT = range(2)
USERS_PAGE_SIZE = 10


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
    config.update(key, raw_value)
    value = getattr(config.data, spec.attr)
    db_value = serialize_setting_value(spec, value)
    await db.set_setting(key, db_value)


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


def _build_user_detail_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(text=texts.BTN_BACK, callback_data="users:list")]]
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
            reply_markup=_build_user_detail_menu(),
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
        reply_markup=_build_user_detail_menu(),
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

    if data == "cfg:sponsors":
        context.user_data.pop("config_pending", None)
        await _show_sponsor_menu(update, context, reference_id)
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

    if data == "users:back":
        context.user_data.pop("config_pending", None)
        context.user_data.pop("users_page", None)
        await _show_main_menu(update, context, reference_id)
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
    if not key and pending_type not in {"sponsor_add", "sponsor_edit"}:
        raise UserVisibleError(texts.CONFIG_INVALID_KEY)

    try:
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
