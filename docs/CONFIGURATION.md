# Configuration

All configuration is done through environment variables. Copy `.env.example` to `.env` for local development, or add them as GitHub Secrets for Actions deployment.

## Database (required)

| Variable | Description | Example |
|----------|-------------|---------|
| `DB_HOST` | Supabase/PostgreSQL host | `db.xxxx.supabase.co` |
| `DB_PORT` | Database port | `6543` |
| `DB_NAME` | Database name | `postgres` |
| `DB_USER` | Database user | `postgres` |
| `DB_PASSWORD` | Database password | — |

The database must have the schema from `supabase/migrations/001_init.sql` applied. This creates the `jobs`, `users`, `bot_runs`, `source_health`, and related tables, plus the `pg_trgm` extension for fuzzy matching.

## Telegram (required)

| Variable | Description | How to get it |
|----------|-------------|---------------|
| `TELEGRAM_BOT_TOKEN` | Bot API token | Create a bot via [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_GROUP_ID` | Group chat ID (negative number) | See [Getting the Group ID](#getting-the-group-id) below |

### Getting the Group ID

1. Add your bot to the Telegram group
2. Send any message in the group
3. Open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
4. Find `"chat":{"id":` — that negative number is your Group ID

## Topic Thread IDs

Each topic in a Telegram supergroup has a thread ID. The thread ID is the number at the end of the topic link (e.g., `t.me/YourGroup/2` -> thread_id is `2`).

| Variable | Topic | Required? |
|----------|-------|-----------|
| `TOPIC_GENERAL` | All Jobs | Recommended |
| `TOPIC_BACKEND` | Backend | Optional |
| `TOPIC_FRONTEND` | Frontend | Optional |
| `TOPIC_MOBILE` | Mobile | Optional |
| `TOPIC_DEVOPS` | DevOps & Cloud | Optional |
| `TOPIC_QA` | QA & Testing | Optional |
| `TOPIC_AI_ML` | AI/ML & Data Science | Optional |
| `TOPIC_CYBERSECURITY` | Cybersecurity | Optional |
| `TOPIC_GAMEDEV` | Game Development | Optional |
| `TOPIC_BLOCKCHAIN` | Blockchain & Web3 | Optional |
| `TOPIC_EGYPT` | Egypt Jobs | Optional |
| `TOPIC_SAUDI` | Saudi Jobs | Optional |
| `TOPIC_INTERNSHIPS` | Internships | Optional |
| `TOPIC_ERP` | ERP & Accounting | Optional |

Topics without a configured thread ID are skipped. You can start with just `TOPIC_GENERAL` and add more later.

### Setting up Telegram Topics

1. Create a **Supergroup** on Telegram
2. Go to group settings and enable **Topics**
3. Create topics for each category you want (Backend, Frontend, etc.)
4. Add the bot as an **Admin** with permission to post in topics
5. Note the thread ID from each topic's link

## API Keys

All API keys are optional. Sources are skipped if their key is absent — the bot works with whatever keys you provide.

| Variable | Source | Where to get it |
|----------|--------|-----------------|
| `RAPIDAPI_KEY` | JSearch (LinkedIn + Indeed + Glassdoor) | [RapidAPI JSearch](https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch) |
| `ADZUNA_APP_ID` | Adzuna | [Adzuna Developer](https://developer.adzuna.com/) |
| `ADZUNA_APP_KEY` | Adzuna | [Adzuna Developer](https://developer.adzuna.com/) |
| `FINDWORK_API_KEY` | Findwork.dev | [Findwork.dev](https://findwork.dev/developers/) |
| `JOOBLE_API_KEY` | Jooble | [Jooble API](https://jooble.org/api/about) |
| `REED_API_KEY` | Reed.co.uk | [Reed Developers](https://www.reed.co.uk/developers) |
| `MUSE_API_KEY` | The Muse | [The Muse API](https://www.themuse.com/developers) |

Sources that don't require keys: Remotive, Himalayas, Jobicy, RemoteOK, Arbeitnow, We Work Remotely, Working Nomads, LinkedIn, USAJobs.

## Admin & Operational

| Variable | Description | Default |
|----------|-------------|---------|
| `ADMIN_TELEGRAM_ID` | Your Telegram user ID (for alert DMs) | — |
| `SEED_MODE` | `true` = register jobs without sending to Telegram | `false` |

Seed mode is useful for the first run — it populates the database without flooding the Telegram group with existing jobs.

## GitHub Actions Secrets

For GitHub Actions deployment, add all the variables above as repository secrets:

1. Go to your repo on GitHub
2. **Settings** > **Secrets and variables** > **Actions**
3. Click **New repository secret** for each variable

The workflow file `.github/workflows/job_bot.yml` maps these secrets to environment variables automatically.

## Dashboard Environment

The React dashboard uses these variables (set in the GitHub Pages deployment workflow):

| Variable | Description |
|----------|-------------|
| `VITE_SUPABASE_URL` | Supabase project URL |
| `VITE_SUPABASE_ANON_KEY` | Supabase anonymous key (read-only) |
| `VITE_API_BASE` | FastAPI backend URL |

## Pipeline Constants

These are hardcoded in the source but can be adjusted:

| Constant | Value | Location | Description |
|----------|-------|----------|-------------|
| `MAX_JOBS_PER_RUN` | 50 | `main.py` | Safety cap per execution |
| `REQUEST_TIMEOUT` | 15s | `main.py` | HTTP request timeout |
| `TELEGRAM_SEND_DELAY` | 3s | `main.py` | Delay between Telegram messages |
| `SCORE_THRESHOLD` | 10 | `core/keywords.py` | Minimum keyword score to pass filter |
| `CIRCUIT_OPEN_FAILURES` | 3 | `core/circuit_breaker.py` | Failures before circuit opens |
| `FUZZY_THRESHOLD` | 0.7 | `core/dedup.py` | pg_trgm similarity threshold |
| `MAX_DMS_PER_USER_PER_HOUR` | 20 | `bot/notifications.py` | DM rate limit per user |
