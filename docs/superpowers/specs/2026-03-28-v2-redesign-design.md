# SWE-Jobs v2 Redesign — Design Spec

**Date:** 2026-03-28
**Scope:** Quality improvements, interactive Telegram bot, web dashboard, operational reliability
**Stack:** PostgreSQL (Supabase) + FastAPI + React + python-telegram-bot
**Approach:** Clean slate rebuild on the same project

---

## 1. Database Schema (PostgreSQL on Supabase)

### 1.1 `jobs` table

The core table. Every fetched job lands here, replacing `seen_jobs.json`.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `SERIAL PK` | |
| `unique_id` | `TEXT UNIQUE` | Normalized URL or title+company hash |
| `title` | `TEXT NOT NULL` | |
| `company` | `TEXT` | |
| `location` | `TEXT` | |
| `url` | `TEXT NOT NULL` | |
| `source` | `TEXT` | remotive, linkedin, etc. |
| `original_source` | `TEXT` | For aggregators like JSearch |
| `salary_raw` | `TEXT` | Original salary string |
| `salary_min` | `INTEGER` | Parsed min (USD/year normalized) |
| `salary_max` | `INTEGER` | Parsed max |
| `salary_currency` | `TEXT` | USD, EUR, EGP, SAR, etc. |
| `job_type` | `TEXT` | full-time, contract, part-time |
| `seniority` | `TEXT` | intern, junior, mid, senior, lead, executive |
| `is_remote` | `BOOLEAN` | |
| `country` | `TEXT` | Detected country |
| `tags` | `TEXT[]` | Array of tags/skills |
| `topics` | `TEXT[]` | Routed topics: backend, frontend, etc. |
| `created_at` | `TIMESTAMPTZ` | When we first saw it |
| `sent_at` | `TIMESTAMPTZ` | When sent to Telegram (null if unsent) |
| `telegram_message_ids` | `JSONB` | `{topic_key: message_id}` for button callbacks |

**Indexes:**

- `pg_trgm` GIN index on `title` for fuzzy dedup and full-text search
- GIN index on `tags` and `topics` for array lookups
- B-tree on `created_at`, `source`, `seniority`, `salary_min`

### 1.2 `users` table

Telegram users who interact with the bot.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `SERIAL PK` | |
| `telegram_id` | `BIGINT UNIQUE` | |
| `username` | `TEXT` | |
| `subscriptions` | `JSONB` | `{"topics": ["backend"], "keywords": ["python"], "seniority": ["senior"], "min_salary": 50000}` |
| `saved_jobs` | `INTEGER[]` | Array of job IDs |
| `notify_dm` | `BOOLEAN DEFAULT true` | |
| `created_at` | `TIMESTAMPTZ` | |

### 1.3 `bot_runs` table

Operational tracking. One row per cron run.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `SERIAL PK` | |
| `started_at` | `TIMESTAMPTZ` | |
| `finished_at` | `TIMESTAMPTZ` | |
| `jobs_fetched` | `INTEGER` | Total raw |
| `jobs_filtered` | `INTEGER` | After keyword+geo filter |
| `jobs_new` | `INTEGER` | After dedup |
| `jobs_sent` | `INTEGER` | Successfully sent to Telegram |
| `source_stats` | `JSONB` | `{"remotive": 45, "linkedin": 12, ...}` |
| `errors` | `JSONB` | `[{"source": "adzuna", "error": "timeout"}]` |

---

## 2. Quality Improvements

### 2.1 Weighted Keyword Scoring

Replace the current boolean contains-match with a scoring system.

- **Exact title match** (whole word boundary): +10 points
- **Tag/skill match**: +8 points
- **Partial match** (substring): +3 points
- **Exclude match**: -20 points (instant reject)
- **Threshold**: job must score >= 10 to pass

A partial match alone won't pass. This eliminates "Sales Engineer" matching "engineer" while keeping real engineering jobs.

### 2.2 Fuzzy Deduplication

Three-layer dedup replacing the current URL-only check:

1. **Exact URL match** — normalized URL comparison (same as today)
2. **Title + Company similarity** — `pg_trgm`: if `similarity(title_a, title_b) > 0.7` AND same company, it's a duplicate
3. **Batch window** — only compare against jobs from the last 7 days

