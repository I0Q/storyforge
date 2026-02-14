from __future__ import annotations

import os
import time


_DB_POOL = None


class _PooledConn:
    def __init__(self, pool, conn):
        self._pool = pool
        self._conn = conn
        self._closed = False

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self):
        # Return to pool (do not close the underlying TCP connection)
        if self._closed:
            return
        self._closed = True
        try:
            self._pool.putconn(self._conn)
        except Exception:
            try:
                self._conn.close()
            except Exception:
                pass


def db_connect():
    """Get a DB connection.

    Uses a small ThreadedConnectionPool by default to avoid exhausting managed Postgres
    connection limits (StoryForge uses many short-lived connections in jobs).
    """
    import psycopg2
    from psycopg2.pool import PoolError, ThreadedConnectionPool

    global _DB_POOL

    dsn = os.environ.get('DATABASE_URL', '').strip()
    if not dsn:
        raise RuntimeError('DATABASE_URL not set')

    # Pool size is intentionally small to cap concurrent connections.
    try:
        maxconn = int(os.environ.get('SF_DB_POOL_MAX', '6') or '6')
    except Exception:
        maxconn = 6
    if maxconn < 2:
        maxconn = 2

    if _DB_POOL is None:
        _DB_POOL = ThreadedConnectionPool(1, maxconn, dsn=dsn, connect_timeout=5)

    # ThreadedConnectionPool raises PoolError immediately when exhausted.
    # For our job workers, a brief wait is safer than failing the whole job.
    last_err = None
    for i in range(30):
        try:
            conn = _DB_POOL.getconn()
            return _PooledConn(_DB_POOL, conn)
        except PoolError as e:
            last_err = e
            time.sleep(min(0.05 * (i + 1), 0.8))

    raise PoolError(f"connection pool exhausted (max={maxconn})") from last_err


def db_init(conn) -> None:
    # Be rollback-safe: a previously-failed statement can leave the transaction aborted,
    # causing subsequent commands to raise InFailedSqlTransaction.
    try:
        conn.rollback()
    except Exception:
        pass

    cur = conn.cursor()
    try:
        cur.execute("SET statement_timeout = '5000'")
    except Exception:
        pass
    cur.execute('CREATE TABLE IF NOT EXISTS jobs (\n  id TEXT PRIMARY KEY,\n  title TEXT NOT NULL,\n  kind TEXT NOT NULL DEFAULT \'\',\n  meta_json TEXT NOT NULL DEFAULT \'\',\n  state TEXT,\n  started_at BIGINT DEFAULT 0,\n  finished_at BIGINT,\n  total_segments BIGINT DEFAULT 0,\n  segments_done BIGINT DEFAULT 0,\n  mp3_url TEXT,\n  sfml_url TEXT,\n  created_at BIGINT NOT NULL\n);')
    # Migrations: add columns to existing jobs table
    try:
        cur.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT ''")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS meta_json TEXT NOT NULL DEFAULT ''")
    except Exception:
        pass

    cur.execute('CREATE TABLE IF NOT EXISTS voice_ratings (\n  engine TEXT NOT NULL,\n  voice_id TEXT NOT NULL,\n  rating INTEGER NOT NULL,\n  updated_at BIGINT NOT NULL,\n  PRIMARY KEY(engine, voice_id)\n);')
    cur.execute('CREATE TABLE IF NOT EXISTS metrics_samples (\n  ts BIGINT PRIMARY KEY,\n  payload_json TEXT NOT NULL\n);')

    # Story Library (text-only) stored in managed Postgres
    # Use a non-generic table name to avoid collisions with any existing pg_type/name.
    cur.execute("""
CREATE TABLE IF NOT EXISTS sf_stories (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  story_md TEXT NOT NULL DEFAULT '',
  characters JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL
);
""")

    # Migrations: drop deprecated columns
    try:
        cur.execute("ALTER TABLE sf_stories DROP COLUMN IF EXISTS description")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE sf_stories DROP COLUMN IF EXISTS tags")
    except Exception:
        pass

    # Voices roster (metadata; samples may be generated externally)
    cur.execute(
        """
CREATE TABLE IF NOT EXISTS sf_voices (
  id TEXT PRIMARY KEY,
  engine TEXT NOT NULL DEFAULT '',
  voice_ref TEXT NOT NULL DEFAULT '',
  display_name TEXT NOT NULL DEFAULT '',
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  sample_text TEXT NOT NULL DEFAULT '',
  sample_url TEXT NOT NULL DEFAULT '',
  voice_traits_json TEXT NOT NULL DEFAULT '',
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL
);
"""
    )

    # Migrations: voice traits
    try:
        cur.execute("ALTER TABLE sf_voices ADD COLUMN IF NOT EXISTS voice_traits_json TEXT NOT NULL DEFAULT ''")
    except Exception:
        pass

    # Settings (small JSON blobs)
    cur.execute(
        """
CREATE TABLE IF NOT EXISTS sf_settings (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL DEFAULT '',
  updated_at BIGINT NOT NULL
);
"""
    )


    # Internal TODO tracker (DB-backed, read-only UI)
    cur.execute(
        """
CREATE TABLE IF NOT EXISTS sf_todos (
  id BIGSERIAL PRIMARY KEY,
  text TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',
  archived BOOLEAN NOT NULL DEFAULT FALSE,
  category TEXT NOT NULL DEFAULT '',
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL
);
"""
    )

    # Ensure schema has category (free-text) + archived
    try:
        cur.execute("ALTER TABLE sf_todos ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT ''")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE sf_todos ADD COLUMN IF NOT EXISTS archived BOOLEAN NOT NULL DEFAULT FALSE")
        cur.execute("ALTER TABLE sf_todos ADD COLUMN IF NOT EXISTS highlighted BOOLEAN NOT NULL DEFAULT FALSE")
    except Exception:
        pass

    conn.commit()


def db_list_jobs(conn, limit: int = 60, before: int | None = None):
    """List jobs ordered by created_at desc.

    If before is provided, returns jobs with created_at < before.
    """
    cur = conn.cursor()
    try:
        cur.execute("SET statement_timeout = '5000'")
    except Exception:
        pass

    if before is not None:
        cur.execute(
            'SELECT id,title,kind,meta_json,state,started_at,finished_at,total_segments,segments_done,mp3_url,sfml_url,created_at '
            'FROM jobs WHERE created_at < %s ORDER BY created_at DESC LIMIT %s',
            (int(before), int(limit)),
        )
    else:
        cur.execute(
            'SELECT id,title,kind,meta_json,state,started_at,finished_at,total_segments,segments_done,mp3_url,sfml_url,created_at '
            'FROM jobs ORDER BY created_at DESC LIMIT %s',
            (int(limit),),
        )

    rows = cur.fetchall()
    return [
        {
            'id': r[0],
            'title': r[1],
            'kind': r[2] or '',
            'meta_json': r[3] or '',
            'state': r[4] or '',
            'started_at': int(r[5] or 0),
            'finished_at': int(r[6] or 0),
            'total_segments': int(r[7] or 0),
            'segments_done': int(r[8] or 0),
            'mp3_url': r[9] or '',
            'sfml_url': r[10] or '',
            'created_at': int(r[11] or 0),
        }
        for r in rows
    ]
