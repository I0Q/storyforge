from __future__ import annotations

import os
import time


_DB_POOL = None
_DB_INIT_DONE = False
_DB_INIT_LOCK = None


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


def _db_init_schema(conn) -> None:
    """One-time schema bootstrap/migrations.

    This is intentionally NOT run on every request.
    """
    cur = conn.cursor()

    cur.execute('CREATE TABLE IF NOT EXISTS jobs (\n  id TEXT PRIMARY KEY,\n  title TEXT NOT NULL,\n  kind TEXT NOT NULL DEFAULT \'\',\n  meta_json TEXT NOT NULL DEFAULT \'\',\n  state TEXT,\n  started_at BIGINT DEFAULT 0,\n  finished_at BIGINT,\n  total_segments BIGINT DEFAULT 0,\n  segments_done BIGINT DEFAULT 0,\n  mp3_url TEXT,\n  sfml_url TEXT,\n  error_text TEXT NOT NULL DEFAULT \'\',\n  created_at BIGINT NOT NULL\n);')

    # Jobs indexes (helps with History/Jobs rendering and claims).
    try:
        cur.execute("CREATE INDEX IF NOT EXISTS jobs_created_at_idx ON jobs(created_at DESC)")
    except Exception:
        pass
    try:
        cur.execute("CREATE INDEX IF NOT EXISTS jobs_state_kind_created_at_idx ON jobs(state, kind, created_at)")
    except Exception:
        pass

    # Per-job event log (streamed to UI via SSE; appended by external workers).
    cur.execute(
        """
CREATE TABLE IF NOT EXISTS job_events (
  id BIGSERIAL PRIMARY KEY,
  job_id TEXT NOT NULL,
  ts BIGINT NOT NULL,
  engine TEXT NOT NULL DEFAULT '',
  line_no BIGINT NOT NULL DEFAULT 0,
  text TEXT NOT NULL DEFAULT ''
);
"""
    )
    try:
        cur.execute("CREATE INDEX IF NOT EXISTS job_events_job_id_id_idx ON job_events(job_id, id)")
    except Exception:
        pass
    # Migrations: add columns to existing jobs table
    try:
        cur.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT ''")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS meta_json TEXT NOT NULL DEFAULT ''")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS error_text TEXT NOT NULL DEFAULT ''")
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
  sfml_text TEXT NOT NULL DEFAULT '',
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

    # Migrations: add SFML storage
    try:
        cur.execute("ALTER TABLE sf_stories ADD COLUMN IF NOT EXISTS sfml_text TEXT NOT NULL DEFAULT ''")
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
  color_hex TEXT NOT NULL DEFAULT '',
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  sample_text TEXT NOT NULL DEFAULT '',
  sample_url TEXT NOT NULL DEFAULT '',
  voice_traits_json TEXT NOT NULL DEFAULT '',
  debut BOOLEAN NOT NULL DEFAULT FALSE,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL
);
"""
    )

    # Migrations: voice traits + color swatch + debut lock
    try:
        cur.execute("ALTER TABLE sf_voices ADD COLUMN IF NOT EXISTS voice_traits_json TEXT NOT NULL DEFAULT ''")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE sf_voices ADD COLUMN IF NOT EXISTS color_hex TEXT NOT NULL DEFAULT ''")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE sf_voices ADD COLUMN IF NOT EXISTS debut BOOLEAN NOT NULL DEFAULT FALSE")
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

    # Prompt iteration / learning artifacts (SFML)
    cur.execute(
        """
CREATE TABLE IF NOT EXISTS sf_prompt_versions (
  id BIGSERIAL PRIMARY KEY,
  key TEXT NOT NULL,
  version BIGINT NOT NULL,
  prompt_text TEXT NOT NULL DEFAULT '',
  meta_json TEXT NOT NULL DEFAULT '',
  created_at BIGINT NOT NULL,
  UNIQUE(key, version)
);
"""
    )

    cur.execute(
        """
CREATE TABLE IF NOT EXISTS sf_sfml_gen_runs (
  id BIGSERIAL PRIMARY KEY,
  story_id TEXT NOT NULL,
  prompt_version BIGINT NOT NULL DEFAULT 0,
  prompt_extra TEXT NOT NULL DEFAULT '',
  model TEXT NOT NULL DEFAULT '',
  duration_ms BIGINT NOT NULL DEFAULT 0,
  warnings_json TEXT NOT NULL DEFAULT '[]',
  raw_snip TEXT NOT NULL DEFAULT '',
  sfml_text TEXT NOT NULL DEFAULT '',
  created_at BIGINT NOT NULL
);
"""
    )

    # Production: per-story casting (character -> voice_id)
    cur.execute(
        """
CREATE TABLE IF NOT EXISTS sf_castings (
  story_id TEXT PRIMARY KEY,
  casting JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL
);
"""
    )

    # Production: re-runnable immutable recipe (what we send to a job)
    cur.execute(
        """
CREATE TABLE IF NOT EXISTS sf_productions (
  id TEXT PRIMARY KEY,
  story_id TEXT NOT NULL,
  label TEXT NOT NULL DEFAULT '',
  engine TEXT NOT NULL DEFAULT '',
  sfml_sha256 TEXT NOT NULL DEFAULT '',
  sfml_url TEXT NOT NULL DEFAULT '',
  sfml_bytes BIGINT NOT NULL DEFAULT 0,
  sfml_preview TEXT NOT NULL DEFAULT '',
  casting JSONB NOT NULL DEFAULT '{}'::jsonb,
  params JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL
);
"""
    )

    # Production: versioned story audio (published when user hits Save from a completed job)
    cur.execute(
        """
