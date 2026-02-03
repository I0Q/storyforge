#!/usr/bin/env bash
set -euo pipefail

BUCKET="${STORYFORGE_ASSETS_BUCKET:-storyforge-assets}"
REGION="${STORYFORGE_ASSETS_REGION:-sfo3}"
OBJECT_KEY="${STORYFORGE_ASSETS_OBJECT:-assets.tar.gz}"
OUTDIR="${STORYFORGE_ASSETS_OUTDIR:-assets}"

URL="https://${BUCKET}.${REGION}.digitaloceanspaces.com/${OBJECT_KEY}"

mkdir -p "$OUTDIR"

tmp=$(mktemp -t storyforge-assets-XXXXXX.tar.gz)
trap 'rm -f "$tmp"' EXIT

echo "Downloading assets archive: $URL"

if command -v curl >/dev/null; then
  curl -fL --retry 3 --retry-delay 2 -o "$tmp" "$URL"
elif command -v wget >/dev/null; then
  wget -O "$tmp" "$URL"
else
  echo "ERROR: need curl or wget" >&2
  exit 1
fi

echo "Extracting into: $OUTDIR"
tar -xzf "$tmp" -C "$OUTDIR"

echo "Done."
