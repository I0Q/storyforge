from __future__ import annotations

import os


def db_connect():
    import psycopg2

    dsn = os.environ.get('DATABASE_URL', '').strip()
    if not dsn:
        raise RuntimeError('DATABASE_URL not set')
    return psycopg2.connect(dsn, connect_timeout=5)


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
  created_at BIGINT NOT NULL,
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


def db_list_jobs(conn, limit: int = 60):
    cur = conn.cursor()
    try:
        cur.execute("SET statement_timeout = '5000'")
    except Exception:
        pass
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
            'state': r[4],
            'started_at': r[5],
            'finished_at': r[6],
            'total_segments': r[7],
            'segments_done': r[8],
            'mp3_url': r[9],
            'sfml_url': r[10],
            'created_at': r[11],
        }
        for r in rows
    ]