CREATE TABLE IF NOT EXISTS sf_story_audio (
  id BIGSERIAL PRIMARY KEY,
  story_id TEXT NOT NULL,
  job_id TEXT NOT NULL,
  production_id TEXT NOT NULL DEFAULT '',
  label TEXT NOT NULL DEFAULT '',
  mp3_url TEXT NOT NULL DEFAULT '',
  meta_json TEXT NOT NULL DEFAULT '',
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL
);
"""
    )

    # Web Push subscriptions (browser/OS notifications)
    cur.execute(
        """
CREATE TABLE IF NOT EXISTS sf_push_subscriptions (
  id BIGSERIAL PRIMARY KEY,
  device_id TEXT NOT NULL DEFAULT '',
  endpoint TEXT NOT NULL,
  p256dh TEXT NOT NULL DEFAULT '',
  auth TEXT NOT NULL DEFAULT '',
  ua TEXT NOT NULL DEFAULT '',
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  job_kinds_json TEXT NOT NULL DEFAULT '[]',
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL
);
"""
    )


def db_init(conn) -> None:
    """Prepare a connection for use.

    - Always rollback-safe + statement_timeout.
    - Runs schema bootstrap/migrations only once per process to avoid DB pool exhaustion.
    """
    global _DB_INIT_DONE, _DB_INIT_LOCK

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

    if _DB_INIT_DONE:
        return

    # Lazily init lock to avoid importing threading in cold paths unnecessarily.
    if _DB_INIT_LOCK is None:
        import threading

        _DB_INIT_LOCK = threading.Lock()

    # Only one thread does schema init.
    with _DB_INIT_LOCK:
        if _DB_INIT_DONE:
            return
        _db_init_schema(conn)
        try:
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
        _DB_INIT_DONE = True
    try:
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS sf_push_endpoint_uniq ON sf_push_subscriptions (endpoint)")
    except Exception:
        pass
    try:
        cur.execute("CREATE INDEX IF NOT EXISTS sf_push_device_id_idx ON sf_push_subscriptions (device_id)")
    except Exception:
        pass
    # Migrations: add preview column
    try:
        cur.execute("ALTER TABLE sf_productions ADD COLUMN IF NOT EXISTS sfml_preview TEXT NOT NULL DEFAULT ''")
    except Exception:
        pass

    try:
        cur.execute("CREATE INDEX IF NOT EXISTS sf_productions_story_id_idx ON sf_productions (story_id)")
    except Exception:
        pass
    try:
        cur.execute("CREATE INDEX IF NOT EXISTS sf_productions_sfml_sha_idx ON sf_productions (sfml_sha256)")
    except Exception:
        pass

    # Migrations: production_id link
    try:
        cur.execute("ALTER TABLE sf_story_audio ADD COLUMN IF NOT EXISTS production_id TEXT NOT NULL DEFAULT ''")
    except Exception:
        pass

    try:
        cur.execute("CREATE INDEX IF NOT EXISTS sf_story_audio_story_id_idx ON sf_story_audio (story_id)")
    except Exception:
        pass
    try:
        cur.execute("CREATE INDEX IF NOT EXISTS sf_story_audio_job_id_idx ON sf_story_audio (job_id)")
    except Exception:
        pass
    try:
        cur.execute("CREATE INDEX IF NOT EXISTS sf_story_audio_production_id_idx ON sf_story_audio (production_id)")
    except Exception:
        pass

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
            'SELECT id,title,kind,meta_json,state,started_at,finished_at,total_segments,segments_done,mp3_url,sfml_url,error_text,created_at '
            'FROM jobs WHERE created_at < %s ORDER BY created_at DESC LIMIT %s',
            (int(before), int(limit)),
        )
    else:
        cur.execute(
            'SELECT id,title,kind,meta_json,state,started_at,finished_at,total_segments,segments_done,mp3_url,sfml_url,error_text,created_at '
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
            'error_text': r[11] or '',
            'created_at': int(r[12] or 0),
        }
        for r in rows
    ]


def db_append_job_event(conn, job_id: str, ts: int, engine: str = '', line_no: int = 0, text: str = '') -> int:
    """Append an event to the per-job event log.

    Returns inserted event id.
    """
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO job_events (job_id, ts, engine, line_no, text) VALUES (%s,%s,%s,%s,%s) RETURNING id",
        (str(job_id or ''), int(ts or 0), str(engine or ''), int(line_no or 0), str(text or '')),
    )
    row = cur.fetchone()
    try:
        return int(row[0] or 0) if row else 0
    except Exception:
        return 0


def db_list_job_events(conn, job_id: str, after_id: int = 0, limit: int = 250):
    cur = conn.cursor()
    try:
        cur.execute("SET statement_timeout = '5000'")
    except Exception:
        pass

    lim = int(limit or 250)
    if lim < 1:
        lim = 1
    if lim > 1000:
        lim = 1000

    aid = int(after_id or 0)
    if aid < 0:
        aid = 0

    cur.execute(
        'SELECT id, job_id, ts, engine, line_no, text FROM job_events WHERE job_id=%s AND id > %s ORDER BY id ASC LIMIT %s',
        (str(job_id or ''), aid, lim),
    )
    rows = cur.fetchall() or []
    out = []
    for r in rows:
        out.append(
            {
                'id': int(r[0] or 0),
                'job_id': str(r[1] or ''),
                'ts': int(r[2] or 0),
                'engine': str(r[3] or ''),
                'line_no': int(r[4] or 0),
                'text': str(r[5] or ''),
            }
        )
    return out
