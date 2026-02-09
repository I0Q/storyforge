from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any

import psutil
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse

APP_NAME = "tinybox-compute-node"

app = FastAPI(title=APP_NAME, version="0.1")


def _read_token() -> str:
    p = Path(os.environ.get("TBCN_TOKEN_FILE", "~/.config/tinybox-compute-node/token")).expanduser()
    try:
        return p.read_text().strip()
    except Exception:
        return ""


def _auth(authorization: str | None) -> None:
    tok = _read_token()
    if not tok:
        raise HTTPException(status_code=500, detail="token_not_configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="unauthorized")
    got = authorization.removeprefix("Bearer ").strip()
    if got != tok:
        raise HTTPException(status_code=403, detail="forbidden")


def _run(cmd: list[str], timeout: int = 3) -> str:
    try:
        return subprocess.check_output(cmd, timeout=timeout, text=True, stderr=subprocess.STDOUT)
    except Exception:
        return ""


def _gpu_list() -> list[dict[str, Any]]:
    """Return per-GPU metrics (NVIDIA only) using nvidia-smi.

    Never raises; returns [] if unavailable.
    """
    out = _run(
        [
            "nvidia-smi",
            "--query-gpu=index,utilization.gpu,utilization.memory,power.draw,temperature.gpu,memory.total,memory.used,name",
            "--format=csv,noheader,nounits",
        ],
        timeout=2,
    )
    if not out.strip():
        return []

    gpus: list[dict[str, Any]] = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 8:
            continue
        idx, util_gpu, util_mem, power_w, temp, mem_total, mem_used, name = parts[:8]
        try:
            gpus.append(
                {
                    "index": int(idx),
                    "name": name,
                    "util_gpu_pct": float(util_gpu),
                    "util_mem_pct": float(util_mem),
                    "power_w": float(power_w),
                    "temp_c": float(temp),
                    "vram_total_mb": float(mem_total),
                    "vram_used_mb": float(mem_used),
                }
            )
        except Exception:
            continue
    return gpus


def _gpu_mem_by_pid() -> dict[int, float]:
    """Return compute-app GPU memory usage per pid in MB."""
    out = _run(
        [
            "nvidia-smi",
            "--query-compute-apps=pid,used_memory",
            "--format=csv,noheader,nounits",
        ],
        timeout=2,
    )
    if not out.strip():
        return {}
    m: dict[int, float] = {}
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        try:
            pid = int(parts[0])
            mb = float(parts[1])
            m[pid] = m.get(pid, 0.0) + mb
        except Exception:
            continue
    return m


def _top_processes(limit: int = 12) -> list[dict[str, Any]]:
    """Return a lightweight top-N process list.

    Uses psutil for CPU/RAM and ps for elapsed+command.
    """
    # Pre-load CPU% baselines.
    procs: list[psutil.Process] = []
    for p in psutil.process_iter(attrs=["pid", "name", "cpu_percent", "memory_info", "memory_percent"]):
        try:
            procs.append(p)
        except Exception:
            continue

    for p in procs:
        try:
            p.cpu_percent(interval=None)
        except Exception:
            pass

    time.sleep(0.15)

    rows: list[dict[str, Any]] = []
    for p in procs:
        try:
            info = p.info
            pid = int(info["pid"])
            cpu = float(p.cpu_percent(interval=None))
            mem_pct = float(info.get("memory_percent") or 0.0)
            mem_mb = float((info.get("memory_info").rss if info.get("memory_info") else 0) / (1024 * 1024))
            rows.append(
                {
                    "pid": pid,
                    "name": info.get("name") or "",
                    "cpu_pct": cpu,
                    "mem_pct": mem_pct,
                    "ram_mb": mem_mb,
                }
            )
        except Exception:
            continue

    rows.sort(key=lambda r: (r.get("cpu_pct") or 0.0, r.get("ram_mb") or 0.0), reverse=True)
    rows = rows[: max(1, int(limit))]

    pids = [str(r["pid"]) for r in rows]
    ps_out = _run(["ps", "-o", "pid=,etime=,comm=,args=", "-p", ",".join(pids)], timeout=2)
    meta: dict[int, dict[str, str]] = {}
    for line in ps_out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 3)
        if len(parts) < 3:
            continue
        try:
            pid = int(parts[0])
        except Exception:
            continue
        meta[pid] = {
            "elapsed": parts[1] if len(parts) >= 2 else "",
            "command": parts[2] if len(parts) >= 3 else "",
            "args": parts[3] if len(parts) >= 4 else "",
        }

    gpu_mem = _gpu_mem_by_pid()
    for r in rows:
        pid = r["pid"]
        if pid in meta:
            r.update(meta[pid])
        if pid in gpu_mem:
            r["gpu_mem_mb"] = gpu_mem[pid]

    return rows


