from __future__ import annotations

import json
from typing import Any

import yaml
from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from .db import db_connect, db_init
from .library import get_story, list_stories
from .library_db import (
    delete_story_db,
    get_story_db,
    list_stories_db,
    upsert_story_db,
    validate_story_id,
)


# Extracted verbatim from _html_page() for safer incremental refactors.
LIBRARY_BASE_CSS = """
    :root{--bg:#0b1020;--card:#0f1733;--text:#e7edff;--muted:#a8b3d8;--line:#24305e;--accent:#4aa3ff;--bad:#ff4d4d;}
    html,body{overscroll-behavior-y:none;}
    *{box-sizing:border-box;}
    body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--text);padding:18px;max-width:920px;margin:0 auto;overflow-x:hidden;}
    a{color:var(--accent);text-decoration:none}
    .brandLink{color:inherit;text-decoration:none;}
    .brandLink:active{opacity:0.9;}
    code,pre,textarea{font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;}
    .navBar{position:sticky;top:0;z-index:1200;background:rgba(11,16,32,0.96);backdrop-filter:blur(8px);border-bottom:1px solid rgba(36,48,94,.55);padding:14px 0 10px 0;margin-bottom:10px;}
    .top{display:flex;justify-content:space-between;align-items:flex-end;gap:12px;flex-wrap:wrap;}
    .brandRow{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;}
    .pageName{color:var(--muted);font-weight:900;font-size:12px;}
    .menuWrap{position:relative;display:inline-block;}
    .userBtn{width:38px;height:38px;border-radius:999px;border:1px solid var(--line);background:transparent;color:var(--text);font-weight:950;display:inline-flex;align-items:center;justify-content:center;}
    .userBtn:hover{background:rgba(255,255,255,0.06);}
    .menuCard{position:absolute;right:0;top:46px;min-width:240px;background:var(--card);border:1px solid var(--line);border-radius:16px;padding:12px;display:none;z-index:60;box-shadow:0 18px 60px rgba(0,0,0,.45);}
    .menuCard.show{display:block;}
    .menuCard .uTop{display:flex;gap:10px;align-items:center;margin-bottom:10px;}
    .menuCard .uAvatar{width:36px;height:36px;border-radius:999px;background:#0b1020;border:1px solid var(--line);display:flex;align-items:center;justify-content:center;}
    .menuCard .uName{font-weight:950;}
    .menuCard .uSub{color:var(--muted);font-size:12px;margin-top:2px;}
    .menuCard .uActions{display:flex;gap:10px;justify-content:flex-end;margin-top:10px;}
    h1{font-size:20px;margin:0;}
    .muted{color:var(--muted);font-size:12px;}
    .card{border:1px solid var(--line);border-radius:16px;padding:12px;margin:12px 0;background:var(--card);}
    .row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;}
    .rowBetween{justify-content:space-between;}
    .rowEnd{justify-content:flex-end;}
    .mt8{margin-top:8px;}
    .mt10{margin-top:10px;}
    .mt12{margin-top:12px;}
    .fw950{font-weight:950;}
    button{padding:10px 12px;border-radius:12px;border:1px solid var(--line);background:#163a74;color:#fff;font-weight:950;cursor:pointer;}
    button.secondary{background:transparent;color:var(--text);}
    button.danger{background:transparent;border-color:rgba(255,77,77,.35);color:var(--bad);}
    input,textarea{width:100%;padding:10px;border:1px solid var(--line);border-radius:12px;background:#0b1020;color:var(--text);font-size:16px;}
    textarea{min-height:130px;resize:none;}
    .k{color:var(--muted);font-size:12px;margin-top:10px;}
    .job{border:1px solid var(--line);border-radius:14px;padding:12px;background:#0b1020;margin:10px 0;}
    .pill{display:inline-block;padding:3px 8px;border-radius:999px;font-size:12px;font-weight:900;border:1px solid var(--line);color:var(--muted)}
    .err{color:var(--bad);font-weight:950;margin-top:10px;}
  
"""

def _html_page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html>
<head>
  <meta charset='utf-8'/>
  <meta name='viewport' content='width=device-width, initial-scale=1'/>
  <title>{title}</title>
  <style>{LIBRARY_BASE_CSS}</style>
