from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .. import utils

router = APIRouter()

templates = Jinja2Templates(directory="app/templates")

@router.get("/stats", response_class=HTMLResponse)
def stats(request: Request):
    username = utils.get_username(request)
    if not username:
        return RedirectResponse("/login")
    global_highest, global_lowest = utils.get_global_media_stats_with_user(username)
    user_highest, user_lowest = utils.get_user_media_stats(username)
    elo_ranking = utils.get_elo_rankings()
    name_group_stats = utils.get_name_group_elo_stats()
    media_total, media_counts = utils.get_media_file_summary()
    rating_total = utils.get_rating_event_count()
    return templates.TemplateResponse(
        "stats.html",
        {
            "request": request,
            "username": username,
            "global_highest": global_highest,
            "global_lowest": global_lowest,
            "user_highest": user_highest,
            "user_lowest": user_lowest,
            "elo_ranking": elo_ranking,
            "name_group_stats": name_group_stats,
            "media_total": media_total,
            "rating_total": rating_total,
            "media_counts": media_counts,
            "show_back": True,
            "show_admin": utils.is_admin(username),
            "show_stats_link": False,
            "body_class": None,
            "container_class": None,
        },
    )
