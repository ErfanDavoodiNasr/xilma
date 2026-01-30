from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from xilma import texts
from xilma.errors import UserVisibleError
from xilma.handlers.common import is_admin
from xilma.utils import reply_text


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update, context):
        await reply_text(update, texts.NOT_AUTHORIZED, context)
        return
    await reply_text(update, texts.ADMIN_PANEL, context)


async def list_sponsors(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update, context):
        await reply_text(update, texts.NOT_AUTHORIZED, context)
        return

    sponsor_service = context.application.bot_data.get("sponsor_service")
    if sponsor_service is None:
        raise RuntimeError("Sponsor service missing")

    channels = sponsor_service.list_channels()
    if not channels:
        await reply_text(update, texts.SPONSOR_LIST_EMPTY, context)
        return

    lines = [texts.SPONSOR_LIST_TITLE]
    lines.extend(f"- {channel.label}" for channel in channels)
    await reply_text(update, "\n".join(lines), context)


async def add_sponsor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update, context):
        await reply_text(update, texts.NOT_AUTHORIZED, context)
        return

    if not context.args:
        raise UserVisibleError(texts.SPONSOR_INVALID)

    sponsor_service = context.application.bot_data.get("sponsor_service")
    if sponsor_service is None:
        raise RuntimeError("Sponsor service missing")

    sponsor_service.add_channel(context.args[0])
    await reply_text(update, texts.SPONSOR_ADDED, context)


async def remove_sponsor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update, context):
        await reply_text(update, texts.NOT_AUTHORIZED, context)
        return

    if not context.args:
        raise UserVisibleError(texts.SPONSOR_INVALID)

    sponsor_service = context.application.bot_data.get("sponsor_service")
    if sponsor_service is None:
        raise RuntimeError("Sponsor service missing")

    sponsor_service.remove_channel(context.args[0])
    await reply_text(update, texts.SPONSOR_REMOVED, context)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update, context):
        await reply_text(update, texts.NOT_AUTHORIZED, context)
        return

    settings = context.application.bot_data.get("settings")
    sponsor_service = context.application.bot_data.get("sponsor_service")
    if settings is None or sponsor_service is None:
        raise RuntimeError("App not configured")

    lines = [
        texts.ADMIN_STATUS_TITLE,
        f"- ارائه‌دهنده پیش‌فرض: {settings.default_provider}",
        f"- مدل پیش‌فرض: {settings.default_model}",
        f"- کانال‌های حامی: {len(sponsor_service.list_channels())}",
    ]

    if settings.fallback_provider or settings.fallback_model:
        lines.append(
            f"- فال‌بک: {settings.fallback_provider or settings.default_provider} / "
            f"{settings.fallback_model or settings.default_model}"
        )
    await reply_text(update, "\n".join(lines), context)
