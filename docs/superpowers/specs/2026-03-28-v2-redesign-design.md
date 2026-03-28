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
| `country` | `TEXT` | Detected country (see Section 2.5) |
| `tags` | `TEXT[]` | Array of tags/skills |
| `topics` | `TEXT[]` | Routed topics: backend, frontend, etc. |
| `created_at` | `TIMESTAMPTZ` | When we first saw it |
| `updated_at` | `TIMESTAMPTZ` | When row was last enriched/updated |
| `sent_at` | `TIMESTAMPTZ` | When sent to Telegram (null if unsent) |
| `telegram_message_ids` | `JSONB` | `{topic_key: {"chat_id": ..., "message_id": ...}}` |

**Indexes:**

- `pg_trgm` GIN index on `title` for fuzzy dedup and full-text search
- GIN index on `tags` and `topics` for array lookups
- B-tree on `created_at`, `source`, `seniority`, `salary_min`

**Retention policy:** Jobs older than 90 days are archived (moved to `jobs_archive` table with same schema but no expensive indexes) via a weekly GitHub Actions job. This keeps the active table under ~200MB with indexes, well within the 500MB Supabase free tier limit.

**Storage estimate:** ~20,000 jobs/day x ~1.5KB/row = ~30MB/day raw. With indexes (pg_trgm GIN adds ~40% overhead), ~42MB/day. 90-day retention = ~3.8GB without archival. With archival, active table stays at ~3.8GB/90 = ~42MB/day x 90 = ~3.8GB... To keep within 500MB: retain 7 days in active table (~300MB with indexes), archive older jobs to `jobs_archive` (no GIN indexes, just B-tree on id/created_at, ~150MB for 90 days compressed). Total: ~450MB. Alternatively, reduce to 50-day retention or prune `jobs_archive` at 60 days.

### 1.2 `users` table

Telegram users who interact with the bot.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `SERIAL PK` | |
| `telegram_id` | `BIGINT UNIQUE` | |
| `username` | `TEXT` | |
| `subscriptions` | `JSONB` | `{"topics": ["backend"], "keywords": ["python"], "seniority": ["senior"], "min_salary": 50000}` |
| `notify_dm` | `BOOLEAN DEFAULT true` | |
| `created_at` | `TIMESTAMPTZ` | |

### 1.3 `user_saved_jobs` table

Junction table for saved jobs (replaces the `INTEGER[]` approach).

| Column | Type | Notes |
|--------|------|-------|
| `id` | `SERIAL PK` | |
| `user_id` | `INTEGER REFERENCES users(id)` | |
| `job_id` | `INTEGER REFERENCES jobs(id)` | |
| `saved_at` | `TIMESTAMPTZ DEFAULT now()` | |

**Unique constraint:** `(user_id, job_id)` — prevents duplicate saves.

### 1.4 `bot_runs` table

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

**Note:** Error messages are sanitized before storage — API keys, tokens, and internal URLs are stripped.

### 1.5 `source_health` table

Persists circuit breaker state across GitHub Actions runs.

| Column | Type | Notes |
|--------|------|-------|
| `source` | `TEXT PK` | e.g. "remotive", "adzuna" |
| `consecutive_failures` | `INTEGER DEFAULT 0` | |
| `circuit_open_until` | `TIMESTAMPTZ` | null = circuit closed |
| `last_success_at` | `TIMESTAMPTZ` | |
| `last_failure_at` | `TIMESTAMPTZ` | |
| `last_error` | `TEXT` | Sanitized error message |

### 1.6 `job_feedback` table

Tracks user feedback signals from "Not Relevant" button presses.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `SERIAL PK` | |
| `job_id` | `INTEGER REFERENCES jobs(id)` | |
| `user_id` | `INTEGER REFERENCES users(id)` | |
| `feedback_type` | `TEXT` | "not_relevant", "save", "similar_click" |
| `created_at` | `TIMESTAMPTZ DEFAULT now()` | |

### 1.7 Row Level Security (RLS) Policies

