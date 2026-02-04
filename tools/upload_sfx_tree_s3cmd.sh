#!/usr/bin/env bash
set -euo pipefail

# Upload Storyforge SFX tree + credits index to DigitalOcean Spaces.
# Requires s3cmd and a local config file (git-ignored): tools/s3cfg_storyforge

CFG="tools/s3cfg_storyforge"
BUCKET="${STORYFORGE_ASSETS_BUCKET:-storyforge-assets}"
REGION="${STORYFORGE_ASSETS_REGION:-sfo3}"
ENDPOINT="${REGION}.digitaloceanspaces.com"

if ! command -v s3cmd >/dev/null; then
  echo "ERROR: s3cmd not installed" >&2
  exit 1
fi

if [[ ! -f "$CFG" ]]; then
  echo "ERROR: Missing $CFG (expected local s3cmd config with Spaces creds)" >&2
  exit 1
fi

# SFX
echo "Uploading SFX -> s3://${BUCKET}/assets/sfx/"
s3cmd -c "$CFG" sync --acl-public --no-mime-magic --guess-mime-type \
  "assets/sfx/" "s3://${BUCKET}/assets/sfx/"

# Credits index
echo "Uploading credits index -> s3://${BUCKET}/assets/credits/index.jsonl"
s3cmd -c "$CFG" put --acl-public --no-mime-magic --guess-mime-type \
  "assets/credits/index.jsonl" "s3://${BUCKET}/assets/credits/index.jsonl"

echo "Done. Public base: https://${BUCKET}.${ENDPOINT}/assets/"
