"""
Logging configuration with colored terminal output.
Uses JSON in CI (GitHub Actions), colored text locally.
"""

import logging
import os
import sys

from pythonjsonlogger import jsonlogger


class ColorFormatter(logging.Formatter):
    """Colored log formatter for terminal output."""

    COLORS = {
        logging.DEBUG:    "\033[90m",       # gray
        logging.INFO:     "\033[36m",       # cyan
        logging.WARNING:  "\033[33m",       # yellow
        logging.ERROR:    "\033[31m",       # red
        logging.CRITICAL: "\033[1;31m",     # bold red
    }
    RESET = "\033[0m"
    BOLD = "\033[1m"

    def format(self, record):
        color = self.COLORS.get(record.levelno, self.RESET)
        level = record.levelname.ljust(5)
        name = f"\033[90m{record.name}\033[0m"
        msg = record.getMessage()

        # Highlight key numbers in the message
        if record.levelno == logging.INFO:
            msg = self._highlight_numbers(msg)

        return f"{color}{level}{self.RESET} {name} {msg}"

    @staticmethod
    def _highlight_numbers(msg: str) -> str:
        """Bold numbers that appear after = or as standalone counts."""
        import re
        # Bold numbers after = (e.g. Remotive=40)
        msg = re.sub(r'=(\d+)', lambda m: f'=\033[1m{m.group(1)}\033[0m', msg)
        return msg


def setup_logging(level: str = "INFO") -> None:
    """
    Configure logging. Uses colored text locally, JSON in CI.
    Call once at application startup.
    """
    handler = logging.StreamHandler(sys.stdout)

    # Use JSON in CI, colored text locally
    if os.getenv("CI") or os.getenv("GITHUB_ACTIONS"):
        formatter = jsonlogger.JsonFormatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%SZ",
        )
    else:
        formatter = ColorFormatter()

    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Quiet noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
