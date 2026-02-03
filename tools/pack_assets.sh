#!/usr/bin/env bash
set -euo pipefail

OUT="${1:-assets.tar.gz}"

# Pack audio subfolders + credits; exclude narrators (currently empty) if desired
# We pack the *contents* of assets/ (so fetch extracts into assets/ directly)

tar -czf "$OUT" -C assets .
echo "Wrote $OUT"
