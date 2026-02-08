from __future__ import annotations

import time
from typing import Any


def _now() -> int:
    return int(time.time())


def list_todos_db(conn, limit: int = 800) -> list[dict[str, Any]]:
    cur = conn.cursor()
    try:
        cur.execute("SET statement_timeout = '5000'")
    except Exception:
        pass
    cur.execute(
        "SELECT id,text,status,created_at,updated_at FROM sf_todos ORDER BY id DESC LIMIT %s",
        (int(limit),),
    )
    rows = cur.fetchall()
    return [
        {
            'id': r[0],
            'text': r[1] or '',
            'status': (r[2] or 'open'),
            'created_at': r[3],
            'updated_at': r[4],
        }
        for r in rows
    ]


def add_todo_db(conn, text: str, status: str = 'open') -> int:
    now = _now()
    cur = conn.cursor()
    try:
        cur.execute("SET statement_timeout = '5000'")
    except Exception:
        pass
    cur.execute(
        "INSERT INTO sf_todos (text,status,created_at,updated_at) VALUES (%s,%s,%s,%s) RETURNING id",
        (str(text or '').strip(), str(status or 'open'), now, now),
    )
    rid = cur.fetchone()[0]
    conn.commit()
    return int(rid)
