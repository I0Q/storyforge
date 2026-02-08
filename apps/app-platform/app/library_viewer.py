from __future__ import annotations

import html
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from .db import db_connect, db_init
from .library_db import get_story_db


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
            [f"<span class='pill' style='margin-right:6px'>{html.escape(str(t))}</span>" for t in tags]
        )

        chars_lines = []
        for c in chars:
            nm = c.get("name") or c.get("id") or ""
            ty = c.get("type") or ""
            desc = c.get("description") or ""
            line = f"- {nm}{(' ('+ty+')') if ty else ''}{(': '+desc) if desc else ''}"
            chars_lines.append(line)

        body = "\n".join(
            [
                "<div class='top'>",
                "  <div>",
                f"    <h1>{html.escape(str(meta.get('title') or story_id))}</h1>",
                f"    <div class='muted'><span class='pill'>{html.escape(story_id)}</span></div>",
                "  </div>",
                "  <div class='row'>",
                "    <a href='/library'><button class='secondary'>Back</button></a>",
                f"    <a href='/library/story/{html.escape(story_id)}'><button>Edit</button></a>",
                "  </div>",
                "</div>",
                "",
                "<div class='card'>",
                "  <div class='muted'>Description</div>",
                f"  <div style='font-weight:950;margin-top:4px'>{html.escape(str(meta.get('description') or '—'))}</div>",
                "  <div class='muted' style='margin-top:10px'>Tags</div>",
                f"  <div style='margin-top:8px'>{tag_html or '—'}</div>",
                "</div>",
                "",
                "<div class='card'>",
                "  <div style='font-weight:950'>Characters</div>",
                f"  <pre style='white-space:pre-wrap;margin-top:10px'>{html.escape(chr(10).join(chars_lines) if chars_lines else '—')}</pre>",
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

        # reuse the same base styling as the editor pages by importing their _html_page
        from .library_pages import _html_page  # local import to avoid cycles

        return _html_page("StoryForge - Story", body)
