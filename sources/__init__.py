"""Source registry for production and shadow job feeds.

Production sources remain WUZZUF and LinkedIn. Saudi LinkedIn V2 and every ATS
company feed are shadow by default until measured data justifies promotion.
"""

try:  # final project layout: sources/__init__.py
    from sources.wuzzuf import fetch_wuzzuf
    from sources.linkedin import fetch_linkedin
    from sources.linkedin_saudi_v2 import fetch_linkedin_saudi_v2
except ModuleNotFoundError:  # local flat-file test layout
    from wuzzuf import fetch_wuzzuf
    from linkedin import fetch_linkedin
    from linkedin_saudi_v2 import fetch_linkedin_saudi_v2

from company_registry import build_ats_fetchers

CORE_FETCHERS = [
    ("WUZZUF", fetch_wuzzuf),
    ("LinkedIn", fetch_linkedin),
    ("LinkedIn Saudi V2", fetch_linkedin_saudi_v2),
]

ATS_FETCHERS = build_ats_fetchers()
ALL_FETCHERS = CORE_FETCHERS + ATS_FETCHERS
ENABLED_SOURCE_NAMES = tuple(name for name, _ in ALL_FETCHERS)
