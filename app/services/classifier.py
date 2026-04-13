import json
import logging

import httpx
from google import genai

from app.config import settings
from app.database import get_db, get_setting

logger = logging.getLogger(__name__)

BATCH_SIZE = 25


async def classify_tweets(tweets: list[dict]):
    if not tweets:
        return

    if not settings.xai_api_key and not settings.gemini_api_key:
        logger.warning("No API key set for xAI or Gemini, skipping classification")
        return

    prompt = await get_setting("classification_prompt")

    if settings.xai_api_key:
        model = await get_setting("xai_model") or "grok-4-1-fast-non-reasoning"
        # Process in batches
        for i in range(0, len(tweets), BATCH_SIZE):
            batch = tweets[i : i + BATCH_SIZE]
            await _classify_batch_xai(model, prompt, batch)
    else:
        model = await get_setting("gemini_model") or "gemini-2.5-flash"
        client = genai.Client(api_key=settings.gemini_api_key)
        # Process in batches
        for i in range(0, len(tweets), BATCH_SIZE):
            batch = tweets[i : i + BATCH_SIZE]
            await _classify_batch_gemini(client, model, prompt, batch)


async def _classify_batch_xai(
    model: str,
    system_prompt: str,
    batch: list[dict],
):
    db = await get_db()

    # Build user message with tweets
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
            logger.info(f"Calling xAI API with model {model} for batch of {len(batch)} tweets")
            response = await client.post(
                "https://api.x.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.xai_api_key}",
                    "Content-Type": "application/json",
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
                logger.error(f"xAI API error: {response.status_code} - {response.text}")
            response.raise_for_status()
            data = response.json()
            text = data["choices"][0]["message"]["content"]
            
            # Some models might return the json block with backticks or wrap it differently
            text = text.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            try:
                results = json.loads(text)
            except json.JSONDecodeError as je:
                # Try a very aggressive cleanup if first load fails
                logger.warning(f"Initial JSON parse failed: {je}. Attempting cleanup...")
                # Find the first { and last }
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
                logger.warning(f"Unexpected JSON structure from xAI: {text[:200]}")
                return

            logger.info(f"xAI returned {len(results)} classifications")
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
            logger.info(f"Classified batch of {len(batch)} tweets using xAI")

    except Exception as e:
        logger.error(f"xAI classification failed: {e}")


async def _classify_batch_gemini(
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
