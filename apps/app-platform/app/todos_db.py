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
        "SELECT id,category,text,status,created_at,updated_at FROM sf_todos ORDER BY id DESC LIMIT %s",
        (int(limit),),
    )
    rows = cur.fetchall()
    return [
        {
            'id': r[0],
            'category': r[1] or '',
            'text': r[2] or '',
            'status': (r[3] or 'open'),
            'created_at': r[4],
            'updated_at': r[5],
        }
        for r in rows
    ]


def add_todo_db(conn, text: str, status: str = 'open', category: str = '') -> int:
    now = _now()
    cur = conn.cursor()
    try:
        cur.execute("SET statement_timeout = '5000'")
    except Exception:
        pass
    cur.execute(
        "INSERT INTO sf_todos (category,text,status,created_at,updated_at) VALUES (%s,%s,%s,%s,%s) RETURNING id",
        (str(category or '').strip(), str(text or '').strip(), str(status or 'open'), now, now),
    )
    rid = cur.fetchone()[0]
    conn.commit()
    return int(rid)



def set_todo_status_db(conn, todo_id: int, status: str) -> None:
    now = _now()
    cur = conn.cursor()
    try:
        cur.execute("SET statement_timeout = '5000'")
    except Exception:
        pass
    cur.execute(
        "UPDATE sf_todos SET status=%s, updated_at=%s WHERE id=%s",
        (str(status or 'open'), now, int(todo_id)),
    )
    conn.commit()
