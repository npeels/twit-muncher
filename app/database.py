import json
import os

import aiosqlite

from app.config import settings

_db: aiosqlite.Connection | None = None

DEFAULT_CATEGORIES = [
    {
        "key": "must_read",
        "label": "Must Read",
        "color": "#e74c3c",
        "expanded_by_default": True,
        "description_for_llm": "High-signal tweets from key accounts. Important market news, breaking developments, or insights you can't afford to miss.",
    },
    {
        "key": "stock_ideas",
        "label": "Stock Ideas",
        "color": "#3498db",
        "expanded_by_default": True,
        "description_for_llm": "Specific stock picks, trade ideas, earnings analysis, or investment theses worth evaluating.",
    },
    {
        "key": "viral",
        "label": "Viral / Trending",
        "color": "#9b59b6",
        "expanded_by_default": True,
        "description_for_llm": "Widely shared or discussed tweets. Hot takes, viral threads, or trending topics getting significant engagement.",
    },
    {
        "key": "charts",
        "label": "Charts & Data",
        "color": "#2ecc71",
        "expanded_by_default": True,
        "description_for_llm": "Technical analysis, data visualizations, charts, or statistical insights. Often has media attachments.",
    },
    {
        "key": "funny",
        "label": "Funny / Entertainment",
        "color": "#f39c12",
        "expanded_by_default": False,
        "description_for_llm": "Humor, memes, entertaining content. Good for a laugh but not actionable.",
    },
    {
        "key": "skip",
        "label": "Skip",
        "color": "#95a5a6",
        "expanded_by_default": False,
        "description_for_llm": "Low-value content: self-promotion, ads, engagement bait, repetitive commentary, or anything not worth reading. Be liberal with this category.",
    },
]

DEFAULT_CLASSIFICATION_PROMPT = """You are a tweet classifier for a financial/tech Twitter briefing service.

Classify each tweet into exactly one category. Return JSON array.

Categories:
{categories_block}

Rules:
- Be liberal with "skip" — most tweets are noise
- If a tweet has media (has_media=true) and mentions charts/data/TA, classify as "charts"
- Must-read is reserved for truly important, can't-miss content
- Retweets of news with no added commentary → skip
- Engagement bait, self-promotion, ads → skip
- When in doubt between two categories, pick the more conservative one

For each tweet, return:
{{"id": "<tweet_id>", "category": "<category_key>", "confidence": <0.0-1.0>, "reason": "<brief reason>"}}

Return a JSON array of these objects, nothing else."""


def generate_classification_prompt(categories: list[dict]) -> str:
    lines = []
    for cat in categories:
        if cat["key"] == "must_read":
            continue
        lines.append(f'- "{cat["key"]}": {cat["description_for_llm"]}')
    categories_block = "\n".join(lines)
    return DEFAULT_CLASSIFICATION_PROMPT.format(categories_block=categories_block)


DEFAULT_SETTINGS = {
    "twitter_list_ids": ["2026289137762898094"],
    "must_read_accounts": [],
    "briefing_times": ["09:00", "16:00"],
    "briefing_days": ["mon", "tue", "wed", "thu", "fri"],
    "poll_interval_minutes": 12,
    "categories": DEFAULT_CATEGORIES,
    "classification_prompt": generate_classification_prompt(DEFAULT_CATEGORIES),
    "gemini_model": "gemini-2.5-flash",
}


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        os.makedirs(os.path.dirname(settings.database_path) or ".", exist_ok=True)
        _db = await aiosqlite.connect(settings.database_path)
        _db.row_factory = aiosqlite.Row
        await _db.execute("PRAGMA journal_mode=WAL")
        await _db.execute("PRAGMA foreign_keys=ON")
        await _create_tables(_db)
        await _seed_settings(_db)
    return _db


async def close_db():
    global _db
    if _db is not None:
        await _db.close()
        _db = None


async def _create_tables(db: aiosqlite.Connection):
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS tweets (
            id TEXT PRIMARY KEY,
            author TEXT NOT NULL,
            content TEXT,
            content_text TEXT,
            media_urls TEXT DEFAULT '[]',
            tweet_url TEXT,
            published_at TEXT,
            fetched_at TEXT NOT NULL,
            category TEXT,
            category_reason TEXT,
            confidence REAL,
            briefing_id INTEGER,
            FOREIGN KEY (briefing_id) REFERENCES briefings(id)
        );

        CREATE TABLE IF NOT EXISTS briefings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            generated_at TEXT NOT NULL,
            period_start TEXT,
            period_end TEXT,
            tweet_count INTEGER DEFAULT 0,
            summary TEXT
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_tweets_category ON tweets(category);
        CREATE INDEX IF NOT EXISTS idx_tweets_briefing_id ON tweets(briefing_id);
        CREATE INDEX IF NOT EXISTS idx_tweets_published_at ON tweets(published_at);
    """)


async def _seed_settings(db: aiosqlite.Connection):
    for key, value in DEFAULT_SETTINGS.items():
        await db.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (key, json.dumps(value)),
        )
    await db.commit()


async def get_setting(key: str):
    db = await get_db()
    row = await db.execute_fetchall(
        "SELECT value FROM settings WHERE key = ?", (key,)
    )
    if row:
        return json.loads(row[0][0])
    return DEFAULT_SETTINGS.get(key)


async def set_setting(key: str, value):
    db = await get_db()
    await db.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (key, json.dumps(value)),
    )
    await db.commit()


async def get_all_settings() -> dict:
    db = await get_db()
    rows = await db.execute_fetchall("SELECT key, value FROM settings")
    result = {}
    for row in rows:
        result[row[0]] = json.loads(row[1])
    return result
