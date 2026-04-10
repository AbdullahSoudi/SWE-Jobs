"""
Channel/topic routing configuration and display helpers.
"""

import os

# ─── Community Topics ───────────────────────────────────────
# Each topic has: thread_id (from the topic link) + keywords for routing
# A job can go to MULTIPLE topics (e.g. "Flutter Dev in Egypt" → Mobile + Egypt)
# thread_id comes from the topic link: t.me/TechJobs0/2 → thread_id = 2
#
# Set thread IDs via env vars so you don't need to edit code.
# General topic uses thread_id from env, or falls back to None (sends to main chat).

CHANNELS = {
    "general": {
        "thread_env": "TOPIC_GENERAL",
        "name": "💻 All Jobs",
        "match": "ALL",
    },
    "backend": {
        "thread_env": "TOPIC_BACKEND",
        "name": "⚙️ Backend",
        "keywords": [
            "backend", "back-end", "back end", "server-side", "server side",
            "api developer", "api engineer",
            "python developer", "python engineer",
            "java developer", "java engineer",
            "golang", "go developer", "go engineer",
            "rust developer", "rust engineer",
            "ruby developer", "rails developer",
            "php developer", "php engineer",
            "node.js developer", "nodejs developer", "node developer",
            "django", "flask", "fastapi", "spring", "laravel", "express",
            ".net developer", "dotnet developer", "c# developer",
        ],
    },
    "frontend": {
        "thread_env": "TOPIC_FRONTEND",
        "name": "🎨 Frontend",
        "keywords": [
            "frontend", "front-end", "front end",
            "ui developer", "ui engineer",
            "react developer", "react engineer", "next.js",
            "angular developer", "vue developer", "vue.js",
            "javascript developer", "js developer",
            "typescript developer", "ts developer",
            "css", "tailwind", "svelte",
            "web developer", "web engineer",
        ],
    },
    "mobile": {
        "thread_env": "TOPIC_MOBILE",
        "name": "📱 Mobile",
        "keywords": [
            "mobile developer", "mobile engineer", "mobile application",
            "ios developer", "ios engineer",
            "android developer", "android engineer",
            "flutter developer", "flutter engineer", "flutter",
            "react native developer", "react native engineer", "react native",
            "swift developer", "kotlin developer",
            "mobile app developer", "app developer",
            "swiftui", "jetpack compose", "dart developer",
        ],
    },
    "devops": {
        "thread_env": "TOPIC_DEVOPS",
        "name": "🚀 DevOps & Cloud",
        "keywords": [
            "devops", "dev ops", "dev-ops",
            "sre", "site reliability",
            "cloud engineer", "cloud developer", "cloud architect",
            "infrastructure engineer", "platform engineer",
            "kubernetes", "docker", "terraform", "ansible",
            "aws engineer", "azure engineer", "gcp engineer",
            "ci/cd", "jenkins", "github actions",
            "linux engineer", "systems engineer", "systems administrator",
            "network engineer", "network administrator",
        ],
    },
    "qa": {
        "thread_env": "TOPIC_QA",
        "name": "🧪 QA & Testing",
        "keywords": [
            "qa engineer", "qa developer", "quality assurance",
            "test engineer", "sdet", "software tester",
            "automation engineer", "test automation",
            "qa analyst", "qa lead", "qa manager",
            "selenium", "cypress", "playwright",
            "manual testing", "performance testing",
            "load testing", "stress testing",
        ],
    },
    "ai_ml": {
        "thread_env": "TOPIC_AI_ML",
        "name": "🤖 AI/ML & Data Science",
        "keywords": [
            "machine learning", "ml engineer", "ml developer",
            "ai engineer", "ai developer", "artificial intelligence",
            "deep learning", "nlp engineer", "computer vision",
            "data scientist", "data science",
            "data analyst", "data analytics",
            "data engineer", "etl developer", "data pipeline",
            "big data", "hadoop", "spark engineer",
            "llm", "generative ai", "prompt engineer",
            "tensorflow", "pytorch", "hugging face",
        ],
    },
    "cybersecurity": {
        "thread_env": "TOPIC_CYBERSECURITY",
        "name": "🔒 Cybersecurity",
        "keywords": [
            "security engineer", "appsec", "application security",
            "cybersecurity", "cyber security", "infosec",
            "penetration tester", "pen tester", "security analyst",
            "soc analyst", "security architect",
            "vulnerability", "ethical hacker",
            "security operations", "threat",
        ],
    },
    "gamedev": {
        "thread_env": "TOPIC_GAMEDEV",
        "name": "🎮 Game Development",
        "keywords": [
            "game developer", "game engineer", "game programmer",
            "unity developer", "unreal developer",
            "game designer", "gameplay programmer",
            "game studio", "gaming",
            "godot", "cocos2d",
        ],
    },
    "blockchain": {
        "thread_env": "TOPIC_BLOCKCHAIN",
        "name": "⛓️ Blockchain & Web3",
        "keywords": [
            "blockchain developer", "blockchain engineer",
            "smart contract", "solidity developer", "solidity",
            "web3 developer", "web3 engineer", "web3",
            "crypto developer", "defi", "nft",
            "ethereum", "solana developer",
        ],
    },
    "fullstack": {
        "thread_env": "TOPIC_FULLSTACK",
        "name": "🔄 Full Stack",
        "keywords": [
            "full-stack", "full stack", "fullstack",
            "full-stack developer", "full stack developer", "fullstack developer",
            "full-stack engineer", "full stack engineer", "fullstack engineer",
            "mern", "mean stack", "lamp stack",
            "t-shaped developer",
        ],
    },
    "egypt": {
        "thread_env": "TOPIC_EGYPT",
        "name": "🇪🇬 Egypt Jobs",
        "match": "GEO_EGYPT",
    },
    "saudi": {
        "thread_env": "TOPIC_SAUDI",
        "name": "🇸🇦 Saudi Jobs",
        "match": "GEO_SAUDI",
    },
    "internships": {
        "thread_env": "TOPIC_INTERNSHIPS",
        "name": "🎓 Internships",
        "keywords": [
            "intern", "internship", "trainee", "training program",
            "graduate program", "junior", "entry level", "entry-level",
            "fresh graduate", "fresh grad", "co-op",
            "apprentice", "apprenticeship",
            "working student", "student developer",
        ],
    },
    "erp": {
        "thread_env": "TOPIC_ERP",
        "name": "🏢 ERP & Accounting",
        "keywords": [
            "erp developer", "erp consultant", "erp engineer", "erp implementation",
            "odoo developer", "odoo engineer", "odoo consultant", "odoo implementation",
            "sap developer", "sap consultant", "sap engineer", "sap abap",
            "sap fiori", "sap hana", "sap basis", "sap functional",
            "salesforce developer", "salesforce engineer", "salesforce admin",
            "salesforce consultant",
            "dynamics developer", "dynamics consultant", "dynamics 365",
            "oracle ebs", "oracle apps", "oracle financials",
            "netsuite developer", "netsuite consultant", "netsuite admin",
            "quickbooks developer",
            "accounting software", "financial software",
            "crm developer", "crm consultant",
        ],
    },
}


