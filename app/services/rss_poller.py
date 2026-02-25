import json
import logging
from datetime import datetime, timezone

import feedparser
import httpx

from app.config import settings
from app.database import get_db, get_setting
from app.services.classifier import classify_tweets

logger = logging.getLogger(__name__)


async def fetch_feed(handle: str) -> list[dict]:
    url = f"{settings.rsshub_base_url}/twitter/user/{handle}"
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch feed for @{handle}: {e}")
            return []

    feed = feedparser.parse(resp.text)
    tweets = []
    for entry in feed.entries:
        tweet_id = entry.get("id") or entry.get("link", "")
        content_html = entry.get("summary", "") or entry.get("description", "")
        content_text = entry.get("title", "")

        # Extract media URLs from enclosures
        media_urls = []
        for enc in entry.get("enclosures", []):
            if enc.get("href"):
                media_urls.append(enc["href"])

        # Parse published date
        published = entry.get("published_parsed")
        published_at = None
        if published:
            from time import mktime
            published_at = datetime.fromtimestamp(
                mktime(published), tz=timezone.utc
            ).isoformat()

        tweets.append({
            "id": tweet_id,
            "author": handle,
            "content": content_html,
            "content_text": content_text,
            "media_urls": json.dumps(media_urls),
            "tweet_url": entry.get("link", ""),
            "published_at": published_at,
        })
    return tweets


async def poll_feeds() -> list[dict]:
    db = await get_db()

    # Get all unique authors from existing tweets + must_read_accounts
    must_read = await get_setting("must_read_accounts") or []
    must_read_handles = {a["handle"].lower().lstrip("@") for a in must_read}

    # Get handles we already track (from existing tweets)
    rows = await db.execute_fetchall("SELECT DISTINCT author FROM tweets")
    known_handles = {row[0].lower() for row in rows}

    all_handles = known_handles | must_read_handles

    if not all_handles:
        logger.info("No handles to poll. Add must_read_accounts in settings.")
        return []

    all_tweets = []
    for handle in all_handles:
        tweets = await fetch_feed(handle)
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
