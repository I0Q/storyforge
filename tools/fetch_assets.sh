#!/usr/bin/env bash
set -euo pipefail

# Public, no-auth fetch. Uses credits index as the canonical file list.

BASE="${STORYFORGE_ASSETS_BASE:-https://storyforge-assets.sfo3.digitaloceanspaces.com/assets/}"
OUTDIR="${STORYFORGE_ASSETS_OUTDIR:-.}"

echo "Fetching Storyforge assets over HTTPS..."
echo "  base:   $BASE"
echo "  outdir: $OUTDIR"

python3 ./tools/fetch_assets_http.py --base "$BASE" --outdir "$OUTDIR"

echo "Done."
