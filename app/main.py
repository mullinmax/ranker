import hashlib
import os
import sqlite3
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI()

# Ensure media directory exists even if mounted at runtime
os.makedirs("media", exist_ok=True)
app.mount("/media", StaticFiles(directory="media"), name="media")

templates = Jinja2Templates(directory="app/templates")

DATABASE = "database.db"


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


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def verify_user(username: str, password: str) -> bool:
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute("SELECT password FROM users WHERE username=?", (username,))
    row = cur.fetchone()
    conn.close()
    return row is not None and row[0] == hash_password(password)


def get_media_file() -> str | None:
    files = [f for f in os.listdir("media") if os.path.isfile(os.path.join("media", f))]
    return sorted(files)[0] if files else None


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    username = request.cookies.get("username")
    if not username:
        return RedirectResponse("/login")
    file_name = get_media_file()
    if not file_name:
        return HTMLResponse("No media files found", status_code=404)
    return templates.TemplateResponse("index.html", {"request": request, "file": file_name})


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

