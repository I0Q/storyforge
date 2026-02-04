#!/usr/bin/env bash
set -euo pipefail

# Local-only voice generation using XTTS v2 inside a Docker container.
#
# Usage:
#   tools/voicegen_xtts.sh --text "Hello" --ref /path/to/ref.wav --out out.wav
#
# Notes:
# - First run will download the XTTS model into a docker volume cache.

MODEL_NAME="tts_models/multilingual/multi-dataset/xtts_v2"
IMAGE="i0q-storyforge-voicegen:latest"
CACHE_VOL="storyforge_tts_cache"

TEXT=""
REF=""      # single ref OR comma-separated list
OUT=""
LANG="en"
DEVICE="auto"  # auto|cpu|cuda
GPU_ID=""       # optional integer id for multi-GPU pinning
SEED=""         # optional integer seed for deterministic voice

while [[ $# -gt 0 ]]; do
  case "$1" in
    --text) TEXT="$2"; shift 2;;
    --ref) REF="$2"; shift 2;;
    --out) OUT="$2"; shift 2;;
    --lang) LANG="$2"; shift 2;;
    --device) DEVICE="$2"; shift 2;;
    --gpu) GPU_ID="$2"; shift 2;;
    --seed) SEED="$2"; shift 2;;
    *) echo "Unknown arg: $1"; exit 2;;
  esac
done

if [[ -z "$TEXT" || -z "$REF" || -z "$OUT" ]]; then
  echo "Usage: $0 --text <text> --ref <ref.wav> --out <out.wav> [--lang en] [--device auto|cpu|cuda] [--gpu N] [--seed N]" >&2
  exit 2
fi

# Support comma-separated refs
IFS=',' read -r -a REF_LIST <<<"$REF"
REF_LIST=("${REF_LIST[@]/#/}")

REF0="${REF_LIST[0]}"
if [[ ! -f "$REF0" ]]; then
  echo "Missing ref wav: $REF0" >&2
  exit 2
fi

REF_DIR="$(cd "$(dirname "$REF0")" && pwd)"
for r in "${REF_LIST[@]}"; do
  rr="$(echo "$r" | xargs)"
  if [[ -z "$rr" ]]; then continue; fi
  if [[ ! -f "$rr" ]]; then
    echo "Missing ref wav: $rr" >&2
    exit 2
  fi
  # Require all refs to live in same directory for clean docker mounting
  if [[ "$(cd "$(dirname "$rr")" && pwd)" != "$REF_DIR" ]]; then
    echo "All refs for a speaker must be in the same directory. Got: $REF0 and $rr" >&2
    exit 2
  fi
done

mkdir -p "$(dirname "$OUT")"

# GPU passthrough if available
GPU_ARGS=()
if [[ "$DEVICE" == "cuda" || "$DEVICE" == "auto" ]]; then
  if [[ -n "$GPU_ID" ]]; then
    GPU_ARGS+=(--gpus "device=${GPU_ID}")
  else
    GPU_ARGS+=(--gpus all)
  fi
fi

# Build image if missing
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Building voicegen image..." >&2
  docker build -t "$IMAGE" -f docker/voicegen/Dockerfile .
fi

# Build /in/ paths for refs
REFS_IN=()
for r in "${REF_LIST[@]}"; do
  rr="$(echo "$r" | xargs)"
  if [[ -z "$rr" ]]; then continue; fi
  REFS_IN+=("/in/$(basename "$rr")")
done
OUT_BASENAME="$(basename "$OUT")"

# Run

docker run --rm -i \
  "${GPU_ARGS[@]}" \
  -e COQUI_TOS_AGREED=1 \
  -e TEXT="$TEXT" \
  -e LANG="$LANG" \
  -e MODEL="$MODEL_NAME" \
  -e DEVICE="$DEVICE" \
  -e SEED="$SEED" \
  -e REFS="$(IFS=','; echo "${REFS_IN[*]}")" \
  -e OUT="/out/${OUT_BASENAME}" \
  -v "$CACHE_VOL:/root/.local/share/tts" \
  -v "$(pwd):/work" \
  -v "$REF_DIR:/in" \
  -v "$(cd "$(dirname "$OUT")" && pwd):/out" \
  -w /work \
  "$IMAGE" \
  python - <<'PY'
import os
import random

import numpy as np

# PyTorch >=2.6 defaults torch.load(weights_only=True), which breaks Coqui XTTS
# checkpoints that contain config objects. We trust the checkpoint source here
# (official model download) and force weights_only=False.
import torch
_orig_torch_load = torch.load

def _torch_load_compat(*args, **kwargs):
    kwargs.setdefault("weights_only", False)
    return _orig_torch_load(*args, **kwargs)

torch.load = _torch_load_compat

from TTS.api import TTS

text = os.environ['TEXT']
refs_env = os.environ.get('REFS','')
refs = [p.strip() for p in refs_env.split(',') if p.strip()]
if not refs:
    raise SystemExit('Missing REFS env')
out = os.environ['OUT']
lang = os.environ.get('LANG','en')
model = os.environ.get('MODEL')
seed = os.environ.get('SEED','')

want = os.environ.get('DEVICE','auto')
try:
    has_cuda = torch.cuda.is_available()
except Exception:
    has_cuda = False

if want == 'cuda':
    device = 'cuda'
elif want == 'cpu':
    device = 'cpu'
else:
    device = 'cuda' if has_cuda else 'cpu'

if seed != '':
    s = int(seed)
    random.seed(s)
    np.random.seed(s)
    torch.manual_seed(s)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(s)

print('device', device, 'seed', seed if seed != '' else '(none)')

# Create model and synthesize

tts = TTS(model)
tts.to(device)
# Mode A: keep coherence on longer text; rely on XTTS punctuation handling.
tts.tts_to_file(text=text, speaker_wav=refs, language=lang, file_path=out, split_sentences=False)
print('wrote', out)
PY
