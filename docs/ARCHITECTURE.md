# Architecture

## Overview

SWE-Jobs is a pipeline-based job aggregation system. Every 5 minutes, GitHub Actions triggers `main.py`, which runs the full pipeline: fetch -> enrich -> filter -> dedup -> insert -> send -> notify -> monitor.

## Pipeline Stages

### 1. Fetch

Each of the 15 sources has a fetcher function in `sources/`. All fetchers return `list[Job]` and handle their own error cases (returning an empty list on failure).

Before fetching, the **circuit breaker** (`core/circuit_breaker.py`) checks if a source is healthy:
- Sources are retried with exponential backoff (2s, 5s delays)
- After 3 consecutive failures, the circuit opens (source is disabled)
- Circuit state is persisted in the `source_health` database table across runs
- Circuits auto-close after a cooldown period

### 2. Enrich

`core/enrichment.py` adds derived data to each job:

- **Salary parsing** (`core/salary_parser.py`) — extracts min/max/currency from free text, normalizes hourly/monthly to yearly
- **Seniority detection** (`core/seniority.py`) — regex patterns classify as intern/junior/mid/senior/lead/executive
- **Country detection** (`core/country_detector.py`) — maps location strings to ISO country codes using city/country patterns
- **Topic routing** (`core/channels.py`) — matches job title/tags against topic keywords to determine which Telegram topics receive the job

### 3. Filter

`core/filtering.py` applies two filters:

**Keyword scoring** — each job gets a weighted score:
- `+10` for exact whole-word match in title
- `+8` for exact match in tags
- `+3` for partial/substring match
- `-20` for exclude keyword match (instant rejection for irrelevant roles)
- Jobs must score >= 10 (configurable `SCORE_THRESHOLD`)

**Geo-filter** — controls which jobs pass based on location:
- Egypt or Saudi Arabia locations: all jobs pass (onsite + remote)
- Remote-only sources (remotive, remoteok, wwr, etc.): always pass
- Other onsite locations: filtered out

### 4. Deduplicate

`core/dedup.py` runs two dedup passes:

- **Exact URL dedup** — compares `unique_id` (URL with UTM parameters stripped) against existing database records
- **Fuzzy dedup** — uses PostgreSQL's `pg_trgm` extension to find titles with >= 0.7 similarity within a 7-day window, preventing near-duplicates from different sources

### 5. Insert

New jobs are inserted into the `jobs` table via `core/db.py`. The database layer uses connection pooling with SSL (required by Supabase).

### 6. Send

`bot/sender.py` formats each job as an HTML Telegram message with:
- Emoji (auto-selected based on job title keywords)
- Title, company, location, salary, seniority, job type, remote status
- Inline buttons: Apply, Save, Report

Each job is sent to all matching topics. Message IDs are stored back in `telegram_message_ids` for cross-referencing.

### 7. Notify

`bot/notifications.py` sends personalized DM alerts to subscribers. Each subscription specifies:
- Topics of interest
- Seniority preferences
- Custom keywords
- Minimum salary threshold

Rate-limited to 20 DMs per user per hour.

### 8. Monitor

`core/monitoring.py` checks for anomalies after each run:
- Zero jobs fetched (all sources may be down)
- Slow run duration
- Low send rate
- Circuit breaker activations

Sends alerts to the admin via Telegram DM. Also sends a daily digest with run statistics.

## Database Schema

```
jobs                    # Job listings with full enrichment
├── unique_id           # URL-based dedup key (UTM stripped)
├── title, company, location, url, source
├── salary_min, salary_max, salary_currency
├── seniority, is_remote, country
├── tags[]              # Source-provided tags
├── topics[]            # Computed topic assignments
├── telegram_message_ids  # {topic: message_id}
└── created_at, sent_at

users                   # Telegram users
├── telegram_id
├── subscriptions       # {topics, seniority, keywords, min_salary}
└── notify_dm

user_saved_jobs         # Bookmarked jobs (user_id, job_id)

bot_runs                # Execution tracking
├── jobs_fetched, jobs_filtered, jobs_new, jobs_sent
├── source_stats        # Per-source counts
└── errors

source_health           # Circuit breaker state
├── source
├── consecutive_failures
├── circuit_open_until
└── last_error

job_feedback            # User feedback on jobs (save, report)

jobs_archive            # Archived old jobs (same schema, fewer indexes)
```

All tables have Row Level Security enabled. The `anon` role can only SELECT from `jobs`.

### Key Indexes

- `jobs_title_trgm_idx` — GIN trigram index for fuzzy title matching
- `jobs_tags_gin_idx` — GIN index for tag array containment queries
- `jobs_topics_gin_idx` — GIN index for topic array queries
- `jobs_created_at_idx` — B-tree for date range queries

## Telegram Bot

The interactive bot (`bot/`) uses `python-telegram-bot` and supports:

| Command | Description |
|---------|-------------|
| `/start` | Welcome message |
| `/help` | List available commands |
| `/subscribe` | Set up job alerts (topics, seniority, keywords) |
| `/unsubscribe` | Remove alert subscription |
| `/mysubs` | View current subscriptions |
| `/search <query>` | Search jobs in database |
| `/saved` | View bookmarked jobs |
| `/stats` | Bot statistics |
| `/top` | Top companies/sources |
| `/salary` | Salary insights |

Inline keyboards handle multi-step flows like subscription setup.

## REST API

The FastAPI backend (`api/`) provides:

| Endpoint | Description | Rate Limit |
|----------|-------------|------------|
| `GET /api/jobs/search` | Full-text search with filters | 30/min |
| `GET /api/stats` | Summary statistics | — |
| `GET /api/salary` | Salary stats by seniority/role/country | — |
| `GET /api/trends` | Trending skills week-over-week | — |

Rate limiting via `slowapi`. CORS enabled for the dashboard origin.

## Web Dashboard

React 19 + TypeScript + Vite + TailwindCSS + Recharts.

Pages:
- **Home** — job listing with search and filters
- **Stats** — jobs by source, topic, company (bar/pie charts)
- **Salary** — salary distributions by seniority, role, country
- **Trends** — skill popularity trends over time

Connects to Supabase directly for reads and the FastAPI backend for aggregated queries.

## Deployment

- **Bot pipeline** — GitHub Actions cron every 5 minutes (`job_bot.yml`)
- **Dashboard** — GitHub Pages, deployed on push to `main` (`deploy_dashboard.yml`)
- **Job archival** — GitHub Actions periodic workflow (`archive_jobs.yml`)
- **Database** — Supabase free tier (PostgreSQL with pgvector, pg_trgm)
