import hashlib
import os
import sqlite3
import time
import random
from fastapi import FastAPI, Request, Form, HTTPException, UploadFile, File
from PIL import Image
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

# Number of media items to display per ranking round (fixed)
NUM_MEDIA = 4

DATABASE = os.path.join(CONFIG_DIR, "database.db")


def init_db():
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT)"
    )
    cur.execute(
        "CREATE TABLE IF NOT EXISTS media (id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT UNIQUE, elo REAL DEFAULT 1000, rating_count INTEGER DEFAULT 0)"
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS rankings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            first_id INTEGER,
            second_id INTEGER,
            third_id INTEGER,
            fourth_id INTEGER,
            rated_at INTEGER
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_media (
            username TEXT,
            media_id INTEGER,
            elo REAL DEFAULT 1000,
            rating_count INTEGER DEFAULT 0,
            PRIMARY KEY (username, media_id)
        )
        """
    )
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


def get_media_file_summary() -> tuple[int, list[tuple[str, int]]]:
    """Return total media count and counts by normalized name."""
    files = [
        f
        for f in os.listdir(MEDIA_DIR)
        if os.path.isfile(os.path.join(MEDIA_DIR, f))
    ]
    total = len(files)
    counts: dict[str, int] = {}
    for f in files:
        name, _ = os.path.splitext(f)
        name = name.lower()
        name = name.replace("_", "")
        name = "".join(ch for ch in name if not ch.isdigit())
        counts[name] = counts.get(name, 0) + 1
    sorted_counts = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    return total, sorted_counts


def get_media_files(username: str, count: int) -> list[str]:
    """Return a shuffled list of media files for ranking."""
    files = [
        f
        for f in os.listdir(MEDIA_DIR)
        if os.path.isfile(os.path.join(MEDIA_DIR, f))
    ]
    if not files:
        return []

    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    for f in files:
        cur.execute("INSERT OR IGNORE INTO media (filename) VALUES (?)", (f,))
    conn.commit()

    cur.execute("SELECT filename, elo, rating_count FROM media")
    rows = cur.fetchall()
    conn.close()

    stats = {row[0]: (row[1], row[2]) for row in rows}

    random.shuffle(files)
    base_count = min(3, len(files))
    base_selection = files[:base_count]

    if len(files) <= 3 or count <= base_count:
        random.shuffle(base_selection)
        return base_selection[: min(count, len(base_selection))]

    avg = sum(stats[f][0] for f in base_selection) / len(base_selection)
    rated_candidates = [
        (fname, elo)
        for fname, (elo, cnt) in stats.items()
        if cnt > 0 and fname not in base_selection
    ]

    fourth: str | None = None
    if rated_candidates:
        fourth = min(rated_candidates, key=lambda r: abs(r[1] - avg))[0]
    else:
        remaining = [f for f in files if f not in base_selection]
        if remaining:
            fourth = random.choice(remaining)

    chosen = base_selection + ([fourth] if fourth else [])
    random.shuffle(chosen)
    return chosen[: min(count, len(chosen))]


def change_user_password(username: str, new_password: str) -> None:
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET password=? WHERE username=?",
        (hash_password(new_password), username),
    )
    conn.commit()
    conn.close()


def get_user_rating_counts() -> dict[str, int]:
    """Return number of rating entries for each user."""
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute("SELECT username, COUNT(*) FROM rankings GROUP BY username")
    rows = cur.fetchall()
    conn.close()
    return {row[0]: row[1] for row in rows}


def get_rating_event_count() -> int:
    """Return total number of ranking events recorded."""
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM rankings")
    count = cur.fetchone()[0]
    conn.close()
    return count


def delete_user(username: str) -> None:
    """Remove a user and all of their rating data."""
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute("DELETE FROM users WHERE username=?", (username,))
    cur.execute("DELETE FROM rankings WHERE username=?", (username,))
    conn.commit()
    conn.close()

def get_user_media_stats(
    username: str, limit: int = 5
) -> tuple[list[tuple[str, float, float, int, int]], list[tuple[str, float, float, int, int]]]:
    """Return a user's highest and lowest ELO rated media with global ELO."""
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT m.filename, um.elo, m.elo, um.rating_count, m.rating_count
        FROM user_media um JOIN media m ON um.media_id=m.id
        WHERE um.username=?
        """,
        (username,),
    )
    rows = cur.fetchall()
    conn.close()
    if not rows:
        return [], []
    rows.sort(key=lambda r: r[1], reverse=True)
    highest = rows[:limit]
    lowest = rows[-limit:][::-1]
    return highest, lowest


def get_global_media_stats_with_user(
    username: str, limit: int = 5
) -> tuple[
    list[tuple[str, float, float | None, int, int]],
    list[tuple[str, float, float | None, int, int]],
]:
    """Return global Elo stats with the requesting user's Elo for each item."""
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute("SELECT id, filename, elo, rating_count FROM media")
    global_rows = cur.fetchall()
    if not global_rows:
        conn.close()
        return [], []
    cur.execute(
        "SELECT media_id, elo, rating_count FROM user_media WHERE username=?",
        (username,),
    )
    user_map = {row[0]: (row[1], row[2]) for row in cur.fetchall()}
    conn.close()

    rows = []
    for media_id, filename, g_elo, g_cnt in global_rows:
        u_elo, u_cnt = user_map.get(media_id, (None, 0))
        rows.append((filename, g_elo, u_elo, g_cnt, u_cnt))

    rows.sort(key=lambda r: r[1], reverse=True)
    highest = rows[:limit]
    lowest = rows[-limit:][::-1]
    return highest, lowest


def get_elo_rankings(limit: int = 20) -> list[tuple[str, float, int]]:
    """Return media items ordered by ELO rating descending."""
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute(
        "SELECT filename, elo, rating_count FROM media ORDER BY elo DESC LIMIT ?",
        (limit,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_name_group_elo_stats() -> list[tuple[str, int, float, float, float, float]]:
    """Return stats of ELO ratings grouped by normalized media name."""
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute("SELECT filename, elo FROM media")
    rows = cur.fetchall()
    conn.close()
    groups: dict[str, list[float]] = {}
    for media, rating in rows:
        name, _ = os.path.splitext(media)
        name = name.lower().replace("_", "")
        name = "".join(ch for ch in name if not ch.isdigit())
        groups.setdefault(name, []).append(rating)

    stats = []
    for name, ratings in groups.items():
        count = len(ratings)
        avg = sum(ratings) / count
        mn = min(ratings)
        mx = max(ratings)
        var = sum((r - avg) ** 2 for r in ratings) / count
        std = var ** 0.5
        stats.append((name, count, mn, mx, avg, std))

    stats.sort(key=lambda s: -s[4])
    return stats


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
            "container_class": "ranking-container",
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
    ids: list[int] = []
    for f in files:
        cur.execute(
            "INSERT OR IGNORE INTO media (filename) VALUES (?)",
            (f,),
        )
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

    # load current ratings and counts
    ratings: dict[int, float] = {}
    counts: dict[int, int] = {}
    user_ratings: dict[int, float] = {}
    user_counts: dict[int, int] = {}
    for media_id in ids:
        cur.execute("SELECT elo, rating_count FROM media WHERE id=?", (media_id,))
        elo, cnt = cur.fetchone()
        ratings[media_id] = elo
        counts[media_id] = cnt
        cur.execute(
            "INSERT OR IGNORE INTO user_media (username, media_id) VALUES (?, ?)",
            (username, media_id),
        )
        cur.execute(
            "SELECT elo, rating_count FROM user_media WHERE username=? AND media_id=?",
            (username, media_id),
        )
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
        cur.execute(
            "UPDATE media SET elo=?, rating_count=? WHERE id=?",
            (ratings[media_id], counts[media_id], media_id),
        )
        cur.execute(
            "UPDATE user_media SET elo=?, rating_count=? WHERE username=? AND media_id=?",
            (user_ratings[media_id], user_counts[media_id], username, media_id),
        )
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
    name_group_stats = get_name_group_elo_stats()
    media_total, media_counts = get_media_file_summary()
    rating_total = get_rating_event_count()
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
    rating_counts = get_user_rating_counts()
    media_total, media_counts = get_media_file_summary()

    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "username": username,
            "users": users,
            "rating_counts": rating_counts,
            "media_total": media_total,
            "media_counts": media_counts,
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


@app.post("/admin/delete_user")
def admin_delete_user(request: Request, target_user: str = Form(...)):
    """Delete a user account and all related ratings."""
    username = request.cookies.get("username")
    if not is_admin(username):
        return RedirectResponse("/login")
    delete_user(target_user)
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


def remove_duplicate_images() -> int:
    """Remove duplicate images based on their pixel data and return count removed."""
    files = [
        f
        for f in os.listdir(MEDIA_DIR)
        if os.path.isfile(os.path.join(MEDIA_DIR, f))
    ]
    hashes: dict[str, list[str]] = {}
    for fname in files:
        path = os.path.join(MEDIA_DIR, fname)
        try:
            with Image.open(path) as img:
                img = img.convert("RGB")
                h = hashlib.sha256(img.tobytes()).hexdigest()
        except Exception:
            # skip non-image files
            continue
        hashes.setdefault(h, []).append(fname)

    removed = 0
    for dup_files in hashes.values():
        if len(dup_files) > 1:
            random.shuffle(dup_files)
            dup_files.pop()  # keep one
            for fname in dup_files:
                try:
                    os.remove(os.path.join(MEDIA_DIR, fname))
                    removed += 1
                except FileNotFoundError:
                    pass
    return removed


@app.post("/admin/remove_duplicates")
def admin_remove_duplicates(request: Request):
    """Endpoint for removing duplicate media files."""
    username = request.cookies.get("username")
    if not is_admin(username):
        return RedirectResponse("/login")
    remove_duplicate_images()
    return RedirectResponse("/admin", status_code=303)
