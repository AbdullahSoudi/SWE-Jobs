# Programming Jobs Telegram Bot

Quality-first Telegram bot for fresh jobs from **WUZZUF** and **LinkedIn**, routed automatically to Telegram forum topics.

The bot is designed for a public Telegram jobs community. It sends short job cards only: title, company, location, job type/salary when visible, source, and the original apply link.

## Current Design

This version intentionally replaced the old 15-source aggregator with a narrower, higher-quality monitor:

- **WUZZUF**: primary Egypt-focused source.
- **LinkedIn**: limited public guest search cards for very fresh jobs.
- **SQLite tracking**: jobs are stored in `jobs.db` before Telegram sending.
- **Per-topic send tracking**: a job is marked fully sent only after all intended topics succeed.
- **Durable Telegram outbox**: each topic delivery is queued in SQLite before the network call and tracked separately.
- **Legacy backlog safety**: old pending/retry rows are expired once instead of being replayed as fresh jobs.
- **Fresh-only send gate**: only newly discovered jobs that are still fresh enough are eligible for Telegram.
- **Automatic source baseline**: the first successful fetch for a new source is stored without sending, preventing bootstrap floods.
- **Freshness evidence**: publication-time signals are stored with their precision instead of being forced into a fake exact timestamp.
- **Coverage-gap safety**: uncertain jobs are not treated as fresh after a source has been unavailable for too long.
- **Source state**: successful fetch time, baseline state, and consecutive failures are persisted per source.
- **Telegram backpressure**: sends are rate-limited per supergroup, `429 retry_after` pauses the whole queue, and transient 5xx/network failures use bounded retries.
- **Ambiguous-send safety**: a read timeout or process crash after claiming a delivery becomes `UNKNOWN` instead of being blindly retried and potentially duplicated.
- **Delivery audit trail**: every Telegram attempt stores outcome, HTTP/error codes, retry delay, and message ID when available.
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

Topics without configured thread IDs are recorded as `CONFIG_ERROR`. That topic is disabled for the rest of the current run so a bad secret cannot create a retry storm or late replay.

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

The workflow still includes a manual `seed_mode` input, but a new source no longer needs seed mode to avoid a bootstrap flood. The runtime automatically treats the source's first successful fetch as a **baseline**: matching jobs are stored and marked skipped, then later runs can notify only newly discovered fresh jobs.

Use `seed_mode = true` only when you intentionally want to suppress every currently pending job during a maintenance/manual run.

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
- raw publication-time text when visible
- earliest/latest possible publication time
- estimated publication time and precision (`EXACT`, `MINUTE`, `HOUR`, `DAY`, `NONE`)
- first seen time
- last seen time
- job send status
- per-topic delivery status, attempt count, next retry time, and hard deadline
- Telegram error class, HTTP status, Bot API error code, `retry_after`, and returned message ID
- append-only `delivery_attempts` audit history
- source run status
- last successful source fetch
- source baseline state
- per-job freshness status and reason
- consecutive source failures

Send statuses include:

| Status | Meaning |
|---|---|
| `pending` | Stored and waiting to send |
| `sent` | Successfully sent to all intended topics |
| `partial` | Some topics are sent while at least one retryable delivery remains |
| `retry` | No topic is sent yet and at least one retryable delivery remains |
| `partial_failed` | At least one topic sent, but the remaining delivery is terminal |
| `failed` | All attempted deliveries are terminal failures |
| `unknown` | Telegram may have accepted a request, so the bot will not blindly retry it |
| `skipped` | No matching topics, or seed mode intentionally skipped sending |
| `expired` | Job is too old, too uncertain, or has exceeded the live-send deadline |

### Legacy Backlog Safety

On the first run after this update, the bot performs a one-time migration. Any legacy `pending`, `retry`, or `partial` row whose `first_seen_at` is older than `LEGACY_BACKLOG_MAX_AGE_MINUTES` (default: 120 minutes) is marked `expired` and will not be sent. The migration is recorded in the `metadata` table so it runs only once.

This remains a compatibility cleanup for the old backlog. In addition, the active runtime expires `pending`, `retry`, and `partial` rows that have waited longer than `PENDING_SEND_MAX_AGE_MINUTES` (default: 60 minutes), so failed Telegram work cannot reappear hours later as a fresh notification.

## Runtime Flow

```text
fetch WUZZUF + LinkedIn
  ↓
filter quality + geo rules
  ↓
new-to-us freshness gate
  ├─ first source fetch → baseline / no send
  ├─ fresh enough → pending
  └─ stale / unsafe uncertainty → expired
  ↓
store/update jobs in SQLite
  ↓
read pending/retry/partial jobs (freshest first)
  ↓
route to Telegram topics
  ↓
create/refresh durable topic deliveries in SQLite
  ↓
claim one delivery and commit before network call
  ↓
rate-limited Telegram send
  ├─ 200 → sent
  ├─ 429 → persist retry_after + pause whole group queue
  ├─ 5xx/network → bounded retry, then retry_wait
  ├─ config/400 → terminal delivery error
  └─ ambiguous read timeout/crash → unknown / no blind retry
  ↓
append delivery_attempts audit row
  ↓
commit jobs.db to data branch
```

## Active Freshness Gate

Schema v4 keeps the freshness model from v3 and adds the durable Telegram delivery state/audit tables. The freshness model separates **what the source tells us** from **whether a newly discovered job is safe to notify**. `12 minutes ago` is stored as a narrow interval, while `1 hour ago` remains a wider hour bucket. Exact `datetime` values stay exact; missing/coarse values stay uncertain.

The send decision is now based on **new-to-us + max age + source baseline**, not `published_at > last_run`. This avoids losing jobs that become visible after indexing delay.

Rules:

- A source's first successful fetch is always a no-send baseline.
- Fresh timestamp evidence is eligible to send.
- Explicitly old timestamp evidence is stored as `expired`.
- LinkedIn may use its bounded `f_TPR` source window as a fallback when a card omits visible time, but only if the previous successful poll is recent.
- WUZZUF may use recent observation as a fallback because its current cards do not expose reliable posting timestamps.
- If the previous successful poll is older than the source's max-age budget, the fallback is disabled and uncertain jobs are stored but not sent.
- Source success is advanced only after fetched jobs have been persisted.

Per-job `freshness_status` values include `FRESH`, `TOO_OLD`, `UNCERTAIN`, `BASELINE`, and `LEGACY`, with a `freshness_reason` for audit/debugging.

## LinkedIn Freshness Rules

LinkedIn requests are currently configured for a rolling freshness window:

```text
f_TPR=r3600
sortBy=DD
```

This means the bot asks for jobs from the last hour and requests newest-first ordering. The workflow runs every 15 minutes, so this one-hour window gives a safety overlap if GitHub Actions starts late. SQLite deduplication prevents repeated sending of the same job.

Freshness/runtime environment overrides:

```text
LINKEDIN_FRESHNESS_SECONDS=3600
WUZZUF_OBSERVATION_MAX_AGE_MINUTES=60
PENDING_SEND_MAX_AGE_MINUTES=60
TELEGRAM_SEND_DELAY=3
TELEGRAM_REQUEST_TIMEOUT_SECONDS=10
TELEGRAM_MAX_INLINE_RETRIES=2
```

These are safety budgets, not promises that a source publishes/indexes every job instantly.

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
├── freshness.py
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
│   ├── test_freshness.py
│   ├── test_linkedin.py
│   ├── test_main_sqlite.py
│   ├── test_routing.py
│   ├── test_sources_registry.py
│   ├── test_telegram_sender.py
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
