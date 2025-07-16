import requests
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import utils
from .routers import auth, ranking, admin, stats

app = FastAPI()

# expose key globals for tests
MEDIA_DIR = utils.MEDIA_DIR
CONFIG_DIR = utils.CONFIG_DIR
DATABASE = utils.DATABASE
ADMIN_USERS = utils.ADMIN_USERS
BUILD_NUMBER = utils.BUILD_NUMBER
NUM_MEDIA = utils.NUM_MEDIA
serializer = utils.serializer

def sync_config() -> None:
    utils.MEDIA_DIR = MEDIA_DIR
    utils.CONFIG_DIR = CONFIG_DIR
    utils.DATABASE = DATABASE
    utils.ADMIN_USERS = ADMIN_USERS


def init_db() -> None:
    sync_config()
    utils.init_db()

def is_admin(username: str | None) -> bool:
    sync_config()
    return utils.is_admin(username)

def hash_password(password: str) -> str:
    return utils.hash_password(password)

def get_username(request):
    sync_config()
    return utils.get_username(request)

def verify_user(username: str, password: str) -> bool:
    sync_config()
    return utils.verify_user(username, password)

def list_users() -> list[str]:
    sync_config()
    return utils.list_users()

def get_media_file_summary():
    sync_config()
    return utils.get_media_file_summary()

def get_media_files(username: str, count: int):
    sync_config()
    return utils.get_media_files(username, count)

def change_user_password(username: str, new_password: str) -> None:
    sync_config()
    utils.change_user_password(username, new_password)

def get_user_rating_counts():
    sync_config()
    return utils.get_user_rating_counts()

def get_rating_event_count() -> int:
    sync_config()
    return utils.get_rating_event_count()

def load_ollama_config():
    sync_config()
    return utils.load_ollama_config()

def save_ollama_config(url: str, api_key: str, model: str) -> None:
    sync_config()
    utils.save_ollama_config(url, api_key, model)

def generate_all_embeddings(url: str, api_key: str, model: str) -> int:
    sync_config()
    return utils.generate_all_embeddings(url, api_key, model)

def delete_user(username: str) -> None:
    sync_config()
    utils.delete_user(username)

def get_user_media_stats(username: str, limit: int = 5):
    sync_config()
    return utils.get_user_media_stats(username, limit)

def get_global_media_stats_with_user(username: str, limit: int = 5):
    sync_config()
    return utils.get_global_media_stats_with_user(username, limit)

def get_elo_rankings(limit: int = 20):
    sync_config()
    return utils.get_elo_rankings(limit)

def get_name_group_elo_stats():
    sync_config()
    return utils.get_name_group_elo_stats()

def remove_duplicate_images() -> int:
    sync_config()
    return utils.remove_duplicate_images()

# mount static and media
app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

templates = Jinja2Templates(directory="app/templates")

# initialize DB
init_db()

# include routers
app.include_router(ranking.router)
app.include_router(auth.router)
app.include_router(stats.router)
app.include_router(admin.router)
