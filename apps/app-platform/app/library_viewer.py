from __future__ import annotations

import hashlib
import html

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi import Response

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
    def library_story_view(story_id: str, response: Response):
        response.headers["Cache-Control"] = "no-store"
        conn = db_connect()
        try:
            db_init(conn)
            st = get_story_db(conn, story_id)
        finally:
            conn.close()

        meta = st.get("meta") or {}
        
        story_md = st.get("story_md") or ""
        chars = st.get("characters") or []

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
        story_md_esc = html.escape(story_md)
        rendered = _render_md_simple(story_md)

        js = f"""
<script>
window.__STORY_ID = {story_id!r};

function $(id){{ return document.getElementById(id); }}

// --- Toasts (persist across fast navigation via localStorage) ---
function toastSet(msg, kind, ms){{
  try{{
    localStorage.setItem('sf_toast_msg', String(msg||''));
    localStorage.setItem('sf_toast_kind', String(kind||'info'));
    localStorage.setItem('sf_toast_until', String(Date.now() + (ms||2600)));
  }}catch(e){{}}
}}

function toastShowNow(msg, kind, ms){{
  toastSet(msg, kind, ms);
  try{{ window.__sfToastInit && window.__sfToastInit(); }}catch(e){{}}
}}

function __sfToastInit(){{
  // Create container once
  var el = document.getElementById('sfToast');
  if (!el){{
    el = document.createElement('div');
    el.id = 'sfToast';
    el.style.position='fixed';
    el.style.left='12px';
    el.style.right='12px';
    el.style.bottom='calc(12px + env(safe-area-inset-bottom, 0px))';
    el.style.zIndex='99999';
    el.style.padding='10px 12px';
    el.style.border='1px solid rgba(255,255,255,0.10)';
    el.style.borderRadius='12px';
    el.style.background='rgba(20,22,30,0.96)';
    el.style.backdropFilter='blur(6px)';
    el.style.webkitBackdropFilter='blur(6px)';
    el.style.fontSize='14px';
    el.style.display='none';
    el.style.boxShadow='0 12px 40px rgba(0,0,0,0.35)';
    el.onclick = function(){{ try{{ el.style.display='none'; toastSet('', 'info', 0); }}catch(e){{}} }};
    document.body.appendChild(el);
  }}

  var msg='', kind='info', until=0;
  try{{
    msg = localStorage.getItem('sf_toast_msg') || '';
    kind = localStorage.getItem('sf_toast_kind') || 'info';
    until = parseInt(localStorage.getItem('sf_toast_until') || '0', 10) || 0;
  }}catch(e){{}}

  if (!msg || Date.now() > until){{
    el.style.display='none';
    return;
  }}

  // color accent
  var border = 'rgba(255,255,255,0.10)';
  if (kind==='ok') border='rgba(80,200,120,0.35)';
  else if (kind==='err') border='rgba(255,90,90,0.35)';
  el.style.borderColor = border;

  el.textContent = msg;
  el.style.display = 'block';

  // auto-hide
  if (window.__sfToastTimer) clearTimeout(window.__sfToastTimer);
  window.__sfToastTimer = setTimeout(function(){{
    try{{ el.style.display='none'; }}catch(e){{}}
  }}, Math.max(200, until - Date.now()));
}}
window.__sfToastInit = __sfToastInit;
try{{ document.addEventListener('DOMContentLoaded', __sfToastInit); }}catch(e){{}}
try{{ __sfToastInit(); }}catch(e){{}}

var saveTimer = null;
var saving = false;

function escapeHtml(s){{
  return String(s)
    .replace(/&/g,'&amp;')
    .replace(/</g,'&lt;')
    .replace(/>/g,'&gt;');
}}

function renderMdSimple(md){{
  var lines = String(md||'').split('\\n');
  var out=[];
  for (var i=0;i<lines.length;i++){{
    var line=lines[i];
    if (line.startsWith('### ')) out.push('<h3>'+escapeHtml(line.slice(4))+'</h3>');
    else if (line.startsWith('## ')) out.push('<h2>'+escapeHtml(line.slice(3))+'</h2>');
    else if (line.startsWith('# ')) out.push('<h1>'+escapeHtml(line.slice(2))+'</h1>');
    else if (line.trim()==='') out.push('');
    else out.push('<p>'+escapeHtml(line)+'</p>');
  }}
  return out.join('\\n');
}}

function scheduleSave(ms){{
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(doSave, ms||600);
  
}}

function doDelete(){{
  if (!confirm('Delete this story?')) return;
  
  fetch('/api/library/story/' + encodeURIComponent(window.__STORY_ID), {{method:'DELETE'}})
    .then(function(r){{ return r.json().catch(function(){{return {{ok:false}};}}); }})
    .then(function(j){{ if (j.ok){{ window.location.href='/#tab-library'; }} else {{  }} }})
    .catch(function(_e){{  }});
}}

function doSave(){{
  if (saving) return;
  saving = true;
  

  var payload = {{
    title: ($('titleInput') ? $('titleInput').value : ''),
    story_md: ($('mdCode') ? $('mdCode').value : '')
  }};

  fetch('/api/library/story/' + encodeURIComponent(window.__STORY_ID), {{
    method: 'PUT',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(payload)
  }}).then(function(r){{
    return r.json().catch(function(){{ return {{ok:false,error:'bad_json'}}; }});
  }}).then(function(j){{
    if (!j.ok){{  saving=false; return; }}
    if ($('titleText')) $('titleText').textContent = payload.title || window.__STORY_ID;
    // if we're in rendered mode, refresh HTML too
    if ($('mdRender') && $('mdCode') && !$('mdCode').classList.contains('hide')){{
      // in code mode, don't touch rendered
    }} else if ($('mdRender') && $('mdCode')){{
      $('mdRender').innerHTML = renderMdSimple(payload.story_md);
    }}
    
    toastShowNow('Saved', 'ok', 2600);
    saving=false;
  }}).catch(function(_e){{
    
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

if ($('mdCode')) {{
  $('mdCode').addEventListener('input', function(){{ scheduleSave(1200); }});
  $('mdCode').addEventListener('blur', function(){{ scheduleSave(10); }});
}}
</script>
"""

        body = "\n".join(
            [
                "<div class='navBar'>",
                "  <div class='navInner'>",
                "    <div style='min-width:0'>",
                "      <div class='brandRow'><h1 style='margin:0'>StoryForge</h1><div class='pageName'>Story</div></div>",
                f"      <div class='muted' style='margin-top:2px'><span id='titleText' style='cursor:pointer;font-weight:950'>{title_txt}</span></div>",
                "      <div id='titleEdit' class='hide' style='margin-top:8px'>",
                f"        <input id='titleInput' value='{title_txt}' />",
                "      </div>",
                "    </div>",
                "    <div class='row' style='justify-content:flex-end'>",
                "      <a href='/#tab-library'><button class='secondary' type='button'>Back</button></a>",
                "      <div class='menuWrap'>",
                "        <button class='userBtn' type='button' onclick=\"toggleUserMenu()\" aria-label='User menu'>",
                "          <svg viewBox='0 0 24 24' width='20' height='20' aria-hidden='true' style='stroke:currentColor;fill:none;stroke-width:2'><path stroke-linecap='round' stroke-linejoin='round' d='M20 21a8 8 0 10-16 0'/><path stroke-linecap='round' stroke-linejoin='round' d='M12 11a4 4 0 100-8 4 4 0 000 8z'/></svg>",
                "        </button>",
                "        <div id='topMenu' class='menuCard'>",
                "          <div class='uTop'>",
                "            <div class='uAvatar'><svg viewBox='0 0 24 24' width='18' height='18' aria-hidden='true' style='stroke:currentColor;fill:none;stroke-width:2'><path stroke-linecap='round' stroke-linejoin='round' d='M20 21a8 8 0 10-16 0'/><path stroke-linecap='round' stroke-linejoin='round' d='M12 11a4 4 0 100-8 4 4 0 000 8z'/></svg></div>",
                "            <div><div class='uName'>User</div><div class='uSub'>Admin</div></div>",
                "          </div>",
                "          <div class='uActions'><a href='/logout'><button class='secondary' type='button'>Log out</button></a></div>",
                "        </div>",
                "      </div>",
                                "    </div>",
                "  </div>",
                "</div>",
                "",
                "",
                "<div class='card'>",
                "  <div class='row' style='justify-content:space-between;'>",
                "    <div>",
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
                                "<div class='card'>",
                "  <div class='row' style='justify-content:space-between;align-items:center'>",
                "    <div>",
                "      <div style='font-weight:950'>Danger zone</div>",
                "      <div class='muted'>Delete cannot be undone.</div>",
                "    </div>",
                "    <button class='danger' type='button' onclick=\"doDelete()\">Delete story</button>",
                "  </div>",
                "</div>",
                "",
"</div>",
                "",
                "<style>",
                ".hide{display:none}",
                ".charCard{display:flex;gap:10px;align-items:flex-start;border:1px solid var(--line);border-radius:14px;padding:10px;background:#0b1020;margin-top:8px}",
                ".charCard .sw{width:18px;height:18px;border-radius:6px;flex:0 0 auto;margin-top:3px}",
                ".charCard .cname{font-weight:950}",
                ".charCard .cbody{min-width:0}",
                "#titleInput,#mdCode{font-size:16px;line-height:1.35}",
                "textarea{font-size:16px}\n.navBar{position:sticky;top:0;z-index:1200;background:rgba(11,16,32,0.96);backdrop-filter:blur(8px);border-bottom:1px solid var(--line);padding:12px 0 10px 0;margin-bottom:10px}\n.navInner{display:flex;justify-content:space-between;align-items:flex-end;gap:12px;flex-wrap:wrap}\n.brandRow{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}\n.pageName{color:var(--muted);font-weight:900;font-size:12px}\n.menuWrap{position:relative;display:inline-block}\n.userBtn{width:38px;height:38px;border-radius:999px;border:1px solid var(--line);background:transparent;color:var(--text);font-weight:950;display:inline-flex;align-items:center;justify-content:center}\n.userBtn:hover{background:rgba(255,255,255,0.06)}\n.menuCard{position:absolute;right:0;top:46px;min-width:240px;background:var(--card);border:1px solid var(--line);border-radius:16px;padding:12px;display:none;z-index:60;box-shadow:0 18px 60px rgba(0,0,0,.45)}\n.menuCard.show{display:block}\n.menuCard .uTop{display:flex;gap:10px;align-items:center;margin-bottom:10px}\n.menuCard .uAvatar{width:36px;height:36px;border-radius:999px;background:#0b1020;border:1px solid var(--line);display:flex;align-items:center;justify-content:center}\n.menuCard .uName{font-weight:950}\n.menuCard .uSub{color:var(--muted);font-size:12px;margin-top:2px}\n.menuCard .uActions{display:flex;gap:10px;justify-content:flex-end;margin-top:10px}",
                "</style>",
                js,
            ]
        )

        from .library_pages import _html_page  # local import to avoid cycles
        return _html_page("StoryForge - Story", body)
