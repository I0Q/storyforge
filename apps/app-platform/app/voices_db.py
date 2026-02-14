from __future__ import annotations

import json
import re
import time
from typing import Any


def _now() -> int:
    return int(time.time())


_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def validate_voice_id(voice_id: str) -> str:
    vid = (voice_id or "").strip()
    if not _ID_RE.match(vid):
        raise ValueError(
            "Invalid id. Use 1-64 chars: lowercase letters, digits, '-' or '_' (must start with letter/digit)."
        )
    return vid


def voices_init(conn) -> None:
    cur = conn.cursor()
    try:
        cur.execute("SET statement_timeout = '5000'")
    except Exception:
        pass

    cur.execute(
        """
CREATE TABLE IF NOT EXISTS sf_voices (
  id TEXT PRIMARY KEY,
  engine TEXT NOT NULL DEFAULT '',
  voice_ref TEXT NOT NULL DEFAULT '',
  display_name TEXT NOT NULL DEFAULT '',
  color_hex TEXT NOT NULL DEFAULT '',
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  sample_text TEXT NOT NULL DEFAULT '',
  sample_url TEXT NOT NULL DEFAULT '',
  voice_traits_json TEXT NOT NULL DEFAULT '',
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL
);
"""
    )
    # Best-effort migration for older installs
    try:
        cur.execute("ALTER TABLE sf_voices ADD COLUMN IF NOT EXISTS color_hex TEXT NOT NULL DEFAULT ''")
    except Exception:
        pass
    conn.commit()


def list_voices_db(conn, limit: int = 500) -> list[dict[str, Any]]:
    cur = conn.cursor()
    try:
        cur.execute("SET statement_timeout = '5000'")
    except Exception:
        pass

    cur.execute(
        "SELECT id,engine,voice_ref,display_name,color_hex,enabled,sample_text,sample_url,voice_traits_json,updated_at "
        "FROM sf_voices ORDER BY updated_at DESC LIMIT %s",
        (int(limit),),
    )
    rows = cur.fetchall()
    out = []
    for r in rows:
        out.append(
            {
                "id": r[0],
                "engine": r[1] or "",
                "voice_ref": r[2] or "",
                "display_name": r[3] or "",
                "color_hex": r[4] or "",
                "enabled": bool(r[5]),
                "sample_text": r[6] or "",
                "sample_url": r[7] or "",
                "voice_traits_json": r[8] or "",
                "updated_at": r[9],
            }
        )
    return out


def get_voice_db(conn, voice_id: str) -> dict[str, Any]:
    cur = conn.cursor()
    try:
        cur.execute("SET statement_timeout = '5000'")
    except Exception:
        pass

    cur.execute(
        "SELECT id,engine,voice_ref,display_name,color_hex,enabled,sample_text,sample_url,voice_traits_json,created_at,updated_at "
        "FROM sf_voices WHERE id=%s",
        (voice_id,),
    )
    r = cur.fetchone()
    if not r:
        raise FileNotFoundError("not found")
    return {
        "id": r[0],
        "engine": r[1] or "",
        "voice_ref": r[2] or "",
        "display_name": r[3] or "",
        "color_hex": r[4] or "",
        "enabled": bool(r[5]),
        "sample_text": r[6] or "",
        "sample_url": r[7] or "",
        "voice_traits_json": r[8] or "",
        "created_at": r[9],
        "updated_at": r[10],
    }


def upsert_voice_db(
    conn,
    voice_id: str,
    engine: str,
    voice_ref: str,
    display_name: str,
    color_hex: str,
    enabled: bool,
    sample_text: str = "",
    sample_url: str = "",
) -> None:
    now = _now()
    cur = conn.cursor()
    try:
        cur.execute("SET statement_timeout = '5000'")
    except Exception:
        pass

    cur.execute(
        """
INSERT INTO sf_voices (id,engine,voice_ref,display_name,color_hex,enabled,sample_text,sample_url,voice_traits_json,created_at,updated_at)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
ON CONFLICT (id) DO UPDATE SET
  engine=EXCLUDED.engine,
  voice_ref=EXCLUDED.voice_ref,
  display_name=EXCLUDED.display_name,
  color_hex=EXCLUDED.color_hex,
  enabled=EXCLUDED.enabled,
  sample_text=EXCLUDED.sample_text,
  sample_url=EXCLUDED.sample_url,
  voice_traits_json=COALESCE(NULLIF(EXCLUDED.voice_traits_json,''), sf_voices.voice_traits_json),
  updated_at=EXCLUDED.updated_at;
""", 
        (
            voice_id,
            str(engine or ""),
            str(voice_ref or ""),
            str(display_name or ""),
            str(color_hex or ""),
            bool(enabled),
            str(sample_text or ""),
            str(sample_url or ""),
            "",  # voice_traits_json (preserve existing on conflict)
            now,
            now,
        ),
    )
    conn.commit()


def set_voice_enabled_db(conn, voice_id: str, enabled: bool) -> None:
    cur = conn.cursor()
    now = _now()
    try:
        cur.execute("SET statement_timeout = '5000'")
    except Exception:
        pass
    cur.execute(
        "UPDATE sf_voices SET enabled=%s, updated_at=%s WHERE id=%s",
        (bool(enabled), now, voice_id),
    )
    conn.commit()


def delete_voice_db(conn, voice_id: str) -> None:
    cur = conn.cursor()
    try:
        cur.execute("SET statement_timeout = '5000'")
    except Exception:
        pass
    cur.execute("DELETE FROM sf_voices WHERE id=%s", (voice_id,))
    conn.commit()
