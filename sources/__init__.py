"""
Source registry — maps enabled source names to their fetch functions.

The bot is intentionally narrowed to quality-first monitoring:
- WUZZUF: primary Egypt source.
- LinkedIn: fresh public search cards only, limited and high-risk.

Old sources remain in the repository for reference/migration, but they are not
registered here and therefore will not run.
"""

try:  # final project layout: sources/__init__.py
    from sources.wuzzuf import fetch_wuzzuf
    from sources.linkedin import fetch_linkedin
except ModuleNotFoundError:  # local flat-file test layout
    from wuzzuf import fetch_wuzzuf
    from linkedin import fetch_linkedin

# (display_name, fetch_function)
ALL_FETCHERS = [
    ("WUZZUF", fetch_wuzzuf),
    ("LinkedIn", fetch_linkedin),
]

ENABLED_SOURCE_NAMES = tuple(name for name, _ in ALL_FETCHERS)
