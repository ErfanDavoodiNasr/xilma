from __future__ import annotations

import logging
from telegram import Update
from telegram.ext import ContextTypes

from xilma import texts
from xilma.errors import UserVisibleError
from xilma.utils import reply_text


logger = logging.getLogger("xilma.handlers.error")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err = context.error
    if isinstance(err, UserVisibleError):
        message = err.message
    else:
        message = texts.GENERIC_ERROR
        logger.exception("unhandled_error", exc_info=err)

    if isinstance(update, Update):
        try:
            await reply_text(update, message, context)
        except Exception as exc:  # noqa: BLE001
            logger.error("failed_to_send_error", extra={"error": str(exc)})
