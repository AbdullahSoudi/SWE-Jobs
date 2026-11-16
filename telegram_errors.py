"""Credential-safe diagnostics for Telegram requests."""
import re


def transport_error(exc: Exception) -> str:
    # Requests exceptions can include the complete token-bearing URL. Keep only
    # the class, never arbitrary exception text (including nested exceptions).
    return f"{type(exc).__name__}: Telegram transport failed"


def redact_telegram_error(text: str, bot_token: str) -> str:
    if bot_token:
        text = text.replace(bot_token, "[REDACTED]")
    return re.sub(r"(/bot)[^/\s\"'<>]+", r"\1[REDACTED]", text, flags=re.IGNORECASE)
