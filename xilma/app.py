from __future__ import annotations

import asyncio
import logging

from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from xilma.config import load_settings
from xilma.handlers import admin as admin_handlers
from xilma.handlers import errors as error_handlers
from xilma.handlers import user as user_handlers
from xilma.logging_setup import setup_logging
from xilma.llm_client import LLMClient
from xilma.providers.avalai import AvalAIProvider
from xilma.services.sponsor import SponsorService


logger = logging.getLogger("xilma.app")


async def _on_startup(app: Application) -> None:
    llm_client = app.bot_data.get("llm_client")
    if llm_client:
        await llm_client.start()
    logger.info("bot_started")


async def _on_shutdown(app: Application) -> None:
    llm_client = app.bot_data.get("llm_client")
    if llm_client:
        await llm_client.close()
    logger.info("bot_stopped")


def build_application() -> Application:
    settings = load_settings()
    setup_logging(settings.log_level, settings.log_format)

    sponsor_service = SponsorService(
        storage_path=settings.sponsor_channels_file,
        initial_channels=settings.sponsor_channels,
    )

    providers = {
        "avalai": AvalAIProvider(
            api_key=settings.avalai_api_key,
            base_url=settings.avalai_base_url,
            timeout=settings.request_timeout,
            max_retries=settings.max_retries,
            retry_backoff=settings.retry_backoff,
        )
    }

    llm_client = LLMClient(
        providers=providers,
        default_provider=settings.default_provider,
        default_model=settings.default_model,
        fallback_provider=settings.fallback_provider,
        fallback_model=settings.fallback_model,
    )

    application = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .post_init(_on_startup)
        .post_shutdown(_on_shutdown)
        .build()
    )

    application.bot_data["settings"] = settings
    application.bot_data["sponsor_service"] = sponsor_service
    application.bot_data["llm_client"] = llm_client

    application.add_handler(CommandHandler("start", user_handlers.start))
    application.add_handler(CommandHandler("help", user_handlers.help_command))
    application.add_handler(CommandHandler("new", user_handlers.new_chat))
    application.add_handler(CommandHandler("model", user_handlers.set_model))

    application.add_handler(CommandHandler("admin", admin_handlers.admin_panel))
    application.add_handler(CommandHandler("status", admin_handlers.status))
    application.add_handler(CommandHandler("sponsors", admin_handlers.list_sponsors))
    application.add_handler(CommandHandler("sponsor_add", admin_handlers.add_sponsor))
    application.add_handler(CommandHandler("sponsor_remove", admin_handlers.remove_sponsor))

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
