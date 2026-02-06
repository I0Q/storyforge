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
    out_dir = Path("/raid/storyforge_test/out")

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

    # If mp3 not recorded in meta, try to locate by title prefix in out/
    if mp3_path is None:
        pref = slugify_title(meta.get("title", ""))
        if pref:
            cands = sorted(out_dir.glob(pref + "*.mp3"), key=lambda p: p.stat().st_mtime, reverse=True)
            if cands:
                mp3_path = cands[0]

    if mp3_path and mp3_path.exists() and total and done == 0:
        done = total

    status = job_runtime_status(job_base, tmp_job, mp3_path if (mp3_path and mp3_path.exists()) else None, done, total)

    return {
        "ok": True,
        "progress": {"done": done, "total": total, "pct": (done/total*100.0) if total else None},
        "mp3": str(mp3_path) if mp3_path and mp3_path.exists() else None,
        "status": status,
    }


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

    if mp3_path and mp3_path.exists() and total and done >= total:
        finished_at = int(mp3_path.stat().st_mtime)
        return {
            'state': 'completed',
            'finished_at': finished_at,
            'aborted_at': None,
            'last_activity_at': finished_at,
        }

    # last activity: newest seg wav or newest log in tmp_job/job_base
    last = None
    cands = []
    if tmp_job and tmp_job.exists():
        narr = tmp_job / 'narr'
        if narr.exists():
            cands += list(narr.glob('seg_*.wav'))
        cands += list(tmp_job.glob('*.log'))
    cands += list(job_base.glob('*.log'))
    for p in cands:
        try:
            ts = int(p.stat().st_mtime)
            if last is None or ts > last:
                last = ts
        except Exception:
            pass

    # running? best-effort: any storyforge render process
    running = False
    try:
        import subprocess
        out = subprocess.check_output(['bash','-lc', f"ps -ef | grep -F '{job_base.as_posix()}' | grep -F 'storyforge.cli render' | grep -v grep | wc -l"], text=True).strip()
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

    # not running + no mp3
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
    jobs_dir = root / "jobs"
    tmp_root = root / "tmp"
    out_dir = Path("/raid/storyforge_test/out")

    meta_path = jobs_dir / f"{job_id}.json"
    if not meta_path.exists():
        return {"ok": False, "error": "job_not_found"}

    meta = json.loads(read_text(meta_path))
    sfml = Path(meta.get("sfml", ""))
    started_at = int(meta.get("started_at", 0) or 0)

    total = int(meta.get("total_segments", 0) or 0)
    if total == 0 and sfml.exists():
        total = count_spoken_segments(sfml)

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
    if not mp3_path or not mp3_path.exists():
        mp3_path = find_latest_mp3(out_dir, started_at)

    # If an MP3 exists but the temp folder is gone (cleanup) we still consider all segments done.
    if mp3_path and mp3_path.exists() and total and done == 0:
        done = total

    status = job_runtime_status(job_base, tmp_job, mp3_path if (mp3_path and mp3_path.exists()) else None, done, total)

    return {
        "ok": True,
        "job": meta,
        "status": status,
        "progress": {
            "done": done,
            "total": total,
            "pct": (done / total * 100.0) if total else None,
        },
        "tmp_dir": str(tmp_job) if tmp_job else None,
        "mp3": str(mp3_path) if mp3_path and mp3_path.exists() else None,
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
            body = (root / "static" / "index.html").read_bytes()
            self._send(200, body, "text/html; charset=utf-8")
            return

        if path == "/ping":
            body = (root / "static" / "ping.html").read_bytes()
            self._send(200, body, "text/html; charset=utf-8")
            return

        if path.startswith("/job/"):
            body = (root / "static" / "job.html").read_bytes()
            self._send(200, body, "text/html; charset=utf-8")
            return

        if path.startswith("/view/"):
            body = (root / "static" / "sfml_view.html").read_bytes()
            self._send(200, body, "text/html; charset=utf-8")
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
