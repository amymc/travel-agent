"""Persistent trip threads, messages, revisions, and streamed agent events."""

import json
import sqlite3
from typing import Literal, TypedDict, cast
from uuid import uuid4

from app.domain.models import ItineraryResponse, JsonValue, TripRequest
from app.services.cache import cache_path


class ThreadSummary(TypedDict):
    thread_id: str
    title: str
    updated_at: str
    revision_number: int | None
    itinerary_title: str | None


class ThreadMessage(TypedDict):
    message_id: int
    role: Literal["user", "assistant"]
    content: str
    created_at: str


class ThreadSnapshot(TypedDict):
    trip_id: str
    revision_number: int
    request: dict[str, JsonValue]
    response: dict[str, JsonValue]
    created_at: str


class ThreadEvent(TypedDict):
    event_id: int
    event_type: str
    payload: dict[str, JsonValue]
    created_at: str


class ThreadDetail(TypedDict):
    thread_id: str
    title: str
    created_at: str
    updated_at: str
    messages: list[ThreadMessage]
    snapshots: list[ThreadSnapshot]
    events: list[ThreadEvent]


def _connect() -> sqlite3.Connection:
    path = cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS trip_threads ("
        "thread_id TEXT PRIMARY KEY, title TEXT NOT NULL, "
        "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS trip_messages ("
        "message_id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id TEXT NOT NULL, "
        "role TEXT NOT NULL CHECK(role IN ('user','assistant')), content TEXT NOT NULL, "
        "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "FOREIGN KEY(thread_id) REFERENCES trip_threads(thread_id) ON DELETE CASCADE)"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS trip_snapshots ("
        "trip_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, revision_number INTEGER NOT NULL, "
        "request_json TEXT NOT NULL, response_json TEXT NOT NULL, "
        "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "UNIQUE(thread_id, revision_number), "
        "FOREIGN KEY(thread_id) REFERENCES trip_threads(thread_id) ON DELETE CASCADE)"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS trip_events ("
        "event_id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id TEXT NOT NULL, "
        "trip_id TEXT, event_type TEXT NOT NULL, payload_json TEXT NOT NULL, "
        "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "FOREIGN KEY(thread_id) REFERENCES trip_threads(thread_id) ON DELETE CASCADE)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_trip_messages_thread "
        "ON trip_messages(thread_id, message_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_trip_events_thread "
        "ON trip_events(thread_id, event_id)"
    )
    return connection


def create_thread(title: str) -> str:
    thread_id = str(uuid4())
    with _connect() as connection:
        connection.execute(
            "INSERT INTO trip_threads(thread_id, title) VALUES (?, ?)",
            (thread_id, title[:120] or "New trip"),
        )
    return thread_id


def add_message(thread_id: str, role: Literal["user", "assistant"], content: str) -> None:
    with _connect() as connection:
        connection.execute(
            "INSERT INTO trip_messages(thread_id, role, content) VALUES (?, ?, ?)",
            (thread_id, role, content),
        )
        connection.execute(
            "UPDATE trip_threads SET updated_at = CURRENT_TIMESTAMP WHERE thread_id = ?",
            (thread_id,),
        )


def save_snapshot(
    thread_id: str,
    request: TripRequest,
    response: ItineraryResponse,
) -> ItineraryResponse:
    trip_id = str(uuid4())
    with _connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT COALESCE(MAX(revision_number), 0) FROM trip_snapshots WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()
        revision_number = int(row[0]) + 1 if row else 1
        response_data = cast(dict[str, JsonValue], response.model_dump(mode="json"))
        response_data.update(
            {
                "thread_id": thread_id,
                "trip_id": trip_id,
                "revision_number": revision_number,
            }
        )
        stored_response = ItineraryResponse.model_validate(response_data)
        connection.execute(
            "INSERT INTO trip_snapshots"
            "(trip_id, thread_id, revision_number, request_json, response_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                trip_id,
                thread_id,
                revision_number,
                request.model_dump_json(),
                stored_response.model_dump_json(),
            ),
        )
        connection.execute(
            "UPDATE trip_threads SET updated_at = CURRENT_TIMESTAMP WHERE thread_id = ?",
            (thread_id,),
        )
    return stored_response


