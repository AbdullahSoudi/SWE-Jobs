# Programming Jobs Telegram Bot

Quality-first Telegram bot for fresh jobs from **WUZZUF** and **LinkedIn**, routed automatically to Telegram forum topics.

The bot is designed for a public Telegram jobs community. It sends short job cards only: title, company, location, job type/salary when visible, source, and the original apply link.

## Current Design

This version intentionally replaced the old 15-source aggregator with a narrower, higher-quality monitor:

- **WUZZUF**: primary Egypt-focused source.
- **LinkedIn**: limited public guest search cards for very fresh jobs.
- **SQLite tracking**: jobs are stored in `jobs.db` before Telegram sending.
- **Per-topic send tracking**: a job is marked fully sent only after all intended topics succeed.
- **Retry-safe**: partial Telegram failures are retried only for the failed topics.
- **GitHub Actions only**: no VPS or external database required.
- **15-minute schedule**: cron runs every 15 minutes.

## Important Limitations

LinkedIn does not provide a public real-time webhook/API for monitoring every new job. This bot uses limited public search-result pages and filters for a rolling fresh window. If LinkedIn changes its public HTML, delays results, hides jobs, blocks requests, or removes public access, the LinkedIn source may miss jobs or return fewer results.

The bot does **not** log into LinkedIn, open profile pages, collect recruiter/member data, or scrape full job descriptions.

## Sources

| Source | Status | What it collects | Notes |
|---|---|---|---|
| WUZZUF | Enabled | Public job cards from selected category/search pages | Main Egypt source |
| LinkedIn | Enabled | Public search-card fields for jobs posted within the configured freshness window | High-risk/fragile source |
| Old sources | Disabled | Not used at runtime | Files may remain for reference, but are not registered |

Enabled sources are defined in `sources/__init__.py`:

```python
ALL_FETCHERS = [
    ("WUZZUF", fetch_wuzzuf),
    ("LinkedIn", fetch_linkedin),
]
```

## Telegram Topics

Each job can go to multiple topics. For example, a Backend Developer in Cairo can go to General, Backend, and Egypt.

There is also a dedicated topic for LinkedIn:

| Topic key | Secret | Purpose |
|---|---|---|
| `linkedin_all` | `TOPIC_LINKEDIN_ALL` | Receives every fresh LinkedIn job, regardless of normal category classification |

Current topic secrets:

| Secret | Purpose |
|---|---|
| `TOPIC_GENERAL` | General jobs topic |
| `TOPIC_LINKEDIN_ALL` | All fresh LinkedIn jobs |
| `TOPIC_BACKEND` | Backend / full-stack jobs |
| `TOPIC_FRONTEND` | Frontend / UI developer jobs |
| `TOPIC_MOBILE` | Mobile jobs |
| `TOPIC_DEVOPS` | DevOps / cloud jobs |
| `TOPIC_QA` | QA / testing jobs |
| `TOPIC_AI_ML` | AI / ML / data science jobs |
| `TOPIC_CYBERSECURITY` | Cybersecurity jobs |
| `TOPIC_GAMEDEV` | Game development jobs |
| `TOPIC_BLOCKCHAIN` | Blockchain / Web3 jobs |
| `TOPIC_EGYPT` | Egypt-located jobs |
| `TOPIC_SAUDI` | Saudi-located jobs |
| `TOPIC_INTERNSHIPS` | Internship / trainee / fresh graduate jobs |
| `TOPIC_ERP` | ERP / Odoo / SAP / Salesforce / accounting software jobs |
| `TOPIC_MARKETING` | Marketing and growth jobs |
| `TOPIC_DATA_ENG` | Data engineering / analytics / BI jobs |
| `TOPIC_APP_SUPPORT` | Application / technical support jobs |
| `TOPIC_DESIGN` | UI/UX / graphic / product design jobs |
| `TOPIC_BUSINESS` | Business analyst / product / project roles |

Topics without configured thread IDs are skipped and recorded as failed, so they can be retried after adding the missing secret.

## Required GitHub Secrets

Go to **GitHub repo → Settings → Secrets and variables → Actions → New repository secret**.

Required:

| Secret | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token from @BotFather |
| `TELEGRAM_GROUP_ID` | Telegram supergroup chat ID, usually starts with `-100` |

Recommended topic secrets:

```text
TOPIC_GENERAL
TOPIC_LINKEDIN_ALL
TOPIC_BACKEND
TOPIC_FRONTEND
TOPIC_MOBILE
TOPIC_DEVOPS
TOPIC_QA
TOPIC_AI_ML
TOPIC_CYBERSECURITY
TOPIC_GAMEDEV
TOPIC_BLOCKCHAIN
TOPIC_EGYPT
TOPIC_SAUDI
TOPIC_INTERNSHIPS
TOPIC_ERP
TOPIC_MARKETING
TOPIC_DATA_ENG
TOPIC_APP_SUPPORT
TOPIC_DESIGN
TOPIC_BUSINESS
```

No RapidAPI, Adzuna, Jooble, Reed, USAJobs, or other old API keys are required in this version.

