import sqlite3
import time
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .. import utils

router = APIRouter()

templates = Jinja2Templates(directory="app/templates")

@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    username = utils.get_username(request)
    if not username:
        return RedirectResponse("/login")
    file_names = utils.get_media_files(username, utils.NUM_MEDIA)
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "files": file_names,
            "username": username,
            "is_admin": utils.is_admin(username),
            "show_admin": utils.is_admin(username),
            "show_back": False,
            "show_stats_link": True,
            "body_class": None,
            "container_class": "ranking-container",
        },
        status_code=200 if file_names else 404,
    )

@router.post("/rate")
def rate(request: Request, order: str = Form(...)):
    username = utils.get_username(request)
    if not username:
        return RedirectResponse("/login")
    files = [f for f in order.split(',') if f]
    ts = int(time.time())
    conn = sqlite3.connect(utils.DATABASE)
    cur = conn.cursor()
    ids: list[int] = []
    for f in files:
        cur.execute("INSERT OR IGNORE INTO media (filename) VALUES (?)", (f,))
        cur.execute("SELECT id, elo, rating_count FROM media WHERE filename=?", (f,))
        row = cur.fetchone()
        assert row
        ids.append(row[0])
    first_id = ids[0] if len(ids) > 0 else None
    second_id = ids[1] if len(ids) > 1 else None
    third_id = ids[2] if len(ids) > 2 else None
    fourth_id = ids[3] if len(ids) > 3 else None
    cur.execute(
        """
        INSERT INTO rankings (username, first_id, second_id, third_id, fourth_id, rated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (username, first_id, second_id, third_id, fourth_id, ts),
    )
    ratings: dict[int, float] = {}
    counts: dict[int, int] = {}
    user_ratings: dict[int, float] = {}
    user_counts: dict[int, int] = {}
    for media_id in ids:
        cur.execute("SELECT elo, rating_count FROM media WHERE id=?", (media_id,))
        elo, cnt = cur.fetchone()
        ratings[media_id] = elo
        counts[media_id] = cnt
        cur.execute("INSERT OR IGNORE INTO user_media (username, media_id) VALUES (?, ?)", (username, media_id))
        cur.execute("SELECT elo, rating_count FROM user_media WHERE username=? AND media_id=?", (username, media_id))
        u_elo, u_cnt = cur.fetchone()
        user_ratings[media_id] = u_elo
        user_counts[media_id] = u_cnt

    K = 32
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            winner_id = ids[i]
            loser_id = ids[j]
            Ra = ratings[winner_id]
            Rb = ratings[loser_id]
            uRa = user_ratings[winner_id]
            uRb = user_ratings[loser_id]
            Ea = 1 / (1 + 10 ** ((Rb - Ra) / 400))
            Eb = 1 / (1 + 10 ** ((Ra - Rb) / 400))
            Ra = Ra + K * (1 - Ea)
            Rb = Rb + K * (0 - Eb)
            EuA = 1 / (1 + 10 ** ((uRb - uRa) / 400))
            EuB = 1 / (1 + 10 ** ((uRa - uRb) / 400))
            uRa = uRa + K * (1 - EuA)
            uRb = uRb + K * (0 - EuB)
            ratings[winner_id] = Ra
            ratings[loser_id] = Rb
            user_ratings[winner_id] = uRa
            user_ratings[loser_id] = uRb
            counts[winner_id] += 1
            counts[loser_id] += 1
            user_counts[winner_id] += 1
            user_counts[loser_id] += 1

    for media_id in ids:
        cur.execute("UPDATE media SET elo=?, rating_count=? WHERE id=?", (ratings[media_id], counts[media_id], media_id))
        cur.execute("UPDATE user_media SET elo=?, rating_count=? WHERE username=? AND media_id=?", (user_ratings[media_id], user_counts[media_id], username, media_id))
    conn.commit()
    conn.close()
    return RedirectResponse("/", status_code=303)
