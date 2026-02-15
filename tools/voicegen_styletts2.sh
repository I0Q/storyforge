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

echo "styletts2_not_implemented ref=$REF" >&2
exit 3
