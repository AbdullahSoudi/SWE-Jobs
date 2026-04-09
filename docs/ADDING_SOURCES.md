# Adding a New Job Source

This guide walks through adding a new job source to SWE-Jobs.

## Step 1: Create the Source File

Create `sources/your_source.py`:

```python
"""YourSource — brief description of the API."""

import logging
from core.models import Job
from sources.http_utils import get_json

log = logging.getLogger(__name__)


def fetch_yoursource() -> list[Job]:
    """Fetch jobs from YourSource."""
    data = get_json("https://api.yoursource.com/jobs", params={"limit": 50})
    if not data:
        return []

    jobs = []
    for item in data.get("results", []):
        jobs.append(Job(
            title=item.get("title", ""),
            company=item.get("company", ""),
            location=item.get("location", ""),
            url=item.get("url", ""),
            source="yoursource",          # lowercase, unique key
            salary_raw=item.get("salary", ""),
            job_type=item.get("type", ""),
            tags=item.get("tags", []),
            is_remote=item.get("remote", False),
        ))

    log.info(f"YourSource: fetched {len(jobs)} jobs.")
    return jobs
```

### Key Rules

- **Return type** must be `list[Job]` — never raise exceptions, return `[]` on failure
- **`source` field** must be a unique lowercase string (used as the circuit breaker key)
- Use `get_json()` from `sources/http_utils.py` for HTTP requests — it handles timeouts, retries, and error logging
- Map the API response fields to the `Job` dataclass fields as completely as possible
- Set `is_remote=True` if the source only lists remote jobs

### Job Fields

| Field | Type | Description |
|-------|------|-------------|
| `title` | `str` | Job title (required) |
| `company` | `str` | Company name |
| `location` | `str` | Location text (used for country detection + geo-filter) |
| `url` | `str` | Application URL (required, used for dedup) |
| `source` | `str` | Source key, lowercase |
| `salary_raw` | `str` | Raw salary text (parsed by `salary_parser.py`) |
| `job_type` | `str` | e.g., "Full Time", "Contract", "Part Time" |
| `tags` | `list[str]` | Categories/skills from the source |
| `is_remote` | `bool` | Whether the job is remote |

You don't need to set `seniority`, `country`, `salary_min/max`, or `topics` — the enrichment pipeline handles those automatically.

### If the Source Requires an API Key

```python
import os

API_KEY = os.getenv("YOURSOURCE_API_KEY", "")


def fetch_yoursource() -> list[Job]:
    if not API_KEY:
        log.debug("YourSource: skipped (no API key)")
        return []

    data = get_json(
        "https://api.yoursource.com/jobs",
        headers={"Authorization": f"Bearer {API_KEY}"},
    )
    # ... rest of fetcher
```

Add the environment variable to `.env.example`:

```
YOURSOURCE_API_KEY=
```

## Step 2: Register the Source

Add your fetcher to `sources/__init__.py`:

```python
from sources.yoursource import fetch_yoursource

ALL_FETCHERS = [
    # ... existing sources ...
    ("YourSource", "yoursource", fetch_yoursource),
]
```

The tuple is `(display_name, source_key, fetch_function)`:
- **display_name** — shown in logs and stats
- **source_key** — must match the `source` field you set in the Job
- **fetch_function** — the function to call

## Step 3: Handle Geo-Filter (if applicable)

If the source only lists remote jobs, add it to the remote-only list in `core/geo.py`:

```python
REMOTE_ONLY_SOURCES = {"remotive", "remoteok", "wwr", ..., "yoursource"}
```

Remote-only sources automatically pass the geo-filter (no location check needed).

## Step 4: Add to GitHub Actions (if API key needed)

If your source requires an API key, add it to `.github/workflows/job_bot.yml`:

```yaml
env:
  # ... existing keys ...
  YOURSOURCE_API_KEY: ${{ secrets.YOURSOURCE_API_KEY }}
```

Then add the secret in **GitHub Settings > Secrets > Actions**.

## Step 5: Test

Run the bot locally and check the logs:

```bash
python main.py
```

You should see:
```
YourSource: fetched N jobs.
```

The circuit breaker will automatically track the health of your new source. If it fails 3 times consecutively, it will be temporarily disabled and recover on its own.

## Existing Source as Reference

`sources/remotive.py` is a clean, simple example to follow. For sources with multiple categories or pagination, see `sources/wwr.py` (multiple RSS feeds) or `sources/linkedin.py` (multiple search queries).

## Checklist

- [ ] Created `sources/your_source.py` with `fetch_yoursource()` returning `list[Job]`
- [ ] Returns `[]` on failure (never raises)
- [ ] Set unique `source` key (lowercase)
- [ ] Registered in `sources/__init__.py` `ALL_FETCHERS` list
- [ ] Added API key env var to `.env.example` (if needed)
- [ ] Added to `REMOTE_ONLY_SOURCES` in `core/geo.py` (if remote-only)
- [ ] Added secret to GitHub Actions workflow (if API key needed)
- [ ] Tested locally with `python main.py`
