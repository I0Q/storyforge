#!/usr/bin/env bash
set -euo pipefail

# Upload assets.tar.gz to a DigitalOcean Spaces bucket using s3cmd.
# Requires env vars:
#   STORYFORGE_SPACES_KEY
#   STORYFORGE_SPACES_SECRET
# Optional:
#   STORYFORGE_ASSETS_BUCKET (default storyforge-assets)
#   STORYFORGE_ASSETS_REGION (default sfo3)
#   STORYFORGE_ASSETS_OBJECT (default assets.tar.gz)

: "${STORYFORGE_SPACES_KEY:?missing STORYFORGE_SPACES_KEY}"
: "${STORYFORGE_SPACES_SECRET:?missing STORYFORGE_SPACES_SECRET}"

BUCKET="${STORYFORGE_ASSETS_BUCKET:-storyforge-assets}"
REGION="${STORYFORGE_ASSETS_REGION:-sfo3}"
OBJECT_KEY="${STORYFORGE_ASSETS_OBJECT:-assets.tar.gz}"

ENDPOINT="${REGION}.digitaloceanspaces.com"

if ! command -v s3cmd >/dev/null; then
  echo "ERROR: s3cmd not installed" >&2
  exit 1
fi

# Build assets tarball if not present
if [ ! -f "/tmp/${OBJECT_KEY}" ]; then
  ./tools/pack_assets.sh "/tmp/${OBJECT_KEY}"
fi

CFG=$(mktemp -t storyforge-s3cfg-XXXXXX)
trap 'rm -f "$CFG"' EXIT

cat > "$CFG" <<CFG
[default]
access_key = ${STORYFORGE_SPACES_KEY}
secret_key = ${STORYFORGE_SPACES_SECRET}
host_base = ${ENDPOINT}
host_bucket = %(bucket)s.${ENDPOINT}
use_https = True
signature_v2 = False
CFG

echo "Uploading /tmp/${OBJECT_KEY} -> s3://${BUCKET}/${OBJECT_KEY}"

s3cmd -c "$CFG" put --acl-public "/tmp/${OBJECT_KEY}" "s3://${BUCKET}/${OBJECT_KEY}"

echo "Uploaded. Public URL: https://${BUCKET}.${ENDPOINT}/${OBJECT_KEY}"
