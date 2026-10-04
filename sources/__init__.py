"""Source registry for production and shadow job feeds.

Production sources remain WUZZUF and LinkedIn. Saudi LinkedIn V2 and every ATS
company feed are shadow by default until measured data justifies promotion.
"""

try:  # final project layout: sources/__init__.py
    from sources.wuzzuf import fetch_wuzzuf
    from sources.linkedin import fetch_linkedin
    from sources.linkedin_saudi_v2 import fetch_linkedin_saudi_v2
    from sources.jobzaty import fetch_jobzaty
except ModuleNotFoundError:  # local flat-file test layout
    from wuzzuf import fetch_wuzzuf
    from linkedin import fetch_linkedin
    from linkedin_saudi_v2 import fetch_linkedin_saudi_v2
    from jobzaty import fetch_jobzaty

from company_registry import build_ats_fetchers, build_ats_poll_intervals

CORE_FETCHERS = [
    ("WUZZUF", fetch_wuzzuf),
    ("LinkedIn", fetch_linkedin),
    ("LinkedIn Saudi V2", fetch_linkedin_saudi_v2),
]

SHADOW_BOARD_FETCHERS = [("Jobzaty", fetch_jobzaty)]
ATS_FETCHERS = build_ats_fetchers()
ALL_FETCHERS = CORE_FETCHERS + SHADOW_BOARD_FETCHERS + ATS_FETCHERS

SOURCE_POLL_INTERVAL_MINUTES = {
    "wuzzuf": 15,
    "linkedin": 15,
    "linkedin_saudi_v2": 15,
    "jobzaty": 60,
    **build_ats_poll_intervals(),
}
ENABLED_SOURCE_NAMES = tuple(name for name, _ in ALL_FETCHERS)
