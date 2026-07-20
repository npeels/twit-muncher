import json
import logging

import httpx

from app.config import settings
from app.database import get_db, get_setting

logger = logging.getLogger(__name__)

BATCH_SIZE = 25
DEFAULT_OPENROUTER_MODEL = "meta-llama/llama-3.1-8b-instruct"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


async def classify_tweets(tweets: list[dict]):
    if not tweets:
        return

    if not settings.openrouter_api_key:
        logger.warning("No OPENROUTER_API_KEY set, skipping classification")
        return

    prompt = await get_setting("classification_prompt")
    model = await get_setting("openrouter_model") or DEFAULT_OPENROUTER_MODEL

    for i in range(0, len(tweets), BATCH_SIZE):
        batch = tweets[i : i + BATCH_SIZE]
        await _classify_batch_openrouter(model, prompt, batch)


async def _classify_batch_openrouter(
    model: str,
    system_prompt: str,
    batch: list[dict],
):
    db = await get_db()

    tweet_items = []
    for t in batch:
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
        async with httpx.AsyncClient(timeout=60.0) as client:
            logger.info(
                f"Calling OpenRouter with model {model} for batch of {len(batch)} tweets"
            )
            response = await client.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {settings.openrouter_api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/twit-muncher",
                    "X-Title": "twit-muncher",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_msg},
                    ],
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"},
                    "max_tokens": 4096,
                },
            )
            if response.status_code != 200:
                logger.error(
                    f"OpenRouter API error: {response.status_code} - {response.text}"
                )
            response.raise_for_status()
            data = response.json()
            text = data["choices"][0]["message"]["content"]

            text = text.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            try:
                results = json.loads(text)
            except json.JSONDecodeError as je:
                logger.warning(f"Initial JSON parse failed: {je}. Attempting cleanup...")
                start = text.find("{")
                end = text.rfind("}")
                if start != -1 and end != -1:
                    text = text[start : end + 1]
                    results = json.loads(text)
                else:
                    raise

            if isinstance(results, dict) and "classifications" in results:
                results = results["classifications"]
            elif isinstance(results, dict) and "tweets" in results:
                results = results["tweets"]
            elif isinstance(results, list):
                pass
            else:
                logger.warning(f"Unexpected JSON structure from OpenRouter: {text[:200]}")
                return

            logger.info(f"OpenRouter returned {len(results)} classifications")
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
            logger.info(f"Classified batch of {len(batch)} tweets using OpenRouter")

    except Exception as e:
        logger.error(f"OpenRouter classification failed: {e}")
