"""Shadow LinkedIn Saudi strategy used for measured comparison with production.

V2 deliberately starts simple: one country-level broad query (geoId) plus a
small ERP/business-systems gap-filler layer. Local classification decides what
is tech. The source is shadow-only until metrics justify promotion.
"""
from __future__ import annotations

import os

try:
    from sources.linkedin import fetch_linkedin, _fresh_params
except ModuleNotFoundError:
    from linkedin import fetch_linkedin, _fresh_params

SAUDI_GEO_ID = "100459316"
DEFAULT_MAX_PAGES = int(os.getenv("LINKEDIN_SAUDI_V2_MAX_PAGES", "2"))
DEFAULT_REQUEST_DELAY = float(os.getenv("LINKEDIN_SAUDI_V2_REQUEST_DELAY", os.getenv("LINKEDIN_REQUEST_DELAY", "4")))

# We intentionally do not hard-code LinkedIn's undocumented f_F job-function
# IDs yet. V2 measures a broad geoId strategy first; if request volume/noise is
# too high we can test f_F in shadow against the same classifier dataset.
SAUDI_V2_SEARCHES = [
    _fresh_params(geoId=SAUDI_GEO_ID, location="Saudi Arabia"),
    _fresh_params(keywords="SAP OR ERP", geoId=SAUDI_GEO_ID, location="Saudi Arabia"),
    _fresh_params(keywords="Oracle OR Odoo", geoId=SAUDI_GEO_ID, location="Saudi Arabia"),
    _fresh_params(keywords="Dynamics 365 OR Salesforce", geoId=SAUDI_GEO_ID, location="Saudi Arabia"),
]


def fetch_linkedin_saudi_v2(
    searches=None,
    max_pages_per_search: int = DEFAULT_MAX_PAGES,
    request_delay: float = DEFAULT_REQUEST_DELAY,
    http_getter=None,
):
    jobs = fetch_linkedin(
        searches=searches or SAUDI_V2_SEARCHES,
        max_pages_per_search=max_pages_per_search,
        request_delay=request_delay,
        http_getter=http_getter,
    )
    for job in jobs:
        job.source = "linkedin_saudi_v2"
        if not job.original_source:
            job.original_source = "LinkedIn"
    return jobs
