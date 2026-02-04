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
REF=""
OUT=""
LANG="en"
DEVICE="auto"  # auto|cpu|cuda
GPU_ID=""       # optional integer id for multi-GPU pinning

while [[ $# -gt 0 ]]; do
  case "$1" in
    --text) TEXT="$2"; shift 2;;
    --ref) REF="$2"; shift 2;;
    --out) OUT="$2"; shift 2;;
    --lang) LANG="$2"; shift 2;;
    --device) DEVICE="$2"; shift 2;;
    --gpu) GPU_ID="$2"; shift 2;;
    *) echo "Unknown arg: $1"; exit 2;;
  esac
done

if [[ -z "$TEXT" || -z "$REF" || -z "$OUT" ]]; then
  echo "Usage: $0 --text <text> --ref <ref.wav> --out <out.wav> [--lang en] [--device auto|cpu|cuda] [--gpu N]" >&2
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

REF_BASENAME="$(basename "$REF")"
OUT_BASENAME="$(basename "$OUT")"

# Run

docker run --rm -i \
  "${GPU_ARGS[@]}" \
  -e COQUI_TOS_AGREED=1 \
  -e TEXT="$TEXT" \
  -e LANG="$LANG" \
  -e MODEL="$MODEL_NAME" \
  -e DEVICE="$DEVICE" \
  -e REF="/in/${REF_BASENAME}" \
  -e OUT="/out/${OUT_BASENAME}" \
  -v "$CACHE_VOL:/root/.local/share/tts" \
  -v "$(pwd):/work" \
  -v "$(cd "$(dirname "$REF")" && pwd):/in" \
  -v "$(cd "$(dirname "$OUT")" && pwd):/out" \
  -w /work \
  "$IMAGE" \
  python - <<'PY'
import os

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
ref = os.environ['REF']
out = os.environ['OUT']
lang = os.environ.get('LANG','en')
model = os.environ.get('MODEL')

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

print('device', device)

# Create model and synthesize

tts = TTS(model)
tts.to(device)
# Mode A: keep coherence on longer text; rely on XTTS punctuation handling.
tts.tts_to_file(text=text, speaker_wav=ref, language=lang, file_path=out, split_sentences=False)
print('wrote', out)
PY