@app.get("/ping")
def ping():
    return {"ok": True, "service": APP_NAME, "ts": int(time.time())}


@app.get("/v1/metrics")
def metrics(authorization: str | None = Header(default=None)):
    _auth(authorization)

    vm = psutil.virtual_memory()
    cpu = psutil.cpu_percent(interval=0.2)
    load1, load5, load15 = os.getloadavg()

    gpus = _gpu_list()
    gpu = gpus[0] if gpus else None
    processes = _top_processes(limit=12)

    return {
        "ok": True,
        "ts": int(time.time()),
        "cpu_pct": cpu,
        "load": [load1, load5, load15],
        "ram_total_mb": vm.total / (1024 * 1024),
        "ram_used_mb": (vm.total - vm.available) / (1024 * 1024),
        "gpu": gpu,
        "gpus": gpus,
        "processes": processes,
    }


@app.get("/v1/voices")
def voices(authorization: str | None = Header(default=None)):
    _auth(authorization)
    return {"ok": True, "voices": []}




@app.get("/v1/engines")
def engines(authorization: str | None = Header(default=None)):
    _auth(authorization)
    return {"ok": True, "engines": ["xtts", "tortoise"]}


@app.get("/v1/voice-clips")
def voice_clips(authorization: str | None = Header(default=None)):
    _auth(authorization)
    base = Path(os.environ.get("TBCN_VOICE_PRESETS", "/raid/storyforge_test/voice_presets"))
    clips: list[dict[str, str]] = []
    try:
        if base.exists() and base.is_dir():
            for pp in sorted(base.glob("**/*")):
                if not pp.is_file():
                    continue
                if pp.suffix.lower() not in (".wav", ".mp3", ".m4a", ".flac", ".ogg"):
                    continue
                clips.append({"name": pp.stem, "path": str(pp)})
    except Exception:
        pass
    return {"ok": True, "clips": clips}




@app.get("/v1/voice-clips/file")
def voice_clip_file(path: str, authorization: str | None = Header(default=None)):
    _auth(authorization)
    base = Path(os.environ.get("TBCN_VOICE_PRESETS", "/raid/storyforge_test/voice_presets")).resolve()
    try:
        pp = Path(path).expanduser()
        if not pp.is_absolute():
            raise HTTPException(status_code=400, detail="bad_path")
        # allow_symlink: validate the requested path is under base even if it is a symlink
        if not str(pp).startswith(str(base) + os.sep):
            raise HTTPException(status_code=403, detail="forbidden")
        if not pp.exists() or not pp.is_file():
            raise HTTPException(status_code=404, detail="not_found")
        if pp.suffix.lower() not in (".wav", ".mp3", ".m4a", ".flac", ".ogg"):
            raise HTTPException(status_code=415, detail="bad_type")
        return FileResponse(str(pp), filename=pp.name)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="bad_path")
@app.post("/v1/voices/train")
def voices_train(payload: dict[str, Any], authorization: str | None = Header(default=None)):
    _auth(authorization)
    engine = str((payload or {}).get("engine") or "").strip() or "xtts"
    name = str((payload or {}).get("name") or "").strip() or "voice"
    clip_url = str((payload or {}).get("clip_url") or "").strip()
    sample_text = str((payload or {}).get("sample_text") or "").strip()
    if not clip_url:
        return {"ok": False, "error": "missing_clip_url"}
    voice_ref = (f"{engine}:{name}")[:128]
    return {"ok": True, "voice_ref": voice_ref, "engine": engine, "sample_text": sample_text}
@app.post("/v1/tts")
def tts(payload: dict[str, Any], authorization: str | None = Header(default=None)):
    _auth(authorization)
    return {"ok": False, "error": "not_implemented"}
