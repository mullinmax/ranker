import hashlib
import os
import sqlite3
import time
import datetime
from fastapi import FastAPI, Request, Form, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI()

# Ensure directories exist even if mounted at runtime. The locations can be
# configured via the environment so tests can override them.
MEDIA_DIR = os.environ.get("MEDIA_DIR", "/ranker-media")
CONFIG_DIR = os.environ.get("CONFIG_DIR", "/config")
os.makedirs(MEDIA_DIR, exist_ok=True)
os.makedirs(CONFIG_DIR, exist_ok=True)
app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

templates = Jinja2Templates(directory="app/templates")

ADMIN_USERS = {
    u.strip() for u in os.environ.get("ADMIN_USERS", "").split(",") if u.strip()
}

BUILD_NUMBER = os.environ.get("BUILD_NUMBER", "dev")

# Number of media items to display per ranking round
NUM_MEDIA = int(os.environ.get("NUM_MEDIA", 4))

DATABASE = os.path.join(CONFIG_DIR, "database.db")


def init_db():
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT)"
    )
    cur.execute(
        "CREATE TABLE IF NOT EXISTS ratings (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, media TEXT, score INTEGER, rated_at INTEGER)"
    )
    cur.execute(
        "CREATE TABLE IF NOT EXISTS elo (media TEXT PRIMARY KEY, rating REAL)"
    )
    # Ensure rated_at column exists if database was created with older schema
    cur.execute("PRAGMA table_info(ratings)")
    cols = [row[1] for row in cur.fetchall()]
    if "rated_at" not in cols:
        cur.execute("ALTER TABLE ratings ADD COLUMN rated_at INTEGER")
    conn.commit()
    conn.close()


init_db()


def is_admin(username: str | None) -> bool:
    return username in ADMIN_USERS


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def verify_user(username: str, password: str) -> bool:
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute("SELECT password FROM users WHERE username=?", (username,))
    row = cur.fetchone()
    conn.close()
    return row is not None and row[0] == hash_password(password)


def list_users() -> list[str]:
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute("SELECT username FROM users")
    rows = [row[0] for row in cur.fetchall()]
    conn.close()
    return rows


def get_media_files(username: str, count: int) -> list[str]:
    files = [
        f
        for f in os.listdir(MEDIA_DIR)
        if os.path.isfile(os.path.join(MEDIA_DIR, f))
    ]
    if not files:
        return []

    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute(
        "SELECT media, MAX(rated_at) FROM ratings WHERE username=? GROUP BY media",
        (username,),
    )
    last_times = {row[0]: row[1] for row in cur.fetchall()}
    conn.close()

    scored_files: list[tuple[int, str]] = []
    for f in files:
        last_time = last_times.get(f)
        last_time = last_time if last_time is not None else 0
        scored_files.append((last_time, f))

    scored_files.sort(key=lambda x: (x[0], x[1]))
    return [f for _, f in scored_files[:count]]


def get_last_rating_time(username: str, media: str) -> int | None:
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute(
        "SELECT MAX(rated_at) FROM ratings WHERE username=? AND media=?",
        (username, media),
    )
    row = cur.fetchone()
    conn.close()
    return row[0] if row and row[0] is not None else None


def change_user_password(username: str, new_password: str) -> None:
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET password=? WHERE username=?",
        (hash_password(new_password), username),
    )
    conn.commit()
    conn.close()


def get_media_stats(limit: int = 5) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute("SELECT media, AVG(score) FROM ratings GROUP BY media")
    rows = cur.fetchall()
    conn.close()
    if not rows:
        return [], []
    rows.sort(key=lambda r: r[1])
    highest = rows[:limit]
    lowest = rows[-limit:][::-1]
    return highest, lowest


def get_user_media_stats(
    username: str, limit: int = 5
) -> tuple[list[tuple[str, float, float | None]], list[tuple[str, float, float | None]]]:
    """Return a user's highest and lowest rated media with global averages."""
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute(
        "SELECT media, AVG(score) FROM ratings WHERE username=? GROUP BY media",
        (username,),
    )
    user_rows = cur.fetchall()
    if not user_rows:
        conn.close()
        return [], []
    cur.execute("SELECT media, AVG(score) FROM ratings GROUP BY media")
    global_rows = dict(cur.fetchall())
    conn.close()
    user_rows.sort(key=lambda r: r[1])
    highest = user_rows[:limit]
    lowest = user_rows[-limit:][::-1]
    highest = [
        (m, u_avg, global_rows.get(m)) for m, u_avg in highest
    ]
    lowest = [(m, u_avg, global_rows.get(m)) for m, u_avg in lowest]
    return highest, lowest


def get_global_media_stats_with_user(
    username: str, limit: int = 5
) -> tuple[list[tuple[str, float, float | None]], list[tuple[str, float, float | None]]]:
    """Return global stats with the requesting user's average for each item."""
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute("SELECT media, AVG(score) FROM ratings GROUP BY media")
    global_rows = cur.fetchall()
    if not global_rows:
        conn.close()
        return [], []
    cur.execute(
        "SELECT media, AVG(score) FROM ratings WHERE username=? GROUP BY media",
        (username,),
    )
    user_rows = dict(cur.fetchall())
    conn.close()
    global_rows.sort(key=lambda r: r[1])
    highest = global_rows[:limit]
    lowest = global_rows[-limit:][::-1]
    highest = [(m, g_avg, user_rows.get(m)) for m, g_avg in highest]
    lowest = [(m, g_avg, user_rows.get(m)) for m, g_avg in lowest]
    return highest, lowest


