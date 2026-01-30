from __future__ import annotations

import hashlib
from telegram import Update
from telegram.ext import ContextTypes


def anonymize_user_id(user_id: int) -> str:
    digest = hashlib.sha256(str(user_id).encode("utf-8")).hexdigest()
    return digest[:10]


async def reply_text(
    update: Update,
    text: str,
    context: ContextTypes.DEFAULT_TYPE | None = None,
    **kwargs,
) -> None:
    if update.message:
        await update.message.reply_text(text, **kwargs)
        return
    if update.callback_query and update.callback_query.message:
        await update.callback_query.message.reply_text(text, **kwargs)
        return

    if context and update.effective_chat:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text, **kwargs)