```sql
-- Enable RLS on all tables
ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_saved_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE bot_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE source_health ENABLE ROW LEVEL SECURITY;
ALTER TABLE job_feedback ENABLE ROW LEVEL SECURITY;

-- ANON (dashboard) can only read jobs
CREATE POLICY "anon_read_jobs" ON jobs
  FOR SELECT TO anon
  USING (true);

-- ANON can read bot_runs but NOT the errors column (may contain sensitive info)
-- Use a VIEW instead:
CREATE VIEW bot_runs_public AS
  SELECT id, started_at, finished_at, jobs_fetched, jobs_filtered,
         jobs_new, jobs_sent, source_stats
  FROM bot_runs;
GRANT SELECT ON bot_runs_public TO anon;

-- ANON cannot access: users, user_saved_jobs, source_health, job_feedback
-- (no SELECT policy = denied by default with RLS enabled)

-- SERVICE_ROLE (bot) has full access (bypasses RLS)
```

### 1.8 Connection Pooling

All connections go through Supabase's built-in pgBouncer connection pooler (port 6543) instead of direct connections (port 5432). This is critical because:
- GitHub Actions creates a new connection every 5 minutes
- FastAPI server maintains a small pool (max 5 connections)
- Supabase free tier allows ~60 direct connections; pgBouncer multiplexes them

---

## 2. Quality Improvements

### 2.1 Weighted Keyword Scoring

Replace the current boolean contains-match with a scoring system.

**Score types:**
- **Exact word match in title** (regex `\b` word boundary): +10 points — "Software Engineer" matches `\bengineer\b`
- **Tag/skill match** (exact match in tags array): +8 points — `"python"` in tags
- **Partial match** (substring, no word boundary): +3 points — "engineering" contains "engineer"
- **Exclude match**: -20 points (instant reject, checked first)
- **Threshold**: job must score >= 10 to pass

**Scoring examples with current keywords:**

| Job Title | Tags | Score | Pass? |
|-----------|------|-------|-------|
| "Senior Python Developer" | ["python"] | +10 (word "developer") + 8 (tag "python") = 18 | Yes |
| "Sales Engineer" | [] | +10 (word "engineer") but "sales" in EXCLUDE = -20 | No (-10) |
| "Software Engineering Intern" | [] | +10 (word "intern") + 3 (partial "engineering") = 13 | Yes |
| "Marketing Developer Tools" | [] | +3 (partial "developer") but "marketing" in EXCLUDE = -20 | No (-17) |
| "React Developer" | ["react", "javascript"] | +10 (word "developer") + 8 (tag "react") = 18 | Yes |
| "Audio Engineer at Spotify" | [] | +10 (word "engineer") only, no exclude match = 10 | Yes (borderline) |

**Note on broad terms:** "developer", "engineer", "programmer" from the current INCLUDE list are treated as **exact word matches** (+10), not partial. This means they must appear as whole words in the title (word boundary `\b`). The EXCLUDE list handles false positives like "Sales Engineer" and "Audio Engineer."

### 2.2 Fuzzy Deduplication

Three-layer dedup replacing the current URL-only check:

1. **Exact URL match** — normalized URL comparison (same as today)
2. **Title + Company similarity** — `pg_trgm`: if `similarity(title_a, title_b) > 0.7` AND `lower(company_a) = lower(company_b)` then it's a duplicate
3. **Batch window** — only compare against jobs from the last 7 days

When a fuzzy duplicate is found, keep the version with more data (has salary > no salary, more tags > fewer tags) and update the existing row (sets `updated_at`).

**Dedup query:**
```sql
SELECT id, title, company FROM jobs
WHERE created_at > now() - interval '7 days'
  AND lower(company) = lower($1)
  AND similarity(title, $2) > 0.7
LIMIT 1;
```

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

### 2.5 Country Detection

Detect country from the `location` field using a pattern-based approach:

- **Egypt** — existing `EGYPT_PATTERNS` (city names, Arabic names)
- **Saudi Arabia** — existing `SAUDI_PATTERNS`
- **Common countries** — a mapping of `{"united states": "US", "uk": "GB", "germany": "DE", ...}` covering ~30 countries by name, abbreviation, and major cities
- **Fallback** — if no pattern matches, store `null`

No external geocoding API needed. The pattern list covers the countries most relevant to the job sources.

---

## 3. Interactive Telegram Bot

### 3.1 Inline Buttons on Every Job Post

Each message gets a button row:

```
[Save] [Share] [Similar] [Not Relevant]
```

