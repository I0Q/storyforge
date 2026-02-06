#!/usr/bin/env python3
import argparse
import ipaddress
import json
import sqlite3
import re
import time
from http import HTTPStatus
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote


def slugify_title(t: str) -> str:
    # match Storyforge output naming: non-alnum -> underscore
    return re.sub(r"[^A-Za-z0-9]", "_", (t or "").strip())


def now_ts():
    return int(time.time())


def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


# --- SQLite job store ---

def db_default_path(root: Path) -> Path:
    return root / "monitor.db"


def db_connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    # Better concurrency for threaded server
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def db_init(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
          id TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          sfml TEXT NOT NULL DEFAULT '',
          started_at INTEGER NOT NULL DEFAULT 0,
          total_segments INTEGER NOT NULL DEFAULT 0,
          mp3 TEXT
        );
        """
    )
    # schema migrations
    cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    if "state" not in cols: conn.execute("ALTER TABLE jobs ADD COLUMN state TEXT")
    if "finished_at" not in cols: conn.execute("ALTER TABLE jobs ADD COLUMN finished_at INTEGER")
    if "aborted_at" not in cols: conn.execute("ALTER TABLE jobs ADD COLUMN aborted_at INTEGER")
    if "segments_done" not in cols: conn.execute("ALTER TABLE jobs ADD COLUMN segments_done INTEGER")
    conn.execute("CREATE TABLE IF NOT EXISTS voice_ratings (engine TEXT NOT NULL, voice_id TEXT NOT NULL, rating INTEGER NOT NULL, updated_at INTEGER NOT NULL, PRIMARY KEY(engine, voice_id))")
    conn.commit()


def db_upsert_job(conn: sqlite3.Connection, meta: dict) -> None:
    conn.execute(
        """
        INSERT INTO jobs (id, title, sfml, started_at, total_segments, mp3)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          title=excluded.title,
          sfml=excluded.sfml,
          started_at=excluded.started_at,
          total_segments=excluded.total_segments,
          mp3=excluded.mp3
        """,
        (
            meta.get("id"),
            meta.get("title") or meta.get("id") or "",
            meta.get("sfml") or "",
            int(meta.get("started_at", 0) or 0),
            int(meta.get("total_segments", 0) or 0),
            meta.get("mp3"),
        ),
    )
    # schema migrations
    cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    if "state" not in cols: conn.execute("ALTER TABLE jobs ADD COLUMN state TEXT")
    if "finished_at" not in cols: conn.execute("ALTER TABLE jobs ADD COLUMN finished_at INTEGER")
    if "aborted_at" not in cols: conn.execute("ALTER TABLE jobs ADD COLUMN aborted_at INTEGER")
    if "segments_done" not in cols: conn.execute("ALTER TABLE jobs ADD COLUMN segments_done INTEGER")
    conn.commit()


def db_get_job(conn: sqlite3.Connection, job_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return dict(row) if row else None


def db_list_jobs(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM jobs ORDER BY started_at DESC").fetchall()
    return [dict(r) for r in rows]


def migrate_jobs_json_to_db(root: Path, db_path: Path) -> int:
    """One-time migration: if DB is empty, import monitor/jobs/*.json."""
    jobs_dir = root / "jobs"
    if not jobs_dir.exists():
        return 0

    conn = db_connect(db_path)
    db_init(conn)
    n = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    if n:
        conn.close()
        return 0

    imported = 0
    for p in sorted(jobs_dir.glob("*.json")):
        try:
            meta = json.loads(read_text(p))
            if not meta.get("id"):
                meta["id"] = p.stem
            db_upsert_job(conn, meta)
            imported += 1
        except Exception:
            pass
    conn.close()
    return imported


def job_status_light(root: Path, job_id: str) -> dict:
    """Lightweight status for list view (no cpu/gpu/log tail)."""
    tmp_root = root / "tmp"

    conn = db_connect(db_default_path(root))
    db_init(conn)
    meta = db_get_job(conn, job_id)
    conn.close()
    if not meta:
        return {"ok": False, "error": "job_not_found"}

    started_at = int(meta.get("started_at", 0) or 0)
    total = int(meta.get("total_segments", 0) or 0)

    job_base = tmp_root / job_id
    tmp_job = find_tmp_job_dir(tmp_root, job_id)
    done = 0
    if tmp_job:
        narr = tmp_job / "narr"
        if narr.exists():
            done = len(list(narr.glob("seg_*.wav")))

    mp3_path = None
    mp3 = meta.get("mp3")
    if mp3:
        cand = Path(mp3)
        if cand.exists():
            mp3_path = cand

    if mp3_path and mp3_path.exists() and total and done == 0:
        done = total

    st = (meta.get("state") or "pending").lower()
    status = {
        'state': st,
        'finished_at': meta.get('finished_at'),
        'aborted_at': meta.get('aborted_at'),
        'last_activity_at': meta.get('finished_at') or meta.get('aborted_at') or None,
    }


    return {
        "ok": True,
        "progress": {"done": done, "total": total, "pct": (done/total*100.0) if total else None},
        "mp3": str(mp3_path) if mp3_path and mp3_path.exists() else None,
        "status": status,
    }




def load_tortoise_roster(repo_root: Path) -> list[dict]:
    """Parse manifests/tortoise_voice_roster.yaml without external deps."""
    path = repo_root / "manifests" / "tortoise_voice_roster.yaml"
    if not path.exists():
        return []
    items = []
    cur = None
    for raw in read_text(path).splitlines():
        ln = raw.rstrip()
        if not ln.strip() or ln.lstrip().startswith('#'):
            continue
        s = ln.lstrip()
        if s.startswith('- '):
            if cur:
                items.append(cur)
            cur = {}
            s = s[2:].strip()
            if s and ':' in s:
                k,v = s.split(':',1)
                cur[k.strip()] = v.strip().strip('"')
            continue
        if cur is None:
            continue
        if ':' in s:
            k,v = s.split(':',1)
            cur[k.strip()] = v.strip().strip('"')
    if cur:
        items.append(cur)
    # normalize
    out=[]
    for it in items:
        out.append({
            'id': it.get('id') or '',
            'color': it.get('color') or it.get('id') or '',
            'role': it.get('role') or '',
            'engine': it.get('engine') or 'tortoise',
            'voice_name': it.get('voice_name') or '',
            'notes': it.get('notes') or '',
        })
    return [x for x in out if x['id']]


def voice_demo_text(voice_id: str, color: str) -> str:
    # unique-ish per voice; keep it short for fast generation
    base = [
        f"Hello. I'm {color}. I keep stories calm and clear.",
        f"Hi. {color} here. Soft voice, steady pace.",
        f"I'm {color}. I'll guide you gently into the story.",
        f"{color} speaking. Warm, quiet, and bedtime-friendly.",
        f"This is {color}. Let's make the night feel safe.",
    ]
    idx = (sum(ord(c) for c in voice_id) % len(base))
    return base[idx]


def filter_log_tail(raw: str, max_lines: int = 60) -> str:
    """Filter noisy logs down to meaningful events.

    Keeps: wrote segs, QC/retry, obvious errors.
    Drops: HF/model warnings and tqdm progress spam.
    """
    keep = []
    for ln in raw.splitlines():
        s = ln.strip()
        if not s:
            continue
        if s.startswith('Some weights of') or 'resume_download' in s or 'weight_norm' in s:
            continue
        if 'You should probably TRAIN this model' in s:
            continue
        if re.search(r"\d+%\|", s):
            continue
        if s.startswith('Generating autoregressive samples') or s.startswith('Computing best candidates') or s.startswith('Transforming autoregressive outputs'):
            keep.append(s)
            continue
        if s.startswith('wrote ') or 'QC' in s or 'retry' in s or 'RuntimeError' in s or 'Traceback' in s or 'Error' in s or 'SIGKILL' in s:
            keep.append(s)
            continue
    return "\n".join(keep[-max_lines:])


def gpu_stats():
    """Best-effort GPU stats (NVIDIA). Returns list[dict] or None."""
    try:
        import subprocess

        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=index,utilization.gpu,memory.used,memory.total,power.draw,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            text=True,
        )
        g = []
        for line in out.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 6:
                g.append(
                    {
                        "index": int(parts[0]),
                        "util": float(parts[1]),
                        "mem_used": float(parts[2]),
                        "mem_total": float(parts[3]),
                        "power": float(parts[4]),
                        "temp": float(parts[5]),
                    }
                )
        return g
    except Exception:
        return None


def cpu_overall_pct() -> float | None:
    """One-shot overall CPU utilization percent (best-effort)"""
    try:
        import subprocess

        out = subprocess.check_output(["bash", "-lc", "LC_ALL=C top -b -n1 | head -n 5"], text=True)
        # Examples:
        # %Cpu(s):  3.0 us,  1.0 sy,  0.0 ni, 95.7 id,  0.1 wa,  0.0 hi,  0.1 si,  0.0 st
        m = re.search(r"\b([0-9.]+)\s*id\b", out)
        if not m:
            return None
        idle = float(m.group(1))
        return max(0.0, min(100.0, 100.0 - idle))
    except Exception:
        return None


def cpu_stats():
    """Best-effort CPU/RAM stats (Linux)."""
    try:
        # meminfo (kB)
        mem = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            if ":" not in line:
                continue
            k, rest = line.split(":", 1)
            v = rest.strip().split()[0]
            if v.isdigit():
                mem[k] = int(v)
        mem_total = mem.get("MemTotal", 0) / 1024 / 1024
        mem_avail = mem.get("MemAvailable", 0) / 1024 / 1024
        mem_used = max(0.0, mem_total - mem_avail)
        mem_pct = (mem_used / mem_total * 100.0) if mem_total else None

        import subprocess

        ps = subprocess.check_output(
            [
                "bash",
                "-lc",
                "ps -eo pid,pcpu,pmem,etime,comm,args --sort=-pcpu | head -n 12",
            ],
            text=True,
        ).strip().splitlines()

        return {
            "cpu_pct": round(cpu_overall_pct(), 1) if cpu_overall_pct() is not None else None,
            "mem_gb": {
                "total": round(mem_total, 2),
                "used": round(mem_used, 2),
                "avail": round(mem_avail, 2),
                "pct": round(mem_pct, 1) if mem_pct is not None else None,
            },
            "ps": ps,
        }
    except Exception:
        return None


def detect_allow_cidrs(root: Path):
    cfg = root / "allow_cidrs.json"
    if cfg.exists():
        nets = [ipaddress.ip_network(x) for x in json.loads(read_text(cfg))]
        nets.append(ipaddress.ip_network("127.0.0.1/32"))
        return nets

    allow = []
    try:
        import subprocess

        out = subprocess.check_output(["ip", "-o", "-f", "inet", "addr", "show"], text=True)
        for line in out.splitlines():
            m = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)/(\d+)", line)
            if not m:
                continue
            ip = m.group(1)
            if ip.startswith("127."):
                continue
            allow.append(str(ipaddress.ip_network(f"{ip}/{m.group(2)}", strict=False)))
    except Exception:
        allow = ["0.0.0.0/0"]

    cfg.write_text(json.dumps(sorted(set(allow)), indent=2) + "\n")
    nets = [ipaddress.ip_network(x) for x in allow]
    nets.append(ipaddress.ip_network("127.0.0.1/32"))
    return nets


def count_spoken_segments(sfml_path: Path) -> int:
    try:
        n = 0
        for ln in read_text(sfml_path).splitlines():
            s = ln.strip()
            if not s or s.startswith("@"):  # directives
                continue
            if ":" in s:
                n += 1
        return n
    except Exception:
        return 0


def find_tmp_job_dir(tmp_root: Path, job_id: str):
    base = tmp_root / job_id
    if not base.exists():
        return None
    cands = [p for p in base.glob("storyforge-*") if p.is_dir()]
    cands = sorted(cands, key=lambda p: p.stat().st_mtime, reverse=True)
    return cands[0] if cands else None


def find_latest_mp3(out_dir: Path, started_at: int):
    cands = [p for p in out_dir.glob("*.mp3") if int(p.stat().st_mtime) >= started_at - 5]
    cands.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return cands[0] if cands else None


def read_log_tail(tmp_job: Path, job_base: Path) -> str:
    logp = tmp_job / "render.log"
    if logp.exists():
        return "\n".join(read_text(logp).splitlines()[-120:])
    logs = sorted(tmp_job.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if logs:
        return "\n".join(read_text(logs[0]).splitlines()[-120:])
    # also consider logs written to the per-job base (older runner versions)
    logs2 = sorted(job_base.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if logs2:
        return "\n".join(read_text(logs2[0]).splitlines()[-120:])

    return ""


def job_runtime_status(job_base: Path, tmp_job: Path | None, mp3_path: Path | None, done: int, total: int) -> dict:
    now = now_ts()

    # last activity: newest seg wav or newest log in tmp_job/job_base
    last = None
    cands = []
    if tmp_job and tmp_job.exists():
        narr = tmp_job / 'narr'
        if narr.exists():
            cands += list(narr.glob('seg_*.wav'))
        cands += list(tmp_job.glob('*.log'))
    cands += list(job_base.glob('*.log'))
    for pp in cands:
        try:
            ts = int(pp.stat().st_mtime)
            if last is None or ts > last:
                last = ts
        except Exception:
            pass

    # running? if any process references this job tmp path (voicegen writes full tmp paths)
    running = False
    try:
        import subprocess
        probe = job_base.as_posix().rstrip('/') + '/'
        cmd = f"ps -eo args | grep -F {probe!r} | grep -v grep | wc -l"
        out = subprocess.check_output(['bash','-lc', cmd], text=True).strip()
        running = int(out) > 0
    except Exception:
        running = False

    if running:
        return {
            'state': 'running',
            'finished_at': None,
            'aborted_at': None,
            'last_activity_at': last,
        }

    # completed only if mp3 exists AND we generated all segments
    if mp3_path and mp3_path.exists() and total and done >= total:
        finished_at = int(mp3_path.stat().st_mtime)
        return {
            'state': 'completed',
            'finished_at': finished_at,
            'aborted_at': None,
            'last_activity_at': finished_at,
        }

    if last is not None and now - last > 600:
        return {
            'state': 'aborted',
            'finished_at': None,
            'aborted_at': now,
            'last_activity_at': last,
        }

    return {
        'state': 'pending',
        'finished_at': None,
        'aborted_at': None,
        'last_activity_at': last,
    }


def job_status(root: Path, job_id: str) -> dict:
    tmp_root = root / "tmp"

    conn = db_connect(db_default_path(root))
    db_init(conn)
    meta = db_get_job(conn, job_id)
    conn.close()
    if not meta:
        return {"ok": False, "error": "job_not_found"}

    sfml_rel = meta.get("sfml") or ""
    sfml_path = Path(sfml_rel)
    if sfml_rel and not sfml_path.is_absolute():
        sfml_path = Path("/raid/storyforge_test") / sfml_path

    started_at = int(meta.get("started_at", 0) or 0)

    total = int(meta.get("total_segments", 0) or 0)
    if total == 0 and sfml_rel and sfml_path.exists():
        total = count_spoken_segments(sfml_path)

    job_base = tmp_root / job_id
    tmp_job = find_tmp_job_dir(tmp_root, job_id)
    done = 0
    tail = ""
    if tmp_job:
        narr = tmp_job / "narr"
        segs = sorted(narr.glob("seg_*.wav")) if narr.exists() else []
        done = len(segs)
        tail = read_log_tail(tmp_job, tmp_root / job_id)

    mp3 = meta.get("mp3")
    mp3_path = Path(mp3) if mp3 else None
    if mp3_path and not mp3_path.exists():
        mp3_path = None

    # If an MP3 exists but the temp folder is gone (cleanup) we still consider all segments done.
    if mp3_path and total and done == 0:
        done = total

    st = (meta.get("state") or "pending").lower()
    status = {
        'state': st,
        'finished_at': meta.get('finished_at'),
        'aborted_at': meta.get('aborted_at'),
        'last_activity_at': meta.get('finished_at') or meta.get('aborted_at') or None,
    }

    return {
        "ok": True,
        "job": meta,
        "status": status,
        "progress": {"done": done, "total": total, "pct": (done / total * 100.0) if total else None},
        "tmp_dir": str(tmp_job) if tmp_job else None,
        "mp3": str(mp3_path) if mp3_path else None,
        "log_tail": filter_log_tail(tail),
        "gpu": gpu_stats(),
        "cpu": cpu_stats(),
        "now": now_ts(),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "StoryforgeMonitor/0.4"

    def _send(self, code: int, body: bytes, content_type: str = "text/plain; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _client_allowed(self) -> bool:
        ip = self.client_address[0]
        try:
            addr = ipaddress.ip_address(ip)
            return any(addr in net for net in self.server.allow_nets)
        except Exception:
            return False

    def _token_ok(self) -> bool:
        qs = parse_qs(urlparse(self.path).query)
        t = (qs.get("t") or [""])[0]
        return t and t == self.server.token

    def _guard(self) -> bool:
        if not self._client_allowed():
            self._send(HTTPStatus.FORBIDDEN, b"forbidden\n")
            return False
        if not self._token_ok():
            self._send(HTTPStatus.UNAUTHORIZED, b"unauthorized\n")
            return False
        return True

    def do_GET(self):
        if not self._guard():
            return

        u = urlparse(self.path)
        path = unquote(u.path)
        root: Path = self.server.root


        if path == "/" or path == "":
            # dynamic index page (server-rendered to avoid mobile browser JS quirks)
            qs = parse_qs(urlparse(self.path).query)
            token = (qs.get("t") or [""])[0]
            conn = db_connect(self.server.db_path)
            db_init(conn)
            metas = db_list_jobs(conn)
            conn.close()

            def h(s: str) -> str:
                return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;")

            def fmt_ts(ts):
                if not ts:
                    return "-"
                try:
                    import datetime
                    return datetime.datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    return str(ts)

            def fmt_elapsed(sec):
                if sec is None:
                    return "-"
                try:
                    sec = int(sec)
                except Exception:
                    return "-"
                if sec < 0:
                    sec = 0
                hh = sec // 3600
                mm = (sec % 3600) // 60
                ss = sec % 60
                if hh > 0:
                    return "%d:%02d:%02d" % (hh, mm, ss)
                return "%d:%02d" % (mm, ss)

            def badge(state):
                st = state or "unknown"
                return '<span class="badge %s">%s</span>' % (st, st)

            running = None
            for meta in metas:
                st = (meta.get("status") or {}).get("state") or meta.get("state")
                if st == "running":
                    running = meta
                    break

            style = """
            <style>
              body{font-family:system-ui, -apple-system, Segoe UI, Roboto, sans-serif; padding:16px;}
              a{color:#0b63ce;}
              h1{margin:0 0 6px;}
              h2{margin:0 0 10px;}
              pre{white-space:pre-wrap; background:#111; color:#ddd; padding:12px; border-radius:10px;}
              .muted{color:#6b7280; font-size:12px;}
              .badge{font-size:10px; font-weight:900; padding:3px 8px; border-radius:999px; border:1px solid transparent; text-transform:uppercase; letter-spacing:0.02em; align-self:flex-start;}

              .badge.running{background:#e0f2fe; border-color:#38bdf8; color:#075985;}
              .badge.completed{background:#dcfce7; border-color:#22c55e; color:#14532d;}
              .badge.aborted{background:#fee2e2; border-color:#ef4444; color:#7f1d1d;}
              .badge.pending{background:#f3f4f6; border-color:#d1d5db; color:#374151;}
              .badge.unknown{background:#f3f4f6; border-color:#d1d5db; color:#374151;}
              .btn{display:inline-block; padding:10px 12px; border-radius:10px; border:1px solid #d1d5db; text-decoration:none; font-weight:800; font-size:14px; background:#fff;}
              .btn.tiny{padding:6px 10px; font-size:12px; border-radius:999px;}
              .btnrow{display:flex; gap:8px; align-items:center; justify-content:flex-end; flex-wrap:wrap;}
              .card{border:1px solid #e5e7eb; border-radius:14px; padding:12px; background:#fff;}
              .cardTop{display:flex; justify-content:space-between; gap:12px; align-items:flex-start;}
              .title{font-weight:950; font-size:16px;}
              .prog{display:flex; align-items:center; gap:12px; margin:10px 0 6px;}
              .pbar{flex:1; height:16px; background:#eee; border-radius:999px; overflow:hidden; position:relative;}
              .pfill{height:16px; background:#0b63ce; width:0%;}
              .ptext{position:absolute; inset:0; display:flex; align-items:center; justify-content:center; font-size:12px; font-weight:900; color:#111;}
              .logbox{max-height:160px; overflow:auto; white-space:pre-wrap; word-break:break-word;}
              .pillrow{display:flex; gap:12px; flex-wrap:wrap; margin:6px 0 0;}
              .pill{font-size:12px; background:#f3f4f6; border-radius:999px; padding:4px 8px; font-weight:700;}
              .row{border:1px solid #e5e7eb; border-radius:14px; padding:10px 12px; margin:10px 0; display:flex; justify-content:space-between; gap:12px; align-items:flex-start; background:#fff;}
.rowTop{display:flex; gap:12px; align-items:flex-start; margin-bottom:6px;}

              .rowBadge{min-width:72px; display:flex; align-items:flex-start; padding-top:2px;}
.rowMain{flex:1; min-width:0;}

              .rowTitle{font-weight:950; overflow:hidden; text-overflow:ellipsis; white-space:normal; line-height:1.25; flex:1; font-size:16px; margin-top:8px; margin-bottom:8px;}

.rowBtns{display:flex; gap:12px; align-items:flex-end; justify-content:flex-end; flex-wrap:wrap;}

              details{border:1px solid #e5e7eb; border-radius:14px; padding:10px 12px; margin:10px 0 0;}
              summary{cursor:pointer; font-weight:800;}
            </style>
            """

            parts = []
            parts.append('<!doctype html><html><head><meta charset="utf-8" />')
            parts.append('<meta name="viewport" content="width=device-width, initial-scale=1" />')
            parts.append('<title>Storyforge Monitor</title>')
            parts.append(style)
            parts.append('</head><body>')
            parts.append('<div style="display:flex; justify-content:space-between; align-items:center; gap:12px;">')
            parts.append('<h1>Storyforge Monitor</h1>')
            parts.append('<div class="btnrow"><a class="btn tiny" href="/voices?t=' + h(token) + '">Voices</a></div>')
            parts.append('</div>')

            parts.append('<h2 style="margin-top:18px;">Running</h2>')
            if running is None:
                parts.append('<div class="card"><div class="title">No job running</div><div class="muted">When you start a render, it will appear here with progress + log tail.</div></div>')
            else:
                jid = running.get('id')
                st = (running.get('status') or {}).get('state') or running.get('state') or 'running'
                st_full = job_status_light(root, jid)
                prog = st_full.get('progress') or {}
                done = prog.get('done')
                total = prog.get('total')
                # fallback to persisted total_segments; for completed assume done=total
                total = meta.get('total_segments') or total
                if st == 'completed' and total:
                    done = total
                elif meta.get('segments_done') is not None:
                    done = meta.get('segments_done')
                    # if we know total but segments_done wasn't recorded, show 0/total
                    if done is None and total:
                        done = 0
                pct = prog.get('pct') or 0
                tmp_root = root / 'tmp'
                job_base = tmp_root / jid
                tmp_job = find_tmp_job_dir(tmp_root, jid) or job_base
                tmp_root = root / 'tmp'
                job_base = tmp_root / jid
                tmp_job = find_tmp_job_dir(tmp_root, jid) or job_base
                log_tail = read_log_tail(tmp_job, job_base)
                log_text = log_tail if log_tail else '(no log yet)'
                started_at = running.get('started_at')
                now = now_ts()
                elapsed = (now - started_at) if (started_at and now) else None
                parts.append('<div class="card">')
                parts.append('<div class="cardTop">')
                parts.append('<div><div class="title"><a href="/view/' + jid + '?t=' + h(token) + '" target="_blank" rel="noopener">' + h(running.get('title') or jid) + '</a></div>')
                parts.append('<div class="muted">' + h(fmt_ts(started_at)) + ' - ' + h(running.get('sfml') or '') + '</div></div>')
                btns = []
                btns.append('<a class="btn tiny" href="/job/' + jid + '?t=' + h(token) + '">OPEN</a>')
                if running.get('mp3') and st == 'completed':
                    btns.append('<a class="btn tiny" href="/dl/' + jid + '?t=' + h(token) + '">AUDIO</a>')
                parts.append('<div class="btnrow">' + ''.join(btns) + '</div>')
                parts.append('</div>')
                parts.append('<div class="prog"><div class="pbar"><div id="run_pfill" class="pfill" style="width:' + str(pct) + '%"></div><div id="run_ptext" class="ptext">' + str(done) + '/' + str(total) + ' segments</div></div></div>')
                parts.append('<div class="pillrow"><div id="run_time" class="pill">Time: ' + fmt_elapsed(elapsed) + '</div><div id="run_state" class="pill">Status: ' + h(st) + '</div></div>')
                parts.append('<details open><summary>Log tail</summary><pre id="run_log" class="logbox">' + h(log_text) + '</pre></details>')
                parts.append('</div>')

                parts.append('<script>(function(){const jid=' + json.dumps(jid) + ';const t=new URLSearchParams(location.search).get(\'t\')||\'\';const logEl=document.getElementById(\'run_log\');const pfill=document.getElementById(\'run_pfill\');const ptext=document.getElementById(\'run_ptext\');const stateEl=document.getElementById(\'run_state\');function lastLines(s,n){if(!s)return\'\';const lines=String(s).split(/\\r?\\n/);return lines.slice(Math.max(0,lines.length-n)).join("\\n");}async function tick(){try{const r=await fetch(\'/api/job/\'+encodeURIComponent(jid)+\'?t=\'+encodeURIComponent(t),{cache:\'no-store\'});if(!r.ok)return;const j=await r.json();if(!j||!j.ok)return;const prog=j.progress||{};const done=(prog.done??0);const total=(prog.total??0);const pct=(prog.pct??0);if(pfill)pfill.style.width=((pct?pct.toFixed(1):0)+\'%\');if(ptext)ptext.textContent=(total?(done+\'/\'+total+\' segments\'):(done+\' segments\'));const st=(j.status&&j.status.state)?j.status.state:\'running\';if(stateEl)stateEl.textContent=\'Status: \'+st;if(logEl){logEl.textContent=lastLines(j.log_tail||\'\',12);}if(st===\'completed\'||st===\'aborted\'){clearInterval(timer);setTimeout(function(){try{location.reload();}catch(e){}},900);}}catch(e){}}tick();const timer=setInterval(tick,2500);})();</script>')


            parts.append('<h2 style="margin-top:18px;">History</h2>')
            parts.append('<div class="muted" style="margin-bottom:8px;">Most recent first.</div>')

            rows = []
            for meta in metas:
                if running is not None and meta.get('id') == running.get('id'):
                    continue
                jid = meta.get('id')
                st = (meta.get('status') or {}).get('state') or meta.get('state') or 'unknown'
                started_at = meta.get('started_at')
                finished_at = meta.get('finished_at') or (meta.get('status') or {}).get('finished_at')
                aborted_at = meta.get('aborted_at') or (meta.get('status') or {}).get('aborted_at')
                end_at = finished_at or aborted_at
                elapsed = (end_at - started_at) if (end_at and started_at) else None
                prog = meta.get('progress') or {}
                done = prog.get('done')
                total = prog.get('total')
                # fallback to persisted total_segments; for completed assume done=total
                total = meta.get('total_segments') or total
                if st == 'completed' and total:
                    done = total
                elif meta.get('segments_done') is not None:
                    done = meta.get('segments_done')
                    # if we know total but segments_done wasn't recorded, show 0/total
                    if done is None and total:
                        done = 0
                if done is None and total:
                    done = 0
                segtxt = (str(done) + '/' + str(total)) if (done is not None and total is not None and total) else ('audio' if (st=='completed' and meta.get('mp3')) else '-')
                btns = []
                # MARKUP (SFML viewer)
                btns.append('<a class=\"btn tiny\" href=\"/view/' + jid + '?t=' + h(token) + '\" target=\"_blank\" rel=\"noopener\">SFML</a>')
                if meta.get('mp3') and st == 'completed':
                    btns.append('<a class=\"btn tiny\" href=\"#\" data-play=\"' + jid + '\">PLAY</a>')
                    btns.append('<a class=\"btn tiny\" href=\"/dl/' + jid + '?t=' + h(token) + '\" target=\"_blank\" rel=\"noopener\">DL</a>')

                row = ''
                row += '<div class=\"row ' + h(st) + '\">'
                row +=   '<div class=\"rowMain\">'
                row +=     '<div class=\"rowTop\">'
                row +=       '<div>' + badge(st) + '</div>'
                row +=     '</div>'
                row +=     '<div class=\"rowTitle\">' + h(meta.get('title') or jid) + '</div>'
                row +=     '<div class=\"metaRow\">'
                row +=       '<div class=\"muted\">' + h(fmt_ts(started_at)) + ' • ' + fmt_elapsed(elapsed) + ' • ' + segtxt + '</div>'
                row +=       '<div class=\"rowBtns\">' + ''.join(btns) + '</div>'
                row +=     '</div>'
                if meta.get('mp3') and st == 'completed':
                    row +=     '<div class=\"rowAudio\" id=\"aud_' + jid + '\" style=\"display:none;\">'
                    row +=       '<audio controls preload=\"none\" src=\"/audio/' + jid + '?t=' + h(token) + '\"></audio>'
                    row +=     '</div>'
                row +=   '</div>'
                row += '</div>'
                rows.append(row)

            if rows:
                parts.append("\n".join(rows))
            else:
                parts.append('<div class="muted">No jobs yet.</div>')

            parts.append("""
<script>
(function(){
  function stopAll(exceptId){
    document.querySelectorAll('.rowAudio').forEach(function(el){
      if(exceptId && el.id === exceptId) return;
      try{ el.style.display='none'; }catch(e){}
      try{ var a=el.querySelector('audio'); if(a) a.pause(); }catch(e){}
    });
    document.querySelectorAll('[data-play]').forEach(function(b){ b.textContent='PLAY'; });
  }

  document.addEventListener('click', function(ev){
    var t = ev.target;
    if(!t) return;
    var jid = t.getAttribute('data-play');
    if(!jid) return;
    ev.preventDefault();
    var box = document.getElementById('aud_'+jid);
    if(!box) return;
    var open = box.style.display !== 'none';
    if(open){
      stopAll(null);
      return;
    }
    stopAll('aud_'+jid);
    box.style.display='block';
    t.textContent='HIDE';
    var a = box.querySelector('audio');
    if(a){ try{ a.play(); }catch(e){} }
  }, {passive:false});
})();
</script>
""")

            parts.append('<!-- Bottom sheet: system monitor -->\n<style>\n  .bs{position:fixed; left:0; right:0; bottom:0; z-index:9999; pointer-events:auto; font-family:system-ui, -apple-system, Segoe UI, Roboto, sans-serif; will-change:transform;}\n  .bs .handle{margin:0 auto; width:46px; height:5px; background:#d1d5db; border-radius:999px;}\n  .bs .bar{background:rgba(255,255,255,.96); border-top:1px solid #e5e7eb; box-shadow:0 -10px 25px rgba(0,0,0,.08); padding:10px 14px calc(10px + env(safe-area-inset-bottom));}\n  .bs .barTop{display:flex; justify-content:space-between; align-items:center; gap:12px;}\n  .bs .title{font-weight:900; font-size:13px;}\n  .bs .mini{font-size:12px; color:#666;}\n  .bs .btn{display:inline-block; padding:6px 10px; border-radius:999px; border:1px solid #d1d5db; text-decoration:none; font-weight:800; font-size:12px; color:#0b63ce; background:#fff;}\n  .bs .panel{display:none; padding-top:10px;}\n  .bs.open .panel{display:block;}\n  .bs .grid{display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin-top:10px;}\n  .bs .g{border:1px solid #ddd; border-radius:12px; padding:10px 12px; background:#fff;}\n  .bs .ghead{display:flex; justify-content:space-between; align-items:baseline; margin-bottom:8px;}\n  .bs .gt{font-weight:850;}\n  .bs .gsub{font-size:12px; color:#666; white-space:nowrap;}\n  .bs .metric{display:flex; align-items:center; gap:8px; margin:6px 0;}\n  .bs .label{width:42px; font-size:12px; color:#666;}\n  .bs .ibar{flex:1; height:8px; background:#f1f1f1; border-radius:999px; overflow:hidden;}\n  .bs .ifill{height:8px; width:0%;}\n  .bs .ifill.green{background:#1f9d55;}\n  .bs .ifill.amber{background:#d97706;}\n  .bs .ifill.red{background:#dc2626;}\n  .bs .val{min-width:64px; text-align:right; font-variant-numeric:tabular-nums; font-size:12px; font-weight:700;}\n  .bs details{border:1px solid #ddd; border-radius:12px; padding:10px 12px; margin-top:10px; background:#fff;}\n  .bs summary{cursor:pointer; font-weight:750;}\n  .bs .plist{margin-top:8px; font-family:ui-monospace, SFMono-Regular, Menlo, monospace; font-size:11px; color:#333; white-space:pre; overflow-x:auto;}\n  html,body{height:100%;}\n  body{padding-bottom:90px; -webkit-overflow-scrolling:touch;} /* room for bar */\n</style>\n\n<div id="bottomSheet" class="bs">\n  <div class="bar">\n    <div class="handle" aria-hidden="true"></div>\n    <div class="barTop" style="margin-top:8px;">\n      <div>\n        <div class="title">System Monitor</div>\n        <div class="mini" id="bsMini">Loading…</div>\n      </div>\n      <div style="display:flex; gap:8px; align-items:center;">\n        <a href="#" id="bsToggle" class="btn">Show</a>\n      </div>\n    </div>\n\n    <div class="panel" id="bsPanel">\n      <div class="grid" id="bsGpu"></div>\n      <div class="grid" style="grid-template-columns:1fr;">\n        <div class="g" id="bsCpu"></div>\n      </div>\n      <details>\n        <summary>Processes</summary>\n        <div class="plist" id="bsPs"></div>\n      </details>\n    </div>\n  </div>\n</div>\n\n<script>\n(function(){\n  const params = new URLSearchParams(location.search);\n  const t = params.get(\'t\') || \'\';\n  const bs = document.getElementById(\'bottomSheet\');\n  const btn = document.getElementById(\'bsToggle\');\n\n  function clampPct(x){\n    if(x===null || x===undefined || Number.isNaN(x)) return 0;\n    return Math.max(0, Math.min(100, x));\n  }\n  function klassForPct(p){\n    if(p >= 85) return \'red\';\n    if(p >= 60) return \'amber\';\n    return \'green\';\n  }\n  function metricRow(label, pct, cls, valueText){\n    return `\n      <div class="metric">\n        <div class="label">${label}</div>\n        <div class="ibar"><div class="ifill ${cls}" style="width:${pct}%"></div></div>\n        <div class="val">${valueText}</div>\n      </div>\n    `;\n  }\n\n  function toggle(open){\n    const isOpen = (open !== undefined) ? open : !bs.classList.contains(\'open\');\n    bs.classList.toggle(\'open\', isOpen);\n    btn.textContent = isOpen ? \'Hide\' : \'Show\';\n    try{ localStorage.setItem(\'bsOpen\', isOpen ? \'1\':\'0\'); }catch(e){}\n  }\n\n  btn.addEventListener(\'click\', (e)=>{ e.preventDefault(); toggle(); });\n  bs.querySelector(\'.handle\').addEventListener(\'click\', ()=>toggle());\n\n  try{\n    const saved = localStorage.getItem(\'bsOpen\');\n    if(saved===\'1\') toggle(true);\n  }catch(e){}\n\n  async function refresh(){\n    const r = await fetch(\'/api/stats?t=\'+encodeURIComponent(t));\n    if(!r.ok) return;\n    const j = await r.json();\n    if(!j.ok) return;\n\n    // Mini line\n    const mini = document.getElementById(\'bsMini\');\n    const cpuPct = j.cpu && (j.cpu.cpu_pct ?? null);\n    const g0 = (j.gpu && j.gpu.length) ? j.gpu[0] : null;\n    const gtxt = g0 ? `GPU0 ${Math.round(g0.util||0)}%` : \'GPU n/a\';\n    mini.textContent = `CPU ${cpuPct===null?\'-\':cpuPct}% • ${gtxt}`;\n\n    // GPU cards\n    const ge = document.getElementById(\'bsGpu\');\n    if(!j.gpu){ ge.innerHTML = \'<div class="muted">(no GPU data)</div>\'; }\n    else {\n      ge.innerHTML = \'\';\n      for(const g of j.gpu){\n        const util = clampPct(g.util);\n        const vram = g.mem_total ? clampPct((g.mem_used/g.mem_total)*100.0) : 0;\n        const gdiv = document.createElement(\'div\');\n        gdiv.className=\'g\';\n        gdiv.innerHTML = `\n          <div class="ghead"><div class="gt">GPU ${g.index}</div><div class="gsub">${Math.round(g.power||0)}W • ${Math.round(g.temp||0)}C</div></div>\n          ${metricRow(\'Util\', util, klassForPct(util), `${Math.round(util)}%`)}\n          ${metricRow(\'VRAM\', vram, klassForPct(vram), `${(g.mem_used||0).toFixed(1)}/${(g.mem_total||0).toFixed(0)} MiB`)}\n        `;\n        ge.appendChild(gdiv);\n      }\n    }\n\n    // CPU\n    const ce = document.getElementById(\'bsCpu\');\n    if(!j.cpu){ ce.innerHTML = \'<span class="muted">(no CPU data)</span>\'; }\n    else {\n      const mem = j.cpu.mem_gb || {};\n      ce.innerHTML = `\n        <div class="ghead"><div class="gt">CPU</div><div class="gsub">RAM ${(mem.used??\'-\')} / ${(mem.total??\'-\')} GB</div></div>\n        ${metricRow(\'CPU\', clampPct(j.cpu.cpu_pct||0), klassForPct(j.cpu.cpu_pct||0), `${j.cpu.cpu_pct ?? \'-\'}%`)}\n      `;\n      document.getElementById(\'bsPs\').textContent = (j.cpu.ps || []).join(\'\\n\');\n    }\n  }\n\n  refresh();\n  setInterval(refresh, 5000);\n})();\n</script>')
            parts.append('</body></html>')
            page = ''.join(parts)
            self._send(200, page.encode('utf-8'), 'text/html; charset=utf-8')
            return
        if path == "/ping":
            body = (root / "static" / "ping.html").read_bytes()
            self._send(200, body, "text/html; charset=utf-8")
            return

        if path == "/history":
            qs = parse_qs(urlparse(self.path).query)
            token = (qs.get("t") or [""])[0]

            conn = db_connect(self.server.db_path)
            db_init(conn)
            metas = db_list_jobs(conn)
            conn.close()

            def h(s: str) -> str:
                return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;")

            rows = []
            for meta in metas:
                jid = meta.get("id")
                st = (meta.get("status") or {}).get("state") or meta.get("state") or "unknown"
                title = meta.get("title") or jid
                started_at = meta.get("started_at")
                btns = []
                btns.append('<a href="/job/%s?t=%s">open</a>' % (jid, h(token)))
                btns.append('<a href="/view/%s?t=%s">sfml</a>' % (jid, h(token)))
                if meta.get("mp3") and st == "completed":
                    btns.append('<a href="/dl/%s?t=%s">audio</a>' % (jid, h(token)))
                rows.append('<li><b>%s</b> [%s] %s<br/>%s</li>' % (h(title), h(st), h(str(started_at or "")), " ".join(btns)))

            body = '<!doctype html><html><head><meta charset="utf-8"/>'
            body += '<meta name="viewport" content="width=device-width, initial-scale=1"/>'
            body += '<title>History</title>'
            body += '<style>body{font-family:system-ui; padding:16px;} a{color:#0b63ce;} li{margin:14px 0;}</style>'
            body += '</head><body>'
            body += '<h1>History (debug)</h1><div style="margin-bottom:10px;"><a href="/?t=%s">back</a></div>' % h(token)
            body += ('<ol>' + ''.join(rows) + '</ol>') if rows else '<div>(no jobs)</div>'
            body += '</body></html>'
            self._send(200, body.encode('utf-8'), 'text/html; charset=utf-8')
            return


        if path.startswith("/job/"):
            body = (root / "static" / "job.html").read_bytes()
            self._send(200, body, "text/html; charset=utf-8")
            return

        if path.startswith("/view/"):
            body = (root / "static" / "sfml_view.html").read_bytes()
            self._send(200, body, "text/html; charset=utf-8")
            return

        if path.startswith("/voices"):
            body = (root / "static" / "voices.html").read_bytes()
            self._send(200, body, "text/html; charset=utf-8")
            return

        if path == "/api/voices":
            qs = parse_qs(urlparse(self.path).query)
            engine = (qs.get("engine") or ["tortoise"])[0]
            repo_root = Path("/raid/storyforge_test")
            voices = []
            if engine == "tortoise":
                voices = load_tortoise_roster(repo_root)
            # attach ratings
            conn = db_connect(self.server.db_path)
            db_init(conn)
            ratings = {row[0]: row[1] for row in conn.execute("SELECT voice_id, rating FROM voice_ratings WHERE engine=?", (engine,)).fetchall()}
            conn.close()
            for v in voices:
                v["rating"] = int(ratings.get(v["id"], 0) or 0)
            self._send(200, (json.dumps({"ok": True, "engine": engine, "voices": voices}) + "\n").encode(), "application/json")
            return

        if path == "/api/voice/rate":
            qs = parse_qs(urlparse(self.path).query)
            engine = (qs.get("engine") or [""])[0]
            vid = (qs.get("id") or [""])[0]
            rating = int((qs.get("rating") or ["0"])[0])
            rating = max(0, min(5, rating))
            if not engine or not vid:
                self._send(400, (json.dumps({"ok": False})+"\n").encode(), "application/json")
                return
            conn = db_connect(self.server.db_path)
            db_init(conn)
            conn.execute("INSERT INTO voice_ratings(engine,voice_id,rating,updated_at) VALUES(?,?,?,?) ON CONFLICT(engine,voice_id) DO UPDATE SET rating=excluded.rating, updated_at=excluded.updated_at", (engine, vid, rating, now_ts()))
            conn.commit(); conn.close()
            self._send(200, (json.dumps({"ok": True})+"\n").encode(), "application/json")
            return

        m = re.match(r"^/api/voice/demo/([a-zA-Z0-9_-]+)/([a-zA-Z0-9_-]+)$", path)
        if m:
            engine = m.group(1)
            vid = m.group(2)
            repo_root = Path("/raid/storyforge_test")
            cache_dir = root / "voices_cache" / engine
            cache_dir.mkdir(parents=True, exist_ok=True)
            mp3_path = cache_dir / f"{vid}.mp3"
            if not mp3_path.exists():
                # build demo
                voice_name = None
                color = vid
                if engine == "tortoise":
                    for v in load_tortoise_roster(repo_root):
                        if v.get("id") == vid:
                            voice_name = v.get("voice_name")
                            color = v.get("color") or vid
                            break
                if not voice_name:
                    self._send(404, b"voice_not_found\n")
                    return
                demo = voice_demo_text(vid, color)
                seed = (sum(ord(c) for c in (engine+":"+vid)) % 2000000000) + 1
                wav_tmp = cache_dir / f"{vid}.wav"
                import subprocess
                subprocess.run([str(repo_root / "tools" / "voicegen_tortoise.sh"), "--text", demo, "--ref", voice_name, "--out", str(wav_tmp), "--lang", "en", "--device", "cuda", "--seed", str(seed), "--gpu", "0"], check=True)
                # convert to mp3 (48k stereo)
                mp3_tmp = cache_dir / f"{vid}.tmp.mp3"
                subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y","-i", str(wav_tmp),"-c:a","libmp3lame","-b:a","192k","-ar","48000","-ac","2", str(mp3_tmp)], check=True)
                try:
                    wav_tmp.unlink(missing_ok=True)
                except Exception:
                    pass
                mp3_tmp.replace(mp3_path)
            data = mp3_path.read_bytes()
            self._send(200, data, "audio/mpeg")
            return

        if path == "/api/stats":
            data = {
                "ok": True,
                "gpu": gpu_stats(),
                "cpu": cpu_stats(),
                "now": now_ts(),
            }
            self._send(200, (json.dumps(data) + "\n").encode(), "application/json")
            return

        if path == "/api/jobs":
            conn = db_connect(self.server.db_path)
            db_init(conn)
            metas = db_list_jobs(conn)
            conn.close()

            items = []
            for meta in metas:
                jid = meta.get("id")
                st = job_status_light(root, jid)
                meta["status"] = st.get("status")
                meta["mp3"] = st.get("mp3")
                meta["progress"] = st.get("progress")
                items.append(meta)

            self._send(200, (json.dumps({"ok": True, "jobs": items}) + "\n").encode(), "application/json")
            return

        m = re.match(r"^/api/job/([a-zA-Z0-9_-]+)$", path)
        if m:
            jid = m.group(1)
            st = job_status(root, jid)
            self._send(200, (json.dumps(st) + "\n").encode(), "application/json")
            return

        m = re.match(r"^/api/sfml/([a-zA-Z0-9_-]+)$", path)
        if m:
            jid = m.group(1)
            conn = db_connect(self.server.db_path)
            db_init(conn)
            meta = db_get_job(conn, jid)
            conn.close()
            if not meta:
                self._send(404, b"job_not_found\n")
                return
            sfml = meta.get("sfml")
            if not sfml:
                self._send(404, b"sfml_missing\n")
                return
            sfml_path = Path(sfml)
            if not sfml_path.is_absolute():
                sfml_path = Path("/raid/storyforge_test") / sfml_path
            if not sfml_path.exists():
                self._send(404, b"sfml_not_found\n")
                return
            data = sfml_path.read_bytes()
            self._send(200, data, "text/plain; charset=utf-8")
            return




        m = re.match(r"^/sfml/([a-zA-Z0-9_-]+)$", path)
        if m:
            jid = m.group(1)
            conn = db_connect(self.server.db_path)
            db_init(conn)
            meta = db_get_job(conn, jid)
            conn.close()
            if not meta:
                self._send(404, b"job_not_found\n")
                return
            try:
                sfml = meta.get("sfml")
                if not sfml:
                    self._send(404, b"sfml_missing\n")
                    return
                sfml_path = Path(sfml)
                if not sfml_path.is_absolute():
                    sfml_path = Path("/raid/storyforge_test") / sfml_path
                if not sfml_path.exists():
                    self._send(404, b"sfml_not_found\n")
                    return
                data = sfml_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Content-Disposition", f"attachment; filename=\"{sfml_path.name}\"")
                self.end_headers()
                self.wfile.write(data)
            except Exception:
                self._send(500, b"error\n")
            return

        

        m = re.match(r"^/audio/([a-zA-Z0-9_-]+)$", path)
        if m:
            qs = parse_qs(urlparse(self.path).query)
            token = (qs.get("t") or [""])[0]
            if token != self.server.token:
                self._send(403, b"forbidden\n")
                return
            jid = m.group(1)
            st = job_status(root, jid)
            mp3 = st.get("mp3")
            if not mp3:
                self._send(404, b"not_ready\n")
                return
            p = Path(mp3)
            data = p.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Disposition", f"inline; filename=\"{p.name}\"")
            self.end_headers()
            self.wfile.write(data)
            return

        m = re.match(r"^/dl/([a-zA-Z0-9_-]+)$", path)
        if m:
            jid = m.group(1)
            st = job_status(root, jid)
            mp3 = st.get("mp3")
            if not mp3:
                self._send(404, b"not_ready\n")
                return
            p = Path(mp3)
            data = p.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Disposition", f"attachment; filename=\"{p.name}\"")
            self.end_headers()
            self.wfile.write(data)
            return

        self._send(404, b"not_found\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="/raid/storyforge_test/monitor")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--db", default="", help="Path to sqlite db (default: <root>/monitor.db)")
    args = ap.parse_args()

    root = Path(args.root)
    token = (root / "token.txt").read_text().strip()
    allow_nets = detect_allow_cidrs(root)

    db_path = Path(args.db) if args.db else db_default_path(root)
    # create/init db + migrate legacy JSON jobs once
    conn = db_connect(db_path)
    db_init(conn)
    conn.close()
    migrate_jobs_json_to_db(root, db_path)

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    httpd.root = root
    httpd.token = token
    httpd.allow_nets = allow_nets
    httpd.db_path = db_path

    print(f"listening on http://{args.host}:{args.port} (token required)")
    print("allow:", ", ".join(str(n) for n in allow_nets))
    httpd.serve_forever()


if __name__ == "__main__":
    main()
