"""
FastAPI server + Telegram bot polling + scheduled job fetcher.
All run in the same asyncio event loop.
"""

import asyncio
import logging
import uvicorn

from core.logging_config import setup_logging
from api.app import create_app
from core.config import FETCH_INTERVAL_MINUTES

setup_logging()
log = logging.getLogger(__name__)

app = create_app()

_scheduler_task: asyncio.Task | None = None


async def _job_fetch_loop():
    """Run the main fetch-and-send pipeline on a fixed interval."""
    from main import main as run_pipeline

    interval = FETCH_INTERVAL_MINUTES * 60
    log.info(f"Job scheduler started — running every {FETCH_INTERVAL_MINUTES} min")

    # Run immediately on first startup, then repeat
    while True:
        try:
            log.info("Scheduler: starting job fetch run…")
            await run_pipeline()
            log.info("Scheduler: run complete")
        except Exception:
            log.exception("Scheduler: run failed (will retry next interval)")
        await asyncio.sleep(interval)


@app.on_event("startup")
async def startup():
    """Start bot polling and the job scheduler alongside FastAPI."""
    global _scheduler_task

    # Start Telegram bot polling
    try:
        from bot.app import start_polling
        asyncio.create_task(start_polling())
        log.info("Bot polling started alongside FastAPI")
    except Exception as e:
        log.warning(f"Bot polling failed to start: {e} (API still running)")

    # Start the periodic job fetcher
    _scheduler_task = asyncio.create_task(_job_fetch_loop())
    log.info("Job fetch scheduler started alongside FastAPI")


@app.on_event("shutdown")
async def shutdown():
    """Stop scheduler, bot, and close DB pool."""
    # Cancel the scheduler
    if _scheduler_task and not _scheduler_task.done():
        _scheduler_task.cancel()
        try:
            await _scheduler_task
        except asyncio.CancelledError:
            pass
        log.info("Job fetch scheduler stopped")

    # Stop bot
    try:
        from bot.app import stop_polling
        await stop_polling()
    except Exception:
        pass

    # Close DB pool
    try:
        from core.db import close_pool
        close_pool()
    except Exception:
        pass


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
