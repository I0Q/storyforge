#!/usr/bin/env bash
set -euo pipefail

cd /raid/storyforge_test

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <sfml_path> [storyforge render args...]" >&2
  exit 2
fi

SFML=$1
shift || true

JOB_ID=$(python3 - <<'PYIN'
import secrets
print(secrets.token_urlsafe(8).replace("-", "_"))
PYIN
)

ROOT=/raid/storyforge_test/monitor
JOBS=$ROOT/jobs
TMPBASE=$ROOT/tmp/$JOB_ID
mkdir -p "$JOBS" "$TMPBASE"

TITLE=$(python3 - <<PYIN
from pathlib import Path
p=Path("$SFML")
for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
    if ln.startswith("@title:"):
        print(ln.split(":",1)[1].strip())
        break
else:
    print(p.stem)
PYIN
)

TOTAL=$(python3 - <<PYIN
from pathlib import Path
p=Path("$SFML")
count=0
for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
    s=ln.strip()
    if not s or s.startswith("@"): 
        continue
    if ":" in s:
        count += 1
print(count)
PYIN
)

STARTED=$(date +%s)
python3 - <<PYIN
import json
from pathlib import Path
job={
  "id": "$JOB_ID",
  "title": "$TITLE",
  "sfml": "$SFML",
  "started_at": int("$STARTED"),
  "total_segments": int("$TOTAL"),
}
Path("$JOBS/$JOB_ID.json").write_text(json.dumps(job, ensure_ascii=False, indent=2)+"\n")
PYIN

# Upsert into sqlite job DB (preferred job store)
DB=${MONITOR_DB:-$ROOT/monitor.db}
python3 - <<PYIN
import sqlite3
conn=sqlite3.connect("$DB")
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("""
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  sfml TEXT NOT NULL DEFAULT '',
  started_at INTEGER NOT NULL DEFAULT 0,
  total_segments INTEGER NOT NULL DEFAULT 0,
  mp3 TEXT
);
""")
conn.execute(
  """INSERT INTO jobs (id,title,sfml,started_at,total_segments,mp3)
     VALUES (?,?,?,?,?,NULL)
     ON CONFLICT(id) DO UPDATE SET
       title=excluded.title,
       sfml=excluded.sfml,
       started_at=excluded.started_at,
       total_segments=excluded.total_segments
  """,
  ("$JOB_ID","$TITLE","$SFML",int("$STARTED"),int("$TOTAL"))
)
conn.commit(); conn.close()
PYIN


TOKEN=$(cat $ROOT/token.txt)
HOST=$(hostname -I | awk '{print $1}')
URL="http://$HOST:8787/job/$JOB_ID?t=$TOKEN"
echo "MONITOR_URL=$URL"

export TMPDIR="$TMPBASE"

# cap CPU threads (keeps jobs=4 from stampeding)
export OMP_NUM_THREADS=16
export MKL_NUM_THREADS=16
export OPENBLAS_NUM_THREADS=16
export NUMEXPR_NUM_THREADS=16
export TOKENIZERS_PARALLELISM=false

LOG="$TMPDIR/storyforge-$(date +%s).log"
exec bash -lc "env PYTHONPATH=src python3 -m storyforge.cli render --story '$SFML' --assets-dir assets --out-dir out $*" 2>&1 | tee -a "$LOG"
