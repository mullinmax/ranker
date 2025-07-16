# Ranker

Simple FastAPI application for ranking media files.

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
retain user accounts and ranking history. Users can register, log in and order
the displayed media using drag and drop or the keyboard. Each submission updates
the global and personal ELO scores for the selected files. Media items are
presented in order of least recently ranked for each user, so once an item is
scored a different file will be shown next. Each ranking stores the time it was
submitted so files can be sorted by when a user last interacted with them.
The page also displays when the current media was last ranked by the user. If it
was ranked today, the timestamp appears in green.

Admin usernames can be supplied via the `ADMIN_USERS` environment variable as a
comma separated list. When set, an authenticated admin can visit `/admin` to
manage accounts and upload new media files. The upload form accepts multiple
files so an admin can add several media items in one request.

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

## Database schema

The application uses a SQLite database with three tables:

```
users(id INTEGER PRIMARY KEY AUTOINCREMENT,
      username TEXT UNIQUE,
      password TEXT)

media(id INTEGER PRIMARY KEY AUTOINCREMENT,
      filename TEXT UNIQUE,
      elo REAL DEFAULT 1000,
      rating_count INTEGER DEFAULT 0)

rankings(id INTEGER PRIMARY KEY AUTOINCREMENT,
         username TEXT REFERENCES users(username),
         first_id INTEGER,
         second_id INTEGER,
         third_id INTEGER,
         fourth_id INTEGER,
         rated_at INTEGER),

user_media(username TEXT,
           media_id INTEGER,
           elo REAL DEFAULT 1000,
           rating_count INTEGER DEFAULT 0,
           PRIMARY KEY(username, media_id))
```

Each row in `rankings` stores the four media IDs shown together in their ranked
order. The `media` table tracks the current ELO rating for every file along with
how many pairwise matches that rating is based on. New media rows start with an
ELO of `1000`.

### Ranking math

Each ranking submission updates the ELO scores of the involved media. For every
pair of files `(winner, loser)` the ratings are adjusted using the standard ELO
formula with `K = 32`:

```
Ea = 1 / (1 + 10 ** ((Rb - Ra) / 400))
Eb = 1 / (1 + 10 ** ((Ra - Rb) / 400))
Ra_new = Ra + K * (1 - Ea)
Rb_new = Rb + K * (0 - Eb)
```

These values are then displayed on the statistics page ordered from highest to
lowest.

Each user also maintains personal Elo ratings for every media item they have
ranked. The stats page shows your own Elo alongside the global values for the
highest and lowest rated media. Every entry on the statistics tables includes
the number of rankings that its Elo score is based on, both globally and for
your account.
