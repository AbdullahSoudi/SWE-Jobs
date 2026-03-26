# 💻 Programming Jobs Telegram Bot

Automated Telegram bot that aggregates **remote programming jobs worldwide** + **onsite jobs in Egypt & Saudi Arabia** from **15 free sources** and posts them to a Telegram channel every 5 minutes via GitHub Actions.

## 🎯 What it does

- Fetches programming jobs (Software Engineer, Backend, Frontend, DevOps, QA, Mobile, Tutoring)
- **Geo-filtering**: Egypt & Saudi Arabia → all jobs | Rest of world → remote only
- Deduplicates across all sources
- Posts new jobs to Telegram with rich formatting
- Runs on GitHub Actions cron (free)

## 📡 Sources (15)

| # | Source | Type | Coverage |
|---|--------|------|----------|
| 1 | Remotive | API | Remote worldwide |
| 2 | Himalayas | API | Remote worldwide |
| 3 | Jobicy | API | Remote worldwide |
| 4 | RemoteOK | JSON Feed | Remote worldwide |
| 5 | Arbeitnow | API | Europe + Remote |
| 6 | We Work Remotely | RSS (5 feeds) | Remote worldwide |
| 7 | Working Nomads | RSS | Remote worldwide |
| 8 | JSearch/RapidAPI | API | LinkedIn + Indeed + Glassdoor (Global + Egypt + Saudi) |
| 9 | LinkedIn | Guest API | Egypt + Saudi + Remote worldwide |
| 10 | Adzuna | API | Multi-country |
| 11 | The Muse | API | Software Engineering |
| 12 | Findwork.dev | API | Software dev remote |
| 13 | Jooble | API | Global (Egypt + Saudi + Remote) |
| 14 | Reed.co.uk | API | UK + Remote |
| 15 | USAJobs | API | US Gov remote IT |

## 🚀 Setup

### 1. Create Telegram Bot & Channel

1. Create a bot via [@BotFather](https://t.me/BotFather) → get `TELEGRAM_BOT_TOKEN`
2. Create a channel → add bot as admin → get `TELEGRAM_CHANNEL_ID` (e.g., `@your_channel`)

### 2. Get API Keys (all free)

| Key | Where | Required? |
|-----|-------|-----------|
| `RAPIDAPI_KEY` | [RapidAPI JSearch](https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch) | Recommended |
| `ADZUNA_APP_ID` + `ADZUNA_APP_KEY` | [Adzuna Developer](https://developer.adzuna.com/) | Optional |
| `FINDWORK_API_KEY` | [Findwork.dev](https://findwork.dev/developers/) | Optional |
| `JOOBLE_API_KEY` | [Jooble API](https://jooble.org/api/about) | Recommended |
| `REED_API_KEY` | [Reed Developers](https://www.reed.co.uk/developers) | Optional |

### 3. GitHub Repository

```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/programming-jobs-bot.git
git push -u origin main
```

### 4. Add Secrets

Go to **Settings → Secrets → Actions** and add:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHANNEL_ID`
- `RAPIDAPI_KEY`
- `ADZUNA_APP_ID` (optional)
- `ADZUNA_APP_KEY` (optional)
- `FINDWORK_API_KEY` (optional)
- `JOOBLE_API_KEY` (optional)
- `REED_API_KEY` (optional)

### 5. Create data branch

```bash
git checkout --orphan data
echo '[]' > seen_jobs.json
git add seen_jobs.json
git commit -m "Init seen_jobs"
git push origin data
git checkout main
```

### 6. Enable GitHub Actions

The workflow runs automatically every 5 minutes. First run is **seed mode** — it registers all existing jobs without sending, so you don't flood the channel.

## 📁 Project Structure

```
├── main.py                 # Entry point
├── config.py               # Keywords, geo patterns, settings
├── models.py               # Job dataclass + filter logic
├── dedup.py                # Deduplication with seen_jobs.json
├── telegram_sender.py      # HTML message formatting + Telegram API
├── requirements.txt        # requests>=2.31.0
├── sources/
│   ├── __init__.py         # ALL_FETCHERS registry
│   ├── http_utils.py       # Shared HTTP helpers
│   ├── remotive.py         # Remotive API
│   ├── himalayas.py        # Himalayas API
│   ├── jobicy.py           # Jobicy API
│   ├── remoteok.py         # RemoteOK JSON Feed
│   ├── arbeitnow.py        # Arbeitnow API
│   ├── wwr.py              # We Work Remotely RSS (5 feeds)
│   ├── workingnomads.py    # Working Nomads RSS
│   ├── jsearch.py          # JSearch/RapidAPI
│   ├── linkedin.py         # LinkedIn Guest API
│   ├── adzuna.py           # Adzuna API
│   ├── themuse.py          # The Muse API
│   ├── findwork.py         # Findwork.dev API
│   ├── jooble.py           # Jooble API
│   ├── reed.py             # Reed.co.uk API
│   └── usajobs.py          # USAJobs API
└── .github/workflows/
    └── job_bot.yml         # GitHub Actions cron
```

## 🔧 Local Testing

```bash
export TELEGRAM_BOT_TOKEN="your_token"
export TELEGRAM_CHANNEL_ID="@your_channel"
export RAPIDAPI_KEY="your_key"
# ... other keys

python main.py
```

## 📝 License

MIT