def get_elo_rankings(limit: int = 20) -> list[tuple[str, float]]:
    """Return media items ordered by ELO rating descending."""
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute("SELECT media, rating FROM elo ORDER BY rating DESC LIMIT ?", (limit,))
    rows = cur.fetchall()
    conn.close()
    return rows


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    username = request.cookies.get("username")
    if not username:
        return RedirectResponse("/login")
    file_names = get_media_files(username, NUM_MEDIA)
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "files": file_names,
            "username": username,
            "is_admin": is_admin(username),
            "show_admin": is_admin(username),
            "show_back": False,
            "show_stats_link": True,
            "body_class": None,
            "container_class": None,
        },
        status_code=200 if file_names else 404,
    )


@app.post("/rate")
def rate(request: Request, order: str = Form(...)):
    """Record the ranking order for the provided files."""
    username = request.cookies.get("username")
    if not username:
        return RedirectResponse("/login")
    files = [f for f in order.split(',') if f]
    ts = int(time.time())
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    for rank, file in enumerate(files, start=1):
        cur.execute(
            "INSERT INTO ratings (username, media, score, rated_at) VALUES (?, ?, ?, ?)",
            (username, file, rank, ts),
        )
        cur.execute(
            "INSERT OR IGNORE INTO elo (media, rating) VALUES (?, ?)", (file, 1000)
        )
    K = 32
    for i in range(len(files)):
        for j in range(i + 1, len(files)):
            winner = files[i]
            loser = files[j]
            cur.execute("SELECT rating FROM elo WHERE media=?", (winner,))
            Ra = cur.fetchone()[0]
            cur.execute("SELECT rating FROM elo WHERE media=?", (loser,))
            Rb = cur.fetchone()[0]
            Ea = 1 / (1 + 10 ** ((Rb - Ra) / 400))
            Eb = 1 / (1 + 10 ** ((Ra - Rb) / 400))
            Ra_new = Ra + K * (1 - Ea)
            Rb_new = Rb + K * (0 - Eb)
            cur.execute("UPDATE elo SET rating=? WHERE media=?", (Ra_new, winner))
            cur.execute("UPDATE elo SET rating=? WHERE media=?", (Rb_new, loser))
    conn.commit()
    conn.close()
    return RedirectResponse("/", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_get(request: Request):
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "username": None,
            "body_class": None,
            "container_class": None,
            "show_admin": False,
            "show_back": False,
        },
    )


@app.post("/login")
def login_post(username: str = Form(...), password: str = Form(...)):
    if verify_user(username, password):
        response = RedirectResponse("/", status_code=303)
        response.set_cookie("username", username)
        return response
    return HTMLResponse("Invalid credentials", status_code=400)


@app.get("/register", response_class=HTMLResponse)
def register_get(request: Request):
    return templates.TemplateResponse(
        "register.html",
        {
            "request": request,
            "username": None,
            "body_class": None,
            "container_class": None,
            "show_admin": False,
            "show_back": False,
        },
    )


@app.post("/register")
def register_post(username: str = Form(...), password: str = Form(...)):
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO users (username, password) VALUES (?, ?)",
            (username, hash_password(password)),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="Username exists")
    conn.close()
    return RedirectResponse("/login", status_code=303)


@app.get("/logout")
def logout():
    """Clear the authentication cookie and redirect to the login page."""
    response = RedirectResponse("/login")
    response.delete_cookie("username")
    return response


@app.get("/stats", response_class=HTMLResponse)
def stats(request: Request):
    username = request.cookies.get("username")
    if not username:
        return RedirectResponse("/login")
    global_highest, global_lowest = get_global_media_stats_with_user(username)
    user_highest, user_lowest = get_user_media_stats(username)
    elo_ranking = get_elo_rankings()
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
            "show_back": True,
            "show_admin": is_admin(username),
            "show_stats_link": False,
            "body_class": None,
            "container_class": None,
        },
    )


@app.get("/admin", response_class=HTMLResponse)
def admin_panel(request: Request):
    username = request.cookies.get("username")
    if not is_admin(username):
        return RedirectResponse("/login")
    users = list_users()
    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "username": username,
            "users": users,
            "build_number": BUILD_NUMBER,
            "show_back": True,
            "show_admin": False,
            "show_stats_link": True,
            "body_class": "admin-page",
            "container_class": "admin-container",
        },
    )


@app.post("/admin/change_password")
def admin_change_password(
    request: Request,
    target_user: str = Form(...),
    new_password: str = Form(...),
):
    username = request.cookies.get("username")
    if not is_admin(username):
        return RedirectResponse("/login")
    change_user_password(target_user, new_password)
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/upload_media")
def admin_upload_media(
    request: Request,
    media_files: list[UploadFile] = File(...),
):
    username = request.cookies.get("username")
    if not is_admin(username):
        return RedirectResponse("/login")
    for media_file in media_files:
        file_path = os.path.join(MEDIA_DIR, media_file.filename)
        with open(file_path, "wb") as f:
            f.write(media_file.file.read())
    return RedirectResponse("/admin", status_code=303)
