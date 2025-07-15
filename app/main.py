import hashlib
import os
import sqlite3
from fastapi import FastAPI, Request, Form, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI()

# Ensure directories exist even if mounted at runtime
MEDIA_DIR = "/ranker-media"
CONFIG_DIR = "/config"
os.makedirs(MEDIA_DIR, exist_ok=True)
os.makedirs(CONFIG_DIR, exist_ok=True)
app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

templates = Jinja2Templates(directory="app/templates")

ADMIN_USERS = {
    u.strip() for u in os.environ.get("ADMIN_USERS", "").split(",") if u.strip()
}

DATABASE = os.path.join(CONFIG_DIR, "database.db")


def init_db():
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT)"
    )
    cur.execute(
        "CREATE TABLE IF NOT EXISTS ratings (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, media TEXT, score INTEGER)"
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


def get_media_file() -> str | None:
    files = [
        f
        for f in os.listdir(MEDIA_DIR)
        if os.path.isfile(os.path.join(MEDIA_DIR, f))
    ]
    return sorted(files)[0] if files else None


def change_user_password(username: str, new_password: str) -> None:
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET password=? WHERE username=?",
        (hash_password(new_password), username),
    )
    conn.commit()
    conn.close()


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    username = request.cookies.get("username")
    if not username:
        return RedirectResponse("/login")
    file_name = get_media_file()
    if not file_name:
        return HTMLResponse("No media files found", status_code=404)
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "file": file_name, "username": username},
    )


@app.post("/rate")
def rate(request: Request, file: str = Form(...), score: int = Form(...)):
    username = request.cookies.get("username")
    if not username:
        return RedirectResponse("/login")
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO ratings (username, media, score) VALUES (?, ?, ?)",
        (username, file, score),
    )
    conn.commit()
    conn.close()
    return RedirectResponse("/", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_get(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
def login_post(username: str = Form(...), password: str = Form(...)):
    if verify_user(username, password):
        response = RedirectResponse("/", status_code=303)
        response.set_cookie("username", username)
        return response
    return HTMLResponse("Invalid credentials", status_code=400)


@app.get("/register", response_class=HTMLResponse)
def register_get(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})


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


@app.get("/admin", response_class=HTMLResponse)
def admin_panel(request: Request):
    username = request.cookies.get("username")
    if not is_admin(username):
        return RedirectResponse("/login")
    users = list_users()
    return templates.TemplateResponse(
        "admin.html",
        {"request": request, "username": username, "users": users},
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
