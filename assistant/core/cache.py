"""Stores answers already produced, so the same question is never paid for twice."""

from __future__ import annotations                            # lets us write modern type hints safely

import hashlib                                                 # turns a long prompt into a short fingerprint
import sqlite3                                                 # a small database kept in a single file
import time                                                    # records when each answer was stored

from assistant.config import project_path                      # turns a config path into a real one

# The table we store answers in; "IF NOT EXISTS" means it is created once and reused afterwards.
SCHEMA = """
CREATE TABLE IF NOT EXISTS responses (
    key        TEXT PRIMARY KEY,
    provider   TEXT NOT NULL,
    model      TEXT NOT NULL,
    prompt     TEXT NOT NULL,
    answer     TEXT NOT NULL,
    created_at REAL NOT NULL
)
"""


def _connect(config: dict) -> sqlite3.Connection:              # opens the cache file, creating it if needed
    """Open the cache database named in config.yaml and make sure its table exists."""
    path = project_path(config["cache"]["path"])               # where the cache file lives
    path.parent.mkdir(parents=True, exist_ok=True)             # create its folder if missing
    connection = sqlite3.connect(path)                         # open the database file
    connection.execute(SCHEMA)                                 # create the table the first time only
    return connection                                          # hand the open connection back


def make_key(provider: str, model: str, prompt: str) -> str:   # builds the name an answer is filed under
    """Build a short unique fingerprint for one exact request."""
    raw = f"{provider}|{model}|{prompt}"                       # the three things that decide the answer
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()     # squeeze them into one fixed-length string


def get(config: dict, key: str) -> str | None:                 # looks for an answer we already have
    """Return the stored answer for this key, or None if we have never answered it."""
    if not config["cache"]["enabled"]:                         # the cache can be switched off in config
        return None                                            # in which case we always pretend to miss
    with _connect(config) as connection:                       # open the database
        row = connection.execute("SELECT answer FROM responses WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None                             # the answer, or nothing


def put(config: dict, key: str, provider: str, model: str, prompt: str, answer: str) -> None:
    """Store one answer so the next identical question costs nothing."""
    if not config["cache"]["enabled"] or not answer:           # cache off, or nothing worth storing
        return                                                 # store nothing
    with _connect(config) as connection:                       # open the database
        connection.execute(                                    # write the row, replacing any older one
            "INSERT OR REPLACE INTO responses (key, provider, model, prompt, answer, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (key, provider, model, prompt, answer, time.time()),
        )


def stats(config: dict) -> dict:                               # how much the cache currently holds
    """Return how many answers the cache is storing."""
    with _connect(config) as connection:                       # open the database
        total = connection.execute("SELECT COUNT(*) FROM responses").fetchone()[0]
    return {"entries": total}                                  # hand the number back