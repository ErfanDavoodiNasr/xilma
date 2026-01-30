import asyncio
import logging
import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text(
            "Hi! I’m Xilma, a simple echo bot. Send me any text and I’ll echo it back."
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text(
            "Commands:\n/start — intro\n/help — this help\n/admin — admin check\nSend any text to echo."
        )


async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message and update.message.text:
        await update.message.reply_text(update.message.text)


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    if update.effective_user is None:
        await update.message.reply_text("Not authorized.")
        return

    admin_id = context.application.bot_data.get("ADMIN_USER_ID")
    if admin_id is None:
        await update.message.reply_text("Admin is not configured.")
        return

    if update.effective_user.id == admin_id:
        await update.message.reply_text("hi admin")
    else:
        await update.message.reply_text("Not authorized.")


def main() -> None:
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set")

    admin_user_id = os.getenv("ADMIN_USER_ID")
    if admin_user_id:
        try:
            admin_user_id_value = int(admin_user_id)
        except ValueError as exc:
            raise SystemExit("ADMIN_USER_ID must be an integer") from exc
    else:
        admin_user_id_value = None

    try:
        asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    app = ApplicationBuilder().token(token).build()
    app.bot_data["ADMIN_USER_ID"] = admin_user_id_value

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    app.run_polling()


if __name__ == "__main__":
    main()
