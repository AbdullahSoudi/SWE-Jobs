"""
Source registry with circuit breaker integration.
"""

from sources.remotive import fetch_remotive
from sources.himalayas import fetch_himalayas
from sources.jobicy import fetch_jobicy
from sources.remoteok import fetch_remoteok
from sources.arbeitnow import fetch_arbeitnow
from sources.wwr import fetch_wwr
from sources.workingnomads import fetch_workingnomads
from sources.jsearch import fetch_jsearch
from sources.linkedin import fetch_linkedin
from sources.adzuna import fetch_adzuna
from sources.themuse import fetch_themuse
from sources.findwork import fetch_findwork
from sources.jooble import fetch_jooble
from sources.reed import fetch_reed
from sources.usajobs import fetch_usajobs
from sources.devitjobs import fetch_devitjobs
from sources.stackoverflow import fetch_stackoverflow
from sources.greenhouse import fetch_greenhouse
from sources.lever import fetch_lever
from sources.workable import fetch_workable
from sources.recruitee import fetch_recruitee
from sources.ashby import fetch_ashby
from sources.smartrecruiters import fetch_smartrecruiters

# (display_name, source_key, fetch_function)
ALL_FETCHERS = [
    ("Remotive",         "remotive",         fetch_remotive),
    ("Himalayas",        "himalayas",        fetch_himalayas),
    ("Jobicy",           "jobicy",           fetch_jobicy),
    ("RemoteOK",         "remoteok",         fetch_remoteok),
    ("Arbeitnow",        "arbeitnow",        fetch_arbeitnow),
    ("WWR",              "wwr",              fetch_wwr),
    ("Working Nomads",   "workingnomads",    fetch_workingnomads),
    ("JSearch",          "jsearch",          fetch_jsearch),
    ("LinkedIn",         "linkedin",         fetch_linkedin),
    ("Adzuna",           "adzuna",           fetch_adzuna),
    ("The Muse",         "themuse",          fetch_themuse),
    ("Findwork",         "findwork",         fetch_findwork),
    ("Jooble",           "jooble",           fetch_jooble),
    ("Reed",             "reed",             fetch_reed),
    ("USAJobs",          "usajobs",          fetch_usajobs),
    ("DevITjobs",        "devitjobs",        fetch_devitjobs),
    ("StackOverflow",    "stackoverflow",    fetch_stackoverflow),
    ("Greenhouse",       "greenhouse",       fetch_greenhouse),
    ("Lever",            "lever",            fetch_lever),
    ("Workable",         "workable",         fetch_workable),
    ("Recruitee",        "recruitee",        fetch_recruitee),
    ("Ashby",            "ashby",            fetch_ashby),
    ("SmartRecruiters",  "smartrecruiters",  fetch_smartrecruiters),
]
