from __future__ import annotations

import os


def db_connect():
    import psycopg2

    dsn = os.environ.get('DATABASE_URL', '').strip()
    if not dsn:
        raise RuntimeError('DATABASE_URL not set')
    return psycopg2.connect(dsn, connect_timeout=5)


def db_init(conn) -> None:
    cur = conn.cursor()
    try:
        cur.execute("SET statement_timeout = '5000'")
    except Exception:
        pass
    cur.execute('CREATE TABLE IF NOT EXISTS jobs (\n  id TEXT PRIMARY KEY,\n  title TEXT NOT NULL,\n  state TEXT,\n  started_at BIGINT DEFAULT 0,\n  finished_at BIGINT,\n  total_segments BIGINT DEFAULT 0,\n  segments_done BIGINT DEFAULT 0,\n  mp3_url TEXT,\n  sfml_url TEXT,\n  created_at BIGINT NOT NULL\n);')
    cur.execute('CREATE TABLE IF NOT EXISTS voice_ratings (\n  engine TEXT NOT NULL,\n  voice_id TEXT NOT NULL,\n  rating INTEGER NOT NULL,\n  updated_at BIGINT NOT NULL,\n  PRIMARY KEY(engine, voice_id)\n);')
    cur.execute('CREATE TABLE IF NOT EXISTS metrics_samples (\n  ts BIGINT PRIMARY KEY,\n  payload_json TEXT NOT NULL\n);')

    # Story Library (text-only) stored in managed Postgres
    cur.execute("""
CREATE TABLE IF NOT EXISTS stories (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  description TEXT DEFAULT '',
  tags JSONB NOT NULL DEFAULT '[]'::jsonb,
  story_md TEXT NOT NULL DEFAULT '',
  characters JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL
);
""")

    conn.commit()


def db_list_jobs(conn, limit: int = 60):
    cur = conn.cursor()
    try:
        cur.execute("SET statement_timeout = '5000'")
    except Exception:
        pass
    cur.execute(
        'SELECT id,title,state,started_at,finished_at,total_segments,segments_done,mp3_url,sfml_url,created_at '        'FROM jobs ORDER BY created_at DESC LIMIT %s',
        (int(limit),),
    )
    rows = cur.fetchall()
    return [
        {
            'id': r[0],
            'title': r[1],
            'state': r[2],
            'started_at': r[3],
            'finished_at': r[4],
            'total_segments': r[5],
            'segments_done': r[6],
            'mp3_url': r[7],
            'sfml_url': r[8],
            'created_at': r[9],
        }
        for r in rows
    ]
