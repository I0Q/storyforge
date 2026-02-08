from __future__ import annotations

import json
import re
import time
from typing import Any


def _now() -> int:
    return int(time.time())


_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def validate_story_id(story_id: str) -> str:
    sid = (story_id or "").strip()
    if not _ID_RE.match(sid):
        raise ValueError(
            "Invalid id. Use 1-64 chars: lowercase letters, digits, '-' or '_' (must start with letter/digit)."
        )
    return sid


def db_init_stories(conn) -> None:
    cur = conn.cursor()
    try:
        cur.execute("SET statement_timeout = '5000'")
    except Exception:
        pass

    cur.execute(
        """
CREATE TABLE IF NOT EXISTS sf_stories (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  tags JSONB NOT NULL DEFAULT '[]'::jsonb,
  story_md TEXT NOT NULL DEFAULT '',
  characters JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL
);
"""
    )
    conn.commit()


def list_stories_db(conn, limit: int = 500) -> list[dict[str, Any]]:
    cur = conn.cursor()
    try:
        cur.execute("SET statement_timeout = '5000'")
    except Exception:
        pass
    cur.execute(
        "SELECT id,title,tags,updated_at FROM sf_stories ORDER BY updated_at DESC LIMIT %s",
        (int(limit),),
    )
    rows = cur.fetchall()
    out = []
    for r in rows:
        tags = r[2]
        # psycopg2 may return dict/list already for jsonb, but be defensive
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except Exception:
                tags = []
        out.append(
            {
                "id": r[0],
                "title": r[1],
                "tags": tags or [],
                "updated_at": r[3],
            }
        )
    return out


def get_story_db(conn, story_id: str) -> dict[str, Any]:
    cur = conn.cursor()
    try:
        cur.execute("SET statement_timeout = '5000'")
    except Exception:
        pass
    cur.execute(
        "SELECT id,title,tags,story_md,characters,created_at,updated_at FROM sf_stories WHERE id=%s",
        (story_id,),
    )
    r = cur.fetchone()
    if not r:
        raise FileNotFoundError("not found")

    tags = r[2]
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except Exception:
            tags = []

    chars = r[4]
    if isinstance(chars, str):
        try:
            chars = json.loads(chars)
        except Exception:
            chars = []

    return {
        "id": r[0],
        "meta": {
            "id": r[0],
            "title": r[1],
            "tags": tags or [],
        },
        "characters": chars or [],
        "story_md": r[3] or "",
        "created_at": r[5],
        "updated_at": r[6],
    }


def upsert_story_db(
    conn,
    story_id: str,
    title: str,
    tags: list[str],
    story_md: str,
    characters: list[dict[str, Any]],
) -> None:
    now = _now()
    cur = conn.cursor()
    try:
        cur.execute("SET statement_timeout = '5000'")
    except Exception:
        pass

    cur.execute(
        """
INSERT INTO sf_stories (id,title,tags,story_md,characters,created_at,updated_at)
VALUES (%s,%s,%s::jsonb,%s,%s::jsonb,%s,%s)
ON CONFLICT (id) DO UPDATE SET
  title=EXCLUDED.title,
  tags=EXCLUDED.tags,
  story_md=EXCLUDED.story_md,
  characters=EXCLUDED.characters,
  updated_at=EXCLUDED.updated_at;
""",
        (
            story_id,
            title,
            json.dumps(tags or []),
            story_md or "",
            json.dumps(characters or []),
            now,
            now,
        ),
    )
    conn.commit()


def delete_story_db(conn, story_id: str) -> None:
    cur = conn.cursor()
    try:
        cur.execute("SET statement_timeout = '5000'")
    except Exception:
        pass
    cur.execute("DELETE FROM sf_stories WHERE id=%s", (story_id,))
    conn.commit()
