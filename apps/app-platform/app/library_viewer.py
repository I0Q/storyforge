from __future__ import annotations

import hashlib
import html

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi import Response

from .db import db_connect, db_init
from .library_db import get_story_db

VIEWER_EXTRA_CSS = """
.hide{display:none}
.rowBetween{justify-content:space-between;}
.rowEnd{justify-content:flex-end;margin-left:auto;}
.rowBetweenCenter{justify-content:space-between;align-items:center;}
.fw950{font-weight:950;}

/* navInner removed (use .top from base header CSS) */
.navTitleWrap{min-width:0;}
.navBrand h1{margin:0;}
.storySub{margin:8px 0 10px 0;font-size:14px;}
.storyTitleText{cursor:pointer;}
.titleEdit{margin-top:8px;}

.mdRender{margin-top:10px;line-height:1.6}
.mdCode{width:100%;min-height:260px;margin-top:10px;white-space:pre-wrap;line-height:1.4}

.vTabs{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0 6px 0;}
.vTab{padding:8px 12px;border-radius:999px;border:1px solid var(--line);background:transparent;color:var(--text);font-weight:950;cursor:pointer;}
.vTab.active{background:#163a74;}
.vPane.hide{display:none;}

.charsWrap{margin-top:10px;}
.pill.ml6{margin-left:6px;}
.desc.mt4{margin-top:4px;}

.charCard{display:flex;gap:10px;align-items:flex-start;border:1px solid var(--line);border-radius:14px;padding:10px;background:#0b1020;margin-top:8px}
.charCard .sw{width:18px;height:18px;border-radius:6px;flex:0 0 auto;margin-top:3px}
.charCard .cname{font-weight:950}
.charCard .cbody{min-width:0}

#titleInput,#mdCode{font-size:16px;line-height:1.35}
textarea{font-size:16px}
"""

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
            try:
                st = get_story_db(conn, story_id)
            except FileNotFoundError:
                raise HTTPException(status_code=404, detail="story_not_found")
        finally:
            conn.close()

        meta = st.get("meta") or {}
        
        story_md = st.get("story_md") or ""
        chars = st.get("characters") or []

