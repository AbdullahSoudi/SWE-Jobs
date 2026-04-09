# SWE-Jobs

Automated job aggregation bot that collects programming jobs from **15 free sources**, enriches them with salary/seniority data, and routes them to specialized **Telegram community topics** — running every 5 minutes on GitHub Actions at zero cost.

## Features

- **15 job sources** — Remotive, LinkedIn, We Work Remotely, Adzuna, USAJobs, and more
- **Smart routing** — each job is auto-routed to matching topic(s) across 14 categories
- **Weighted keyword filtering** — 253 include keywords scored against 54 exclude keywords
- **Geo-intelligence** — Egypt & Saudi Arabia get all jobs; rest of world gets remote only
- **Fuzzy deduplication** — PostgreSQL trigram similarity (pg_trgm) catches near-duplicates
- **Circuit breaker** — auto-disables failing sources, recovers automatically
- **Salary parsing** — extracts and normalizes salary ranges from free text
- **Seniority detection** — classifies jobs as intern/junior/mid/senior/lead/executive
- **Personalized DM alerts** — subscribers get notified based on their preferences
- **Interactive Telegram bot** — commands for search, subscribe, save, stats
- **Web dashboard** — React app with search, statistics, salary insights, skill trends
- **REST API** — FastAPI backend with rate limiting
- **Admin monitoring** — alerts on zero-job runs, slow runs, circuit breaks, daily digest
- **100% free** — uses only free APIs + GitHub Actions

## Architecture

```
GitHub Actions (every 5 min)
        |
        v
  +-- main.py -------------------------------------------+
  |                                                      |
  |  1. Fetch ---- 15 sources (with circuit breaker)     |
  |  2. Enrich --- salary, seniority, country, topics    |
  |  3. Filter --- keyword scoring + geo-filter          |
  |  4. Dedup ---- URL exact + pg_trgm fuzzy             |
  |  5. Insert --- Supabase PostgreSQL                   |
  |  6. Send ----- Telegram multi-topic routing          |
  |  7. Notify --- personalized DM alerts                |
  |  8. Monitor -- alerts + circuit breaker health       |
  |                                                      |
  +------------------------------------------------------+
        |                          |
        v                          v
   Telegram Bot              Web Dashboard
   (commands, callbacks)     (React + FastAPI)
```

## Sources

| # | Source | Type | Coverage |
|---|--------|------|----------|
| 1 | Remotive | API | Remote worldwide |
| 2 | Himalayas | API | Remote worldwide |
| 3 | Jobicy | API | Remote worldwide |
| 4 | RemoteOK | JSON Feed | Remote worldwide |
| 5 | Arbeitnow | API | Europe + Remote |
| 6 | We Work Remotely | RSS (5 feeds) | Remote worldwide |
| 7 | Working Nomads | API/RSS | Remote worldwide |
| 8 | JSearch/RapidAPI | API | LinkedIn + Indeed + Glassdoor |
| 9 | LinkedIn | Guest API | Egypt + Saudi + Remote worldwide |
| 10 | Adzuna | API | Multi-country (GB, US, DE) |
| 11 | The Muse | API | Software Engineering |
| 12 | Findwork.dev | API | Software dev remote |
| 13 | Jooble | API | Egypt + Saudi + Remote |
| 14 | Reed.co.uk | API | UK + Remote |
| 15 | USAJobs | API | US Gov remote IT |

Sources requiring API keys are skipped silently if the key is absent.

## Telegram Topics (14)

Each job is routed to all matching topics automatically:

| Topic | What goes there |
|-------|----------------|
| All Jobs | Everything |
| Backend | Backend, Full-Stack, API, Django, Node.js, Python, Java |
| Frontend | Frontend, React, Angular, Vue, TypeScript, CSS |
| Mobile | Flutter, React Native, iOS, Android, Swift, Kotlin |
| DevOps & Cloud | DevOps, SRE, Kubernetes, Docker, AWS, Azure, GCP |
| QA & Testing | QA, SDET, Selenium, Cypress, Playwright |
| AI/ML & Data | ML Engineer, Data Scientist, NLP, LLM, Deep Learning |
| Cybersecurity | Security, Penetration Testing, SOC, InfoSec |
| Game Dev | Unity, Unreal, Godot, Gameplay Programming |
| Blockchain & Web3 | Solidity, Smart Contracts, DeFi, Web3 |
| Egypt Jobs | All jobs located in Egypt (geo-matched) |
| Saudi Jobs | All jobs located in Saudi Arabia (geo-matched) |
| Internships | Internships, Trainee, Entry Level, Fresh Grad |
| ERP & Accounting | Odoo, SAP, Salesforce, Oracle, Dynamics |

**Routing examples:**
- `Flutter Developer in Cairo` -> General + Mobile + Egypt
- `Full Stack Developer` -> General + Backend + Frontend
- `ML Engineer Remote` -> General + AI/ML
- `Software Intern in Egypt` -> General + Egypt + Internships

## Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL database ([Supabase](https://supabase.com/) free tier works)
- Telegram bot token from [@BotFather](https://t.me/BotFather)

### Local Setup

```bash
# Clone and setup
git clone https://github.com/YOUR_USERNAME/SWE-Jobs.git
cd SWE-Jobs
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your database credentials, Telegram token, and API keys

# Run database migration
# Execute supabase/migrations/001_init.sql against your database

# Run the bot
python main.py
```

### Dashboard (optional)

```bash
cd dashboard
npm install
npm run dev     # Development server at http://localhost:5173
```

### API Server (optional)

```bash
uvicorn api.app:create_app --reload  # API at http://localhost:8000
```

### GitHub Actions Deployment

1. Add secrets in **Settings > Secrets > Actions** (see [Configuration](docs/CONFIGURATION.md))
2. The bot runs automatically every 5 minutes via the workflow in `.github/workflows/job_bot.yml`
3. The dashboard deploys to GitHub Pages on push to `main`

## Project Structure

```
SWE-Jobs/
├── main.py                     # Pipeline entry point
├── config.py                   # Legacy config (v1 compat)
├── requirements.txt            # Python dependencies
├── .env.example                # Environment variable template
│
├── core/                       # Core business logic
│   ├── config.py               # Environment & settings
│   ├── models.py               # Job dataclass
│   ├── keywords.py             # Include/exclude keyword lists
│   ├── channels.py             # 14 topic definitions + routing
│   ├── geo.py                  # Egypt/Saudi/Remote patterns
│   ├── db.py                   # PostgreSQL access layer
│   ├── filtering.py            # Keyword scoring + geo-filter
│   ├── enrichment.py           # Salary, seniority, country, topics
│   ├── dedup.py                # URL exact + fuzzy deduplication
│   ├── salary_parser.py        # Salary text -> min/max/currency
│   ├── seniority.py            # Seniority level detection
│   ├── country_detector.py     # Location -> country code
│   ├── circuit_breaker.py      # Per-source retry + circuit breaker
│   ├── monitoring.py           # Alerts + daily digest
│   └── logging_config.py       # Structured JSON logging
│
├── sources/                    # Job source fetchers (15)
│   ├── __init__.py             # ALL_FETCHERS registry
│   ├── http_utils.py           # Shared HTTP helpers
│   ├── remotive.py             # Remotive API
│   ├── himalayas.py            # Himalayas API
│   ├── jobicy.py               # Jobicy API
│   ├── remoteok.py             # RemoteOK JSON Feed
│   ├── arbeitnow.py            # Arbeitnow API
│   ├── wwr.py                  # We Work Remotely RSS
│   ├── workingnomads.py        # Working Nomads API
│   ├── jsearch.py              # JSearch/RapidAPI
│   ├── linkedin.py             # LinkedIn Guest API
│   ├── adzuna.py               # Adzuna API
│   ├── themuse.py              # The Muse API
│   ├── findwork.py             # Findwork.dev API
│   ├── jooble.py               # Jooble API
│   ├── reed.py                 # Reed.co.uk API
│   └── usajobs.py              # USAJobs API
│
├── bot/                        # Telegram bot
│   ├── app.py                  # Bot application setup
│   ├── commands.py             # /start, /search, /subscribe, etc.
│   ├── callbacks.py            # Inline button handlers
│   ├── keyboards.py            # Inline keyboard layouts
│   ├── sender.py               # Job message formatting + sending
│   └── notifications.py        # Personalized DM alerts
│
├── api/                        # REST API (FastAPI)
│   ├── app.py                  # App factory + CORS
│   ├── middleware.py           # Rate limiting
│   ├── routes_jobs.py          # /api/jobs/search
│   └── routes_stats.py         # /api/stats, /api/salary, /api/trends
│
├── dashboard/                  # Web frontend (React + Vite)
│   └── src/
│       ├── pages/              # Home, Stats, Salary, Trends
│       └── components/         # Shared UI components
│
├── supabase/
│   └── migrations/
│       └── 001_init.sql        # Database schema
│
├── tests/                      # Unit tests
│   ├── test_models.py
│   ├── test_db.py
│   ├── test_filtering.py
│   ├── test_enrichment.py
│   ├── test_dedup.py
│   ├── test_salary_parser.py
│   ├── test_seniority.py
│   ├── test_country_detector.py
│   └── test_circuit_breaker.py
│
├── scripts/
│   └── migrate_seen_jobs.py    # v1 -> v2 migration helper
│
├── .github/workflows/
│   ├── job_bot.yml             # Main bot (cron: */5 * * * *)
│   ├── deploy_dashboard.yml    # Dashboard -> GitHub Pages
│   └── archive_jobs.yml        # Periodic job archival
│
└── docs/                       # Documentation
    ├── CONFIGURATION.md        # All environment variables
    ├── ARCHITECTURE.md         # System design deep-dive
    └── ADDING_SOURCES.md       # Guide to adding new job sources
```

## Configuration

See [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for all environment variables, API keys, and topic setup.

## Documentation

| Document | Description |
|----------|-------------|
| [Configuration](docs/CONFIGURATION.md) | Environment variables, API keys, Telegram setup |
| [Architecture](docs/ARCHITECTURE.md) | System design, pipeline, database schema |
| [Adding Sources](docs/ADDING_SOURCES.md) | Step-by-step guide to add a new job source |

## Running Tests

```bash
python -m pytest tests/ -v
```

## License

MIT
