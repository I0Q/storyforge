from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    # In App Platform, the working tree layout can differ. Walk upward and
    # find the repo root by locating a `stories/` folder (preferred) or `.git/`.
    for parent in [p.parent, *p.parents]:
        try:
            if (parent / "stories").exists():
                return parent
            if (parent / ".git").exists():
                return parent
        except Exception:
            pass
    # Fallback to a reasonable default.
    return p.parents[3]


def _stories_dir() -> Path:
    p = os.environ.get("STORYFORGE_STORIES_DIR")
    if p:
        return Path(p).expanduser().resolve()
    return (_repo_root() / "stories").resolve()


def _safe_id(s: str) -> bool:
    # very conservative
    return bool(s) and all(c.isalnum() or c in ("-", "_") for c in s)


def _load_yaml(p: Path) -> dict[str, Any]:
    if not p.exists():
        return {}
    data = yaml.safe_load(p.read_text("utf-8"))
    return data if isinstance(data, dict) else {}


def list_stories() -> list[dict[str, Any]]:
    root = _stories_dir()
    if not root.exists():
        return []

    out: list[dict[str, Any]] = []
    for d in sorted([x for x in root.iterdir() if x.is_dir()], key=lambda p: p.name):
        sid = d.name
        if not _safe_id(sid):
            continue
        meta = _load_yaml(d / "meta.yaml")
        out.append(
            {
                "id": sid,
                "title": str(meta.get("title") or sid),
                "description": str(meta.get("description") or ""),
                "tags": meta.get("tags") or [],
            }
        )

    # newest-ish first if meta has updated_at/created_at later; otherwise alphabetical
    return out


def get_story(story_id: str) -> dict[str, Any]:
    if not _safe_id(story_id):
        raise FileNotFoundError("invalid story id")

    d = _stories_dir() / story_id
    if not d.exists() or not d.is_dir():
        raise FileNotFoundError("not found")

    meta = _load_yaml(d / "meta.yaml")
    chars = _load_yaml(d / "characters.yaml")
    story_md = (d / "story.md").read_text("utf-8") if (d / "story.md").exists() else ""

    return {
        "id": story_id,
        "meta": {
            "id": meta.get("id") or story_id,
            "title": meta.get("title") or story_id,
            "description": meta.get("description") or "",
            "tags": meta.get("tags") or [],
        },
        "characters": chars.get("characters") or [],
        "story_md": story_md,
    }
