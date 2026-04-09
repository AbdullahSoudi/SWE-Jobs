"""
FastAPI server + Telegram bot polling entry point.
Both run in the same asyncio event loop.
"""

import asyncio
import logging
import uvicorn

from core.logging_config import setup_logging
from api.app import create_app

setup_logging()
log = logging.getLogger(__name__)

app = create_app()


@app.on_event("startup")
async def startup():
    """Start the Telegram bot polling alongside FastAPI."""
    try:
        from bot.app import start_polling
        asyncio.create_task(start_polling())
        log.info("Bot polling started alongside FastAPI")
    except Exception as e:
        log.warning(f"Bot polling failed to start: {e} (API still running)")


@app.on_event("shutdown")
async def shutdown():
    """Stop bot and close DB pool."""
    try:
        from bot.app import stop_polling
        await stop_polling()
    except Exception:
        pass
    try:
        from core.db import close_pool
        close_pool()
    except Exception:
        pass


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