def get_topic_thread_id(channel_key: str) -> int | None:
    """Get the topic thread_id from environment variable."""
    ch = CHANNELS.get(channel_key, {})
    env_var = ch.get("thread_env", "")
    val = os.getenv(env_var, "")
    if val:
        try:
            return int(val)
        except ValueError:
            return None
    return None


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
    "aws": "☁️",
    "azure": "☁️",
    "qa": "🧪",
    "test": "🧪",
    "quality": "🧪",
    "mobile": "📱",
    "ios": "🍎",
    "android": "🤖",
    "flutter": "🦋",
    "react native": "📱",
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
    "data engineer": "📊",
    "data scien": "📊",
    "machine learning": "🤖",
    "ml ": "🤖",
    "ai ": "🤖",
    "artificial intel": "🤖",
    "deep learning": "🧠",
    "blockchain": "⛓️",
    "web3": "⛓️",
    "solidity": "⛓️",
    "game dev": "🎮",
    "unity": "🎮",
    "unreal": "🎮",
    "security": "🔒",
    "cyber": "🔒",
    "penetration": "🔒",
    "embedded": "🔌",
    "iot": "🔌",
    "firmware": "🔌",
    "database": "🗄️",
    "dba": "🗄️",
    "sql": "🗄️",
    "wordpress": "📝",
    "shopify": "🛒",
    "salesforce": "☁️",
    "sap": "🏢",
    "network": "🌐",
    "instructor": "📚",
    "tutor": "📚",
    "teacher": "📚",
    "mentor": "📚",
    "senior": "👨‍💻",
    "junior": "🌱",
    "lead": "⭐",
    "principal": "⭐",
    "staff": "⭐",
    "intern": "🎓",
    "architect": "🏗️",
    "erp": "🏢",
    "odoo": "🏢",
    "sap": "🏢",
    "salesforce": "☁️",
    "dynamics": "🏢",
    "oracle": "🏢",
    "netsuite": "🏢",
    "accounting": "🏢",
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
    "devitjobs": "DevITjobs",
    "stackoverflow": "StackOverflow",
    "greenhouse": "Greenhouse",
    "lever": "Lever",
    "workable": "Workable",
    "recruitee": "Recruitee",
    "ashby": "Ashby",
    "smartrecruiters": "SmartRecruiters",
}
