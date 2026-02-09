from __future__ import annotations

import os
import time
import uuid
from typing import Tuple


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def spaces_enabled() -> bool:
    return bool(_env("SPACES_KEY") and _env("SPACES_SECRET") and _env("SPACES_BUCKET") and _env("SPACES_REGION"))


def _client():
    import boto3

    region = _env("SPACES_REGION")
    endpoint = _env("SPACES_ENDPOINT") or f"https://{region}.digitaloceanspaces.com"

    return boto3.client(
        "s3",
        region_name=region,
        endpoint_url=endpoint,
        aws_access_key_id=_env("SPACES_KEY"),
        aws_secret_access_key=_env("SPACES_SECRET"),
    )


def upload_bytes(data: bytes, key_prefix: str, filename: str, content_type: str) -> Tuple[str, str]:
    """Upload bytes to Spaces. Returns (object_key, public_url)."""
    if not spaces_enabled():
        raise RuntimeError("spaces_not_configured")

    bucket = _env("SPACES_BUCKET")
    public_base = _env("SPACES_PUBLIC_BASE")  # e.g. https://storyforge-assets.nyc3.digitaloceanspaces.com
    if not public_base:
        # Fall back to virtual-host style
        region = _env("SPACES_REGION")
        public_base = f"https://{bucket}.{region}.digitaloceanspaces.com"

    ext = ""
    if "." in (filename or ""):
        ext = "." + filename.rsplit(".", 1)[1].lower()
        if len(ext) > 12:
            ext = ""

    obj_key = f"{key_prefix.rstrip('/')}/{int(time.time())}-{uuid.uuid4().hex}{ext}"

    c = _client()
    c.put_object(
        Bucket=bucket,
        Key=obj_key,
        Body=data,
        ACL="public-read",
        ContentType=content_type or "application/octet-stream",
    )

    return obj_key, f"{public_base.rstrip('/')}/{obj_key}"
