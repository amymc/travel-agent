"""Small persistent SQLite response cache for public geospatial APIs."""

import json
import sqlite3
from pathlib import Path

from app.config import settings


def cache_path() -> Path:
    path = Path(settings.cache_db_path).expanduser()
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[2] / path
    return path


def _connect() -> sqlite3.Connection:
    path = cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.execute(
        "CREATE TABLE IF NOT EXISTS api_cache "
        "(cache_key TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    return connection


def get_cached(key: str) -> object | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT payload FROM api_cache WHERE cache_key = ?", (key,)
        ).fetchone()
    payload: object | None = json.loads(row[0]) if row else None
    return payload


def set_cached(key: str, payload: object) -> None:
    with _connect() as connection:
        connection.execute(
            "INSERT INTO api_cache(cache_key, payload) VALUES (?, ?) "
            "ON CONFLICT(cache_key) DO UPDATE SET payload = excluded.payload, "
            "created_at = CURRENT_TIMESTAMP",
            (key, json.dumps(payload, separators=(",", ":"))),
        )
