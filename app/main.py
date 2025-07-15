import hashlib
import os
import sqlite3
from fastapi import FastAPI, Request, Form, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI()

# Ensure media directory exists even if mounted at runtime
os.makedirs("media", exist_ok=True)
app.mount("/media", StaticFiles(directory="media"), name="media")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

templates = Jinja2Templates(directory="app/templates")

DATABASE = "database.db"


def init_db():
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT, is_admin INTEGER DEFAULT 0)"
    )
    cur.execute(
        "CREATE TABLE IF NOT EXISTS ratings (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, media TEXT, score INTEGER)"
    )
    cur.execute("PRAGMA table_info(users)")
    cols = [row[1] for row in cur.fetchall()]
    if 'is_admin' not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0")
    conn.commit()
    conn.close()


init_db()

def create_default_admin():
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE username=?", ("admin",))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (username, password, is_admin) VALUES (?, ?, 1)", ("admin", hash_password("admin")))
        conn.commit()
    conn.close()

create_default_admin()


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def verify_user(username: str, password: str) -> bool:
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute("SELECT password FROM users WHERE username=?", (username,))
    row = cur.fetchone()
    conn.close()
    return row is not None and row[0] == hash_password(password)



def is_admin(username: str) -> bool:
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute("SELECT is_admin FROM users WHERE username=?", (username,))
    row = cur.fetchone()
    conn.close()
    return bool(row and row[0])

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
            "INSERT INTO users (username, password, is_admin) VALUES (?, ?, 0)",
            (username, hash_password(password)),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="Username exists")
    conn.close()
    return RedirectResponse("/login", status_code=303)


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request):
    username = request.cookies.get("username")
    if not username or not is_admin(username):
        return RedirectResponse("/login")
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute("SELECT username FROM users")
    users = [row[0] for row in cur.fetchall()]
    conn.close()
    return templates.TemplateResponse("admin.html", {"request": request, "users": users})

@app.post("/admin/reset-password")
def reset_password(request: Request, username: str = Form(...), new_password: str = Form(...)):
    current = request.cookies.get("username")
    if not current or not is_admin(current):
        return RedirectResponse("/login")
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute("UPDATE users SET password=? WHERE username=?", (hash_password(new_password), username))
    conn.commit()
    conn.close()
    return RedirectResponse("/admin", status_code=303)

@app.post("/admin/upload")
async def upload_media(request: Request, file: UploadFile = File(...)):
    current = request.cookies.get("username")
    if not current or not is_admin(current):
        return RedirectResponse("/login")
    contents = await file.read()
    path = os.path.join("media", file.filename)
    with open(path, "wb") as fobj:
        fobj.write(contents)
    return RedirectResponse("/admin", status_code=303)
