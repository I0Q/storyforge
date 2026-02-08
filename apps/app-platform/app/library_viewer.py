from __future__ import annotations

import hashlib
import html

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from .db import db_connect, db_init
from .library_db import get_story_db


def _swatch(key: str) -> str:
    h = hashlib.sha256((key or "").encode("utf-8")).hexdigest()
    return "#" + h[:6]


def _render_md_simple(md: str) -> str:
    # safe, tiny renderer (no HTML allowed)
    lines = (md or "").splitlines()
    out: list[str] = []
    for line in lines:
        if line.startswith("### "):
            out.append(f"<h3>{html.escape(line[4:])}</h3>")
        elif line.startswith("## "):
            out.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("# "):
            out.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.strip() == "":
            out.append("")
        else:
            out.append(f"<p>{html.escape(line)}</p>")
    return "\n".join(out)


def register_library_viewer(app: FastAPI) -> None:
    @app.get("/library/story/{story_id}/view", response_class=HTMLResponse)
    def library_story_view(story_id: str):
        conn = db_connect()
        try:
            db_init(conn)
            st = get_story_db(conn, story_id)
        finally:
            conn.close()

        meta = st.get("meta") or {}
        tags = list(meta.get("tags") or [])
        story_md = st.get("story_md") or ""
        chars = st.get("characters") or []

        tag_html = "".join(
            [
                f"<span class='pill' style='margin-right:6px'>{html.escape(str(t))}</span>"
                for t in tags
            ]
        )

        char_cards = []
        for c in chars:
            cid = str(c.get("id") or c.get("name") or "")
            nm = str(c.get("name") or c.get("id") or "")
            desc = str(c.get("description") or "")
            ty = str(c.get("type") or "")
            color = _swatch(cid)

            pill = (
                f" <span class='pill' style='margin-left:6px'>{html.escape(ty)}</span>"
                if ty
                else ""
            )
            desc_html = (
                f"<div class='muted' style='margin-top:4px'>{html.escape(desc)}</div>"
                if desc
                else ""
            )
            char_cards.append(
                "<div style='display:flex;gap:10px;align-items:flex-start;"
                "border:1px solid var(--line);border-radius:14px;padding:10px;"
                "background:#0b1020;margin-top:8px'>"
                f"<div style='width:18px;height:18px;border-radius:6px;background:{color};"
                "flex:0 0 auto;margin-top:3px'></div>"
                "<div style='min-width:0'>"
                f"<div style='font-weight:950'>{html.escape(nm)}{pill}</div>"
                f"{desc_html}"
                "</div></div>"
            )

        chars_html = (
            "<div style='margin-top:10px'>" + "".join(char_cards) + "</div>"
            if char_cards
            else "<div class='muted'>—</div>"
        )

        body = "\n".join(
            [
                "<div class='top'>",
                "  <div>",
                f"    <h1>{html.escape(str(meta.get('title') or story_id))}</h1>",
                f"    <div class='muted'><span class='pill'>{html.escape(story_id)}</span></div>",
                "  </div>",
                "  <div class='row'>",
                "    <a href='/?tab=library'><button class='secondary'>Back</button></a>",
                f"    <a href='/library/story/{html.escape(story_id)}'><button>Edit</button></a>",
                "  </div>",
                "</div>",
                "",
                "<div class='card'>",
                "  <div class='muted' style='margin-top:10px'>Tags</div>",
                f"  <div style='margin-top:8px'>{tag_html or '—'}</div>",
                "</div>",
                "",
                "<div class='card'>",
                "  <div style='font-weight:950'>Characters</div>",
                f"  {chars_html}",
                "</div>",
                "",
                "<div class='card'>",
                "  <div class='row' style='justify-content:space-between;'>",
                "    <div style='font-weight:950'>Story</div>",
                "    <button class='secondary' onclick=\"toggleMd()\" type='button' id='mdBtn'>Show code</button>",
                "  </div>",
                f"  <div id='mdRender' style='margin-top:10px;line-height:1.6'>{_render_md_simple(story_md)}</div>",
                f"  <pre id='mdCode' style='display:none;white-space:pre-wrap;line-height:1.5;margin-top:10px'>{html.escape(story_md)}</pre>",
                "</div>",
                "",
                "<script>",
                "function toggleMd(){",
                "  var r=document.getElementById('mdRender');",
                "  var c=document.getElementById('mdCode');",
                "  var b=document.getElementById('mdBtn');",
                "  if (!r||!c||!b) return;",
                "  var showing = (c.style.display !== 'none');",
                "  if (showing){",
                "    c.style.display='none'; r.style.display='block'; b.textContent='Show code';",
                "  }else{",
                "    r.style.display='none'; c.style.display='block'; b.textContent='Render';",
                "  }",
                "}",
                "</script>",
            ]
        )

        from .library_pages import _html_page  # local import to avoid cycles

        return _html_page("StoryForge - Story", body)
