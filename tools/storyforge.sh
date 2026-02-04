#!/usr/bin/env bash
set -euo pipefail

# Run Storyforge without installing the package.
# Usage:
#   ./tools/storyforge.sh render --story out/x.sfml --ref Ruby=...

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"
PYTHONPATH="$REPO_ROOT/src" exec python3 -m storyforge.cli "$@"