# character cards (narrator first)
        try:
            chars = list(chars or [])
        except Exception:
            chars = []
        chars.sort(
            key=lambda c: (
                0
                if str((c or {}).get("role") or "").strip().lower() == "narrator"
                or str((c or {}).get("name") or "").strip().lower() == "narrator"
                else 1,
                str((c or {}).get("name") or ""),
            )
        )

        char_cards = []
        for idx, c in enumerate(chars):
            cid = str(c.get("id") or c.get("name") or "")
            nm = str(c.get("name") or c.get("id") or "")
            desc = str(c.get("description") or "")
            role = str(c.get("role") or "")
            ty = role
            color = _swatch(cid)

            pill = (
                f" <span class='pill ml6'>{html.escape(ty)}</span>"
                if ty
                else ""
            )
            desc_html = (
                f"<div class='muted desc mt4'>{html.escape(desc)}</div>"
                if desc
                else ""
            )
            char_cards.append(
                "<div class='charCard' onclick=\"openCharEdit(" + str(idx) + ")\">"
                f"<div class='sw' style='background:{color}'></div>"
                "<div class='cbody'>"
                f"<div class='cname'>{html.escape(nm)}{pill}</div>"
                f"{desc_html}"
                "</div></div>"
            )

        chars_html = (
            "<div class='charsWrap'>" + "".join(char_cards) + "</div>"
            if char_cards
            else "<div class='muted'>—</div>"
        )

        title_txt = html.escape(str(meta.get("title") or story_id))
        story_md_esc = html.escape(story_md)
        rendered = _render_md_simple(story_md)

        js = f"""
<script>
window.__STORY_ID = {story_id!r};
window.__CHARS = {json.dumps(chars, separators=(',',':'))};

function $(id){{ return document.getElementById(id); }}

function openCharEdit(idx){{
  try{{
    idx = parseInt(String(idx||'0'),10) || 0;
    var chars = window.__CHARS || [];
    var c = (chars && chars[idx]) ? chars[idx] : null;
    if (!c) return;

    $('ce_idx').value = String(idx);
    $('ce_name').value = String(c.name||'');
    $('ce_role').value = String(c.role||'');
    $('ce_desc').value = String(c.description||'');

    var vt = (c.voice_traits||{{}});
    $('ce_gender').value = String(vt.gender||'unknown');
    $('ce_age').value = String(vt.age||'unknown');
    $('ce_pitch').value = String(vt.pitch||'medium');
    $('ce_accent').value = String(vt.accent||'');
    $('ce_tone').value = Array.isArray(vt.tone) ? vt.tone.join(', ') : '';

    $('charEdit').classList.remove('hide');
  }}catch(e){{}}
}}

function closeCharEdit(){{
  try{{ $('charEdit').classList.add('hide'); }}catch(e){{}}
}}

function saveCharEdit(){{
  try{{
    var idx = parseInt(String(($('ce_idx')||{{}}).value||'0'),10) || 0;
    var chars = window.__CHARS || [];
    if (!chars[idx]) return;

    chars[idx].name = String(($('ce_name')||{{}}).value||'').trim();
    chars[idx].role = String(($('ce_role')||{{}}).value||'').trim();
    chars[idx].description = String(($('ce_desc')||{{}}).value||'').trim();

    var vt = chars[idx].voice_traits || {{}};
    vt.gender = String(($('ce_gender')||{{}}).value||'unknown').trim();
    vt.age = String(($('ce_age')||{{}}).value||'unknown').trim();
    vt.pitch = String(($('ce_pitch')||{{}}).value||'medium').trim();
    vt.accent = String(($('ce_accent')||{{}}).value||'').trim();
    var tone = String(($('ce_tone')||{{}}).value||'').split(',').map(function(x){{return String(x||'').trim();}}).filter(Boolean);
    vt.tone = tone;
    chars[idx].voice_traits = vt;

    // enforce narrator first
    try{{ chars.sort(function(a,b){{
      function isN(x){{ return String((x&&x.role)||'').toLowerCase()==='narrator' || String((x&&x.name)||'').toLowerCase()==='narrator'; }}
      var an=isN(a), bn=isN(b);
      if (an && !bn) return -1;
      if (!an && bn) return 1;
      return String((a&&a.name)||'').localeCompare(String((b&&b.name)||''));
    }}); }}catch(e){{}}

    fetch('/api/library/story/' + encodeURIComponent(String(window.__STORY_ID||'')) + '/characters', {{
      method:'PUT',
      headers:{{'Content-Type':'application/json'}},
      credentials:'include',
      body: JSON.stringify({{characters: chars}})
    }})
    .then(function(r){{ return r.json().catch(function(){{return {{ok:false,error:'bad_json'}};}}); }})
    .then(function(j){{
      if (!j || !j.ok) throw new Error((j&&j.error)||'save_failed');
      window.__CHARS = (j.characters||chars);
      closeCharEdit();
      window.location.reload();
    }})
    .catch(function(e){{
      var out=$('charsOut');
      if (out) out.innerHTML = '<div class="err">'+String(e&&e.message?e.message:e)+'</div>';
      try{{ toastShowNow('Save failed', 'err', 2200); }}catch(_e){{}}
    }});
  }}catch(e){{}}
}}

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

function identifyCharacters(){{
  try{{
    var out=$('charsOut');
    if (out) out.textContent='Identifying…';
    fetch('/api/library/story/' + encodeURIComponent(String(window.__STORY_ID||'')) + '/identify_characters', {{method:'POST', headers:{{'Content-Type':'application/json'}}, credentials:'include', body: JSON.stringify({{}})}})
      .then(function(r){{ return r.json().catch(function(){{ return {{ok:false,error:'bad_json'}}; }}); }})
      .then(function(j){{
        if (!j || !j.ok) throw new Error((j&&j.error)||'identify_failed');
        try{{ toastShowNow('Characters updated', 'ok', 1800); }}catch(e){{}}
        window.location.reload();
      }})
      .catch(function(e){{
        if (out) out.innerHTML = '<div class="err">'+String(e&&e.message?e.message:e)+'</div>';
        try{{ toastShowNow('Identify failed', 'err', 2200); }}catch(_e){{}}
      }});
  }}catch(e){{}}
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

function showVTab(which){{
  try{{
    var ps=$('vp-story');
    var pc=$('vp-chars');
    var ts=$('vtab-story');
    var tc=$('vtab-chars');
    if (which==='chars'){{
      if (ps) ps.classList.add('hide');
      if (pc) pc.classList.remove('hide');
      if (ts) ts.classList.remove('active');
      if (tc) tc.classList.add('active');
      try{{ window.location.hash = '#chars'; }}catch(e){{}}
    }} else {{
      if (pc) pc.classList.add('hide');
      if (ps) ps.classList.remove('hide');
      if (tc) tc.classList.remove('active');
      if (ts) ts.classList.add('active');
      try{{ window.location.hash = '#story'; }}catch(e){{}}
    }}
  }}catch(e){{}}
}}

(function initVTab(){{
  try{{
    var h = String(window.location.hash||'');
    if (h==='#chars') showVTab('chars');
    else showVTab('story');
  }}catch(e){{}}
}})();


if ($('mdCode')) {{
  $('mdCode').addEventListener('input', function(){{ scheduleSave(1200); }});
  $('mdCode').addEventListener('blur', function(){{ scheduleSave(10); }});
}}
</script>
"""

        body = "\n".join(
            [
                "<div class='navBar'>",
                "  <div class='top'>",
                "    <div class='navTitleWrap'>",
                "      <div class='brandRow navBrand'><h1><a class='brandLink' href='/'>StoryForge</a></h1><div class='pageName'>Story</div></div>",
                "",  # subtitle moved below header

                "    </div>",
                "    <div class='row rowEnd'>",
                "      <a href='/#tab-library'><button class='secondary' type='button'>Back</button></a>",
                "      <div class='menuWrap'>",
                "        <button class='userBtn' type='button' onclick=\"toggleUserMenu()\" aria-label='User menu'>",
                "          <svg viewBox='0 0 24 24' width='20' height='20' aria-hidden='true' stroke='currentColor' fill='none' stroke-width='2'><path stroke-linecap='round' stroke-linejoin='round' d='M20 21a8 8 0 10-16 0'/><path stroke-linecap='round' stroke-linejoin='round' d='M12 11a4 4 0 100-8 4 4 0 000 8z'/></svg>",
                "        </button>",
                "        <div id='topMenu' class='menuCard'>",
                "          <div class='uTop'>",
                "            <div class='uAvatar'><svg viewBox='0 0 24 24' width='18' height='18' aria-hidden='true' stroke='currentColor' fill='none' stroke-width='2'><path stroke-linecap='round' stroke-linejoin='round' d='M20 21a8 8 0 10-16 0'/><path stroke-linecap='round' stroke-linejoin='round' d='M12 11a4 4 0 100-8 4 4 0 000 8z'/></svg></div>",
                "            <div><div class='uName'>User</div><div class='uSub'>Admin</div></div>",
                "          </div>",
                "          <div class='uActions'><a href='/logout'><button class='secondary' type='button'>Log out</button></a></div>",
                "        </div>",
                "      </div>",
                "    </div>",
                "  </div>",
                "</div>",
                "",
                f"<div class='muted storySub'><span id='titleText' class='storyTitleText'>{title_txt}</span></div>",
                "<div id='titleEdit' class='hide titleEdit'>",
                f"  <input id='titleInput' value='{title_txt}' />",
                "</div>",
                "",
                "<div class='vTabs'>",
                "  <button id='vtab-story' class='vTab active' type='button' onclick=\"showVTab('story')\">Story</button>",
                "  <button id='vtab-chars' class='vTab' type='button' onclick=\"showVTab('chars')\">Characters</button>",
                "</div>",
                "",
                "<div id='vp-story' class='vPane'>",
                "  <div class='card'>",
                "    <div class='row rowBetween'>",
                "      <div class='fw950'>Story</div>",
                "      <button class='secondary' onclick=\"toggleMd()\" type='button' id='mdBtn'>Show code</button>",
                "    </div>",
                f"    <div id='mdRender' class='mdRender'>{rendered}</div>",
                f"    <textarea id='mdCode' class='term mdCode hide'>{story_md_esc}</textarea>",
                "  </div>",
                "</div>",
                "",
                "<div id='vp-chars' class='vPane hide'>",
                "  <div class='card'>",
                "    <div class='row rowBetweenCenter'>",
                "      <div class='fw950'>Characters</div>",
                "      <button class='secondary' type='button' onclick=\"identifyCharacters()\">Identify characters</button>",
                "    </div>",
                "    <div id='charsOut' class='muted' style='margin-top:8px'></div>",
                f"    {chars_html}",
                "  </div>",
                "",
                "  <div id='charEdit' class='card hide'>",
                "    <div class='row rowBetweenCenter'>",
                "      <div class='fw950'>Edit character</div>",
                "      <button class='secondary' type='button' onclick=\"closeCharEdit()\">Close</button>",
                "    </div>",
                "    <input id='ce_idx' type='hidden' value='0' />",
                "    <div class='kvs' style='margin-top:10px'>",
                "      <div class='k'>Name</div><div><input id='ce_name' /></div>",
                "      <div class='k'>Role</div><div><input id='ce_role' placeholder='narrator / protagonist / …' /></div>",
                "      <div class='k'>Desc</div><div><input id='ce_desc' placeholder='short description' /></div>",
                "      <div class='k'>Gender</div><div><input id='ce_gender' placeholder='female/male/neutral/unknown' /></div>",
                "      <div class='k'>Age</div><div><input id='ce_age' placeholder='child/teen/adult/elder/unknown' /></div>",
                "      <div class='k'>Pitch</div><div><input id='ce_pitch' placeholder='low/medium/high' /></div>",
                "      <div class='k'>Accent</div><div><input id='ce_accent' placeholder='e.g. british, none' /></div>",
                "      <div class='k'>Tone</div><div><input id='ce_tone' placeholder='comma-separated tags' /></div>",
                "    </div>",
                "    <div class='row' style='margin-top:12px;justify-content:flex-end'>",
                "      <button type='button' onclick=\"saveCharEdit()\">Save</button>",
                "    </div>",
                "  </div>",
                "</div>",
                "",
                "<div class='card'>",
                "  <div class='row rowBetweenCenter'>",
                "    <div>",
                "      <div class='fw950'>Danger zone</div>",
                "      <div class='muted'>Delete cannot be undone.</div>",
                "    </div>",
                "    <button class='danger' type='button' onclick=\"doDelete()\">Delete story</button>",
                "  </div>",
                "</div>",
                "",
                f"<style>{VIEWER_EXTRA_CSS}</style>",
                js,
            ]
        )
        from .library_pages import _html_page  # local import to avoid cycles
        return _html_page("StoryForge - Story", body)
