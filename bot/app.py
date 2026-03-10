"""Bot application builder — wires handlers to python-telegram-bot."""

from __future__ import annotations

import time

from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from bot.handlers import callback_router, cmd_start, text_handler
from bot.service import WatchService
from core.scheduler import Scheduler


def create_bot(token: str, chat_id: str, watch_service: WatchService, scheduler: Scheduler):
    """Build and return a configured telegram Application."""
    app = ApplicationBuilder().token(token).build()

    app.bot_data["watch_service"] = watch_service
    app.bot_data["scheduler"] = scheduler
    app.bot_data["chat_id"] = chat_id
    app.bot_data["start_time"] = time.time()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    return app