When a fuzzy duplicate is found, keep the version with more data (salary, tags, etc.) and discard the other.

### 2.3 Salary Extraction & Normalization

A `salary_parser` module that handles common formats:

- `"$80,000 - $120,000"` -> min=80000, max=120000, currency=USD
- `"EUR 50k-70k"` -> min=50000, max=70000, currency=EUR
- `"GBP 45,000/year"` -> min=45000, max=45000, currency=GBP
- `"EGP 15,000 - 25,000/month"` -> normalized to yearly (x12)
- Hourly rates -> yearly (x2080)

Stores `salary_raw` (original) + parsed `salary_min`/`salary_max`/`salary_currency`. Unparseable salaries get null values, no guessing.

### 2.4 Seniority Detection

Pattern-based detection from job title:

| Seniority | Patterns |
|-----------|----------|
| `intern` | intern, internship, trainee, co-op |
| `junior` | junior, jr, entry level, fresh grad, associate |
| `mid` | mid-level, intermediate, or no seniority indicator (default) |
| `senior` | senior, sr, experienced |
| `lead` | lead, principal, staff, architect |
| `executive` | cto, vp engineering, head of, director |

---

## 3. Interactive Telegram Bot

### 3.1 Inline Buttons on Every Job Post

Each message gets a button row:

```
[Save] [Share] [Similar] [Not Relevant]
```

- **Save** — adds to user's `saved_jobs`, confirms via DM
- **Share** — generates a clean shareable text to forward
- **Similar** — DMs 3-5 similar jobs (by tags + seniority + salary, using `pg_trgm` on title)
- **Not Relevant** — feedback signal stored in DB for future scoring weight adjustments

### 3.2 Bot Commands

| Command | What it does |
|---------|-------------|
| `/subscribe backend python senior` | Subscribe to DM alerts matching filters |
| `/unsubscribe` | Remove all subscriptions |
| `/mysubs` | Show current subscription filters |
| `/search react remote 80k+` | Search stored jobs with filters |
| `/saved` | List saved jobs |
| `/stats` | Bot stats: jobs today, top sources, top skills |
| `/top` | Top 10 jobs this week by engagement |
| `/salary python remote` | Salary ranges for matching jobs |
| `/help` | List all commands |

### 3.3 Personalized DM Alerts

When a new job matches a user's subscription:

1. Bot sends DM with full job post + inline buttons
2. Respects `notify_dm` toggle
3. Rate limit: max 20 DMs per user per hour
4. Matches against: `topics`, `keywords`, `seniority`, `min_salary`

### 3.4 Bot Architecture

- `python-telegram-bot` library, async, webhook mode
- FastAPI receives webhook callbacks at `/webhook/telegram`
- Button callback queries handled by the same webhook endpoint
- Runs on Render/Railway alongside the dashboard API

---

## 4. Web Dashboard

### 4.1 Pages

| Page | Content |
|------|---------|
| **Home** | Live job feed with filters (topic, seniority, salary range, remote/onsite, country). Paginated, 20/page. |
| **Stats** | Total jobs (today/week/all), jobs by source (bar chart), jobs by topic (pie chart), jobs over time (line chart), top 10 hiring companies |
| **Salary Insights** | Average salary by role, seniority, country. Filterable. Only shows parseable salary data. |
| **Trends** | Most demanded skills this week vs last, rising/falling keywords, new companies |

### 4.2 Tech Stack

- **Frontend:** React + Tailwind CSS, static SPA
- **Hosting:** GitHub Pages (free), deployed via GitHub Actions on push
- **Data:** Supabase auto-generated REST API (PostgREST)
- **Charts:** Recharts

### 4.3 Data Access

Dashboard reads from Supabase REST API with Row Level Security:

- `GET /rest/v1/jobs?order=created_at.desc&limit=20` — job feed
- `GET /rest/v1/jobs?topics=cs.{backend}&seniority=eq.senior` — filtered
- `GET /rest/v1/bot_runs?order=started_at.desc&limit=30` — run history

RLS: read-only via `anon` key. Writes restricted to `service_role` key (bot only).

### 4.4 Custom FastAPI Endpoints

For complex aggregations:

