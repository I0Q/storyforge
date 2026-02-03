#!/usr/bin/env bash
set -euo pipefail

# Local-only voice generation using XTTS v2 inside a Docker container.
#
# Usage:
#   tools/voicegen_xtts.sh --text "Hello" --ref /path/to/ref.wav --out out.wav
#
# Notes:
# - First run will download the XTTS model into the docker volume cache.

MODEL_NAME="tts_models/multilingual/multi-dataset/xtts_v2"
IMAGE="i0q-storyforge-voicegen:latest"
CACHE_VOL="storyforge_tts_cache"

TEXT=""
REF=""
OUT=""
LANG="en"
DEVICE="auto"  # auto|cpu|cuda

while [[ $# -gt 0 ]]; do
  case "$1" in
    --text) TEXT="$2"; shift 2;;
    --ref) REF="$2"; shift 2;;
    --out) OUT="$2"; shift 2;;
    --lang) LANG="$2"; shift 2;;
    --device) DEVICE="$2"; shift 2;;
    *) echo "Unknown arg: $1"; exit 2;;
  esac
done

if [[ -z "$TEXT" || -z "$REF" || -z "$OUT" ]]; then
  echo "Usage: $0 --text <text> --ref <ref.wav> --out <out.wav> [--lang en] [--device auto|cpu|cuda]" >&2
  exit 2
fi

if [[ ! -f "$REF" ]]; then
  echo "Missing ref wav: $REF" >&2
  exit 2
fi

mkdir -p "$(dirname "$OUT")"

# GPU passthrough if available
GPU_ARGS=()
if [[ "$DEVICE" == "cuda" || "$DEVICE" == "auto" ]]; then
  # Works if nvidia-container-toolkit is installed; otherwise docker will ignore.
  GPU_ARGS+=(--gpus all)
fi

# Build image if missing
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Building voicegen image..." >&2
  docker build -t "$IMAGE" -f docker/voicegen/Dockerfile .
fi

# Run

docker run --rm \
  "${GPU_ARGS[@]}" \
  -v "$CACHE_VOL:/root/.local/share/tts" \
  -v "$(pwd):/work" \
  -v "$(cd "$(dirname "$REF")" && pwd):/in" \
  -v "$(cd "$(dirname "$OUT")" && pwd):/out" \
  -w /work \
  "$IMAGE" \
  docker run
import os
from TTS.api import TTS

text = os.environ['TEXT']
ref = os.environ['REF']
out = os.environ['OUT']
lang = os.environ.get('LANG','en')
model = os.environ.get('MODEL')

# Select device
want = os.environ.get('DEVICE','auto')
try:
    import torch
    has_cuda = torch.cuda.is_available()
except Exception:
    has_cuda = False

if want == 'cuda':
    device = 'cuda'
elif want == 'cpu':
    device = 'cpu'
else:
    device = 'cuda' if has_cuda else 'cpu'

print('device', device)

tts = TTS(model)
tts.to(device)
tts.tts_to_file(text=text, speaker_wav=ref, language=lang, file_path=out)
print('wrote', out)
PY