- **Save** — inserts into `user_saved_jobs`, confirms via DM
- **Share** — generates a clean shareable text to forward
- **Similar** — DMs 3-5 similar jobs (see ranking query below)
- **Not Relevant** — inserts into `job_feedback`, used for future scoring analysis

**Similar jobs ranking query:**
```sql
SELECT j.*, (
  -- Title similarity (0-1, weighted x3)
  similarity(j.title, $1) * 3 +
  -- Tag overlap (count of shared tags / max tags, weighted x2)
  (SELECT COUNT(*) FROM unnest(j.tags) t WHERE t = ANY($2))::float
    / GREATEST(array_length($2, 1), 1) * 2 +
  -- Same seniority bonus
  CASE WHEN j.seniority = $3 THEN 1 ELSE 0 END +
  -- Salary proximity bonus (within 30%)
  CASE WHEN j.salary_min IS NOT NULL AND $4 IS NOT NULL
       AND j.salary_min BETWEEN $4 * 0.7 AND $4 * 1.3 THEN 1 ELSE 0 END
) AS relevance_score
FROM jobs j
WHERE j.id != $5
  AND j.created_at > now() - interval '14 days'
ORDER BY relevance_score DESC
LIMIT 5;
```

### 3.2 Bot Commands

| Command | What it does |
|---------|-------------|
| `/subscribe` | Interactive setup via inline keyboard: pick topics, skills, seniority, min salary step by step |
| `/unsubscribe` | Remove all subscriptions |
| `/mysubs` | Show current subscription filters |
| `/search` | Interactive search: bot asks for filters via inline keyboard, then returns results |
| `/saved` | List saved jobs (paginated) |
| `/stats` | Bot stats: jobs today, top sources, top skills |
| `/top` | Top 10 jobs this week by engagement (saves + similar clicks) |
| `/salary` | Interactive: pick role + location, see salary ranges |
| `/help` | List all commands |

**Note:** Commands use interactive inline keyboards instead of free-text parsing. E.g., `/subscribe` shows buttons for topics, then skills, then seniority. This avoids the complexity of parsing natural language filters.

### 3.3 Personalized DM Alerts

When a new job matches a user's subscription:

1. Bot sends DM with full job post + inline buttons
2. Respects `notify_dm` toggle
3. Rate limit: max 20 DMs per user per hour
4. Matches against: `topics`, `keywords`, `seniority`, `min_salary`

### 3.4 Bot Architecture

- `python-telegram-bot` library, async, **polling mode** (not webhooks)
- Polling mode avoids Render free tier cold-start issues — the bot actively polls Telegram for updates, so it works even if the server sleeps and wakes up
- FastAPI serves the dashboard API endpoints only (no webhook needed)
- Bot polling loop and FastAPI run in the same process via `asyncio`
- Render/Railway free tier: the bot's polling acts as a keep-alive, preventing the server from sleeping

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
- `GET /rest/v1/bot_runs_public?order=started_at.desc&limit=30` — run history (public view, no errors)

RLS: read-only via `anon` key. Only `jobs` and `bot_runs_public` view are accessible. `users`, `user_saved_jobs`, `source_health`, `job_feedback` are blocked.

### 4.4 Custom FastAPI Endpoints

For complex aggregations:

| Endpoint | Purpose | Rate Limit |
|----------|---------|------------|
| `GET /api/stats/summary` | Aggregated stats for home page | 30 req/min |
| `GET /api/stats/salary?role=backend&country=egypt` | Salary breakdown | 20 req/min |
| `GET /api/stats/trends?period=7d` | Skill trends with week-over-week delta | 20 req/min |
| `GET /api/jobs/search?q=python&min_salary=50000` | Full-text search + salary filter | 30 req/min |

Rate limiting implemented via `slowapi` (FastAPI-compatible rate limiter using IP-based tracking).

---

## 5. Operational Reliability

### 5.1 Per-Source Error Handling & Retry

- **Retry with backoff** — 2 retries per source, 2s/5s delays
- **Circuit breaker** — state persisted in `source_health` table. On failure: increment `consecutive_failures`. At 3 failures: set `circuit_open_until = now() + 30 min`. On success: reset to 0. Each cron run checks `source_health` before fetching.
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

## 6. Migration from v1

### 6.1 Migration Runbook

