from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from typing import Any

import requests

from .db import db_connect, db_init


# Curated hints for Tortoise named voices.
# We should prefer explicit provider metadata when available, but Tortoise doesn't provide it.
_TORTOISE_GENDER_HINTS: dict[str, str] = {
    # Known StoryForge tortoise refs (best-effort; can be adjusted as we learn)
    'snakes': 'male',
    'freeman': 'male',
}


def _now() -> int:
    return int(time.time())


def _ffprobe_duration_s(path: str) -> float | None:
    try:
        if not shutil.which('ffprobe'):
            return None
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
        if not shutil.which('ffmpeg'):
            return None
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


def _audio_to_wav16k(src_path: str, dst_path: str) -> bool:
    try:
        if not shutil.which('ffmpeg'):
            return False
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-nostats",
                "-y",
                "-i",
                src_path,
                "-ac",
                "1",
                "-ar",
                "16000",
                "-f",
                "wav",
                dst_path,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=40,
        )
        return True
    except Exception:
        return False


def _wav_duration_s(wav_path: str) -> float | None:
    try:
        import wave

        with wave.open(wav_path, 'rb') as w:
            sr = float(w.getframerate() or 0)
            n = float(w.getnframes() or 0)
        if sr <= 0 or n <= 0:
            return None
        return float(n / sr)
    except Exception:
        return None


