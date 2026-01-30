from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from xilma import texts
from xilma.utils import reply_text


def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.effective_user is None:
        return False
    settings = context.application.bot_data.get("settings")
    if settings is None:
        return False
    return update.effective_user.id in settings.admin_user_ids


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


async def ensure_sponsor_membership(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    reference_id: str | None = None,
) -> bool:
    if is_admin(update, context):
        return True

    if update.effective_user is None:
        return False

    sponsor_service = context.application.bot_data.get("sponsor_service")
    if sponsor_service is None:
        return True

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
