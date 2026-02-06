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

audio = tts.tts_with_preset(
    text,
    voice_samples=voice_samples,
    conditioning_latents=conditioning_latents,
    preset=preset,
)

torchaudio.save(out_path, audio.squeeze(0).cpu(), 24000)
print("wrote", out_path)

PY
