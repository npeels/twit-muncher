import json

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.database import get_all_settings, get_db, get_setting, set_setting, generate_classification_prompt
from app.services.briefing import generate_briefing
from app.services.rss_poller import poll_and_classify

router = APIRouter(prefix="/api")


@router.post("/poll-now")
async def poll_now():
    await poll_and_classify()
    return {"status": "ok", "message": "Poll and classification complete"}


@router.post("/generate-briefing")
async def create_briefing():
    briefing_id = await generate_briefing()
    if briefing_id is None:
        return {"status": "ok", "message": "No tweets to include in briefing"}
    return {"status": "ok", "briefing_id": briefing_id}


@router.get("/briefings/{briefing_id}/tweets")
async def get_briefing_tweets(briefing_id: int, category: str | None = None):
    db = await get_db()
    if category:
        rows = await db.execute_fetchall(
            """SELECT * FROM tweets WHERE briefing_id = ? AND category = ?
               ORDER BY published_at DESC""",
            (briefing_id, category),
        )
    else:
        rows = await db.execute_fetchall(
            "SELECT * FROM tweets WHERE briefing_id = ? ORDER BY published_at DESC",
            (briefing_id,),
        )

    tweets = []
    for row in rows:
        t = dict(row)
        if t.get("media_urls"):
            try:
                t["media_urls"] = json.loads(t["media_urls"])
            except (json.JSONDecodeError, TypeError):
                t["media_urls"] = []
        else:
            t["media_urls"] = []
        tweets.append(t)

    return tweets


@router.post("/reclassify/{tweet_id}")
async def reclassify_tweet(tweet_id: str, category: str):
    db = await get_db()
    await db.execute(
        "UPDATE tweets SET category = ?, category_reason = 'Manual override', confidence = 1.0 WHERE id = ?",
        (category, tweet_id),
    )
    await db.commit()
    return {"status": "ok"}


@router.get("/settings")
async def get_settings():
    return await get_all_settings()


@router.put("/settings")
async def update_settings(body: dict):
    for key, value in body.items():
        await set_setting(key, value)

    # Reschedule jobs if timing changed
    if any(k in body for k in ("poll_interval_minutes", "briefing_times", "briefing_days")):
        from app.main import reschedule_jobs
        await reschedule_jobs()

    return {"status": "ok"}


@router.post("/settings/reset-prompt")
async def reset_classification_prompt():
    categories = await get_setting("categories")
    prompt = generate_classification_prompt(categories)
    await set_setting("classification_prompt", prompt)
    return {"status": "ok", "prompt": prompt}
