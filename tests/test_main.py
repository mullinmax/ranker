import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[1]))
import os
import sqlite3
import tempfile
from PIL import Image

# Ensure the app uses a writable location during import
_base = tempfile.mkdtemp()
os.environ.setdefault("MEDIA_DIR", os.path.join(_base, "media"))
os.environ.setdefault("CONFIG_DIR", os.path.join(_base, "config"))

import pytest
from fastapi.testclient import TestClient

import app.main as main


def create_client(tmp_path: Path, admin_users: list[str] | None = None) -> TestClient:
    media_dir = tmp_path / "media"
    config_dir = tmp_path / "config"
    os.makedirs(media_dir, exist_ok=True)
    os.makedirs(config_dir, exist_ok=True)
    main.MEDIA_DIR = str(media_dir)
    main.CONFIG_DIR = str(config_dir)
    main.DATABASE = str(config_dir / "database.db")
    main.ADMIN_USERS = set(admin_users or [])
    if os.path.exists(main.DATABASE):
        os.remove(main.DATABASE)
    main.init_db()
    return TestClient(main.app)


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    return create_client(tmp_path)


@pytest.fixture()
def admin_client(tmp_path: Path) -> TestClient:
    return create_client(tmp_path, admin_users=["admin"])


def test_register_and_login(client: TestClient):
    resp = client.post("/register", data={"username": "alice", "password": "secret"}, follow_redirects=False)
    assert resp.status_code == 303
    resp = client.post("/login", data={"username": "alice", "password": "secret"}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    assert "username=alice" in resp.headers.get("set-cookie", "")


def test_rating_and_stats(client: TestClient, tmp_path: Path):
    media1 = tmp_path / "f1.jpg"
    media2 = tmp_path / "f2.jpg"
    media1.write_bytes(b"a")
    media2.write_bytes(b"b")
    # move media files into MEDIA_DIR
    media1_dest = Path(main.MEDIA_DIR) / media1.name
    media2_dest = Path(main.MEDIA_DIR) / media2.name
    media1_dest.write_bytes(media1.read_bytes())
    media2_dest.write_bytes(media2.read_bytes())

    client.post("/register", data={"username": "u", "password": "p"}, follow_redirects=False)
    client.post("/login", data={"username": "u", "password": "p"}, follow_redirects=False)

    resp = client.post("/rate", data={"order": f"{media1.name},{media2.name}"}, follow_redirects=False)
    assert resp.status_code == 303

    conn = sqlite3.connect(main.DATABASE)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM rankings WHERE username=?", ("u",))
    count = cur.fetchone()[0]
    conn.close()
    assert count == 1

    resp = client.get("/stats")
    assert resp.status_code == 200


def test_rank_event_recorded(client: TestClient, tmp_path: Path):
    files = []
    for i in range(4):
        f = tmp_path / f"f{i}.jpg"
        f.write_bytes(bytes(str(i), "utf-8"))
        dest = Path(main.MEDIA_DIR) / f.name
        dest.write_bytes(f.read_bytes())
        files.append(f.name)

    client.post("/register", data={"username": "u", "password": "p"}, follow_redirects=False)
    client.post("/login", data={"username": "u", "password": "p"}, follow_redirects=False)

    order = ",".join(files)
    resp = client.post("/rate", data={"order": order}, follow_redirects=False)
    assert resp.status_code == 303

    conn = sqlite3.connect(main.DATABASE)
    cur = conn.cursor()
    cur.execute(
        "SELECT first_id, second_id, third_id, fourth_id FROM rankings WHERE username=?",
        ("u",),
    )
    row = cur.fetchone()
    assert row is not None
    cur.execute("SELECT filename FROM media ORDER BY id")
    media_names = [r[0] for r in cur.fetchall()]
    conn.close()
    recorded = [media_names[row[i] - 1] if row[i] else None for i in range(4)]
    assert recorded[: len(files)] == files


def test_admin_panel(admin_client: TestClient):
    admin_client.post("/register", data={"username": "admin", "password": "x"}, follow_redirects=False)
    admin_client.post("/register", data={"username": "bob", "password": "old"}, follow_redirects=False)
    admin_client.post("/login", data={"username": "admin", "password": "x"}, follow_redirects=False)

    resp = admin_client.get("/admin")
    assert resp.status_code == 200

    resp = admin_client.post(
        "/admin/change_password", data={"target_user": "bob", "new_password": "new"}, follow_redirects=False
    )
    assert resp.status_code == 303

    admin_client.get("/logout")
    resp = admin_client.post("/login", data={"username": "bob", "password": "new"}, follow_redirects=False)
    assert resp.status_code == 303

    admin_client.post("/login", data={"username": "admin", "password": "x"}, follow_redirects=False)
    resp = admin_client.post(
        "/admin/upload_media",
        files={"media_files": ("uploaded.txt", b"data")},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert os.path.exists(os.path.join(main.MEDIA_DIR, "uploaded.txt"))


def test_remove_duplicates_endpoint(admin_client: TestClient):
    admin_client.post("/register", data={"username": "admin", "password": "x"}, follow_redirects=False)
    admin_client.post("/login", data={"username": "admin", "password": "x"}, follow_redirects=False)

    img1 = Image.new("RGB", (1, 1), color="red")
    img2 = Image.new("RGB", (1, 1), color="red")
    img3 = Image.new("RGB", (1, 1), color="blue")

    path1 = Path(main.MEDIA_DIR) / "a.png"
    path2 = Path(main.MEDIA_DIR) / "b.png"
    path3 = Path(main.MEDIA_DIR) / "c.png"
    img1.save(path1)
    img2.save(path2)
    img3.save(path3)

    resp = admin_client.post("/admin/remove_duplicates", follow_redirects=False)
    assert resp.status_code == 303

    remaining = [path1.exists(), path2.exists()]
    assert remaining.count(True) == 1
    assert path3.exists()
