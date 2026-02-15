#!/usr/bin/env bash
set -euo pipefail

# StyleTTS2 wrapper (placeholder v0)
# Contract matches other voicegen scripts:
#   --text <text> --ref <voiceRef> --out <wavPath> [--gpu N] [--seed N]
#
# voiceRef formats supported (planned):
#   styletts2:<model_id>           (local model folder)
#   styletts2_url:https://...      (download + cache)
#

TEXT=""
REF=""
OUT=""
GPU=""
SEED=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --text) TEXT="$2"; shift 2;;
    --ref) REF="$2"; shift 2;;
    --out) OUT="$2"; shift 2;;
    --gpu) GPU="$2"; shift 2;;
    --seed) SEED="$2"; shift 2;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done

if [[ -z "$TEXT" || -z "$REF" || -z "$OUT" ]]; then
  echo "usage: $0 --text <text> --ref <voiceRef> --out <wavPath> [--gpu N] [--seed N]" >&2
  exit 2
fi

# Resolve styletts2 voice refs.
# - styletts2:<model_id>  -> /raid/styletts2_models/<model_id>
# - styletts2_url:<path>  -> cached asset file (zip). (extraction TBD)
MODELS_DIR="${STYLETT2_MODELS_DIR:-/raid/styletts2_models}"
REPO_DIR="${STYLETT2_REPO_DIR:-/raid/styletts2/StyleTTS2}"

# GPU mapping (same pattern as tortoise wrapper)
if [[ -n "$GPU" ]]; then
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

# Use the known-good torch+cuda env (same as tortoise_pip)
PY=/raid/storyforge_envs/micromamba_root/envs/tortoise_pip/bin/python

# Scaffold runner will currently write a short silent wav so we can test full plumbing.
$PY /raid/storyforge_test/tools/styletts2_runner.py --repo "$REPO_DIR" --text "$TEXT" --voice_ref "$REF" --out "$OUT"