1. **Set up Supabase** — create project, run `001_init.sql` migration
2. **Import seen_jobs.json** — one-time script reads the JSON from `data` branch, inserts each URL as a minimal `jobs` row (just `unique_id`, `url`, `created_at = now()`, `sent_at = now()`) so they won't be re-sent
3. **Deploy FastAPI + bot** — to Render/Railway, verify bot polling works
4. **Update GitHub Actions** — switch `job_bot.yml` to use the new `main.py` that writes to PostgreSQL instead of JSON
5. **Verify** — run manually, check that jobs flow to Telegram correctly
6. **Retire v1** — remove `seen_jobs.json` workflow steps, optionally delete the `data` branch
7. **Deploy dashboard** — set up GitHub Pages workflow, push React app

**Transition approach:** No parallel running needed since it's a clean slate. The import step (2) ensures no duplicate sends. If something breaks, the old workflow YAML is in git history.

---

## 7. Project Structure (New)

```
SWE-Jobs/
├── bot/
│   ├── __init__.py
│   ├── commands.py          # /subscribe, /search, /saved, etc.
│   ├── callbacks.py         # Inline button handlers
│   ├── notifications.py     # DM alert sender
│   └── polling.py           # Telegram polling setup
├── core/
│   ├── __init__.py
│   ├── config.py            # Env vars, settings, timeouts
│   ├── keywords.py          # Include/exclude lists, scoring weights
│   ├── channels.py          # Topic definitions, routing config
│   ├── db.py                # PostgreSQL connection (pgBouncer) + queries
│   ├── models.py            # Job dataclass + Pydantic models
│   ├── filtering.py         # Weighted keyword scoring + geo filter
│   ├── dedup.py             # Fuzzy dedup (pg_trgm)
│   ├── salary_parser.py     # Salary extraction & normalization
│   ├── seniority.py         # Seniority detection
│   ├── country_detector.py  # Country detection from location
│   └── circuit_breaker.py   # Per-source retry + circuit breaker (DB-backed)
├── sources/
│   ├── __init__.py          # ALL_FETCHERS registry
│   ├── http_utils.py        # Shared HTTP helpers
│   ├── remotive.py          # (existing 15 sources, unchanged)
│   └── ...
├── api/
│   ├── __init__.py
│   ├── app.py               # FastAPI app (dashboard API only)
│   ├── routes_stats.py      # /api/stats/* endpoints
│   ├── routes_jobs.py       # /api/jobs/* endpoints
│   └── middleware.py         # Rate limiting (slowapi)
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
├── tests/
│   ├── test_salary_parser.py
│   ├── test_seniority.py
│   ├── test_filtering.py
│   ├── test_dedup.py
│   ├── test_country_detector.py
│   └── test_circuit_breaker.py
├── main.py                  # Cron entry point (fetch -> filter -> dedup -> send)
├── server.py                # FastAPI + bot polling entry point
├── requirements.txt
├── .github/workflows/
│   ├── job_bot.yml          # Cron: fetch jobs every 5 min
│   ├── deploy_dashboard.yml # Build & deploy React to GitHub Pages
│   └── archive_jobs.yml     # Weekly: archive old jobs for retention
└── supabase/
    └── migrations/
        └── 001_init.sql     # Schema + indexes + RLS policies
```

---

## 8. Deployment

| Component | Where | Cost |
|-----------|-------|------|
| Job fetcher (cron) | GitHub Actions | Free |
| PostgreSQL | Supabase free tier (500MB, pgBouncer) | Free |
| FastAPI + Bot polling | Render/Railway free tier | Free |
| React dashboard | GitHub Pages | Free |
| Job archival | GitHub Actions (weekly cron) | Free |

**Total cost: $0/month**

---

## 9. Testing Strategy

Unit tests for the highest-value modules:

| Module | What to test |
|--------|-------------|
| `salary_parser` | Each format pattern, edge cases (no salary, malformed), currency detection |
| `seniority` | Each level, ambiguous titles, multi-signal titles |
| `filtering` | Scoring examples from Section 2.1, edge cases, exclude overrides |
| `dedup` | Exact URL match, fuzzy title match, cross-source dedup |
| `country_detector` | Known countries, Arabic names, ambiguous locations |
| `circuit_breaker` | State transitions, DB persistence, reset on success |

Run via `pytest` in GitHub Actions as part of the bot workflow (fast, no DB needed for unit tests — mock the DB layer).
