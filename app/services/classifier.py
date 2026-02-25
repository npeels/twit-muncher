import json
import logging

from google import genai

from app.config import settings
from app.database import get_db, get_setting

logger = logging.getLogger(__name__)

BATCH_SIZE = 25


async def classify_tweets(tweets: list[dict]):
    if not tweets:
        return

    if not settings.gemini_api_key:
        logger.warning("No GEMINI_API_KEY set, skipping classification")
        return

    prompt = await get_setting("classification_prompt")
    model = await get_setting("gemini_model") or "gemini-2.5-flash"

    client = genai.Client(api_key=settings.gemini_api_key)

    # Process in batches
    for i in range(0, len(tweets), BATCH_SIZE):
        batch = tweets[i : i + BATCH_SIZE]
        await _classify_batch(client, model, prompt, batch)


async def _classify_batch(
    client: genai.Client,
    model: str,
    system_prompt: str,
    tweets: list[dict],
):
    db = await get_db()

    # Build user message with tweets
    tweet_items = []
    for t in tweets:
        media_urls = t.get("media_urls", "[]")
        if isinstance(media_urls, str):
            try:
                media_urls = json.loads(media_urls)
            except json.JSONDecodeError:
                media_urls = []
        has_media = len(media_urls) > 0

        tweet_items.append({
            "id": t["id"],
            "author": t.get("author", ""),
            "text": t.get("content_text", ""),
            "has_media": has_media,
        })

    user_msg = json.dumps(tweet_items, indent=2)

    try:
        response = client.models.generate_content(
            model=model,
            contents=user_msg,
            config=genai.types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.1,
                response_mime_type="application/json",
            ),
        )

        text = response.text.strip()
        results = json.loads(text)

        if isinstance(results, dict) and "classifications" in results:
            results = results["classifications"]

        for item in results:
            tweet_id = item.get("id")
            category = item.get("category")
            confidence = item.get("confidence", 0.5)
            reason = item.get("reason", "")

            if tweet_id and category:
                await db.execute(
                    """UPDATE tweets SET category = ?, confidence = ?,
                       category_reason = ? WHERE id = ? AND category IS NULL""",
                    (category, confidence, reason, tweet_id),
                )

        await db.commit()
        logger.info(f"Classified batch of {len(tweets)} tweets")

    except Exception as e:
        logger.error(f"Classification failed: {e}")
