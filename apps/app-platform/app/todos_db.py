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

    try:
        cur.execute(
            "SELECT id,category,text,status,archived,highlighted,created_at,updated_at FROM sf_todos ORDER BY id DESC LIMIT %s",
            (int(limit),),
        )
        rows = cur.fetchall()
    except Exception as e:
        # If a deploy hits before migrations, self-heal.
        try:
            conn.rollback()
        except Exception:
            pass
        msg = str(e)
        if 'highlighted' in msg and ('does not exist' in msg or 'UndefinedColumn' in msg):
            try:
                cur.execute(
                    "ALTER TABLE sf_todos ADD COLUMN IF NOT EXISTS highlighted BOOLEAN NOT NULL DEFAULT FALSE"
                )
                conn.commit()
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
            cur.execute(
                "SELECT id,category,text,status,archived,highlighted,created_at,updated_at FROM sf_todos ORDER BY id DESC LIMIT %s",
                (int(limit),),
            )
            rows = cur.fetchall()
        else:
            raise

    return [
        {
            'id': r[0],
            'category': r[1] or '',
            'text': r[2] or '',
            'status': (r[3] or 'open'),
            'archived': bool(r[4]),
            'highlighted': bool(r[5]),
            'created_at': r[6],
            'updated_at': r[7],
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


def archive_done_todos_db(conn) -> int:
    """Archive all completed (status != open) todos. Returns count updated."""
    now = _now()
    cur = conn.cursor()
    try:
        cur.execute("SET statement_timeout = '5000'")
    except Exception:
        pass
    cur.execute(
        "UPDATE sf_todos SET archived=TRUE, updated_at=%s WHERE archived=FALSE AND status<>'open'",
        (now,),
    )
    n = cur.rowcount or 0
    conn.commit()
    return int(n)


def delete_todo_db(conn, todo_id: int) -> bool:
    cur = conn.cursor()
    cur.execute("DELETE FROM sf_todos WHERE id=%s", (int(todo_id),))
    ok = cur.rowcount > 0
    conn.commit()
    return ok


def set_todo_highlight_db(conn, todo_id: int, highlighted: bool) -> None:
    cur = conn.cursor()
    cur.execute(
        "UPDATE sf_todos SET highlighted=%s, updated_at=NOW() WHERE id=%s",
        (bool(highlighted), int(todo_id)),
    )
    conn.commit()


def toggle_todo_highlight_db(conn, todo_id: int) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT highlighted FROM sf_todos WHERE id=%s", (int(todo_id),))
    row = cur.fetchone()
    cur_high = bool(row[0]) if row else False
    new_val = not cur_high
    cur.execute(
        "UPDATE sf_todos SET highlighted=%s, updated_at=NOW() WHERE id=%s",
        (new_val, int(todo_id)),
    )
    conn.commit()
    return new_val