| Endpoint | Purpose |
|----------|---------|
| `GET /api/stats/summary` | Aggregated stats for home page |
| `GET /api/stats/salary?role=backend&country=egypt` | Salary breakdown |
| `GET /api/stats/trends?period=7d` | Skill trends with week-over-week delta |
| `GET /api/jobs/search?q=python&min_salary=50000` | Full-text search + salary filter |

---

## 5. Operational Reliability

### 5.1 Per-Source Error Handling & Retry

- **Retry with backoff** — 2 retries per source, 2s/5s delays
- **Circuit breaker** — 3 consecutive failures -> skip for 6 runs (30 min), then retry
- **Per-source timeout** — configurable, default 15s
- **Partial success** — failed sources never block others

### 5.2 Run Monitoring & Alerts

Powered by `bot_runs` table:

- **Admin alert channel** — separate private Telegram topic or admin DM
- **Alert triggers:**
  - Run fetched 0 jobs (all sources failed)
  - Source circuit-broken
  - Run took > 5 minutes
  - `jobs` count dropped (data corruption)
  - Telegram send success rate < 80%
- **Daily digest** — summary at midnight: jobs sent, source health, error count

### 5.3 Data Integrity

- **Database backups** — Supabase free tier: daily backups, 7-day retention
- **Idempotent runs** — crashed run resumes via `sent_at` column check
- **Transaction safety** — job insert + dedup in single transaction

### 5.4 Logging & Observability

- **Structured JSON logging** — replaces plain text
- **Log levels** — DEBUG: individual jobs, INFO: run summaries, WARNING: retries, ERROR: failures
- **GitHub Actions** — primary log viewer
- **Dashboard** — run history, source health, error trends on stats page

---

## 6. Project Structure (New)

```
SWE-Jobs/
├── bot/
│   ├── __init__.py
│   ├── commands.py          # /subscribe, /search, /saved, etc.
│   ├── callbacks.py         # Inline button handlers
│   ├── notifications.py     # DM alert sender
│   └── webhook.py           # Telegram webhook setup
├── core/
│   ├── __init__.py
│   ├── config.py            # Settings, keywords, topics, env vars
│   ├── db.py                # PostgreSQL connection + queries
│   ├── models.py            # Job dataclass + Pydantic models
│   ├── filtering.py         # Weighted keyword scoring + geo filter
│   ├── dedup.py             # Fuzzy dedup (pg_trgm)
│   ├── salary_parser.py     # Salary extraction & normalization
│   ├── seniority.py         # Seniority detection
│   └── circuit_breaker.py   # Per-source retry + circuit breaker
├── sources/
│   ├── __init__.py          # ALL_FETCHERS registry
│   ├── http_utils.py        # Shared HTTP helpers
│   ├── remotive.py          # (existing 15 sources, unchanged)
│   └── ...
├── api/
│   ├── __init__.py
│   ├── app.py               # FastAPI app (webhook + dashboard API)
│   ├── routes_stats.py      # /api/stats/* endpoints
│   ├── routes_jobs.py       # /api/jobs/* endpoints
│   └── routes_webhook.py    # /webhook/telegram
├── dashboard/
│   ├── package.json
│   ├── src/
│   │   ├── App.tsx
│   │   ├── pages/
│   │   │   ├── Home.tsx     # Job feed with filters
│   │   │   ├── Stats.tsx    # Charts and numbers
│   │   │   ├── Salary.tsx   # Salary insights
│   │   │   └── Trends.tsx   # Skill trends
│   │   └── components/
│   │       ├── JobCard.tsx
│   │       ├── FilterBar.tsx
│   │       └── Charts.tsx
│   └── tailwind.config.js
├── main.py                  # Cron entry point (fetch -> filter -> dedup -> send)
├── server.py                # FastAPI server entry point
├── requirements.txt
├── .github/workflows/
│   ├── job_bot.yml          # Cron: fetch jobs every 5 min
│   └── deploy_dashboard.yml # Build & deploy React to GitHub Pages
└── supabase/
    └── migrations/
        └── 001_init.sql     # Schema + indexes + RLS policies
```

---

## 7. Deployment

| Component | Where | Cost |
|-----------|-------|------|
| Job fetcher (cron) | GitHub Actions | Free |
| PostgreSQL | Supabase free tier (500MB) | Free |
| FastAPI + Bot webhook | Render/Railway free tier | Free |
| React dashboard | GitHub Pages | Free |

**Total cost: $0/month**
