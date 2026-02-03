#!/usr/bin/env bash
set -euo pipefail

BUCKET="${STORYFORGE_ASSETS_BUCKET:-storyforge-assets}"
REGION="${STORYFORGE_ASSETS_REGION:-sfo3}"
PREFIX="${STORYFORGE_ASSETS_PREFIX:-assets}"
OUTDIR="${STORYFORGE_ASSETS_OUTDIR:-assets}"

ENDPOINT="https://${REGION}.digitaloceanspaces.com"

if ! command -v aws >/dev/null; then
  echo "ERROR: awscli not installed. Install awscli first." >&2
  exit 1
fi

mkdir -p "$OUTDIR"

echo "Syncing Storyforge assets from DigitalOcean Spaces (public)..."
echo "  s3://${BUCKET}/${PREFIX} -> ${OUTDIR}"

aws --endpoint-url "$ENDPOINT" s3 sync "s3://${BUCKET}/${PREFIX}" "$OUTDIR" --no-sign-request

echo "Done."
