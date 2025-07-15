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

The app serves files from a `media` directory. You should mount a folder from
the host into `/app/media` when running the container. Users can register, log
in and rate the displayed media from 1 to 5 using buttons or the keyboard.

## Docker

Build and run with Docker:

```bash
docker build -t ranker .
docker run -p 8000:8000 -v /path/to/media:/app/media ranker
```

## CI

GitHub Actions workflow builds the Docker image and publishes it to GHCR on each push to `main`.
