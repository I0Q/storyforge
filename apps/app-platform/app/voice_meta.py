from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from typing import Any

import requests

from .db import db_connect, db_init


def _now() -> int:
    return int(time.time())


def _ffprobe_duration_s(path: str) -> float | None:
    try:
        out = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            stderr=subprocess.STDOUT,
            timeout=20,
        )
        s = out.decode("utf-8", errors="ignore").strip()
        return float(s)
    except Exception:
        return None


def _ffmpeg_lufs(path: str) -> float | None:
    """Best-effort integrated loudness in LUFS via ffmpeg ebur128."""
    try:
        # We parse the final "I:" integrated value from ebur128 summary.
        p = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-nostats",
                "-i",
                path,
                "-filter_complex",
                "ebur128=peak=true",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=40,
        )
        txt = (p.stderr or "") + "\n" + (p.stdout or "")
        # look for summary line like: "I:         -16.8 LUFS"
        import re

        m = None
        for mm in re.finditer(r"\bI:\s*(-?\d+(?:\.\d+)?)\s*LUFS\b", txt):
            m = mm
        if not m:
            return None
        return float(m.group(1))
    except Exception:
        return None


def _set_voice_traits_json(voice_id: str, voice_traits: dict[str, Any], measured: dict[str, Any] | None = None) -> None:
    conn = db_connect()
    try:
        db_init(conn)
        cur = conn.cursor()
        now = _now()
        payload = {
            "voice_traits": voice_traits,
            "measured": measured or {},
            "updated_at": now,
        }
        cur.execute(
            "UPDATE sf_voices SET voice_traits_json=%s, updated_at=%s WHERE id=%s",
            (json.dumps(payload, separators=(",", ":")), now, voice_id),
        )
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass


def analyze_voice_metadata(
    *,
    voice_id: str,
    engine: str,
    voice_ref: str,
    sample_text: str,
    sample_url: str,
    tortoise_voice: str = "",
    tortoise_gender: str = "",
    tortoise_preset: str = "",
    gateway_base: str,
    headers: dict[str, str],
) -> dict[str, Any]:
    """Generate voice metadata.

    Phase 1 (safe/minimal):
    - Measure duration + LUFS from the saved sample audio.
    - Use Tinybox LLM to produce STRICT JSON voice_traits, but keep it conservative.

    Returns dict with keys: ok, voice_traits, measured, error.
    """
    if not sample_url:
        return {"ok": False, "error": "missing_sample_url"}

    # Download sample audio
    with tempfile.TemporaryDirectory(prefix="sf_voice_meta_") as td:
        in_path = os.path.join(td, "sample")
        try:
            r = requests.get(sample_url, timeout=30)
            r.raise_for_status()
            with open(in_path, "wb") as f:
                f.write(r.content)
        except Exception as e:
            return {"ok": False, "error": f"download_failed: {type(e).__name__}: {str(e)[:160]}"}

        dur = _ffprobe_duration_s(in_path)
        lufs = _ffmpeg_lufs(in_path)

    measured = {
        "duration_s": dur,
        "lufs_i": lufs,
    }

    # LLM: conservative labels. (No audio listening; just use known params + measured.)
    prompt = {
        "task": "Label voice traits for a TTS voice from metadata only. Be conservative. If unknown, use 'unknown' or '' and do not guess accents.",
        "engine": engine,
        "voice_ref": voice_ref,
        "tortoise": {
            "voice": tortoise_voice,
            "gender": tortoise_gender,
            "preset": tortoise_preset,
        },
        "sample_text": sample_text,
        "measured": measured,
        "output": {
            "format": "STRICT_JSON",
            "schema": {
                "gender": "female|male|neutral|unknown",
                "age": "child|teen|adult|elder|unknown",
                "pitch": "low|medium|high|unknown",
                "tone": "array of short tags like warm, bright, calm, stern (max 8)",
                "accent": "string or ''",
                "notes": "short string",
            },
        },
    }

    try:
        # Use the same rule as gemma: single user message only.
        r = requests.post(
            gateway_base + "/v1/llm",
            json={
                "model": "google/gemma-2-9b-it",
                "messages": [
                    {
                        "role": "user",
                        "content": "Return ONLY strict JSON matching the schema.\n\n" + json.dumps(prompt, separators=(",", ":")),
                    }
                ],
                "temperature": 0.2,
                "max_tokens": 220,
            },
            headers=headers,
            timeout=90,
        )

        # Robust parse: gateway occasionally returns HTML/plaintext errors.
        status = int(getattr(r, "status_code", 0) or 0)
        raw_txt = ""
        try:
            raw_txt = r.text or ""
        except Exception:
            raw_txt = ""

        if status < 200 or status >= 300:
            return {
                "ok": False,
                "error": f"llm_http_{status}",
                "detail": (raw_txt[:400] if raw_txt else ""),
                "measured": measured,
            }

        try:
            j = json.loads(raw_txt) if raw_txt else {}
        except Exception:
            return {
                "ok": False,
                "error": "llm_non_json",
                "detail": (raw_txt[:400] if raw_txt else ""),
                "measured": measured,
            }

        txt = ""
        try:
            txt = str((j.get("choices") or [{}])[0].get("message", {}).get("content") or "").strip()
        except Exception:
            txt = ""
        if not txt:
            return {"ok": False, "error": "llm_empty", "measured": measured}
        # Extract JSON (handle ```json fenced blocks and trailing text)
        import re

        raw = ''
        try:
            # Prefer outermost {...} anywhere in the content
            i0 = txt.find('{')
            i1 = txt.rfind('}')
            if i0 != -1 and i1 != -1 and i1 > i0:
                raw = txt[i0 : i1 + 1]
            else:
                m = re.search(r"\{[\s\S]*\}", txt)
                raw = m.group(0) if m else txt
        except Exception:
            raw = txt

        try:
            traits = json.loads(raw)
        except Exception:
            return {
                "ok": False,
                "error": "llm_bad_output",
                "detail": (txt[:400] if txt else ""),
                "measured": measured,
            }
        if not isinstance(traits, dict):
            return {"ok": False, "error": "llm_bad_json_shape", "measured": measured}

        # Normalize
        def _norm(s: Any, maxlen: int = 80) -> str:
            s2 = str(s or "").strip()
            return s2[:maxlen]

        out_traits = {
            "gender": _norm(traits.get("gender"), 16).lower() or "unknown",
            "age": _norm(traits.get("age"), 16).lower() or "unknown",
            "pitch": _norm(traits.get("pitch"), 16).lower() or "unknown",
            "accent": _norm(traits.get("accent"), 80),
            "tone": [],
        }
        tone = traits.get("tone")
        if isinstance(tone, list):
            out_traits["tone"] = [_norm(x, 40) for x in tone if _norm(x, 40)][:8]

        # Prefer explicit tortoise_gender if provided
        if tortoise_gender and out_traits["gender"] in ("", "unknown"):
            out_traits["gender"] = _norm(tortoise_gender, 16).lower()

        # Persist
        _set_voice_traits_json(voice_id, out_traits, measured=measured)
        return {"ok": True, "voice_traits": out_traits, "measured": measured}
    except Exception as e:
        return {"ok": False, "error": f"llm_failed: {type(e).__name__}: {str(e)[:160]}", "measured": measured}
