"""
Telegram bot application setup.
Uses python-telegram-bot in polling mode with asyncio.
"""

import logging
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
)
from core.config import TELEGRAM_BOT_TOKEN

log = logging.getLogger(__name__)

_app: Application | None = None


def get_app() -> Application:
    """Get or create the bot Application singleton."""
    global _app
    if _app is None:
        if not TELEGRAM_BOT_TOKEN:
            raise RuntimeError("TELEGRAM_BOT_TOKEN not set")
        _app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        _register_handlers(_app)
        log.info("Telegram bot application created")
    return _app


def _register_handlers(app: Application) -> None:
    """Register all command and callback handlers."""
    from bot.commands import (
        cmd_start, cmd_help, cmd_subscribe, cmd_unsubscribe,
        cmd_mysubs, cmd_search, cmd_saved, cmd_stats, cmd_top,
        cmd_salary, cmd_applied, cmd_streak, cmd_blacklist,
    )
    from bot.callbacks import handle_callback

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("subscribe", cmd_subscribe))
    app.add_handler(CommandHandler("unsubscribe", cmd_unsubscribe))
    app.add_handler(CommandHandler("mysubs", cmd_mysubs))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(CommandHandler("saved", cmd_saved))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("top", cmd_top))
    app.add_handler(CommandHandler("salary", cmd_salary))
    app.add_handler(CommandHandler("applied", cmd_applied))
    app.add_handler(CommandHandler("streak", cmd_streak))
    app.add_handler(CommandHandler("blacklist", cmd_blacklist))

    # Callback queries (inline button presses)
    app.add_handler(CallbackQueryHandler(handle_callback))


async def start_polling() -> None:
    """Start the bot in polling mode."""
    app = get_app()
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    log.info("Bot polling started")


async def stop_polling() -> None:
    """Stop the bot gracefully."""
    if _app and _app.updater:
        await _app.updater.stop()
        await _app.stop()
        await _app.shutdown()
        log.info("Bot polling stopped")
