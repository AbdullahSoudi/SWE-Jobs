# Programming Jobs Telegram Bot

Quality-first Telegram bot for **fresh jobs** from WUZZUF and LinkedIn, with a growing focus on Egypt and Saudi Arabia.

The product goal is a real-time job feed, not a historical job archive:

> discover jobs that are new to us, prove they are still fresh enough, and notify users once.

## Current Design

- **Sources:** WUZZUF + LinkedIn public job search cards.
- **Fresh-only gate:** old or uncertain jobs are stored for dedup/audit but are not posted late.
- **Source baselines:** the first successful fetch of a new source never sends its existing backlog.
- **Shadow-by-default sources:** any source not explicitly promoted to production is measured and stored but cannot send to Telegram.
- **Per-source run history:** fetch counts, freshness outcomes, failures, duration, shadow yield, and coverage gaps are stored for later source scoring.
- **SQLite state:** jobs, source state, freshness evidence, delivery state, and delivery attempts live in `jobs.db`.
- **Durable Telegram outbox:** delivery state is written before the network call.
- **One job = one Telegram post:** each job is assigned one primary role topic only.
- **Market/source as metadata:** Egypt/Saudi/Remote and the source are shown in the message instead of creating duplicate topic posts.
- **Telegram backpressure:** rate limiting, `retry_after`, bounded transient retries, and ambiguous-timeout protection.
- **GitHub Actions:** runs every 15 minutes and persists `jobs.db` on the `data` branch.

## Sources

Enabled sources are defined in `sources/__init__.py`:

```python
ALL_FETCHERS = [
    ("WUZZUF", fetch_wuzzuf),
    ("LinkedIn", fetch_linkedin),
]
```

| Source | Status | Notes |
|---|---|---|
| WUZZUF | Enabled | Public category/search cards; mainly Egypt |
| LinkedIn | Enabled | Public guest search cards; fragile and subject to source changes |
| Legacy sources | Disabled | Not registered at runtime |

LinkedIn is intentionally treated as a fragile source. The bot does not log in, access profiles, collect member data, or scrape full descriptions.


## Shadow Mode and Source Metrics

New sources are **shadowed by default**. The production allowlist currently contains only:

```python
PRODUCTION_SOURCE_KEYS = {"linkedin", "wuzzuf"}
```

A source that is not in this set still runs the complete discovery pipeline:

```text
fetch
→ filter
→ freshness evaluation
→ SQLite persistence
→ metrics/history
→ NO Telegram delivery
```

Fresh jobs discovered by a shadow source are stored with `send_status = shadow`. When the source is later promoted, historical shadow rows remain suppressed; only jobs discovered **after** promotion can create Telegram deliveries. This prevents a promotion-time backlog flood.

Each source run appends one row to `source_run_history` with fields such as:

```text
status / error / duration_ms
raw_count / filtered_count
inserted_count / refreshed_count
fresh_count / expired_count / uncertain_count
baseline_skipped_count / shadow_eligible_count
coverage_gap / shadow_mode
```

`source_runs` also keeps the latest health snapshot and consecutive failure/empty-run counters. A warning is logged after repeated successful zero-result fetches.

This is the foundation for evaluating future Saudi sources in shadow mode before enabling them. Cross-source exclusive yield and lead-time scoring will be added after the dedup/cluster layer exists; this update intentionally does not invent those metrics yet.

## Telegram Topics

Update 5 uses **one primary topic per job**. A job is no longer copied to General + role + country + source topics.

Active topics:

| Topic key | GitHub secret | Purpose |
|---|---|---|
| `general` | `TOPIC_GENERAL` | Other relevant tech roles that do not match a more specific category |
| `backend` | `TOPIC_BACKEND` | Backend and full-stack |
| `frontend` | `TOPIC_FRONTEND` | Frontend / web UI development |
| `mobile` | `TOPIC_MOBILE` | Android, iOS, Flutter, React Native |
| `ai_ml` | `TOPIC_AI_ML` | Data engineering, analytics, data science, AI/ML |
| `devops` | `TOPIC_DEVOPS` | DevOps, cloud, infrastructure, SRE |
| `qa` | `TOPIC_QA` | QA and software testing |
| `cybersecurity` | `TOPIC_CYBERSECURITY` | Security roles |
| `internships` | `TOPIC_INTERNSHIPS` | Internships, trainees, fresh/entry-level roles |
| `erp` | `TOPIC_ERP` | ERP, SAP, Odoo, Salesforce, Dynamics, business applications |

Routing is deterministic. The first matching category wins, with `Internships & Fresh` intentionally having the highest priority. Generic relevant tech titles such as `Software Engineer` fall back to `general`.

Retired routing dimensions such as `LinkedIn Fresh`, `Egypt`, and `Saudi` are no longer active topics. Existing Telegram forum topics can remain in the group, but the bot will not route new jobs to them.

Country is represented in the card and with lightweight hashtags such as:

```text
#SaudiArabia
#Egypt
#Remote
```

### Routing transition safety

Older bot versions could create several delivery rows for one job. During the Update 5 transition, if a pending job was already successfully posted to a retired topic, the bot marks it delivered instead of creating a new primary-topic duplicate.

## Required GitHub Secrets

Go to **GitHub repository → Settings → Secrets and variables → Actions**.

Core secrets:

```text
TELEGRAM_BOT_TOKEN
TELEGRAM_GROUP_ID
```

Active topic secrets:

```text
TOPIC_GENERAL
TOPIC_BACKEND
TOPIC_FRONTEND
TOPIC_MOBILE
TOPIC_DEVOPS
TOPIC_QA
TOPIC_AI_ML
TOPIC_CYBERSECURITY
TOPIC_INTERNSHIPS
TOPIC_ERP
```

