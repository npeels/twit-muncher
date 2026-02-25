from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.database import get_all_settings

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    all_settings = await get_all_settings()
    return templates.TemplateResponse(
        "settings.html", {"request": request, "settings": all_settings}
    )
