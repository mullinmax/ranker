import sqlite3
from fastapi import HTTPException
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .. import utils

router = APIRouter()

templates = Jinja2Templates(directory="app/templates")

@router.get("/login", response_class=HTMLResponse)
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

@router.post("/login")
def login_post(username: str = Form(...), password: str = Form(...)):
    if utils.verify_user(username, password):
        response = RedirectResponse("/", status_code=303)
        token = utils.serializer.dumps(username)
        response.set_cookie("session", token, httponly=True)
        return response
    return HTMLResponse("Invalid credentials", status_code=400)

@router.get("/register", response_class=HTMLResponse)
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

@router.post("/register")
def register_post(username: str = Form(...), password: str = Form(...)):
    conn = sqlite3.connect(utils.DATABASE)
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO users (username, password) VALUES (?, ?)",
            (username, utils.hash_password(password)),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="Username exists")
    conn.close()
    return RedirectResponse("/login", status_code=303)

@router.get("/logout")
def logout():
    response = RedirectResponse("/login")
    response.delete_cookie("session")
    return response