</head>
<body>
{body}
<script>
function toggleUserMenu(){{
  var m=document.getElementById('topMenu');
  if(!m) return;
  if(m.classList.contains('show')) m.classList.remove('show');
  else m.classList.add('show');
}}
document.addEventListener('click', function(ev){{
  try{{
    var m=document.getElementById('topMenu');
    if(!m) return;
    var w=ev.target && ev.target.closest ? ev.target.closest('.menuWrap') : null;
    if(!w) m.classList.remove('show');
  }}catch(e){{}}
}});
</script>
</body>
</html>"""


def _parse_characters_yaml(chars_yaml: str) -> list[dict[str, Any]]:
    raw = yaml.safe_load(chars_yaml or "")
    if raw is None:
        return []
    if isinstance(raw, dict) and isinstance(raw.get("characters"), list):
        return raw["characters"]
    if isinstance(raw, list):
        return raw
    raise ValueError("Characters must be YAML list or {characters: [...]} ")


def register_library_pages(app: FastAPI) -> None:
    @app.get("/library", response_class=HTMLResponse)
    def library_home(request: Request, response: Response):
        response.headers["Cache-Control"] = "no-store"
        err = str(request.query_params.get("err") or "")

        conn = db_connect()
        try:
            db_init(conn)
            stories = list_stories_db(conn)
        finally:
            conn.close()

        items = "".join(
            [
                f"<div class='job'>"
                f"<div class='row rowBetween'>"
                f"<div class='fw950'>{s['title']}</div>"
                f"</div>"  # end header row
                f"<div class='row mt10'>"
                f"<a href='/library/story/{s['id']}/view'><button class='secondary'>View</button></a> "
                f"<a href='/library/story/{s['id']}'><button class='secondary'>Edit</button></a>"
                f"</div>"  # end button row
                f"</div>"  # end job
                for s in stories
            ]
        )
        if not items:
            items = "<div class='muted'>No stories yet.</div>"

        err_html = f"<div class='err'>{err}</div>" if err else ""

        body = f"""
<div class='navBar'>
  <div class='top'>
    <div>
      <div class='brandRow'><h1><a class='brandLink' href='/'>StoryForge</a></h1><div class='pageName'>Library</div></div>
      <div class='muted'>Story list</div>
    </div>
    <div class='row rowEnd'>
      <a href='/#tab-library'><button class='secondary'>Back</button></a>
      <a href='/library/new'><button>New story</button></a>
      <div class='menuWrap'>
        <button class='userBtn' type='button' onclick='toggleUserMenu()' aria-label='User menu'>
          <svg viewBox='0 0 24 24' width='20' height='20' aria-hidden='true' stroke='currentColor' fill='none' stroke-width='2'>
            <path stroke-linecap='round' stroke-linejoin='round' d='M20 21a8 8 0 10-16 0'/>
            <path stroke-linecap='round' stroke-linejoin='round' d='M12 11a4 4 0 100-8 4 4 0 000 8z'/>
          </svg>
        </button>
        <div id='topMenu' class='menuCard'>
          <div class='uTop'>
            <div class='uAvatar'>
              <svg viewBox='0 0 24 24' width='18' height='18' aria-hidden='true' stroke='currentColor' fill='none' stroke-width='2'>
                <path stroke-linecap='round' stroke-linejoin='round' d='M20 21a8 8 0 10-16 0'/>
                <path stroke-linecap='round' stroke-linejoin='round' d='M12 11a4 4 0 100-8 4 4 0 000 8z'/>
              </svg>
            </div>
            <div><div class='uName'>User</div><div class='uSub'>Admin</div></div>
          </div>
          <div class='uActions'><a href='/logout'><button class='secondary' type='button'>Log out</button></a></div>
        </div>
      </div>
    </div>
  </div>
</div>

<div class='card'>
  <div class='row rowBetween'>
    <div>
      <div class='fw950'>Stories</div>
      <div class='muted'>Stored in managed Postgres.</div>
    </div>
    <form method='post' action='/library/import'>
      <button class='secondary' type='submit'>Import bundled stories</button>
    </form>
  </div>
  {err_html}
  {items}
