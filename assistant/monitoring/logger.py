"""Records one row per answered question, so the interface can report statistics."""

from __future__ import annotations                            # lets us write modern type hints safely

import sqlite3                                                 # the small database that holds the rows
from datetime import datetime, timezone                        # to stamp each row with the time

from assistant.config import project_path                      # turns a config path into a real path

SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asked_at TEXT NOT NULL,
    question TEXT NOT NULL,
    refused INTEGER NOT NULL,
    refused_by TEXT,
    seconds REAL NOT NULL,
    passages_used INTEGER NOT NULL,
    best_similarity REAL NOT NULL,
    sources_cited INTEGER NOT NULL,
    cached INTEGER NOT NULL,
    model TEXT,
    prompt_version TEXT
)
"""                                                            # one row per question, created on first use


def _connect(config):
    """Open the monitoring database, creating the file and table if needed."""
    path = project_path(config["monitoring"]["database"])      # where the database file lives
    path.parent.mkdir(parents=True, exist_ok=True)             # make data/ if it is not there yet
    connection = sqlite3.connect(path)                         # open it
    connection.row_factory = sqlite3.Row                       # lets us read columns by name
    connection.execute(SCHEMA)                                 # create the table the first time only
    return connection                                          # hand the open connection back


def log_request(config, result: dict, prompt_version: str) -> None:
    """Write one row describing how the assistant handled this question."""
    settings = config["monitoring"]                            # the monitoring settings
    if not settings.get("enabled", True):                      # monitoring can be switched off entirely
        return                                                 # then we record nothing
    question = result["question"] if settings.get("store_questions", True) else "(not stored)"
    with _connect(config) as connection:                       # open, write, commit automatically
        connection.execute(
            "INSERT INTO requests (asked_at, question, refused, refused_by, seconds,"
            " passages_used, best_similarity, sources_cited, cached, model, prompt_version)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",       # placeholders, never string formatting
            (
                datetime.now(timezone.utc).isoformat(timespec="seconds"),   # when it was asked
                question,                                      # the question, or the placeholder
                int(result["refused"]),                        # SQLite has no boolean, so 0 or 1
                result["refused_by"],                          # "threshold", "model", or nothing
                result["seconds"],                             # the response time the brief asks for
                result["passages_used"],                       # how many passages were sent
                result["best_similarity"],                     # how close the best passage was
                len(result["sources"]),                        # how many sources ended up cited
                int(result["cached"]),                         # whether the cache answered it
                result["model"],                               # which model wrote it
                prompt_version,                                # which prompt version was used
            ),
        )


def read_rows(config, limit: int = 200) -> list[dict]:
    """Return the most recent rows, newest first."""
    with _connect(config) as connection:                       # open the database
        rows = connection.execute(                             # newest first, capped so it stays fast
            "SELECT * FROM requests ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(row) for row in rows]                         # plain dictionaries are easier to send


def _mean(values: list[float]) -> float:
    """Average a list of numbers, returning 0 for an empty list instead of crashing."""
    return round(sum(values) / len(values), 3) if values else 0.0


def summarise(config) -> dict:
    """Turn every recorded row into the handful of numbers the statistics page shows."""
    with _connect(config) as connection:                       # read everything
        rows = [dict(row) for row in connection.execute("SELECT * FROM requests").fetchall()]
    total = len(rows)                                          # how many questions in total
    if not total:                                              # nothing recorded yet
        return {"total": 0}                                    # the page will show an empty state
    refused = [r for r in rows if r["refused"]]                # the questions it declined
    live = [r for r in rows if not r["cached"]]                # the ones that really called the model
    cached = [r for r in rows if r["cached"]]                  # the ones the cache answered
    return {
        "total": total,                                        # questions answered
        "refused": len(refused),                               # how many were refused
        "refusal_rate": round(len(refused) / total, 3),        # the proportion refused
        "refused_by_threshold": sum(1 for r in refused if r["refused_by"] == "threshold"),   # before the model
        "refused_by_model": sum(1 for r in refused if r["refused_by"] == "model"),           # by the model
        "cached": len(cached),                                 # how many came from the cache
        "cache_rate": round(len(cached) / total, 3),           # the proportion served from cache
        "avg_seconds": _mean([r["seconds"] for r in rows]),    # average response time overall
        "avg_seconds_live": _mean([r["seconds"] for r in live]),       # average when the model really ran
        "avg_seconds_cached": _mean([r["seconds"] for r in cached]),   # average when the cache answered
        "avg_passages": _mean([r["passages_used"] for r in rows]),     # average passages sent
        "avg_similarity": _mean([r["best_similarity"] for r in rows]), # average retrieval quality
        "store_questions": bool(config["monitoring"].get("store_questions", True)),  # for the privacy notice
    }