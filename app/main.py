import asyncio
from contextlib import asynccontextmanager
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.auth import configure_oauth, get_allowed_emails, oauth
from app.middleware import AuthMiddleware, SecurityHeadersMiddleware
from app.database import close_db, get_all_settings, get_db
from app.services.rss_poller import poll_and_classify
from app.services.briefing import generate_briefing

configure_oauth()

scheduler = AsyncIOScheduler()


async def scheduled_poll():
    await poll_and_classify()


async def scheduled_briefing():
    await generate_briefing()


async def reschedule_jobs():
    settings = await get_all_settings()
    poll_interval = settings.get("poll_interval_minutes", 12)
    briefing_times = settings.get("briefing_times", ["09:00", "16:00"])
    briefing_days = settings.get("briefing_days", ["mon", "tue", "wed", "thu", "fri"])

    # Remove existing jobs
    for job in scheduler.get_jobs():
        job.remove()

    # Schedule polling
    scheduler.add_job(
        scheduled_poll,
        IntervalTrigger(minutes=poll_interval),
        id="poll",
        replace_existing=True,
    )

    # Schedule briefings
    day_map = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
    days_of_week = ",".join(
        str(day_map[d]) for d in briefing_days if d in day_map
    )

    for i, time_str in enumerate(briefing_times):
        hour, minute = time_str.split(":")
        scheduler.add_job(
            scheduled_briefing,
            CronTrigger(
                day_of_week=days_of_week,
                hour=int(hour),
                minute=int(minute),
                timezone=ZoneInfo("Europe/London"),
            ),
            id=f"briefing_{i}",
            replace_existing=True,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_db()
    await reschedule_jobs()
    scheduler.start()
    yield
    scheduler.shutdown()
    await close_db()


app = FastAPI(title="Twit Muncher", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Middleware order: first added = innermost, last added = outermost (runs first).
# Request flow: Session -> SecurityHeaders -> Auth -> route
app.add_middleware(AuthMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret)

templates = Jinja2Templates(directory="app/templates")

from app.routers import briefings, settings as settings_router, api

app.include_router(briefings.router)
app.include_router(settings_router.router)
app.include_router(api.router)


@app.get("/")
async def index(request: Request):
    if request.session.get("user"):
        db = await get_db()
        row = await db.execute_fetchall(
            "SELECT id FROM briefings ORDER BY id DESC LIMIT 1"
        )
        if row:
            return RedirectResponse(url=f"/briefings/{row[0][0]}")
        return RedirectResponse(url="/briefings")
    error = request.query_params.get("error")
    return templates.TemplateResponse("landing.html", {"request": request, "error": error})


@app.get("/login/google")
async def login_google(request: Request):
    redirect_uri = request.url_for("auth_callback")
    # Always use HTTPS since Cloudflare terminates TLS
    redirect_uri = str(redirect_uri).replace("http://", "https://", 1)
    return await oauth.google.authorize_redirect(request, redirect_uri)


@app.get("/auth/callback")
async def auth_callback(request: Request):
    token = await oauth.google.authorize_access_token(request)
    user_info = token.get("userinfo", {})
    email = user_info.get("email", "").lower()

    allowed = get_allowed_emails()
    if allowed and email not in allowed:
        return RedirectResponse("/?error=unauthorized", status_code=302)

    request.session["user"] = email
    return RedirectResponse("/", status_code=302)


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=302)