def record_event(
    thread_id: str,
    event_type: str,
    payload: dict[str, JsonValue],
    trip_id: str | None = None,
) -> None:
    with _connect() as connection:
        connection.execute(
            "INSERT INTO trip_events(thread_id, trip_id, event_type, payload_json) "
            "VALUES (?, ?, ?, ?)",
            (
                thread_id,
                trip_id,
                event_type,
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            ),
        )


def list_threads(limit: int = 30) -> list[ThreadSummary]:
    with _connect() as connection:
        threads = connection.execute(
            "SELECT thread_id, title, updated_at FROM trip_threads "
            "ORDER BY updated_at DESC LIMIT ?",
            (max(1, min(limit, 100)),),
        ).fetchall()
        summaries: list[ThreadSummary] = []
        for thread_id, title, updated_at in threads:
            snapshot = connection.execute(
                "SELECT revision_number, response_json FROM trip_snapshots "
                "WHERE thread_id = ? ORDER BY revision_number DESC LIMIT 1",
                (thread_id,),
            ).fetchone()
            itinerary_title: str | None = None
            revision_number: int | None = None
            if snapshot:
                revision_number = int(snapshot[0])
                response_data = cast(dict[str, JsonValue], json.loads(snapshot[1]))
                itinerary = response_data.get("itinerary")
                if isinstance(itinerary, dict):
                    value = itinerary.get("title")
                    itinerary_title = value if isinstance(value, str) else None
            summaries.append(
                {
                    "thread_id": thread_id,
                    "title": title,
                    "updated_at": updated_at,
                    "revision_number": revision_number,
                    "itinerary_title": itinerary_title,
                }
            )
    return summaries


def get_thread(thread_id: str) -> ThreadDetail | None:
    with _connect() as connection:
        thread = connection.execute(
            "SELECT thread_id, title, created_at, updated_at FROM trip_threads WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()
        if thread is None:
            return None
        raw_messages = connection.execute(
            "SELECT message_id, role, content, created_at FROM trip_messages "
            "WHERE thread_id = ? ORDER BY message_id",
            (thread_id,),
        ).fetchall()
        raw_snapshots = connection.execute(
            "SELECT trip_id, revision_number, request_json, response_json, created_at "
            "FROM trip_snapshots WHERE thread_id = ? ORDER BY revision_number",
            (thread_id,),
        ).fetchall()
        raw_events = connection.execute(
            "SELECT event_id, event_type, payload_json, created_at FROM trip_events "
            "WHERE thread_id = ? ORDER BY event_id",
            (thread_id,),
        ).fetchall()
    messages: list[ThreadMessage] = [
        {
            "message_id": int(row[0]),
            "role": cast(Literal["user", "assistant"], row[1]),
            "content": str(row[2]),
            "created_at": str(row[3]),
        }
        for row in raw_messages
    ]
    snapshots: list[ThreadSnapshot] = [
        {
            "trip_id": str(row[0]),
            "revision_number": int(row[1]),
            "request": cast(dict[str, JsonValue], json.loads(row[2])),
            "response": cast(dict[str, JsonValue], json.loads(row[3])),
            "created_at": str(row[4]),
        }
        for row in raw_snapshots
    ]
    events: list[ThreadEvent] = [
        {
            "event_id": int(row[0]),
            "event_type": str(row[1]),
            "payload": cast(dict[str, JsonValue], json.loads(row[2])),
            "created_at": str(row[3]),
        }
        for row in raw_events
    ]
    return {
        "thread_id": str(thread[0]),
        "title": str(thread[1]),
        "created_at": str(thread[2]),
        "updated_at": str(thread[3]),
        "messages": messages,
        "snapshots": snapshots,
        "events": events,
    }


def latest_snapshot(thread_id: str) -> tuple[TripRequest, ItineraryResponse] | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT request_json, response_json FROM trip_snapshots "
            "WHERE thread_id = ? ORDER BY revision_number DESC LIMIT 1",
            (thread_id,),
        ).fetchone()
    if row is None:
        return None
    return TripRequest.model_validate_json(row[0]), ItineraryResponse.model_validate_json(row[1])