## How to Get Telegram Topic IDs

1. Create a Telegram supergroup.
2. Enable Topics.
3. Create the topic, for example `LinkedIn Fresh Jobs`.
4. Open/copy the topic link. If the link looks like `https://t.me/YourGroup/123`, the topic ID is usually `123`.
5. Save that number as the matching GitHub secret, for example `TOPIC_LINKEDIN_ALL=123`.

The bot sends to Telegram forum topics using `message_thread_id`.

## GitHub Actions Workflow

Workflow file:

```text
.github/workflows/job_bot.yml
```

Runtime behavior:

1. Checkout `main` branch.
2. Restore `jobs.db` from the `data` branch if it exists.
3. Run `python main.py`.
4. Save updated `jobs.db` back to the `data` branch.

The workflow uses:

```yaml
concurrency:
  group: programming-jobs-bot
  cancel-in-progress: false
```

This prevents overlapping runs from writing to `jobs.db` at the same time.

## First Run / Seed Mode

The workflow includes a manual `seed_mode` input.

Use seed mode when you want to populate `jobs.db` with current jobs without sending them to Telegram.

Recommended first launch:

1. Go to **Actions → Programming Jobs Bot → Run workflow**.
2. Set `seed_mode = true`.
3. Wait until it finishes and creates/saves `jobs.db` on the `data` branch.
4. Run the workflow again with `seed_mode = false` or let the scheduled runs continue.

If you skip seed mode, the bot may send all currently fetched matching jobs during the first real run.

## SQLite Tracking

The database file is:

```text
jobs.db
```

It is stored on the GitHub `data` branch by the workflow.

The database tracks:

- source
- source job ID when available
- title
- company
- location
- canonical URL
- first seen time
- last seen time
- job send status
- per-topic send status
- source run status

Send statuses include:

| Status | Meaning |
|---|---|
| `pending` | Stored and waiting to send |
| `sent` | Successfully sent to all intended topics |
| `partial` | Sent to at least one topic, failed in at least one other topic |
| `retry` | Send failed and should be retried |
| `skipped` | No matching topics, or seed mode intentionally skipped sending |

## Runtime Flow

```text
fetch WUZZUF + LinkedIn
  ↓
filter quality + geo rules
  ↓
store/update jobs in SQLite
  ↓
read pending/retry/partial jobs
  ↓
route to Telegram topics
  ↓
send only unsent topics
  ↓
record topic-level result
  ↓
commit jobs.db to data branch
```

## LinkedIn Freshness Rules

LinkedIn requests are configured for a rolling freshness window:

```text
f_TPR=r3600
sortBy=DD
```

This means the bot asks for jobs from the last hour and requests newest-first ordering. The workflow runs every 15 minutes, so this one-hour window gives a safety overlap if GitHub Actions starts late. SQLite deduplication prevents repeated sending of the same job.

Local defensive filters also skip LinkedIn cards that visibly look stale or closed, such as:

- `2 hours ago`
- `1 day ago`
- `No longer accepting applications`
- `Job is no longer available`
- `Expired`
- `Closed`

## Local Testing

Install requirements:

```bash
pip install -r requirements.txt
```

Run all tests:

```bash
python -m unittest discover -s tests -v
```

Run the bot locally:

```bash
export TELEGRAM_BOT_TOKEN="your_bot_token"
export TELEGRAM_GROUP_ID="-100xxxxxxxxxx"
export TOPIC_GENERAL="1"
export TOPIC_LINKEDIN_ALL="2"
export TOPIC_BACKEND="3"
python main.py
```

Seed locally:

```bash
export SEED_MODE=true
python main.py
```

## Project Structure

```text
├── main.py
├── config.py
├── models.py
├── db.py
├── telegram_sender.py
├── cleanup.py
├── requirements.txt
├── README.md
├── sources/
│   ├── __init__.py
│   ├── http_utils.py
│   ├── wuzzuf.py
│   └── linkedin.py
├── tests/
│   ├── test_db.py
│   ├── test_linkedin.py
│   ├── test_main_sqlite.py
│   ├── test_routing.py
│   ├── test_sources_registry.py
│   ├── test_workflow.py
│   └── test_wuzzuf.py
└── .github/workflows/
    └── job_bot.yml
```

## Migration Notes from the Old Version

The old version used:

```text
seen_jobs.json
15 sources
many external API keys
```

The new version uses:

```text
jobs.db
WUZZUF + LinkedIn only
no external job-board API keys
```

The workflow removes `seen_jobs.json` from the `data` branch if it exists.

## Operational Notes

- Keep the bot admin in the Telegram group.
- Make sure the group has Topics enabled.
- Configure `TOPIC_LINKEDIN_ALL` if you want every fresh LinkedIn job in a dedicated topic.
- Do not post full descriptions in a public group; the bot intentionally sends short cards only.
- If a topic secret is missing, the bot records the send as failed and retries after the secret is added.
- If LinkedIn becomes unstable, WUZZUF remains the main stable source.
