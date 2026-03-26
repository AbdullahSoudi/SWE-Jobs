"""
Configuration for Programming Jobs Telegram Bot.
Keywords, geo-filtering rules, and settings.
"""

import os

# ─── Telegram ───────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "")
TELEGRAM_SEND_DELAY = 3  # seconds between messages

# ─── API Keys ───────────────────────────────────────────────
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "")
ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY", "")
FINDWORK_API_KEY = os.getenv("FINDWORK_API_KEY", "")
JOOBLE_API_KEY = os.getenv("JOOBLE_API_KEY", "")
REED_API_KEY = os.getenv("REED_API_KEY", "")
MUSE_API_KEY = os.getenv("MUSE_API_KEY", "")

# ─── Geo-filtering ──────────────────────────────────────────
# Jobs in these countries pass regardless of remote/onsite
ALLOWED_ONSITE_COUNTRIES = {"egypt", "مصر", "saudi arabia", "saudi", "ksa", "السعودية"}

# Patterns that indicate a location is in Egypt
EGYPT_PATTERNS = {
    "egypt", "مصر", "cairo", "القاهرة", "alexandria", "الإسكندرية",
    "giza", "الجيزة", "minya", "المنيا", "mansoura", "المنصورة",
    "tanta", "طنطا", "aswan", "أسوان", "luxor", "الأقصر",
    "port said", "بورسعيد", "suez", "السويس", "ismailia", "الإسماعيلية",
    "fayoum", "الفيوم", "zagazig", "الزقازيق", "damanhur", "دمنهور",
    "beni suef", "بني سويف", "sohag", "سوهاج", "asyut", "أسيوط",
    "qena", "قنا", "hurghada", "الغردقة", "sharm el sheikh",
    "new cairo", "6th of october", "6 october", "smart village",
    "new capital", "العاصمة الإدارية", "nasr city", "مدينة نصر",
    "maadi", "المعادي", "heliopolis", "مصر الجديدة", "dokki", "الدقي",
    "mohandessin", "المهندسين",
}

# Patterns that indicate a location is in Saudi Arabia
SAUDI_PATTERNS = {
    "saudi arabia", "saudi", "ksa", "السعودية", "المملكة العربية السعودية",
    "riyadh", "الرياض", "jeddah", "جدة", "mecca", "مكة",
    "medina", "المدينة", "dammam", "الدمام", "khobar", "الخبر",
    "dhahran", "الظهران", "tabuk", "تبوك", "abha", "أبها",
    "taif", "الطائف", "jubail", "الجبيل", "yanbu", "ينبع",
    "neom", "نيوم", "qassim", "القصيم", "hail", "حائل",
    "jazan", "جازان", "najran", "نجران", "al kharj", "الخرج",
}

# Patterns that indicate a job is remote
REMOTE_PATTERNS = {
    "remote", "anywhere", "worldwide", "work from home", "wfh",
    "distributed", "global", "fully remote", "100% remote",
    "remote-friendly", "location independent", "عن بعد",
}

# ─── Job Keywords ────────────────────────────────────────────
# Job MUST contain at least one of these (case-insensitive, checked in title + tags)
INCLUDE_KEYWORDS = [
    # Software Engineering
    "software engineer", "software developer", "software development",
    "swe", "sde",
    # Backend
    "backend", "back-end", "back end",
    "server-side", "server side",
    # Frontend
    "frontend", "front-end", "front end",
    "ui developer", "ui engineer",
    # Full-Stack
    "full-stack", "full stack", "fullstack",
    # DevOps / SRE / Cloud
    "devops", "dev ops", "dev-ops",
    "sre", "site reliability",
    "cloud engineer", "cloud developer",
    "infrastructure engineer", "platform engineer",
    # QA / Testing
    "qa engineer", "qa developer", "quality assurance",
    "test engineer", "sdet", "software tester",
    "automation engineer", "test automation",
    # Mobile
    "mobile developer", "mobile engineer",
    "ios developer", "ios engineer",
    "android developer", "android engineer",
    "flutter developer", "react native developer",
    # Web Development
    "web developer", "web engineer",
    # Programming Languages (as job titles)
    "python developer", "python engineer",
    "java developer", "java engineer",
    "javascript developer", "js developer",
    "typescript developer", "ts developer",
    "golang developer", "go developer", "go engineer",
    "rust developer", "rust engineer",
    "ruby developer", "ruby engineer",
    "php developer", "php engineer",
    "c# developer", ".net developer", "dotnet developer",
    "c++ developer", "cpp developer",
    "kotlin developer", "swift developer",
    "node.js developer", "nodejs developer", "node developer",
    "react developer", "react engineer",
    "angular developer", "vue developer",
    "django developer", "flask developer",
    "spring developer", "laravel developer",
    # Data Engineering
    "data engineer", "etl developer",
    # Security
    "security engineer", "appsec", "application security",
    # Teaching / Tutoring
    "coding instructor", "programming instructor",
    "coding tutor", "programming tutor",
    "coding teacher", "programming teacher",
    "bootcamp instructor", "technical instructor",
    "computer science instructor", "cs instructor",
    # General
    "programmer", "developer", "engineer",
]

