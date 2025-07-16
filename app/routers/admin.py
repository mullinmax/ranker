import os
import sqlite3
from fastapi import APIRouter, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from .. import utils

router = APIRouter()

templates = Jinja2Templates(directory="app/templates")

@router.get("/admin", response_class=HTMLResponse)
def admin_panel(request: Request):
    username = utils.get_username(request)
    if not utils.is_admin(username):
        return RedirectResponse("/login")
    users = utils.list_users()
    rating_counts = utils.get_user_rating_counts()
    media_total, media_counts = utils.get_media_file_summary()
    ollama_url, ollama_api_key, ollama_model = utils.load_ollama_config()
    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "username": username,
            "users": users,
            "rating_counts": rating_counts,
            "media_total": media_total,
            "media_counts": media_counts,
            "build_number": utils.BUILD_NUMBER,
            "ollama_url": ollama_url,
            "ollama_api_key": ollama_api_key,
            "ollama_model": ollama_model,
            "show_back": True,
            "show_admin": False,
            "show_stats_link": True,
            "body_class": "admin-page",
            "container_class": "admin-container",
        },
    )

@router.post("/admin/change_password")
def admin_change_password(
    request: Request,
    target_user: str = Form(...),
    new_password: str = Form(...),
):
    username = utils.get_username(request)
    if not utils.is_admin(username):
        return RedirectResponse("/login")
    utils.change_user_password(target_user, new_password)
    return RedirectResponse("/admin", status_code=303)

@router.post("/admin/delete_user")
def admin_delete_user(request: Request, target_user: str = Form(...)):
    username = utils.get_username(request)
    if not utils.is_admin(username):
        return RedirectResponse("/login")
    utils.delete_user(target_user)
    return RedirectResponse("/admin", status_code=303)

@router.post("/admin/upload_media")
def admin_upload_media(
    request: Request,
    media_files: list[UploadFile] = File(...),
):
    username = utils.get_username(request)
    if not utils.is_admin(username):
        return RedirectResponse("/login")
    for media_file in media_files:
        file_path = os.path.join(utils.MEDIA_DIR, media_file.filename)
        with open(file_path, "wb") as f:
            f.write(media_file.file.read())
    return RedirectResponse("/admin", status_code=303)

@router.post("/admin/set_ollama")
def admin_set_ollama(
    request: Request,
    url: str = Form(...),
    api_key: str = Form(""),
    model: str = Form(...),
):
    username = utils.get_username(request)
    if not utils.is_admin(username):
        return RedirectResponse("/login")
    utils.save_ollama_config(url, api_key, model)
    return RedirectResponse("/admin", status_code=303)

@router.post("/admin/generate_embeddings")
def admin_generate_embeddings(request: Request):
    username = utils.get_username(request)
    if not utils.is_admin(username):
        return RedirectResponse("/login")
    url, api_key, model = utils.load_ollama_config()
    if not url or not model:
        raise HTTPException(status_code=400, detail="Ollama configuration missing")
    utils.generate_all_embeddings(url, api_key, model)
    return RedirectResponse("/admin", status_code=303)

@router.post("/admin/remove_duplicates")
def admin_remove_duplicates(request: Request):
    username = utils.get_username(request)
    if not utils.is_admin(username):
        return RedirectResponse("/login")
    utils.remove_duplicate_images()
    return RedirectResponse("/admin", status_code=303)