Old secrets such as `TOPIC_LINKEDIN_ALL`, `TOPIC_EGYPT`, `TOPIC_SAUDI`, `TOPIC_MARKETING`, and similar retired topic secrets are no longer read by the workflow. They can be removed from GitHub later if desired.

## Getting a Telegram Topic ID

1. Create or open the Telegram supergroup.
2. Enable Topics.
3. Create the required role topic.
4. Copy/open its topic link.
5. Use the topic thread ID as the matching GitHub secret.

The bot sends using Telegram's `message_thread_id`.

## Freshness Model

The bot does **not** use `published_at > last_run` as its notification rule because search indexing can be delayed.

Instead:

```text
new to us
+
source already baselined
+
fresh enough for that source
=
send eligible
```

Publication evidence is stored with its precision:

```text
published_at_raw
published_at_earliest
published_at_latest
published_at_est
published_precision = EXACT | MINUTE | HOUR | DAY | NONE
first_seen_at
last_seen_at
```

Examples:

- exact ISO timestamp → exact evidence;
- `12 minutes ago` → narrow time interval;
- `1 hour ago` → wider uncertain interval;
- missing/coarse time → source-specific fallback only when safe.

A source's first successful fetch is a **baseline** and never floods Telegram with its existing inventory.

### Current freshness configuration

```text
LINKEDIN_FRESHNESS_SECONDS=3600
WUZZUF_OBSERVATION_MAX_AGE_MINUTES=60
PENDING_SEND_MAX_AGE_MINUTES=60
```

LinkedIn currently requests a rolling recent window with newest-first ordering. WUZZUF can use recent snapshot observation when exact posting time is unavailable. A long source gap disables uncertain freshness fallbacks.

## Telegram Delivery State

Telegram delivery is decoupled from discovery through SQLite delivery rows.

Simplified states:

```text
queued
  ↓
sending
  ├─ sent
  ├─ retry_wait
  ├─ unknown
  ├─ config_error
  └─ failed_permanent
```

Important behavior:

- a delivery is claimed and committed before calling Telegram;
- 429 pauses the supergroup queue and persists `retry_after`;
- transient 5xx/network failures use bounded retries;
- ambiguous read timeouts become `UNKNOWN` instead of being blindly retried;
- formatting errors get one safe plain-text fallback;
- missing/broken topic configuration is treated as `CONFIG_ERROR`;
- deliveries expire after the live-send deadline so stale jobs do not appear later.

Each attempt is recorded in `delivery_attempts` with useful debugging fields such as HTTP status, Telegram error code, description, retry delay, and message ID when available.

## SQLite

`jobs.db` stores:

- normalized job/posting data;
- source job IDs and canonical URLs;
- freshness evidence and decision reason;
- first/last seen times;
- source baseline, shadow/production state, and latest health counters;
- append-only per-source run history and metrics;
- job send status;
- durable topic delivery rows;
- append-only delivery attempt audit rows;
- runtime metadata.

Legacy pending/retry work that is too old is expired instead of replayed.

## Runtime Flow

```text
GitHub Actions
    ↓
restore jobs.db from data branch
    ↓
fetch WUZZUF + LinkedIn
    ↓
quality + geography filtering
    ↓
freshness gate
    ├─ baseline → store, no send
    ├─ fresh + production source → queue
    ├─ fresh + shadow source → store as shadow, no send
    └─ stale/unsafe → expire
    ↓
SQLite upsert
    ↓
choose ONE primary Telegram topic
    ↓
create durable delivery
    ↓
rate-limited Telegram sender
    ↓
persist delivery result/audit
    ↓
save jobs.db to data branch
```

## GitHub Actions

Workflow:

```text
.github/workflows/job_bot.yml
```

Schedule:

```text
every 15 minutes
```

The workflow has a `concurrency` group with `cancel-in-progress: false`, restores SQLite from the `data` branch, runs `main.py`, and writes the updated database back.

Git-backed SQLite is still the current persistence mechanism. The longer-term architecture may move the bot to a persistent host while keeping SQLite.

## Seed Mode

Manual GitHub runs support `seed_mode=true`.

Seed mode stores/baselines jobs without sending them. New source integrations should normally remain in shadow mode across multiple runs before promotion; seed mode is still useful for manual one-time baselining.

## Local Testing

Install dependencies:

```powershell
pip install -r requirements.txt
```

Run tests:

```powershell
python -m unittest discover -s tests -v
```

Run locally from PowerShell:

```powershell
$env:TELEGRAM_BOT_TOKEN="your_bot_token"
$env:TELEGRAM_GROUP_ID="-100xxxxxxxxxx"
$env:TOPIC_GENERAL="1"
$env:TOPIC_BACKEND="2"
$env:TOPIC_FRONTEND="3"
python main.py
```

Seed locally:

```powershell
$env:SEED_MODE="true"
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
│   ├── test_readme.py
│   ├── test_routing.py
│   ├── test_sources_registry.py
│   ├── test_telegram_sender.py
│   ├── test_workflow.py
│   └── test_wuzzuf.py
└── .github/workflows/
    └── job_bot.yml
```

## Operational Notes

- Keep the bot as an admin in the Telegram supergroup.
- Configure all active primary topic secrets before enabling production sends.
- A missing active topic secret causes `CONFIG_ERROR` for jobs assigned to that topic.
- Old Telegram topics do not need to be deleted immediately; they simply stop receiving new jobs.
- Do not publish full job descriptions in the group; cards intentionally stay compact.
- LinkedIn remains a fragile dependency, which is why Saudi source diversification and ATS/company feeds are planned next.
- New Saudi sources should be added to the fetch registry first, observed in shadow mode, and promoted only after their freshness/relevance/reliability metrics look healthy.
