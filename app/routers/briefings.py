import json

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.database import get_db, get_setting

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/briefings", response_class=HTMLResponse)
async def briefing_list(request: Request):
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM briefings ORDER BY id DESC"
    )
    briefings = [dict(row) for row in rows]
    return templates.TemplateResponse(
        "briefing_list.html", {"request": request, "briefings": briefings}
    )


@router.get("/briefings/{briefing_id}", response_class=HTMLResponse)
async def briefing_detail(request: Request, briefing_id: int):
    db = await get_db()

    briefing_rows = await db.execute_fetchall(
        "SELECT * FROM briefings WHERE id = ?", (briefing_id,)
    )
    if not briefing_rows:
        return HTMLResponse("Briefing not found", status_code=404)

    briefing = dict(briefing_rows[0])

    tweets_rows = await db.execute_fetchall(
        """SELECT * FROM tweets WHERE briefing_id = ?
           ORDER BY
             CASE category
               WHEN 'must_read' THEN 0
               WHEN 'stock_ideas' THEN 1
               WHEN 'viral' THEN 2
               WHEN 'charts' THEN 3
               WHEN 'funny' THEN 4
               WHEN 'skip' THEN 5
               ELSE 6
             END,
             published_at DESC""",
        (briefing_id,),
    )

    tweets = []
    for row in tweets_rows:
        t = dict(row)
        if t.get("media_urls"):
            try:
                t["media_urls"] = json.loads(t["media_urls"])
            except (json.JSONDecodeError, TypeError):
                t["media_urls"] = []
        else:
            t["media_urls"] = []
        tweets.append(t)

    # Group tweets by category
    categories = await get_setting("categories") or []
    cat_map = {c["key"]: c for c in categories}

    grouped = {}
    for t in tweets:
        cat = t.get("category") or "uncategorized"
        if cat == "skip":
            continue  # Skip tweets loaded via AJAX
        if cat not in grouped:
            cat_info = cat_map.get(cat, {"label": cat.title(), "color": "#999", "expanded_by_default": True})
            grouped[cat] = {"info": cat_info, "tweets": []}
        grouped[cat]["tweets"].append(t)

    skip_count = sum(1 for t in tweets if t.get("category") == "skip")

    # Order groups by category order
    cat_order = [c["key"] for c in categories]
    ordered_groups = []
    for key in cat_order:
        if key in grouped and key != "skip":
            ordered_groups.append((key, grouped[key]))

    return templates.TemplateResponse(
        "briefing.html",
        {
            "request": request,
            "briefing": briefing,
            "groups": ordered_groups,
            "skip_count": skip_count,
            "categories": categories,
        },
    )
