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
                f"<span class='pill tagPill' style='margin-right:6px'>{html.escape(str(t))}</span>"
                for t in tags
            ]
        )

        # character cards
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
                "<div class='charCard'>"
                f"<div class='sw' style='background:{color}'></div>"
                "<div class='cbody'>"
                f"<div class='cname'>{html.escape(nm)}{pill}</div>"
                f"{desc_html}"
                "</div></div>"
            )

        chars_html = (
            "<div style='margin-top:10px'>" + "".join(char_cards) + "</div>"
            if char_cards
            else "<div class='muted'>—</div>"
        )

        title_txt = html.escape(str(meta.get("title") or story_id))
        tags_csv = html.escape(", ".join([str(t) for t in tags]))
        story_md_esc = html.escape(story_md)
        rendered = _render_md_simple(story_md)

        js = f"""
<script>
window.__STORY_ID = {story_id!r};

function $(id){{ return document.getElementById(id); }}
var saveTimer = null;
var saving = false;

function setStatus(t){{ var el=$('saveStatus'); if (el) el.textContent=t; }}

function escapeHtml(s){{
  return String(s)
    .replaceAll('&','&amp;')
    .replaceAll('<','&lt;')
    .replaceAll('>','&gt;');
}}

function parseTags(s){{
  return (s||'').split(',').map(function(x){{return x.trim();}}).filter(Boolean);
}}

function renderTagPills(tags){{
  if (!tags.length) return '—';
  return tags.map(function(t){{
    return "<span class='pill tagPill' style='margin-right:6px'>" + escapeHtml(t) + "</span>";
  }}).join(' ');
}}

function renderMdSimple(md){{
  var lines = String(md||'').split('\n');
  var out=[];
  for (var i=0;i<lines.length;i++){{
    var line=lines[i];
    if (line.startsWith('### ')) out.push('<h3>'+escapeHtml(line.slice(4))+'</h3>');
    else if (line.startsWith('## ')) out.push('<h2>'+escapeHtml(line.slice(3))+'</h2>');
    else if (line.startsWith('# ')) out.push('<h1>'+escapeHtml(line.slice(2))+'</h1>');
    else if (line.trim()==='') out.push('');
    else out.push('<p>'+escapeHtml(line)+'</p>');
  }}
  return out.join('\n');
}}

function scheduleSave(ms){{
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(doSave, ms||600);
  setStatus('Pending…');
}}

function doDelete(){{
  if (!confirm('Delete this story?')) return;
  setStatus('Deleting…');
  fetch('/api/library/story/' + encodeURIComponent(window.__STORY_ID), {{method:'DELETE'}})
    .then(function(r){{ return r.json().catch(function(){{return {{ok:false}};}}); }})
    .then(function(j){{ if (j.ok){{ window.location.href='/?tab=library'; }} else {{ setStatus('Error'); }} }})
    .catch(function(_e){{ setStatus('Error'); }});
}}

function doSave(){{
  if (saving) return;
  saving = true;
  setStatus('Saving…');

  var payload = {{
    title: ($('titleInput') ? $('titleInput').value : ''),
    tags: parseTags($('tagsInput') ? $('tagsInput').value : ''),
    story_md: ($('mdCode') ? $('mdCode').value : '')
  }};

  fetch('/api/library/story/' + encodeURIComponent(window.__STORY_ID), {{
    method: 'PUT',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(payload)
  }}).then(function(r){{
    return r.json().catch(function(){{ return {{ok:false,error:'bad_json'}}; }});
  }}).then(function(j){{
    if (!j.ok){{ setStatus('Error'); saving=false; return; }}
    if ($('titleText')) $('titleText').textContent = payload.title || window.__STORY_ID;
    if ($('tagsPills')) $('tagsPills').innerHTML = renderTagPills(payload.tags);
    // if we're in rendered mode, refresh HTML too
    if ($('mdRender') && $('mdCode') && !$('mdCode').classList.contains('hide')){{
      // in code mode, don't touch rendered
    }} else if ($('mdRender') && $('mdCode')){{
      $('mdRender').innerHTML = renderMdSimple(payload.story_md);
    }}
    setStatus('Saved');
    saving=false;
  }}).catch(function(_e){{
    setStatus('Error');
    saving=false;
  }});
}}

function toggleMd(){{
  var r=$('mdRender');
  var c=$('mdCode');
  var b=$('mdBtn');
  if (!r||!c||!b) return;
  var codeVisible = !c.classList.contains('hide');
  if (codeVisible){{
    // code -> render
    try{{ r.innerHTML = renderMdSimple(c.value); }}catch(_e){{}}
    c.classList.add('hide');
    r.classList.remove('hide');
    b.textContent='Show code';
  }} else {{
    // render -> code
    r.classList.add('hide');
    c.classList.remove('hide');
    b.textContent='Render';
    try{{ c.focus(); }}catch(_e){{}}
  }}
}}

function enableInlineEdit(textId, editId, inputId){{
  var t=$(textId), e=$(editId), inp=$(inputId);
  if (!t||!e||!inp) return;
  t.addEventListener('click', function(){{
    t.classList.add('hide');
    e.classList.remove('hide');
    try{{ inp.focus(); inp.select(); }}catch(_e){{}}
  }});
  inp.addEventListener('blur', function(){{
    e.classList.add('hide');
    t.classList.remove('hide');
    scheduleSave(10);
  }});
  inp.addEventListener('input', function(){{ scheduleSave(800); }});
}}

enableInlineEdit('titleText','titleEdit','titleInput');

if ($('tagsPills')) $('tagsPills').addEventListener('click', function(){{
  $('tagsPills').classList.add('hide');
  $('tagsEdit').classList.remove('hide');
  try{{ $('tagsInput').focus(); $('tagsInput').select(); }}catch(_e){{}}
}});

if ($('tagsInput')) {{
  $('tagsInput').addEventListener('blur', function(){{
    $('tagsEdit').classList.add('hide');
    $('tagsPills').classList.remove('hide');
    scheduleSave(10);
  }});
  $('tagsInput').addEventListener('input', function(){{ scheduleSave(800); }});
}}

if ($('mdCode')) {{
  $('mdCode').addEventListener('input', function(){{ scheduleSave(1200); }});
  $('mdCode').addEventListener('blur', function(){{ scheduleSave(10); }});
}}
</script>
"""

        body = "\n".join(
            [
                "<div class='top'>",
                "  <div style='min-width:0'>",
                f"    <h1 id='titleText' style='cursor:pointer'>{title_txt}</h1>",
                "    <div id='titleEdit' class='hide' style='margin-top:8px'>",
                f"      <input id='titleInput' value='{title_txt}' />",
                "    </div>",
                f"    <div class='muted'><span class='pill'>{html.escape(story_id)}</span></div>",
                "  </div>",
                "  <div class='row'>",
                "    <a href='/?tab=library'><button class='secondary' type='button'>Back</button></a>",
                "    <button class='danger' type='button' onclick=\"doDelete()\">Delete</button>",
                "  </div>",
                "</div>",
                "",
                "<div class='card'>",
                "  <div class='row' style='justify-content:space-between;'>",
                "    <div>",
                "      <div class='muted'>Tags</div>",
                f"      <div id='tagsPills' style='margin-top:8px;cursor:pointer'>{tag_html or '—'}</div>",
                "      <div id='tagsEdit' class='hide' style='margin-top:8px'>",
                f"        <input id='tagsInput' value='{tags_csv}' placeholder='bedtime, calm' />",
                "        <div class='muted' style='margin-top:6px'>Comma-separated</div>",
                "      </div>",
                "    </div>",
                "    <div class='muted' id='saveStatus'>Saved</div>",
                "  </div>",
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
                f"  <div id='mdRender' style='margin-top:10px;line-height:1.6'>{rendered}</div>",
                f"  <textarea id='mdCode' class='term hide' style='width:100%;min-height:260px;margin-top:10px;white-space:pre-wrap;line-height:1.4'>{story_md_esc}</textarea>",
                "</div>",
                "",
                "<style>",
                ".hide{display:none}",
                ".charCard{display:flex;gap:10px;align-items:flex-start;border:1px solid var(--line);border-radius:14px;padding:10px;background:#0b1020;margin-top:8px}",
                ".charCard .sw{width:18px;height:18px;border-radius:6px;flex:0 0 auto;margin-top:3px}",
                ".charCard .cname{font-weight:950}",
                ".charCard .cbody{min-width:0}",
                "</style>",
                js,
            ]
        )

        from .library_pages import _html_page  # local import to avoid cycles
        return _html_page("StoryForge - Story", body)
