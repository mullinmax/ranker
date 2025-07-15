# Ranker

Simple FastAPI application for rating media files.

## Development

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the application:

```bash
uvicorn app.main:app --reload
```

The app serves files from a `/ranker-media` directory. You should mount a
folder from the host into this location when running the container. A SQLite
database is stored under `/config`, so that directory should also be mounted to
retain user accounts and ratings. Users can register, log in and rate the
displayed media from 1 to 5 using buttons or the keyboard.

Admin usernames can be supplied via the `ADMIN_USERS` environment variable as a
comma separated list. When set, an authenticated admin can visit `/admin` to
manage accounts and upload new media files.

## Docker

Build and run with Docker:

```bash
docker build -t ranker .
docker run -p 8000:8000 \
    -v /path/to/config:/config \
    -v /path/to/media:/ranker-media \
    -e ADMIN_USERS=admin1,admin2 \
    ranker
```

## CI

GitHub Actions workflow builds the Docker image and publishes it to GHCR on each push to `main`.
