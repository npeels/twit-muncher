import json
import logging
from datetime import datetime, timezone
from time import mktime

import feedparser
import httpx

from app.config import settings
from app.database import get_db, get_setting
from app.services.classifier import classify_tweets

logger = logging.getLogger(__name__)


def _parse_author(entry: dict) -> str:
    """Extract Twitter handle from a feed entry."""
    # feedparser puts author in author_detail.name or author field
    author = ""
    if hasattr(entry, "author_detail") and entry.author_detail.get("name"):
        author = entry.author_detail["name"]
    elif entry.get("author"):
        author = entry["author"]

    # Strip leading @ and whitespace
    return author.lstrip("@").strip()


def _parse_entry(entry, fallback_author: str = "") -> dict:
    tweet_id = entry.get("id") or entry.get("link", "")
    content_html = entry.get("summary", "") or entry.get("description", "")
    content_text = entry.get("title", "")

    author = _parse_author(entry) or fallback_author

    media_urls = []
    for enc in entry.get("enclosures", []):
        if enc.get("href"):
            media_urls.append(enc["href"])

    published = entry.get("published_parsed")
    published_at = None
    if published:
        published_at = datetime.fromtimestamp(
            mktime(published), tz=timezone.utc
        ).isoformat()

    return {
        "id": tweet_id,
        "author": author,
        "content": content_html,
        "content_text": content_text,
        "media_urls": json.dumps(media_urls),
        "tweet_url": entry.get("link", ""),
        "published_at": published_at,
    }


async def fetch_list_feed(list_id: str) -> list[dict]:
    url = f"{settings.rsshub_base_url}/twitter/list/{list_id}"
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        try:
            resp = await client.get(url)
            if resp.status_code in (301, 302, 307, 308):
                logger.error(f"List feed {list_id} redirected to {resp.headers.get('location')} — check RSSHUB_BASE_URL")
                return []
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch list feed {list_id}: {e}")
            return []

    feed = feedparser.parse(resp.text)
    if not feed.entries:
        logger.warning(f"List feed {list_id} returned no entries. Feed title: {feed.feed.get('title', 'unknown')}")
        return []

    tweets = [_parse_entry(e) for e in feed.entries]
    logger.info(f"Fetched {len(tweets)} entries from list {list_id}")
    return tweets


async def poll_feeds() -> list[dict]:
    list_ids = await get_setting("twitter_list_ids") or []

    if not list_ids:
        logger.info("No twitter_list_ids configured. Add list IDs in Settings > Advanced.")
        return []

    all_tweets = []
    for list_id in list_ids:
        tweets = await fetch_list_feed(list_id)
        all_tweets.extend(tweets)

    return all_tweets


async def store_tweets(tweets: list[dict]) -> list[dict]:
    db = await get_db()
    now = datetime.now(timezone.utc).isoformat()
    new_tweets = []

    for tweet in tweets:
        existing = await db.execute_fetchall(
            "SELECT id FROM tweets WHERE id = ?", (tweet["id"],)
        )
        if existing:
            continue

        await db.execute(
            """INSERT INTO tweets (id, author, content, content_text, media_urls, tweet_url, published_at, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                tweet["id"],
                tweet["author"],
                tweet["content"],
                tweet["content_text"],
                tweet["media_urls"],
                tweet["tweet_url"],
                tweet["published_at"],
                now,
            ),
        )
        new_tweets.append(tweet)

    await db.commit()
    logger.info(f"Stored {len(new_tweets)} new tweets out of {len(tweets)} fetched")
    return new_tweets


async def tag_must_reads():
    db = await get_db()
    must_read = await get_setting("must_read_accounts") or []
    must_read_handles = [a["handle"].lower().lstrip("@") for a in must_read]

    if not must_read_handles:
        return

    placeholders = ",".join("?" for _ in must_read_handles)
    await db.execute(
        f"""UPDATE tweets SET category = 'must_read', confidence = 1.0,
            category_reason = 'Must-read account'
            WHERE LOWER(author) IN ({placeholders})
            AND category IS NULL AND briefing_id IS NULL""",
        must_read_handles,
    )
    await db.commit()


async def poll_and_classify():
    logger.info("Starting poll cycle")
    tweets = await poll_feeds()
    new_tweets = await store_tweets(tweets)
    await tag_must_reads()

    # Classify untagged tweets
    db = await get_db()
    rows = await db.execute_fetchall(
        """SELECT id, author, content_text, media_urls
           FROM tweets WHERE category IS NULL AND briefing_id IS NULL"""
    )
    unclassified = [dict(row) for row in rows]

    if unclassified:
        await classify_tweets(unclassified)

    logger.info(f"Poll cycle complete. {len(new_tweets)} new, {len(unclassified)} classified.")
