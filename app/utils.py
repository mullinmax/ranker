import os
import hashlib
import sqlite3
import time
import random
import base64
import io
import json
from typing import Any

import requests
from itsdangerous import BadSignature, URLSafeSerializer
from PIL import Image

# configuration
MEDIA_DIR = os.environ.get("MEDIA_DIR", "/ranker-media")
CONFIG_DIR = os.environ.get("CONFIG_DIR", "/config")
DATABASE = os.path.join(CONFIG_DIR, "database.db")
OLLAMA_CONFIG_PATH = os.path.join(CONFIG_DIR, "ollama_config.json")
ADMIN_USERS = {u.strip() for u in os.environ.get("ADMIN_USERS", "").split(',') if u.strip()}
BUILD_NUMBER = os.environ.get("BUILD_NUMBER", "dev")

SECRET_KEY = os.environ.get("SECRET_KEY", "devkey")
serializer = URLSafeSerializer(SECRET_KEY)

NUM_MEDIA = 4

# Ensure directories exist
os.makedirs(MEDIA_DIR, exist_ok=True)
os.makedirs(CONFIG_DIR, exist_ok=True)


def init_db() -> None:
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
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS embeddings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            media_id INTEGER,
            model TEXT,
            embedding TEXT,
            UNIQUE(media_id, model)
        )
        """
    )
    conn.commit()
    conn.close()


def is_admin(username: str | None) -> bool:
    return username in ADMIN_USERS


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def get_username(request) -> str | None:
    token = request.cookies.get("session")
    if not token:
        return None
    try:
        return serializer.loads(token)
    except BadSignature:
        return None


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
    files = [f for f in os.listdir(MEDIA_DIR) if os.path.isfile(os.path.join(MEDIA_DIR, f))]
    total = len(files)
    counts: dict[str, int] = {}
    for f in files:
        name, _ = os.path.splitext(f)
        name = name.lower().replace('_', '')
        name = ''.join(ch for ch in name if not ch.isdigit())
        counts[name] = counts.get(name, 0) + 1
    sorted_counts = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    return total, sorted_counts


def get_media_files(username: str, count: int) -> list[str]:
    files = [f for f in os.listdir(MEDIA_DIR) if os.path.isfile(os.path.join(MEDIA_DIR, f))]
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
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute("SELECT username, COUNT(*) FROM rankings GROUP BY username")
    rows = cur.fetchall()
    conn.close()
    return {row[0]: row[1] for row in rows}


def get_rating_event_count() -> int:
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM rankings")
    count = cur.fetchone()[0]
    conn.close()
    return count


def load_ollama_config() -> tuple[str, str, str]:
    if os.path.exists(OLLAMA_CONFIG_PATH):
        try:
            with open(OLLAMA_CONFIG_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return (
                    data.get('url', ''),
                    data.get('api_key', ''),
                    data.get('model', ''),
                )
        except Exception:
            pass
    return '', '', ''


def save_ollama_config(url: str, api_key: str, model: str) -> None:
    with open(OLLAMA_CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump({'url': url, 'api_key': api_key, 'model': model}, f)


def generate_all_embeddings(url: str, api_key: str, model: str) -> int:
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    files = [f for f in os.listdir(MEDIA_DIR) if os.path.isfile(os.path.join(MEDIA_DIR, f))]
    for fname in files:
        cur.execute("INSERT OR IGNORE INTO media (filename) VALUES (?)", (fname,))
    conn.commit()

    cur.execute("SELECT id, filename FROM media")
    rows = cur.fetchall()
    headers = {'Authorization': f'Bearer {api_key}'} if api_key else {}
    processed = 0
    for media_id, fname in rows:
        cur.execute(
            "SELECT 1 FROM embeddings WHERE media_id=? AND model=?",
            (media_id, model),
        )
        if cur.fetchone():
            continue
        path = os.path.join(MEDIA_DIR, fname)
        try:
            with Image.open(path) as img:
                if getattr(img, 'is_animated', False):
                    img.seek(0)
                img = img.convert('RGB')
                buf = io.BytesIO()
                img.save(buf, format='PNG')
            b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
        except Exception:
            continue
        try:
            resp = requests.post(
                url.rstrip('/') + '/api/embeddings',
                json={'model': model, 'prompt': b64},
                headers=headers,
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            emb = data.get('embedding')
            if emb is None:
                continue
            cur.execute(
                "INSERT INTO embeddings (media_id, model, embedding) VALUES (?, ?, ?)",
                (media_id, model, json.dumps(emb)),
            )
            conn.commit()
            processed += 1
        except Exception:
            continue
    conn.close()
    return processed


def delete_user(username: str) -> None:
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute("DELETE FROM users WHERE username=?", (username,))
    cur.execute("DELETE FROM rankings WHERE username=?", (username,))
    conn.commit()
    conn.close()


def get_user_media_stats(username: str, limit: int = 5) -> tuple[
    list[tuple[str, float, float, int, int]], list[tuple[str, float, float, int, int]]
]:
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


def get_global_media_stats_with_user(username: str, limit: int = 5) -> tuple[
    list[tuple[str, float, float | None, int, int]],
    list[tuple[str, float, float | None, int, int]],
]:
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute("SELECT filename, elo, rating_count FROM media")
    global_rows = cur.fetchall()
    if not global_rows:
        conn.close()
        return [], []
    cur.execute(
        """
        SELECT m.filename, um.elo, um.rating_count
        FROM user_media um JOIN media m ON um.media_id = m.id
        WHERE um.username=?
        """,
        (username,),
    )
    user_rows = {row[0]: (row[1], row[2]) for row in cur.fetchall()}
    conn.close()

    global_rows.sort(key=lambda r: r[1], reverse=True)
    highest = global_rows[:limit]
    lowest = global_rows[-limit:][::-1]
    highest = [
        (
            m,
            g_elo,
            user_rows.get(m, (None, 0))[0],
            g_cnt,
            user_rows.get(m, (None, 0))[1],
        )
        for m, g_elo, g_cnt in highest
    ]
    lowest = [
        (
            m,
            g_elo,
            user_rows.get(m, (None, 0))[0],
            g_cnt,
            user_rows.get(m, (None, 0))[1],
        )
        for m, g_elo, g_cnt in lowest
    ]
    return highest, lowest


def get_elo_rankings(limit: int = 20) -> list[tuple[str, float, int]]:
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute(
        "SELECT filename, elo, rating_count FROM media ORDER BY elo DESC LIMIT ?",
        (limit,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_name_group_elo_stats() -> list[tuple[str, int, int, float, float, float, float]]:
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute("SELECT filename, elo, rating_count FROM media")
    rows = cur.fetchall()
    conn.close()
    groups: dict[str, list[tuple[float, int]]] = {}
    for media, rating, cnt in rows:
        name, _ = os.path.splitext(media)
        name = name.lower().replace('_', '')
        name = ''.join(ch for ch in name if not ch.isdigit())
        groups.setdefault(name, []).append((rating, cnt))

    stats = []
    for name, values in groups.items():
        count = len(values)
        total_ratings = sum(c for _, c in values)
        ratings = [r for r, _ in values]
        avg = sum(ratings) / count
        mn = min(ratings)
        mx = max(ratings)
        var = sum((r - avg) ** 2 for r in ratings) / count
        std = var ** 0.5
        stats.append((name, count, total_ratings, mn, mx, avg, std))

    stats.sort(key=lambda s: -s[5])
    return stats


def remove_duplicate_images() -> int:
    files = [f for f in os.listdir(MEDIA_DIR) if os.path.isfile(os.path.join(MEDIA_DIR, f))]
    hashes: dict[str, list[str]] = {}
    for fname in files:
        path = os.path.join(MEDIA_DIR, fname)
        try:
            with Image.open(path) as img:
                img = img.convert('RGB')
                h = hashlib.sha256(img.tobytes()).hexdigest()
        except Exception:
            continue
        hashes.setdefault(h, []).append(fname)

    removed = 0
    for dup_files in hashes.values():
        if len(dup_files) > 1:
            random.shuffle(dup_files)
            dup_files.pop()
            for fname in dup_files:
                try:
                    os.remove(os.path.join(MEDIA_DIR, fname))
                    removed += 1
                except FileNotFoundError:
                    pass
    return removed
