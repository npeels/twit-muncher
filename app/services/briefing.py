import logging
from datetime import datetime, timezone

from app.database import get_db

logger = logging.getLogger(__name__)


async def generate_briefing() -> int | None:
    db = await get_db()

    # Find tweets not yet assigned to a briefing and already classified
    rows = await db.execute_fetchall(
        """SELECT id FROM tweets
           WHERE briefing_id IS NULL AND category IS NOT NULL
           ORDER BY published_at ASC"""
    )

    if not rows:
        logger.info("No unassigned tweets for briefing")
        return None

    tweet_ids = [row[0] for row in rows]
    now = datetime.now(timezone.utc).isoformat()

    # Get time range
    time_range = await db.execute_fetchall(
        """SELECT MIN(published_at), MAX(published_at)
           FROM tweets WHERE id IN ({})""".format(
            ",".join("?" for _ in tweet_ids)
        ),
        tweet_ids,
    )
    period_start = time_range[0][0] if time_range else now
    period_end = time_range[0][1] if time_range else now

    # Create briefing
    cursor = await db.execute(
        """INSERT INTO briefings (generated_at, period_start, period_end, tweet_count, summary)
           VALUES (?, ?, ?, ?, ?)""",
        (now, period_start, period_end, len(tweet_ids), ""),
    )
    briefing_id = cursor.lastrowid

    # Assign tweets to briefing
    placeholders = ",".join("?" for _ in tweet_ids)
    await db.execute(
        f"UPDATE tweets SET briefing_id = ? WHERE id IN ({placeholders})",
        [briefing_id] + tweet_ids,
    )
    await db.commit()

    logger.info(f"Generated briefing #{briefing_id} with {len(tweet_ids)} tweets")
    return briefing_id
