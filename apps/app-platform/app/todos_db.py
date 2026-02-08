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


def bootstrap_todos_from_markdown(conn, md_text: str) -> int:
    """Best-effort one-time import of TODO.md into sf_todos.

    - Heading lines: "## X" -> category "X" (free text)
    - Items:
      - "- [ ] text" -> status=open
      - "- [x] text" -> status=done

    Returns number of inserted rows.
    """

    if not md_text:
        return 0

    cur = conn.cursor()
    # Build a set of existing (category,text,status) so we can import missing lines
    cur.execute('SELECT category,text,status FROM sf_todos')
    existing = set((r[0] or '', r[1] or '', (r[2] or 'open')) for r in cur.fetchall())

    cat = ''
    inserted = 0
    for raw in md_text.splitlines():
        line = (raw or '').strip()
        if line.startswith('## '):
            cat = line[3:].strip()
            continue

        status = None
        text = None
        if line.startswith('- [ ] '):
            status = 'open'
            text = line[6:]
        elif line.lower().startswith('- [x] '):
            status = 'done'
            text = line[6:]

        if status and text and text.strip():
            key = (cat or '', text.strip(), status)
            if key in existing:
                continue
            add_todo_db(conn, text=text.strip(), status=status, category=cat)
            existing.add(key)
            inserted += 1

    return inserted