def _extract_wav_features(wav_path: str) -> dict[str, Any]:
    """Extract lightweight acoustic features from a mono 16k WAV.

    No external deps beyond numpy.
    Returns dict with keys like:
      - f0_hz_median
      - f0_hz_p10 / p90
      - pitch_bucket (low|medium|high)
      - centroid_hz_median
      - brightness (dark|neutral|bright)
      - rms
    """
    try:
        import wave
        import numpy as np

        with wave.open(wav_path, 'rb') as w:
            sr = int(w.getframerate() or 16000)
            n = int(w.getnframes() or 0)
            b = w.readframes(n)
        if not b:
            return {}
        x = np.frombuffer(b, dtype=np.int16).astype(np.float32) / 32768.0
        if x.size < sr * 0.2:
            return {}

        # RMS loudness proxy
        rms = float(np.sqrt(np.mean(np.square(x)) + 1e-12))

        # Pitch via autocorrelation on voiced frames
        frame = int(0.04 * sr)   # 40ms
        hop = int(0.01 * sr)     # 10ms
        fmin, fmax = 70.0, 320.0
        lag_min = int(sr / fmax)
        lag_max = int(sr / fmin)

        f0s = []
        for i in range(0, len(x) - frame, hop):
            seg = x[i:i+frame]
            seg = seg - float(np.mean(seg))
            e = float(np.mean(seg*seg))
            if e < 1e-4:
                continue
            ac = np.correlate(seg, seg, mode='full')[frame-1:]
            ac0 = float(ac[0]) if ac.size else 0.0
            if ac0 <= 0:
                continue
            # normalize
            ac = ac / (ac0 + 1e-9)
            if lag_max >= ac.size:
                continue
            sl = ac[lag_min:lag_max]
            j = int(np.argmax(sl))
            peak = float(sl[j])
            if peak < 0.25:
                continue
            lag = lag_min + j
            f0 = float(sr / max(1, lag))
            if fmin <= f0 <= fmax:
                f0s.append(f0)

        feat: dict[str, Any] = {"rms": rms}
        if f0s:
            f0a = np.array(f0s, dtype=np.float32)
            f0_med = float(np.median(f0a))
            feat["f0_hz_median"] = f0_med
            feat["f0_hz_p10"] = float(np.percentile(f0a, 10))
            feat["f0_hz_p90"] = float(np.percentile(f0a, 90))
            # bucket
            if f0_med < 140:
                feat["pitch_bucket"] = "low"
            elif f0_med > 210:
                feat["pitch_bucket"] = "high"
            else:
                feat["pitch_bucket"] = "medium"

        # Spectral centroid for brightness
        # Compute on a small subset for speed
        try:
            import numpy.fft as fft

            centroids = []
            win = np.hanning(frame).astype(np.float32)
            freqs = (np.arange(frame//2 + 1, dtype=np.float32) * (sr / frame))
            for i in range(0, len(x) - frame, hop*4):
                seg = x[i:i+frame] * win
                mag = np.abs(fft.rfft(seg)) + 1e-9
                c = float((freqs * mag).sum() / mag.sum())
                if c > 0:
                    centroids.append(c)
            if centroids:
                c_med = float(np.median(np.array(centroids, dtype=np.float32)))
                feat["centroid_hz_median"] = c_med
                if c_med < 1700:
                    feat["brightness"] = "dark"
                elif c_med > 2600:
                    feat["brightness"] = "bright"
                else:
                    feat["brightness"] = "neutral"
        except Exception:
            pass

        return feat
    except Exception:
        return {}


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

    # Download + analyze sample audio
    with tempfile.TemporaryDirectory(prefix="sf_voice_meta_") as td:
        in_path = os.path.join(td, "sample")
        wav_path = os.path.join(td, "sample_16k.wav")
        try:
            r = requests.get(sample_url, timeout=30)
            r.raise_for_status()
            with open(in_path, "wb") as f:
                f.write(r.content)
        except Exception as e:
            return {"ok": False, "error": f"download_failed: {type(e).__name__}: {str(e)[:160]}"}

        # Prefer remote analysis (Tinybox) via gateway: cloud containers often lack ffmpeg.
        dur = _ffprobe_duration_s(in_path)
        lufs = _ffmpeg_lufs(in_path)

        feats: dict[str, Any] = {}

        # 1) Try remote analyze first (best)
        try:
            ra = requests.post(
                gateway_base + '/v1/audio/analyze',
                json={'url': sample_url},
                headers=headers,
                timeout=120,
            )
            if int(getattr(ra, 'status_code', 0) or 0) == 200:
                j = {}
                try:
                    j = ra.json()
                except Exception:
                    j = {}
                if isinstance(j, dict) and j.get('ok'):
                    dur = j.get('duration_s') if j.get('duration_s') is not None else dur
                    lufs = j.get('lufs_i') if j.get('lufs_i') is not None else lufs
                    feats = j.get('features') if isinstance(j.get('features'), dict) else feats
        except Exception:
            pass

        # 2) Fallback: local extraction if tools exist
        try:
            if not feats and _audio_to_wav16k(in_path, wav_path):
                feats = _extract_wav_features(wav_path) or {}
                if dur is None:
                    dur = _wav_duration_s(wav_path)
        except Exception:
            feats = feats or {}

    measured = {
        "duration_s": dur,
        "lufs_i": lufs,
        "features": feats or {},
        # Note: engine + voice_ref are already stored on sf_voices; avoid duplicating here.
        # (Same for tortoise hints — those live in provider/voice fields.)
    }

    # LLM: use measured audio features + known engine params.
    # IMPORTANT: We do NOT ask the model to decide gender; we keep it unknown unless sourced from provider hints.
    prompt = {
        "task": "Label voice traits for a TTS voice using the provided measured audio features and engine parameters. If unknown, use 'unknown' or '' (do not invent accents). Do NOT guess gender.",
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
                "gender": "unknown (do not guess)",
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

        # Tolerate common non-strict JSON issues (trailing commas)
        raw2 = raw
        try:
            raw2 = raw2.strip()
            # strip code fences if they survived slicing
            if raw2.startswith('```'):
                raw2 = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", raw2)
                raw2 = re.sub(r"```\s*$", "", raw2).strip()
            # remove trailing commas before } or ]
            raw2 = re.sub(r",\s*([}\]])", r"\1", raw2)
        except Exception:
            raw2 = raw

        try:
            traits = json.loads(raw2)
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

        # Start with LLM suggestions
        out_traits = {
            "gender": _norm(traits.get("gender"), 16).lower() or "unknown",
            "age": (lambda a: (a if a in ('child','teen','adult','elder') else 'unknown'))(_norm(traits.get("age"), 16).lower() or "unknown"),
            "pitch": _norm(traits.get("pitch"), 16).lower() or "unknown",
            "accent": _norm(traits.get("accent"), 80),
            "tone": [],
        }

        # Age: prefer dedicated regressor endpoint (Tinybox) when available.
        try:
            ar = requests.post(
                gateway_base + '/v1/audio/age',
                json={'url': sample_url},
                headers=headers,
                timeout=120,
            )
            if int(getattr(ar, 'status_code', 0) or 0) == 200:
                aj = {}
                try:
                    aj = ar.json()
                except Exception:
                    aj = {}
                if isinstance(aj, dict) and aj.get('ok') and aj.get('age_years') is not None:
                    try:
                        agey = float(aj.get('age_years'))
                    except Exception:
                        agey = None
                    if agey is not None:
                        # bucket
                        if agey < 13:
                            out_traits['age'] = 'child'
                        elif agey < 20:
                            out_traits['age'] = 'teen'
                        elif agey < 60:
                            out_traits['age'] = 'adult'
                        else:
                            out_traits['age'] = 'elder'
                        measured['age_years'] = agey
        except Exception:
            pass

        # If still unknown, default to adult (better UX than unknown).
        try:
            if out_traits.get('age') in ('', 'unknown', None):
                out_traits['age'] = 'adult'
        except Exception:
            pass

        # Override with measured pitch bucket if available
        try:
            pb = str(((measured.get('features') or {}).get('pitch_bucket') or '')).strip().lower()
            if pb in ('low','medium','high'):
                out_traits['pitch'] = pb
        except Exception:
            pass
        tone = traits.get("tone")
        if isinstance(tone, list):
            out_traits["tone"] = [_norm(x, 40) for x in tone if _norm(x, 40)][:8]

        # Add brightness tag from spectral centroid
        try:
            br = str(((measured.get('features') or {}).get('brightness') or '')).strip().lower()
            if br in ('dark','neutral','bright') and br not in out_traits['tone']:
                out_traits['tone'].append(br)
        except Exception:
            pass

            # Gender: use a dedicated classifier endpoint (Tinybox) when available.
        # Fall back only to explicit provider/curated hints.
        out_traits["gender"] = "unknown"

        # 1) explicit provider hint
        if tortoise_gender:
            out_traits["gender"] = _norm(tortoise_gender, 16).lower() or "unknown"

        # 2) classifier via gateway
        if out_traits["gender"] in ("", "unknown"):
            try:
                gr = requests.post(
                    gateway_base + '/v1/audio/gender',
                    json={'url': sample_url},
                    headers=headers,
                    timeout=120,
                )
                if int(getattr(gr, 'status_code', 0) or 0) == 200:
                    gj = {}
                    try:
                        gj = gr.json()
                    except Exception:
                        gj = {}
                    if isinstance(gj, dict) and gj.get('ok'):
                        g = str(gj.get('gender') or 'unknown').strip().lower()
                        if g in ('male','female'):
                            out_traits['gender'] = g
            except Exception:
                pass

        # 2b) heuristic fallback (pitch-based) if still unknown.
        if out_traits["gender"] in ("", "unknown"):
            try:
                f0 = (measured.get('features') or {}).get('f0_hz_median')
                f0v = float(f0) if f0 is not None else None
                if f0v is not None:
                    # Very rough heuristic: voices with f0 median above ~170Hz tend to be perceived as female.
                    out_traits['gender'] = 'female' if f0v >= 170.0 else 'male'
                    measured['gender_estimated_from_f0'] = True
            except Exception:
                pass

        # 3) curated tortoise voice hint
        if out_traits["gender"] in ("", "unknown") and engine == 'tortoise':
            try:
                k = (tortoise_voice or voice_ref or '').strip().lower()
                g = _TORTOISE_GENDER_HINTS.get(k)
                if g:
                    out_traits['gender'] = str(g).strip().lower()[:16]
            except Exception:
                pass

        # Persist
        _set_voice_traits_json(voice_id, out_traits, measured=measured)
        return {"ok": True, "voice_traits": out_traits, "measured": measured}
    except Exception as e:
        return {"ok": False, "error": f"llm_failed: {type(e).__name__}: {str(e)[:160]}", "measured": measured}
