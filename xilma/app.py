from __future__ import annotations

import asyncio
import logging

from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from dotenv import load_dotenv

from xilma.config import (
    apply_env_overrides,
    build_config_store,
    default_settings_raw,
    load_env_credentials,
)
from xilma.db import Database, load_database_url
from xilma.handlers import admin as admin_handlers
from xilma.handlers import errors as error_handlers
from xilma.handlers import user as user_handlers
from xilma.logging_setup import setup_logging
from xilma.ai_client import AIClient
from xilma.services.sponsor import SponsorService


logger = logging.getLogger("xilma.app")


async def _on_startup(app: Application) -> None:
    ai_client = app.bot_data.get("ai_client")
    if ai_client:
        await ai_client.start()
    logger.info("bot_started")


async def _on_shutdown(app: Application) -> None:
    ai_client = app.bot_data.get("ai_client")
    if ai_client:
        await ai_client.close()
    db = app.bot_data.get("db")
    if db:
        await db.close()
    logger.info("bot_stopped")


def build_application() -> Application:
    load_dotenv()
    database_url = load_database_url()
    bot_token, admin_user_id = load_env_credentials()
    db = Database(database_url)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(db.migrate())
    defaults = default_settings_raw()
    loop.run_until_complete(db.ensure_settings_defaults(defaults))
    settings = loop.run_until_complete(db.fetch_settings())
    settings, env_updates = apply_env_overrides(settings=settings, defaults=defaults)
    for key, value in env_updates.items():
        loop.run_until_complete(db.set_setting(key, value))
    config_store = build_config_store(
        telegram_bot_token=bot_token,
        admin_user_id=admin_user_id,
        settings=settings,
    )
    setup_logging(config_store.data.log_level, config_store.data.log_format)

    ai_client = AIClient(
        api_key=config_store.data.api_key or "",
        base_url=config_store.data.base_url,
        timeout=30.0,
        max_retries=config_store.data.max_retries,
        retry_backoff=config_store.data.retry_backoff,
    )

    application = (
        ApplicationBuilder()
        .token(config_store.data.telegram_bot_token)
        .post_init(_on_startup)
        .post_shutdown(_on_shutdown)
        .build()
    )

    sponsor_service = SponsorService(config_store.data.sponsor_channels)

    application.bot_data["config"] = config_store
    application.bot_data["ai_client"] = ai_client
    application.bot_data["sponsor_service"] = sponsor_service
    application.bot_data["db"] = db

    admin_conversation = ConversationHandler(
        entry_points=[CommandHandler("admin", admin_handlers.admin_panel)],
        states={
            admin_handlers.ADMIN_MENU: [
                CallbackQueryHandler(
                    admin_handlers.handle_admin_callback, pattern="^(cfg|sponsor):"
                ),
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_handlers.handle_admin_menu_text),
            ],
            admin_handlers.WAITING_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_handlers.handle_admin_input),
                CallbackQueryHandler(
                    admin_handlers.handle_admin_callback, pattern="^(cfg|sponsor):"
                ),
            ],
        },
        fallbacks=[CommandHandler("admin", admin_handlers.admin_panel)],
        name="admin_panel",
        persistent=False,
    )
    application.add_handler(admin_conversation)

    application.add_handler(CommandHandler("start", user_handlers.start))
    application.add_handler(CommandHandler("help", user_handlers.help_command))
    application.add_handler(CommandHandler("new", user_handlers.new_chat))
    application.add_handler(CommandHandler("model", user_handlers.set_model))

    application.add_handler(
        CallbackQueryHandler(user_handlers.check_membership, pattern="^check_membership$")
    )

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, user_handlers.chat))
    application.add_handler(MessageHandler(~filters.TEXT & ~filters.COMMAND, user_handlers.unsupported))

    application.add_error_handler(error_handlers.error_handler)

    return application


def run() -> None:
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    app = build_application()
    app.run_polling()
