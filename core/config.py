"""
core/config.py — SWE-Jobs v2 configuration.

Loads environment variables for Supabase, Telegram, API keys, and misc
settings. This module is the sole place for env-var access in v2 code.

NOTE: The root-level config.py is NOT modified — it remains in use by
existing v1 source fetchers.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# =============================================================================
# Supabase / PostgreSQL
# =============================================================================

SUPABASE_DB_HOST: str = os.getenv("DB_HOST", "")
SUPABASE_DB_PORT: int = int(os.getenv("DB_PORT", "") or "6543")
SUPABASE_DB_NAME: str = os.getenv("DB_NAME", "postgres")
SUPABASE_DB_USER: str = os.getenv("DB_USER", "postgres")
SUPABASE_DB_PASSWORD: str = os.getenv("DB_PASSWORD", "")

# =============================================================================
# Telegram
# =============================================================================

TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_GROUP_ID: str = os.getenv("TELEGRAM_GROUP_ID", "")
TELEGRAM_SEND_DELAY: int = 3  # seconds between messages

# =============================================================================
# API Keys (all optional — sources are skipped if key is absent)
# =============================================================================

RAPIDAPI_KEY: str = os.getenv("RAPIDAPI_KEY", "")
ADZUNA_APP_ID: str = os.getenv("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY: str = os.getenv("ADZUNA_APP_KEY", "")
FINDWORK_API_KEY: str = os.getenv("FINDWORK_API_KEY", "")
JOOBLE_API_KEY: str = os.getenv("JOOBLE_API_KEY", "")
REED_API_KEY: str = os.getenv("REED_API_KEY", "")
MUSE_API_KEY: str = os.getenv("MUSE_API_KEY", "")

# =============================================================================
# Admin
# =============================================================================

ADMIN_TELEGRAM_ID: str = os.getenv("ADMIN_TELEGRAM_ID", "")

# =============================================================================
# Misc
# =============================================================================

MAX_JOBS_PER_RUN: int = 50       # safety cap per run
REQUEST_TIMEOUT: int = 15        # seconds for HTTP requests
SEED_MODE_ENV: str = "SEED_MODE" # env var name checked to force seed mode
SEEN_JOBS_FILE: str = "seen_jobs.json"
FETCH_INTERVAL_MINUTES: int = int(os.getenv("FETCH_INTERVAL_MINUTES", "5"))
