#!/usr/bin/env bash
set -euo pipefail

TEXT=""
REF=""
OUT=""
LANG="en"
DEVICE="cuda"
SEED=""
GPU=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --text) TEXT="$2"; shift 2;;
    --ref) REF="$2"; shift 2;;
    --out) OUT="$2"; shift 2;;
    --lang) LANG="$2"; shift 2;;
    --device) DEVICE="$2"; shift 2;;
    --seed) SEED="$2"; shift 2;;
    --gpu) GPU="$2"; shift 2;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done

if [[ -z "$TEXT" || -z "$REF" || -z "$OUT" ]]; then
  echo "usage: $0 --text <text> --ref <voiceName> --out <wavPath> [--gpu N] [--seed N]" >&2
  exit 2
fi

VOICE="${REF%%,*}"  # take first item


if [[ -n "$GPU" ]]; then
  # Optional GPU map: STORYFORGE_GPU_MAP="1,2,3" maps logical 0->1, 1->2, 2->3
  if [[ -n "${STORYFORGE_GPU_MAP:-}" ]]; then
    IFS="," read -r -a __MAP <<< "${STORYFORGE_GPU_MAP}"
    if [[ "$GPU" =~ ^[0-9]+$ ]] && [[ ${#__MAP[@]} -gt 0 ]]; then
      IDX=$GPU
      if [[ $IDX -ge 0 ]] && [[ $IDX -lt ${#__MAP[@]} ]]; then
        GPU=${__MAP[$IDX]}
      fi
    fi
  fi
  export CUDA_VISIBLE_DEVICES="$GPU"
fi

if [[ -n "$SEED" ]]; then
  export TORTOISE_SEED="$SEED"
fi

TORTOISE_VOICE="$VOICE" \
TORTOISE_TEXT="$TEXT" \
TORTOISE_OUT="$OUT" \
timeout 1200 /raid/storyforge_envs/micromamba_root/envs/tortoise_pip/bin/python - <<"PY"
import os
import random

seed = os.environ.get("TORTOISE_SEED")
if seed:
    random.seed(int(seed))

voice = os.environ["TORTOISE_VOICE"]
text = os.environ["TORTOISE_TEXT"]
out_path = os.environ["TORTOISE_OUT"]

preset = os.environ.get("TORTOISE_PRESET", "standard")

import torchaudio
from tortoise.api import TextToSpeech
from tortoise.utils.audio import load_voice

tts = TextToSpeech(kv_cache=True)
voice_samples, conditioning_latents = load_voice(voice)

# Longform strategy (like tortoise/read.py): split text into chunks, synthesize each, then concatenate.
# We try hard to not split too much: merge small adjacent chunks up to a char budget.
try:
    from tortoise.utils.text import split_and_recombine_text
except Exception:
    split_and_recombine_text = None

chunks = []
if '|' in text:
    chunks = [c.strip() for c in text.split('|') if c.strip()]
elif split_and_recombine_text is not None:
    try:
        chunks = [c.strip() for c in split_and_recombine_text(text) if str(c).strip()]
    except Exception:
        chunks = [text]
else:
    chunks = [text]

# Merge adjacent chunks to reduce over-splitting (default budget ~450 chars)
try:
    budget = int(os.environ.get('TORTOISE_CHUNK_CHARS', os.environ.get('TORTOISE_CHUNK_CHARS_DEFAULT','450')) or '450')
except Exception:
    budget = 450
if budget < 200:
    budget = 200

merged = []
acc = ''
for c in chunks:
    if not acc:
        acc = c
        continue
    if len(acc) + 1 + len(c) <= budget:
        acc = acc + ' ' + c
    else:
        merged.append(acc)
        acc = c
if acc:
    merged.append(acc)
chunks = merged or chunks

import torch

def _score_clip(x):
    # Heuristic: reject NaNs, extreme peaks, extreme silence.
    try:
        if x is None:
            return -1e18
        if torch.isnan(x).any():
            return -1e18
        peak = float(torch.max(torch.abs(x)).item()) if x.numel() else 0.0
        rms = float(torch.sqrt(torch.mean(x.float()*x.float())).item()) if x.numel() else 0.0
        if peak <= 0.0:
            return -1e18
        if peak > 1.2:
            return -1e18
        if rms < 0.001:
            return -1e18
        # prefer moderate rms (avoid blown out noise)
        return -abs(rms - 0.06)
    except Exception:
        return -1e18

try:
    candidates = int(os.environ.get('TORTOISE_CANDIDATES', '1') or '1')
except Exception:
    candidates = 1
if candidates < 1:
    candidates = 1
if candidates > 3:
    candidates = 3

pause_ms = 0
try:
    pause_ms = int(os.environ.get('TORTOISE_CHUNK_PAUSE_MS', '120') or '120')
except Exception:
    pause_ms = 120
if pause_ms < 0:
    pause_ms = 0
if pause_ms > 2000:
    pause_ms = 2000

parts = []
for c in chunks:
    gen = tts.tts_with_preset(
        c,
        voice_samples=voice_samples,
        conditioning_latents=conditioning_latents,
        preset=preset,
        k=candidates,
        use_deterministic_seed=(int(seed) if seed else None),
    )

    # gen: (k,1,S) or (1,S)
    if candidates == 1:
        clip = gen.squeeze(0).cpu()
    else:
        best = None
        best_s = -1e18
        for g in gen:
            gg = g.squeeze(0).cpu()
            sc = _score_clip(gg)
            if sc > best_s:
                best_s = sc
                best = gg
        clip = best if best is not None else gen[0].squeeze(0).cpu()

    parts.append(clip)
    if pause_ms and (len(chunks) > 1):
        # insert silence between chunks
        sil = torch.zeros(int(24000 * (pause_ms/1000.0)), dtype=clip.dtype)
        parts.append(sil)

# Remove trailing silence
while parts and parts[-1].numel() and torch.all(parts[-1] == 0):
    parts.pop()

if not parts:
    raise RuntimeError('no_audio_parts')

audio = parts[0] if len(parts) == 1 else torch.cat(parts, dim=-1)

torchaudio.save(out_path, audio, 24000)
print("wrote", out_path, "parts=", len(parts), "k=", candidates)

PY
