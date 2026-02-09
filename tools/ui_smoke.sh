#!/usr/bin/env bash
set -euo pipefail

# UI smoke test runner (dev-only)
# Usage:
#   export SF_TODO_TOKEN=...   # required
#   export SF_BASE_URL=https://storyforge.i0q.com   # optional
#   ./tools/ui_smoke.sh

python3 -m venv .venv-ui-smoke >/dev/null 2>&1 || true
source .venv-ui-smoke/bin/activate

pip -q install -r requirements-dev.txt
python -m playwright install chromium >/dev/null

pytest -q

echo "\nArtifacts saved under ui_artifacts/"