# Job is EXCLUDED if it contains any of these (case-insensitive)
EXCLUDE_KEYWORDS = [
    # Non-programming roles
    "graphic design", "ui/ux design", "ux design", "ux researcher",
    "product design", "visual design", "brand design",
    "marketing", "sales", "account manager", "account executive",
    "recruiter", "talent acquisition", "hr manager", "human resources",
    "customer support", "customer service", "customer success",
    "content writer", "copywriter", "technical writer",
    "project manager", "program manager", "scrum master",
    "product manager", "product owner",
    "business analyst", "business development",
    "financial analyst", "accountant", "bookkeeper",
    "office manager", "administrative",
    "data entry", "virtual assistant",
    # Hardware / Non-software engineering
    "mechanical engineer", "electrical engineer", "civil engineer",
    "chemical engineer", "structural engineer",
    "hardware engineer", "pcb", "firmware",
    # Medical / Other
    "medical coder", "billing coder", "clinical",
    "nurse", "physician", "pharmacist",
]

# ─── Emoji Map ───────────────────────────────────────────────
# Maps keywords in job title/tags to emoji
EMOJI_MAP = {
    "backend": "⚙️",
    "back-end": "⚙️",
    "frontend": "🎨",
    "front-end": "🎨",
    "full-stack": "🔄",
    "fullstack": "🔄",
    "devops": "🚀",
    "sre": "🚀",
    "cloud": "☁️",
    "qa": "🧪",
    "test": "🧪",
    "quality": "🧪",
    "mobile": "📱",
    "ios": "🍎",
    "android": "🤖",
    "python": "🐍",
    "java": "☕",
    "javascript": "🟨",
    "typescript": "🔷",
    "react": "⚛️",
    "node": "🟩",
    "golang": "🐹",
    "rust": "🦀",
    "ruby": "💎",
    "php": "🐘",
    ".net": "🟣",
    "c#": "🟣",
    "c++": "🔵",
    "swift": "🍎",
    "kotlin": "🟠",
    "flutter": "🦋",
    "data engineer": "📊",
    "security": "🔒",
    "instructor": "📚",
    "tutor": "📚",
    "teacher": "📚",
    "senior": "👨‍💻",
    "junior": "🌱",
    "lead": "⭐",
    "intern": "🎓",
    "remote": "🌍",
    "egypt": "🇪🇬",
    "مصر": "🇪🇬",
    "cairo": "🇪🇬",
    "saudi": "🇸🇦",
    "riyadh": "🇸🇦",
    "jeddah": "🇸🇦",
}

# Default emoji if no match
DEFAULT_EMOJI = "💻"

# ─── Source Display Names ────────────────────────────────────
SOURCE_DISPLAY = {
    "remotive": "Remotive",
    "himalayas": "Himalayas",
    "jobicy": "Jobicy",
    "remoteok": "RemoteOK",
    "arbeitnow": "Arbeitnow",
    "wwr": "We Work Remotely",
    "workingnomads": "Working Nomads",
    "jsearch": None,  # Uses original source (LinkedIn, Indeed, etc.)
    "linkedin": "LinkedIn",
    "adzuna": "Adzuna",
    "themuse": "The Muse",
    "findwork": "Findwork",
    "jooble": "Jooble",
    "reed": "Reed",
    "careerjet": "Careerjet",
    "usajobs": "USAJobs",
}

# ─── Misc ────────────────────────────────────────────────────
SEEN_JOBS_FILE = "seen_jobs.json"
MAX_JOBS_PER_RUN = 50  # safety cap per run
REQUEST_TIMEOUT = 15   # seconds
SEED_MODE_ENV = "SEED_MODE"  # env var to force seed mode