</div>
"""
        return _html_page("StoryForge - Library", body)

    @app.get("/library/new", response_class=HTMLResponse)
    def library_new_get(request: Request):
        err = str(request.query_params.get("err") or "")
        err_html = f"<div class='err'>{err}</div>" if err else ""
        chars_default = """characters:\n  - id: narrator\n    name: Narrator\n    type: narrator\n    description: \"Warm, calm storyteller.\"\n    aliases: []\n"""
        body = f"""
<div class='navBar'>
  <div class='top'>
    <div>
      <div class='brandRow'><h1><a class='brandLink' href='/'>StoryForge</a></h1><div class='pageName'>New story</div></div>
      <div class='muted'>Create a new text-only story</div>
    </div>
    <div class='row rowEnd'>
      <a href='/#tab-library'><button class='secondary'>Back</button></a>
      <div class='menuWrap'>
        <button class='userBtn' type='button' onclick='toggleUserMenu()' aria-label='User menu'>
          <svg viewBox='0 0 24 24' width='20' height='20' aria-hidden='true' stroke='currentColor' fill='none' stroke-width='2'>
            <path stroke-linecap='round' stroke-linejoin='round' d='M20 21a8 8 0 10-16 0'/>
            <path stroke-linecap='round' stroke-linejoin='round' d='M12 11a4 4 0 100-8 4 4 0 000 8z'/>
          </svg>
        </button>
        <div id='topMenu' class='menuCard'>
          <div class='uTop'>
            <div class='uAvatar'>
              <svg viewBox='0 0 24 24' width='18' height='18' aria-hidden='true' stroke='currentColor' fill='none' stroke-width='2'>
                <path stroke-linecap='round' stroke-linejoin='round' d='M20 21a8 8 0 10-16 0'/>
                <path stroke-linecap='round' stroke-linejoin='round' d='M12 11a4 4 0 100-8 4 4 0 000 8z'/>
              </svg>
            </div>
            <div><div class='uName'>User</div><div class='uSub'>Admin</div></div>
          </div>
          <div class='uActions'><a href='/logout'><button class='secondary' type='button'>Log out</button></a></div>
        </div>
      </div>

    </div>
  </div>
</div>

<div class='card'>
  <form method='post' action='/library/new'>
    <input type='hidden' name='id' id='idHidden' value='' />

    <div class='k'>Title</div>
    <input name='title' placeholder='Maris and the Lighthouse' required />

    <script>
    (function(){{
      function slugify(x){{
        x = String(x||'').toLowerCase();
        x = x.replace(/[^a-z0-9]+/g,'-');
        x = x.replace(/^-+|-+$/g,'');
        x = x.slice(0,64);
        return x || 'story';
      }}
      var idEl = document.getElementById('idHidden');
      var titleEl = document.getElementsByName('title')[0];
      if (!idEl || !titleEl) return;
      var touched = false;
      idEl.addEventListener('input', function(){{ touched = true; }});
      titleEl.addEventListener('input', function(){{
        if (touched) return;
        idEl.value = slugify(titleEl.value);
      }});
    }})();
    </script>



    <div class='k'>Characters (YAML)</div>
    <textarea name='characters_yaml'>{chars_default}</textarea>

    <div class='k'>Story (Markdown)</div>
    <textarea name='story_md' placeholder='# Title\n\nOnce upon a time…'></textarea>

    {err_html}

    <div class='row mt12'>
      <button type='submit'>Create</button>
    </div>
  </form>
</div>
"""
        return _html_page("StoryForge - New story", body)

    @app.post("/library/new")
    def library_new_post(
        id: str = Form(default=""),
        title: str = Form(default=""),
        characters_yaml: str = Form(default=""),
        story_md: str = Form(default=""),
    ):
        try:
            sid = validate_story_id(id)
            chars = _parse_characters_yaml(characters_yaml)

            conn = db_connect()
            try:
                db_init(conn)
                upsert_story_db(conn, sid, title or sid, story_md or "", chars)
            finally:
                conn.close()

            return RedirectResponse(url='/#tab-library', status_code=302)
        except Exception as e:
            return RedirectResponse(url=f"/library/new?err={str(e)}", status_code=302)


    @app.get("/library/story/{story_id}", response_class=HTMLResponse)
    def library_story_get(story_id: str, request: Request):
        err = str(request.query_params.get("err") or "")
        err_html = f"<div class='err'>{err}</div>" if err else ""

        conn = db_connect()
        try:
            db_init(conn)
            s = get_story_db(conn, story_id)
        finally:
            conn.close()

        meta = s.get("meta") or {}
        chars_yaml = yaml.safe_dump({"characters": s.get("characters") or []}, sort_keys=False, allow_unicode=True)

        body = f"""
<div class='top'>
  <div>
    <h1>{meta.get('title') or story_id}</h1>
  </div>
  <div class='row'>
    <a href='/#tab-library'><button class='secondary'>Back</button></a>
    <form method='post' action='/library/story/{story_id}/delete' onsubmit="return confirm('Delete this story?');">
      <button class='danger' type='submit'>Delete</button>
    </form>
  </div>
</div>

<div class='card'>
  <form method='post' action='/library/story/{story_id}/save'>
    <div class='k'>Title</div>
    <input name='title' value={json.dumps(meta.get('title') or story_id)} required />


    <div class='k'>Characters (YAML)</div>
    <textarea name='characters_yaml'>{chars_yaml}</textarea>

    <div class='k'>Story (Markdown)</div>
    <textarea name='story_md' id='story_md'>{s.get('story_md') or ''}</textarea>

    <div class='muted mt8' id='autosaveStatus'>Autosave: idle</div>

    <script>
(function(){{
  function byName(n){{ return document.getElementsByName(n)[0]; }}
  var elTitle=byName('title');
  var elChars=byName('characters_yaml');
  var elStory=document.getElementById('story_md');
  var st=document.getElementById('autosaveStatus');
  var timer=null;

  function schedule(){{
    if (st) st.textContent='Autosave: pending';
    if (timer) clearTimeout(timer);
    timer=setTimeout(saveNow, 1200);
  }}

  function saveNow(){{
    if (st) st.textContent='Autosave: saving';
    var fd = new FormData();
    fd.append('title', elTitle ? elTitle.value : '');
    fd.append('characters_yaml', elChars ? elChars.value : '');
    fd.append('story_md', elStory ? elStory.value : '');
    fetch('/library/story/{story_id}/save', {{method:'POST', body: fd}})
      .then(function(r){{ if (st) st.textContent = r.ok ? 'Autosave: saved' : ('Autosave: error ' + r.status); }})
      .catch(function(_e){{ if (st) st.textContent='Autosave: error'; }});
  }}

  [elTitle, elChars, elStory].forEach(function(el){{
    if (!el) return;
    el.addEventListener('input', schedule);
  }});
}})();
</script>

    {err_html}

    <div class='row mt12'>
      <button type='submit'>Save</button>
    </div>
  </form>
</div>
"""
        return _html_page("StoryForge - Story", body)

    @app.post("/library/story/{story_id}/save")
    def library_story_save(
        story_id: str,
        title: str = Form(default=""),
        characters_yaml: str = Form(default=""),
        story_md: str = Form(default=""),
    ):
        try:
            sid = validate_story_id(story_id)
            chars = _parse_characters_yaml(characters_yaml)

            conn = db_connect()
            try:
                db_init(conn)
                upsert_story_db(conn, sid, title or sid, story_md or "", chars)
            finally:
                conn.close()
            return RedirectResponse(url='/#tab-library', status_code=302)
        except Exception as e:
            return RedirectResponse(url=f"/library/story/{story_id}?err={str(e)}", status_code=302)

    @app.post("/library/story/{story_id}/delete")
    def library_story_delete(story_id: str):
        try:
            sid = validate_story_id(story_id)
            conn = db_connect()
            try:
                db_init(conn)
                delete_story_db(conn, sid)
            finally:
                conn.close()
            return RedirectResponse(url='/#tab-library', status_code=302)
        except Exception as e:
            return RedirectResponse(url=f"/library?err={str(e)}", status_code=302)

    @app.post("/library/import")
    def library_import_bundled():
        # Import file-based stories bundled into the image/repo into DB.
        try:
            file_list = list_stories()
            conn = db_connect()
            try:
                db_init(conn)
                imported = 0
                for item in file_list:
                    sid = item.get("id")
                    if not sid:
                        continue
                    s = get_story(str(sid))
                    meta = s.get("meta") or {}
                    upsert_story_db(
                        conn,
                        str(sid),
                        str(meta.get("title") or sid),
                        str(s.get("story_md") or ""),
                        list(s.get("characters") or []),
                    )
                    imported += 1
            finally:
                conn.close()
            return RedirectResponse(url=f"/library?err=Imported%20{imported}%20story%28ies%29", status_code=302)
        except Exception as e:
            return RedirectResponse(url=f"/library?err={str(e)}", status_code=302)
