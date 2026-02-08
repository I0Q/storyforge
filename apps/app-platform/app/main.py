from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import json
import time
import html as pyhtml

import requests
from fastapi import FastAPI

from .auth import register_passphrase_auth
from .library_pages import register_library_pages
from .library_viewer import register_library_viewer
from .db import db_connect, db_init, db_list_jobs
from .library import list_stories, list_stories_debug, get_story
from .library_db import (
    delete_story_db,
    get_story_db,
    list_stories_db,
    upsert_story_db,
    validate_story_id,
)
from .voices_db import (
    validate_voice_id,
    list_voices_db,
    get_voice_db,
    upsert_voice_db,
    set_voice_enabled_db,
    delete_voice_db,
)
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi import Response

APP_NAME = "storyforge"

GATEWAY_BASE = os.environ.get("GATEWAY_BASE", "http://10.108.0.3:8791").rstrip("/")
GATEWAY_TOKEN = os.environ.get("GATEWAY_TOKEN", "")

VOICE_SERVERS: list[dict[str, Any]] = []
try:
    _raw = os.environ.get("VOICE_SERVERS_JSON", "").strip()
    if _raw:
        _v = json.loads(_raw)
        if isinstance(_v, list):
            VOICE_SERVERS = [x for x in _v if isinstance(x, dict)]
except Exception:
    VOICE_SERVERS = []

if not VOICE_SERVERS:
    VOICE_SERVERS = [
        {"name": "Tinybox", "base": GATEWAY_BASE, "kind": "gateway"},
    ]

app = FastAPI(title=APP_NAME, version="0.1")
register_passphrase_auth(app)
register_library_pages(app)
register_library_viewer(app)


def _h() -> dict[str, str]:
    if not GATEWAY_TOKEN:
        return {}
    return {"Authorization": "Bearer " + GATEWAY_TOKEN}


def _get(path: str) -> dict[str, Any]:
    r = requests.get(GATEWAY_BASE + path, headers=_h(), timeout=8)
    r.raise_for_status()
    return r.json()


@app.get("/", response_class=HTMLResponse)
def index(response: Response):
    build = int(time.time())
    # iOS Safari can be aggressive about caching; keep the UI fresh.
    response.headers["Cache-Control"] = "no-store"

    # Voice servers list (rendered server-side to avoid brittle JS)
    vs_items: list[str] = []
    for s in VOICE_SERVERS:
        try:
            nm_raw = str(s.get("name") or "server")
            nm = pyhtml.escape(nm_raw)
            base = pyhtml.escape(str(s.get("base") or ""))
            kind = pyhtml.escape(str(s.get("kind") or ""))
            meta = f" <span class='pill'>{kind}</span>" if kind else ""

            # Tinybox-specific monitor toggle lives inline with the Tinybox server item.
            mon_btn = ""
            if nm_raw.lower() == "tinybox":
                mon_btn = "<div class='row' style='margin-top:10px'><button id='monToggle' class='secondary' onclick='toggleMonitor()'>Disable monitor</button></div>"

            vs_items.append(
                "<div class='job'>"
                f"<div class='title'>{nm}{meta}</div>"
                f"<div class='muted' style='margin-top:6px'><code>{base}</code></div>"
                f"{mon_btn}"
                "</div>"
            )
        except Exception:
            continue
    voice_servers_html = "".join(vs_items) if vs_items else "<div class='muted'>No voice servers configured.</div>"

    html = """<!doctype html>
<html>
<head>
  <meta charset='utf-8'/>
  <meta name='viewport' content='width=device-width, initial-scale=1'/>
  <title>StoryForge</title>
  <style>
    :root{--bg:#0b1020;--card:#0f1733;--text:#e7edff;--muted:#a8b3d8;--line:#24305e;--accent:#4aa3ff;--good:#26d07c;--warn:#ffcc00;--bad:#ff4d4d;}
    body.noScroll{overflow:hidden;}
    body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--text);padding:18px 18px calc(70px + env(safe-area-inset-bottom)) 18px;max-width:920px;margin:0 auto;}
    body.monOff{padding-bottom:18px;}
    body.monOff .dock{display:none}
    body.monOff #monitorBackdrop{display:none}
    body.monOff #monitorSheet{display:none}
    a{color:var(--accent);text-decoration:none}
    code{font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;}
    .top{display:flex;justify-content:space-between;align-items:flex-end;gap:12px;flex-wrap:wrap;}
    h1{font-size:20px;margin:0;}
    .muted{color:var(--muted);font-size:12px;}
    .boot{margin-top:10px;padding:10px 12px;border-radius:14px;border:1px dashed rgba(168,179,216,.35);background:rgba(7,11,22,.35);} 
    body.debugOff #boot{display:none}
    .boot strong{color:var(--text);}
    .tabs{display:flex;gap:10px;margin-top:14px;flex-wrap:wrap;}
    .tab{padding:10px 12px;border-radius:12px;border:1px solid var(--line);background:transparent;color:var(--text);font-weight:900;cursor:pointer}
    .tab.active{background:var(--card);}
    .card{border:1px solid var(--line);border-radius:16px;padding:12px;margin:12px 0;background:var(--card);}
    .row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;}
    button{padding:10px 12px;border-radius:12px;border:1px solid var(--line);background:#163a74;color:#fff;font-weight:950;cursor:pointer;}
    button.secondary{background:transparent;color:var(--text);}
    input,textarea{width:100%;padding:10px;border:1px solid var(--line);border-radius:12px;background:#0b1020;color:var(--text);}
    textarea{min-height:90px;}
    pre{background:#070b16;color:#d7e1ff;padding:12px;border-radius:12px;overflow:auto;border:1px solid var(--line)}
    .term{font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;font-size:12px;line-height:1.25;white-space:pre;}
    .job{border:1px solid var(--line);border-radius:14px;padding:12px;background:#0b1020;margin:10px 0;}
    .job .title{font-weight:950;font-size:14px;}
    .pill{display:inline-block;padding:3px 8px;border-radius:999px;font-size:12px;font-weight:900;border:1px solid var(--line);color:var(--muted)}
    .pill.good{color:var(--good);border-color:rgba(38,208,124,.35)}
    .pill.bad{color:var(--bad);border-color:rgba(255,77,77,.35)}
    .pill.warn{color:var(--warn);border-color:rgba(255,204,0,.35)}
    .kvs{display:grid;grid-template-columns:120px 1fr;gap:6px 10px;margin-top:8px;font-size:13px;}
    .fadeLine{position:relative;display:flex;align-items:center;gap:8px;min-width:0;}
    .fadeText{flex:1;min-width:0;white-space:nowrap;overflow-x:auto;overflow-y:hidden;color:var(--muted);-webkit-overflow-scrolling:touch;scrollbar-width:none;}
    .fadeText::-webkit-scrollbar{display:none;}
        .copyBtn{border:1px solid var(--line);background:transparent;color:var(--text);font-weight:900;border-radius:10px;padding:6px;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;width:34px;height:30px;}
    .copyBtn:active{transform:translateY(1px);}
    .copyBtn svg{width:18px;height:18px;stroke:currentColor;fill:none;stroke-width:2;}
    .copyBtn:hover{background:rgba(255,255,255,0.06);}
    .kvs div.k{color:var(--muted)}
    .hide{display:none}

    /* bottom dock */
    .dock{display:none;position:fixed;left:0;right:0;bottom:0;z-index:1500;background:rgba(15,23,51,.92);backdrop-filter:blur(10px);border-top:1px solid var(--line);padding:10px 12px calc(10px + env(safe-area-inset-bottom)) 12px;}
    html.monOn .dock{display:block;}
    .dockInner{max-width:920px;margin:0 auto;display:flex;justify-content:space-between;align-items:center;gap:10px;}
    .dockStats{color:var(--muted);font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:70%;}
    body.sheetOpen .dock{pointer-events:none;}

    /* bottom sheet */
    .sheetBackdrop{display:none;position:fixed;inset:0;background:rgba(0,0,0,.55);backdrop-filter:blur(3px);z-index:2000;touch-action:none;}
    .sheet{display:none;position:fixed;left:0;right:0;bottom:0;z-index:2001;background:var(--card);border-top:1px solid var(--line);border-top-left-radius:18px;border-top-right-radius:18px;max-height:78vh;box-shadow:0 -18px 60px rgba(0,0,0,.45);overflow:hidden;}
    html.monOn .sheetBackdrop{display:block;}
    html.monOn .sheet{display:block;}
    .sheetBackdrop.hide{display:none;}
    .sheet.hide{display:none;}
    .sheetInner{padding:12px 14px;max-height:78vh;overflow-y:auto;-webkit-overflow-scrolling:touch;overscroll-behavior:contain;}
    .sheetHandle{width:44px;height:5px;border-radius:999px;background:rgba(255,255,255,.25);margin:6px auto 10px auto;}
    .sheetTitle{font-weight:950;}
    #monitorSheet button{touch-action:manipulation;}
    .grid2{display:grid;grid-template-columns:1fr 1fr;gap:10px;}
    .gpuGrid{display:grid;grid-template-columns:repeat(2, minmax(0, 1fr));gap:8px;}
    .gpuCard{background:#0b1020;border:1px solid var(--line);border-radius:14px;padding:10px;min-width:0;}
    .gpuHead{display:flex;justify-content:space-between;align-items:baseline;gap:8px;}
    .gpuHead .l{font-weight:950;}
    .gpuHead .r{color:var(--muted);font-size:12px;white-space:nowrap;}
    .gpuRow{display:flex;justify-content:space-between;align-items:baseline;margin-top:6px;}
    .gpuRow .k{color:var(--muted);font-size:12px;}
    .gpuRow .v{font-weight:950;font-size:13px;}
    .bar.small{height:8px;margin-top:6px;}
    @media (max-width:520px){.grid2{grid-template-columns:1fr;}}
    .meter{background:#0b1020;border:1px solid var(--line);border-radius:14px;padding:10px;}
    .meter .k{color:var(--muted);font-size:12px;}
    .meter .v{font-weight:950;margin-top:4px;}
    .bar{height:10px;background:#0a0f20;border:1px solid rgba(255,255,255,.08);border-radius:999px;overflow:hidden;margin-top:8px;}
    .bar > div{height:100%;width:0%;background:linear-gradient(90deg,#4aa3ff,#26d07c);}
    .bar.warn > div{background:linear-gradient(90deg,#ffcc00,#ff7a00);}
    .bar.bad > div{background:linear-gradient(90deg,#ff4d4d,#ff2e83);}
  </style>
  <script>
  // Ensure monitor UI is hidden on first paint when disabled.
  // Emergency override: add ?mon=0 (or ?monitor=0 / ?monoff=1) to force monitor OFF even if the sheet is stuck.
  (function(){
    function hasParam(name){
      try{
        var q = window.location.search || '';
        if (q.indexOf('?')===0) q=q.slice(1);
        var parts = q.split('&');
        for (var i=0;i<parts.length;i++){
          var kv = parts[i].split('=');
          var k = decodeURIComponent(kv[0]||'');
          var v = decodeURIComponent(kv.slice(1).join('=')||'');
          if (k===name) return v;
        }
      }catch(e){}
      return '';
    }

    try{
      var forceOff = false;
      var mon = hasParam('mon');
      var monitor = hasParam('monitor');
      var monoff = hasParam('monoff');
      if (mon==='0' || monitor==='0' || monoff==='1') forceOff = true;

      if (forceOff){
        try{ localStorage.setItem('sf_monitor_enabled','0'); }catch(e){}
        document.documentElement.classList.remove('monOn');
        return;
      }

      var v = localStorage.getItem('sf_monitor_enabled');
      if (v === '0') document.documentElement.classList.remove('monOn');
      else document.documentElement.classList.add('monOn');
    }catch(e){
      document.documentElement.classList.add('monOn');
    }
  })();
  </script>
</head>
<body>
  <div class='top'>
    <div>
      <h1>StoryForge</h1>
      <div class='muted'>Cloud control plane (App Platform) + Tinybox compute via VPC gateway.</div>
    </div>
    <div id='boot' class='boot muted'><strong>Build</strong>: __BUILD__ • JS: booting…</div>
    <div class='row'>
            
    </div>
  </div>

  <div class='tabs'>
    <button id='tab-history' class='tab active' onclick='showTab("history")'>History</button>
    <button id='tab-library' class='tab' onclick='showTab("library")'>Library</button>
        <button id='tab-advanced' class='tab' onclick='showTab("advanced")'>Advanced</button>
  </div>

  <div id='pane-history'>
    <div class='card'>
      <div class='row' style='justify-content:space-between;'>
        <div>
          <div style='font-weight:950;'>Recent jobs</div>
          <div class='muted'>Read-only from managed Postgres (migrated from Tinybox monitor).</div>
        </div>
        <div class='row'>
          
        </div>
      </div>
      <div id='jobs'>Loading…</div>
    </div>
  </div>

  

  <div id='pane-library' class='hide'>
    <div class='card'>
      <div class='row' style='justify-content:space-between;'>
        <div>
          <div style='font-weight:950;'>Story Library</div>
          <div class='muted'>Text-only source stories (no voice/SFX assignments yet).</div>
        </div>
        <div class='row'>
          <a href='/library/new'><button class='secondary'>New story</button></a>
          
        </div>
      </div>
      <div id='lib' class='muted'>Tap Reload to load stories.</div>
    </div>

    <div class='card' id='libDetailCard' style='display:none'>
      <div class='row' style='justify-content:space-between;'>
        <div>
          <div id='libTitle' style='font-weight:950;'>Story</div>
          <div id='libDesc' class='muted'></div>
        </div>
        <div class='row'>
          <button class='secondary' onclick='closeStory()'>Close</button>
        </div>
      </div>

      <div style='font-weight:950;margin-top:12px;'>Characters</div>
      <pre id='libChars' class='term' style='margin-top:8px;'>—</pre>

      <div style='font-weight:950;margin-top:12px;'>Narrative (Markdown)</div>
      <pre id='libStory' class='term' style='margin-top:8px;white-space:pre-wrap;'>—</pre>

      <div class='row' style='margin-top:12px;'>
        <button class='secondary' onclick='copyStory()'>Copy story text</button>
      </div>
    </div>
  </div>

  <div id='pane-advanced' class='hide'>

    <div class='card'>
      <div style='font-weight:950;margin-bottom:6px;'>Voice servers</div>
      <div class='muted'>Configured endpoints used for voice/TTS work.</div>
      <div style='margin-top:10px'>__VOICE_SERVERS__</div>
    </div>

    <div class='card'>
      <div style='font-weight:950;margin-bottom:6px;'>Voices</div>
      <div class='muted'>CRUD for voice metadata (samples can be generated later).</div>

      <div class='row' style='margin-top:10px;'>
        <button class='secondary' onclick='loadVoices()'>Reload voices</button>
      </div>

      <div id='voicesList' style='margin-top:10px' class='muted'>—</div>

      <div style='font-weight:950;margin-top:12px;'>Add voice</div>
      <div class='kvs' style='margin-top:8px'>
        <div class='k'>id</div><div><input id='v_id' placeholder='mira' /></div>
        <div class='k'>name</div><div><input id='v_name' placeholder='Mira' /></div>
        <div class='k'>engine</div><div><input id='v_engine' placeholder='xtts' /></div>
        <div class='k'>voice_ref</div><div><input id='v_ref' placeholder='speaker_12 / provider id' /></div>
      </div>
      <div class='row' style='margin-top:10px;'>
        <button onclick='createVoice()'>Create</button>
      </div>
    </div>

<div style='font-weight:950;margin-bottom:6px;'>Debug UI</div>
      <div class='muted'>Hide/show the build + JS error banner.</div>
      <div class='row' style='margin-top:10px;'>
        <button id='dbgToggle' class='secondary' onclick='toggleDebugUi()'>Disable debug</button>
      </div>
    </div>

  </div>

<script>
// minimal boot script (runs even if the main app script has a syntax error)
window.__SF_BUILD = '__BUILD__';
window.__SF_BOOT_TS = Date.now();
window.addEventListener('error', (ev)=>{
  const b=document.getElementById('boot');
  if (b) b.textContent = `Build: ${window.__SF_BUILD} • JS error: ${ev.message || ev.type}`;
});
window.addEventListener('unhandledrejection', (ev)=>{
  const b=document.getElementById('boot');
  if (b) b.textContent = `Build: ${window.__SF_BUILD} • JS promise error`;
});
</script>

<script>
function getQueryParam(key){
  try{
    var q = window.location.search || '';
    if (q.startsWith('?')) q=q.slice(1);
    var parts = q.split('&');
    for (var i=0;i<parts.length;i++){
      var kv = parts[i].split('=');
      if (decodeURIComponent(kv[0]||'')===key) return decodeURIComponent(kv.slice(1).join('=')||'');
    }
  }catch(e){}
  return '';
}


// --- Toasts (persist across fast navigation via localStorage) ---
function __sfToastInit(){
  var el = document.getElementById('sfToast');
  if (!el){
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
    el.onclick = function(){ try{ el.style.display='none'; localStorage.setItem('sf_toast_until','0'); }catch(e){} };
    document.body.appendChild(el);
  }

  var msg='', kind='info', until=0;
  try{
    msg = localStorage.getItem('sf_toast_msg') || '';
    kind = localStorage.getItem('sf_toast_kind') || 'info';
    until = parseInt(localStorage.getItem('sf_toast_until') || '0', 10) || 0;
  }catch(e){}

  if (!msg || Date.now() > until){ el.style.display='none'; return; }

  var border = 'rgba(255,255,255,0.10)';
  if (kind==='ok') border='rgba(80,200,120,0.35)';
  else if (kind==='err') border='rgba(255,90,90,0.35)';
  el.style.borderColor = border;

  el.textContent = msg;
  el.style.display = 'block';

  if (window.__sfToastTimer) clearTimeout(window.__sfToastTimer);
  window.__sfToastTimer = setTimeout(function(){ try{ el.style.display='none'; }catch(e){} }, Math.max(200, until - Date.now()));
}
try{ document.addEventListener('DOMContentLoaded', __sfToastInit); }catch(e){}
try{ __sfToastInit(); }catch(e){}

function showTab(name, opts){
  opts = opts || {};
  for (var i=0;i<['history','library','advanced'].length;i++){
    var n=['history','library','advanced'][i];
    document.getElementById('pane-'+n).classList.toggle('hide', n!==name);
    document.getElementById('tab-'+n).classList.toggle('active', n===name);
  }
  // persist in URL hash
  try{
    if (!opts.noHash){
      var h = '#tab-' + name;
      if (window.location.hash !== h) window.location.hash = h;
    }
  }catch(_e){}

  // lazy-load tab content
  try{
    if (name==='history') loadHistory();
    else if (name==='library') loadLibrary();
  }catch(_e){}
}

function getTabFromHash(){
  try{
    var h = (window.location.hash || '').replace('#','');
    if (h==='tab-history') return 'history';
    if (h==='tab-library') return 'library';
    if (h==='tab-advanced') return 'advanced';
  }catch(e){}
  return '';
}

try{
  window.addEventListener('hashchange', function(){
    var t = getTabFromHash();
    if (t) showTab(t, {noHash:true});
  });
}catch(e){}

function pill(state){
  const s=(state||'unknown').toLowerCase();
  let cls='pill';
  if (s==='completed' || s==='done' || s==='success') cls+=' good';
  else if (s==='aborted' || s==='error' || s==='failed') cls+=' bad';
  else if (s==='running' || s==='queued') cls+=' warn';
  return `<span class="${cls}">${s}</span>`;
}

function copyIconSvg(){
  // Heroicons (MIT) - clipboard-document
  return `<svg viewBox="0 0 24 24" aria-hidden="true">`
    + `<path stroke-linecap="round" stroke-linejoin="round" d="M11 7H7a2 2 0 00-2 2v9a2 2 0 002 2h10a2 2 0 002-2v-9a2 2 0 00-2-2h-4M11 7V5a2 2 0 114 0v2M11 7h4"/>`
    + `</svg>`;
}

function copyFromAttr(el){
  var v = ''; try{ v = (el && el.getAttribute) ? (el.getAttribute('data-copy') || '') : ''; }catch(e){}
  if (v) copyToClipboard(v);
}

function fetchJsonAuthed(url, opts){
  return fetch(url, opts).then(function(r){
    if (r.status === 401){
      window.location.href = '/login';
      throw new Error('unauthorized');
    }
    if (!r.ok){
      return r.text().then(function(t){
        throw new Error('HTTP ' + r.status + ' ' + (t || '').slice(0,200));
      });
    }
    return r.json();
  });
}



function copyToClipboard(text){
  try{
    if (navigator.clipboard && navigator.clipboard.writeText){
      return navigator.clipboard.writeText(text).catch(function(_e){
        const ta=document.createElement('textarea');
        ta.value=text; document.body.appendChild(ta);
        ta.select();
        try{document.execCommand('copy');}catch(__e){}
        ta.remove();
      });
    }
  }catch(e){
    const ta=document.createElement('textarea');
    ta.value=text; document.body.appendChild(ta);
    ta.select();
    try{document.execCommand('copy');}catch(_e){}
    ta.remove();
  }
}

function fmtTs(ts){
  if (!ts) return '—';
  try{
    const d=new Date(ts*1000);
    return d.toLocaleString();
  }catch(e){
    return String(ts);
  }
}

function loadHistory(){
  const el=document.getElementById('jobs');
  el.textContent='Loading…';
  return fetchJsonAuthed('/api/history?limit=60').then(function(j){
    if (!j.ok){
      el.innerHTML=`<div class='muted'>Error: ${j.error||'unknown'}</div>`;
      return;
    }
    if (!j.jobs.length){
      el.innerHTML="<div class='muted'>No jobs yet.</div>";
      return;
    }

      el.innerHTML=j.jobs.map(job=>{
    return `<div class='job'>
      <div class='row' style='justify-content:space-between;'>
        <div class='title'>${job.title||job.id}</div>
        <div>${pill(job.state)}</div>
      </div>
      <div class='kvs'>
        <div class='k'>id</div><div>${job.id}</div>
        <div class='k'>started</div><div>${fmtTs(job.started_at)}</div>
        <div class='k'>finished</div><div>${fmtTs(job.finished_at)}</div>
        <div class='k'>segments</div><div>${job.total_segments||0}</div>
        <div class='k'>mp3</div><div class='fadeLine'><div class='fadeText' title='${job.mp3_url||""}'>${job.mp3_url||'—'}</div>${job.mp3_url?`<button class="copyBtn" data-copy="${job.mp3_url}" onclick="copyFromAttr(this)" aria-label="Copy">${copyIconSvg()}</button>`:''}</div>
        <div class='k'>sfml</div><div class='fadeLine'><div class='fadeText' title='${job.sfml_url||""}'>${job.sfml_url||'—'}</div>${job.sfml_url?`<button class="copyBtn" data-copy="${job.sfml_url}" onclick="copyFromAttr(this)" aria-label="Copy">${copyIconSvg()}</button>`:''}</div>
      </div>
    </div></a>`;
    }).join('');
  }).catch(function(e){
    el.innerHTML = `<div class='muted'>Loading failed: ${String(e)}</div>`;
  });
}

let metricsES = null;
let monitorEnabled = true;
let lastMetrics = null;

// Debug UI toggle (controls Build/JS banner visibility)
function loadDebugPref(){
  try{
    var v = localStorage.getItem('sf_debug_ui');
    if (v===null || v==='') return true;
    return v === '1';
  }catch(e){
    return true;
  }
}

function setDebugUiEnabled(on){
  try{ localStorage.setItem('sf_debug_ui', on ? '1' : '0'); }catch(e){}
  document.body.classList.toggle('debugOff', !on);
  var btn=document.getElementById('dbgToggle');
  if (btn){ btn.textContent = on ? 'Disable debug' : 'Enable debug'; btn.classList.toggle('secondary', on); }
}

function toggleDebugUi(){
  setDebugUiEnabled(!loadDebugPref());
}

function renderMetrics(m){
  lastMetrics = m;
  const pre=document.getElementById('metrics'); if (pre) pre.textContent = JSON.stringify(m, null, 2);
}


function renderProc(m){
  const el = document.getElementById('monProc');
  if (!el) return;
  const b = m?.body || m || {};
  const procs = b.processes || b.procs || null;
  if (!procs || !Array.isArray(procs) || procs.length===0){
    el.textContent = 'No process list available.';
    return;
  }

  // terminal-like table
  const rows = procs.slice(0, 18).map(p => ({
    pid: String(p.pid ?? ''),
    cpu: (p.cpu_pct!=null) ? Number(p.cpu_pct).toFixed(1) : '',
    mem: (p.mem_pct!=null) ? Number(p.mem_pct).toFixed(1) : '',
    gmem: (p.gpu_mem_mb!=null) ? Number(p.gpu_mem_mb).toFixed(0) : '',
    et: String(p.elapsed ?? ''),
    cmd: String(p.command ?? p.name ?? ''),
    args: String(p.args ?? '')
  }));

  const pad = (s, n) => (s.length >= n ? s.slice(0,n) : s + ' '.repeat(n - s.length));
  const header = [
    pad('PID', 7),
    pad('%CPU', 6),
    pad('%MEM', 6),
    pad('GPU', 5),
    pad('ELAPSED', 9),
    'COMMAND'
  ].join(' ');

  const lines = [header, '-'.repeat(header.length)];
  for (const r of rows){
    const right = (r.args && r.args !== r.cmd) ? (r.cmd + ' ' + r.args) : r.cmd;
    lines.push([
      pad(r.pid,7),
      pad(r.cpu,6),
      pad(r.mem,6),
      pad(r.gmem,5),
      pad(r.et,9),
      right
    ].join(' '));
  }
  el.textContent = lines.join(String.fromCharCode(10));
}

function startMetricsStream(){
  if (!monitorEnabled) return;
  stopMetricsStream();
  // SSE stream (server pushes metrics continuously)
  metricsES = new EventSource('/api/metrics/stream');
  metricsES.onmessage = (ev) => {
    try{
      const m = JSON.parse(ev.data);
      renderMetrics(m);
      updateMonitorFromMetrics(m);
      renderProc(m);
      updateDockFromMetrics(m);
    }catch(e){}
  };
  metricsES.onerror = () => {
    // Browser will auto-reconnect; we keep it simple.
  };
}

function stopMetricsStream(){
  if (metricsES){
    metricsES.close();
    metricsES = null;
  }
}


function loadMonitorPref(){
  try{
    const v = localStorage.getItem('sf_monitor_enabled');
    if (v === null) return true;
    return v === '1';
  }catch(e){
    return true;
  }
}

function saveMonitorPref(on){
  try{ localStorage.setItem('sf_monitor_enabled', on ? '1' : '0'); }catch(e){}
}

function setMonitorEnabled(on){
  monitorEnabled = !!on;
  saveMonitorPref(monitorEnabled);
  const dock = document.getElementById('monitorDock');
  const backdrop = document.getElementById('monitorBackdrop');
  const sheet = document.getElementById('monitorSheet');
  const btn = document.getElementById('monToggle');

  try{ document.documentElement.classList.toggle('monOn', !!monitorEnabled); }catch(e){}

  if (!monitorEnabled){
    stopMetricsStream();
    document.body.classList.add('monOff');
    if (dock) dock.classList.add('hide');
    if (backdrop) backdrop.classList.add('hide');
    if (sheet) sheet.classList.add('hide');
    document.body.classList.remove('noScroll');
  document.body.classList.remove('sheetOpen');
    if (btn){ btn.textContent = 'Enable monitor'; btn.classList.remove('secondary'); }
    return;
  }

  document.body.classList.remove('monOff');
  if (dock) dock.classList.remove('hide');
  if (btn){ btn.textContent = 'Disable monitor'; btn.classList.add('secondary'); }
  const ds=document.getElementById('dockStats'); if (ds) ds.textContent='Connecting…';
  startMetricsStream();
}

function toggleMonitor(){
  setMonitorEnabled(!monitorEnabled);
}





function escapeHtml(s){
  try{
    return String(s||'')
      .replace(/&/g,'&amp;')
      .replace(/</g,'&lt;')
      .replace(/>/g,'&gt;');
  }catch(e){
    return '';
  }
}

function loadVoices(){
  var el=document.getElementById('voicesList');
  if (el) el.textContent='Loading…';
  return fetchJsonAuthed('/api/voices').then(function(j){
    if (!j.ok){ if(el) el.innerHTML = "<div class='muted'>Error loading voices</div>"; return; }
    var voices = j.voices || [];
    if (!voices.length){ if(el) el.innerHTML = "<div class='muted'>No voices yet.</div>"; return; }

    if (!el) return;
    el.innerHTML = voices.map(function(v){
      var nm = v.display_name || v.id;
      var meta = [];
      if (v.engine) meta.push(v.engine);
      if (v.voice_ref) meta.push(v.voice_ref);
      var metaLine = meta.join(' • ');
      var en = (v.enabled!==false);
      var pill = en ? "<span class='pill good'>enabled</span>" : "<span class='pill bad'>disabled</span>";
      return "<div class='job'>"
        + "<div class='row' style='justify-content:space-between;'>"
        + "<div class='title'>" + escapeHtml(nm) + "</div>"
        + "<div>" + pill + "</div>"
        + "</div>"
        + (metaLine ? ("<div class='muted' style='margin-top:6px'><code>" + escapeHtml(metaLine) + "</code></div>") : "")
        + "<div class='row' style='margin-top:10px'>"
        + "<button class='secondary' data-vid='" + encodeURIComponent(v.id) + "' onclick='renameVoiceEl(this)'>Rename</button>"
        + (en ? ("<button class='secondary' data-vid='" + encodeURIComponent(v.id) + "' onclick='disableVoiceEl(this)'>Disable</button>") : "")
        + "</div>"
        + "</div>";
    }).join('');
  }).catch(function(e){
    if (el) el.innerHTML = "<div class='muted'>Error loading voices: " + escapeHtml(String(e)) + "</div>";
  });
}

function createVoice(){
  var idEl=document.getElementById('v_id');
  var nmEl=document.getElementById('v_name');
  var engEl=document.getElementById('v_engine');
  var refEl=document.getElementById('v_ref');
  var payload={
    id: idEl ? idEl.value : '',
    display_name: nmEl ? nmEl.value : '',
    engine: engEl ? engEl.value : '',
    voice_ref: refEl ? refEl.value : ''
  };
  return fetchJsonAuthed('/api/voices', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)})
    .then(function(j){
      if (j && j.ok){
        try{ toastSet('Voice created', 'ok', 2600); window.__sfToastInit && window.__sfToastInit(); }catch(e){}
        if (idEl) idEl.value='';
        if (nmEl) nmEl.value='';
        if (engEl) engEl.value='';
        if (refEl) refEl.value='';
        return loadVoices();
      }
      alert((j && j.error) ? j.error : 'Create failed');
    })
    .catch(function(e){ alert(String(e)); });
}


function renameVoiceEl(btn){
  try{
    var idEnc = btn ? (btn.getAttribute('data-vid')||'') : '';
    return renameVoice(idEnc);
  }catch(e){}
}

function disableVoiceEl(btn){
  try{
    var idEnc = btn ? (btn.getAttribute('data-vid')||'') : '';
    return disableVoice(idEnc);
  }catch(e){}
}

function renameVoice(idEnc){
  var id = decodeURIComponent(idEnc||'');
  var nm = prompt('New voice name:', '');
  if (nm==null) return;
  nm = String(nm||'').trim();
  if (!nm) return;
  return fetchJsonAuthed('/api/voices/' + encodeURIComponent(id), {method:'PUT', headers:{'Content-Type':'application/json'}, body: JSON.stringify({display_name: nm})})
    .then(function(j){
      if (j && j.ok){
        try{ toastSet('Saved', 'ok', 2200); window.__sfToastInit && window.__sfToastInit(); }catch(e){}
        return loadVoices();
      }
      alert((j && j.error) ? j.error : 'Rename failed');
    })
    .catch(function(e){ alert(String(e)); });
}

function disableVoice(idEnc){
  var id = decodeURIComponent(idEnc||'');
  if (!confirm('Disable this voice?')) return;
  return fetchJsonAuthed('/api/voices/' + encodeURIComponent(id) + '/disable', {method:'POST'})
    .then(function(j){
      if (j && j.ok){
        try{ toastSet('Disabled', 'ok', 2200); window.__sfToastInit && window.__sfToastInit(); }catch(e){}
        return loadVoices();
      }
      alert((j && j.error) ? j.error : 'Disable failed');
    })
    .catch(function(e){ alert(String(e)); });
}


function loadLibrary(){
  const el=document.getElementById('lib');
  el.textContent='Loading…';
  document.getElementById('libDetailCard').style.display='none';

  return fetchJsonAuthed('/api/library/stories').then(function(j){
  if (!j.ok){ el.innerHTML = `<div class='muted'>Error loading library</div>`; return; }


    var stories = j.stories || [];
    if (!j.ok){ el.innerHTML = `<div class='muted'>Error loading library</div>`; return; }
    if (!stories.length){ el.innerHTML = `<div class='muted'>No stories yet. Add folders under <code>stories/</code>.</div>`; return; }

      el.innerHTML = stories.map(st => {
    var chars = Array.isArray(st.characters) ? st.characters : [];
    var names = chars.map(function(c){ return (c && (c.name || c.id)) ? String(c.name || c.id) : ''; }).filter(Boolean);
    var shown = names.slice(0,3);
    var more = Math.max(0, names.length - shown.length);
    var charsLine = '';
    if (shown.length){
      charsLine = shown.join(', ');
      if (more>0) charsLine += ' (+' + String(more) + ')';
    }

    return '<a href="/library/story/' + encodeURIComponent(st.id) + '/view" style="text-decoration:none;color:inherit">'
      + '<div class="job">'
      + '<div class="row" style="justify-content:space-between;">'
      + '<div class="title">' + (st.title || st.id) + '</div>'
      + '</div>'
      + (charsLine ? ("<div class='muted' style='margin-top:6px'>" + charsLine + "</div>") : '')
      + '</div></a>';
    }).join('');
  }).catch(function(e){
    el.innerHTML = `<div class='muted'>Error loading library: ${String(e)}</div>`;
  });
}

let currentStory = null;

function openStory(id){
  return fetchJsonAuthed('/api/library/story/' + encodeURIComponent(id)).then(function(j){
    if (!j.ok){ alert('Error loading story'); return; }
    currentStory = j.story;
    const meta = currentStory.meta || {};

  document.getElementById('libTitle').textContent = meta.title || currentStory.id;
  
  const chars = (currentStory.characters || []).map(c => {
    const nm = c.name || c.id || '';
    const ty = c.type || '';
    const desc = c.description || '';
    return `- ${nm}${ty?` (${ty})`:''}${desc?`: ${desc}`:''}`;
  }).join('\\n') || '(none)';

  document.getElementById('libChars').textContent = chars;
  document.getElementById('libStory').textContent = currentStory.story_md || '';

  document.getElementById('libDetailCard').style.display='block';
  }).catch(function(e){ alert('Error loading story'); });
}

function closeStory(){
  document.getElementById('libDetailCard').style.display='none';
  currentStory = null;
}

function copyStory(){
  const txt = (currentStory && currentStory.story_md) ? currentStory.story_md : ''; 
  if (txt) copyToClipboard(txt);
}


function refreshAll(){
  // best-effort refresh without allSettled for older Safari
  try{ var p = loadHistory(); if (p && p.catch) p.catch(function(_e){}); }catch(_e){}
}

function setBar(elId, pct){
  const el=document.getElementById(elId);
  if (!el) return;
  const p=Math.max(0, Math.min(100, pct||0));
  const fill=el.querySelector('div');
  if (fill) fill.style.width = p.toFixed(0) + '%';
  el.classList.remove('warn','bad');
  if (p >= 85) el.classList.add('bad');
  else if (p >= 60) el.classList.add('warn');
}

function fmtPct(x){
  if (x==null) return '—';
  return (Number(x).toFixed(1)) + '%';
}

function openMonitor(){
  if (!monitorEnabled) return;
  try{ bindMonitorClose(); }catch(e){}
  var b=document.getElementById('monitorBackdrop');
  var sh=document.getElementById('monitorSheet');
  if (b){ b.classList.remove('hide'); b.style.display='block'; }
  if (sh){ sh.classList.remove('hide'); sh.style.display='block'; }
  try{ document.body.classList.add('noScroll'); }catch(e){}
  try{ document.body.classList.add('sheetOpen'); }catch(e){}
  const ds=document.getElementById('dockStats'); if (ds) ds.textContent='Connecting…';
  startMetricsStream();
  if (lastMetrics) updateMonitorFromMetrics(lastMetrics);
}

function closeMonitor(){
  var b=document.getElementById('monitorBackdrop');
  var sh=document.getElementById('monitorSheet');
  if (b){ b.classList.add('hide'); b.style.display='none'; }
  if (sh){ sh.classList.add('hide'); sh.style.display='none'; }
  try{ document.body.classList.remove('noScroll'); }catch(e){}
  try{ document.body.classList.remove('sheetOpen'); }catch(e){}
}

function closeMonitorEv(ev){
  try{ if (ev && ev.stopPropagation) ev.stopPropagation(); }catch(e){}
  closeMonitor();
  return false;
}


// iOS Safari sometimes misses click events on fixed sheets; bind touchend as well.
function bindMonitorClose(){
  try{
    var btn = document.getElementById('monCloseBtn');
    if (btn && !btn.__bound){
      btn.__bound = true;
      btn.addEventListener('touchend', function(ev){ closeMonitorEv(ev); }, {passive:false});
      btn.addEventListener('click', function(ev){ closeMonitorEv(ev); });
    }
  }catch(e){}
}
try{ document.addEventListener('DOMContentLoaded', bindMonitorClose); }catch(e){}
try{ bindMonitorClose(); }catch(e){}

function renderGpus(b){
  const el = document.getElementById('monGpus');
  if (!el) return;
  const gpus = Array.isArray(b?.gpus) ? b.gpus : (b?.gpu ? [b.gpu] : []);
  if (!gpus.length){
    el.innerHTML = '<div class="muted">No GPU data</div>';
    return;
  }

  el.innerHTML = gpus.slice(0,8).map((g,i)=>{
    const idx = (g.index!=null) ? g.index : i;
    const util = Number(g.util_gpu_pct||0);
    const power = (g.power_w!=null) ? Number(g.power_w).toFixed(0)+'W' : null;
    const temp = (g.temp_c!=null) ? Number(g.temp_c).toFixed(0)+'C' : null;
    const right = [power, temp].filter(Boolean).join(' • ');

    const vt = Number(g.vram_total_mb||0);
    const vu = Number(g.vram_used_mb||0);
    const vp = vt ? (vu/vt*100) : 0;

    return `<div class='gpuCard'>
      <div class='gpuHead'>
        <div class='l'>GPU ${idx}</div>
        <div class='r'>${right || ''}</div>
      </div>

      <div class='gpuRow'>
        <div class='k'>Util</div>
        <div class='v'>${fmtPct(util)}</div>
      </div>
      <div class='bar small' id='barGpu${idx}'><div></div></div>

      <div class='gpuRow' style='margin-top:10px'>
        <div class='k'>VRAM</div>
        <div class='v'>${vt ? `${(vu/1024).toFixed(1)} / ${(vt/1024).toFixed(1)} GB` : '—'}</div>
      </div>
      <div class='bar small' id='barVram${idx}'><div></div></div>
    </div>`;
  }).join('');

  gpus.slice(0,8).forEach((g,i)=>{
    const idx = (g.index!=null) ? g.index : i;
    const util = Number(g.util_gpu_pct||0);
    const vt = Number(g.vram_total_mb||0);
    const vu = Number(g.vram_used_mb||0);
    const vp = vt ? (vu/vt*100) : 0;
    setBar(`barGpu${idx}`, util);
    setBar(`barVram${idx}`, vp);
  });
}

function updateDockFromMetrics(m){
  const el = document.getElementById('dockStats');
  if (!el) return;
  const b = m?.body || m || {};
  const cpu = (b.cpu_pct!=null) ? Number(b.cpu_pct).toFixed(1)+'%' : '—';
  const rt = Number(b.ram_total_mb||0); const ru = Number(b.ram_used_mb||0);
  const rp = rt ? (ru/rt*100) : 0;
  const ram = rt ? rp.toFixed(1)+'%' : '—';
  const gpus = Array.isArray(b?.gpus) ? b.gpus : (b?.gpu ? [b.gpu] : []);
  let maxGpu = null;
  if (gpus.length){
    maxGpu = 0;
    for (const g of gpus){
      const u = Number(g.util_gpu_pct||0);
      if (u > maxGpu) maxGpu = u;
    }
  }
  const gpu = (maxGpu==null) ? '—' : maxGpu.toFixed(1)+'%';
  el.textContent = `CPU ${cpu} • RAM ${ram} • GPU ${gpu}`;
}


function updateMonitorFromMetrics(m){
  // m is the /api/metrics response: {status, body}
  const b = m?.body || m || {};
  const cpu = Number(b.cpu_pct || 0);
  document.getElementById('monCpu').textContent = fmtPct(cpu);
  setBar('barCpu', cpu);

  const rt = Number(b.ram_total_mb || 0);
  const ru = Number(b.ram_used_mb || 0);
  const rp = rt ? (ru/rt*100) : 0;
  document.getElementById('monRam').textContent = rt ? `${ru.toFixed(0)} / ${rt.toFixed(0)} MB (${rp.toFixed(1)}%)` : '—';
  setBar('barRam', rp);
  renderGpus(b);

  const ts = b.ts ? fmtTs(b.ts) : '—';
  document.getElementById('monSub').textContent = `Tinybox time: ${ts}`;
    updateDockFromMetrics(m);
}

function tts(){
  var payload = {
    engine: document.getElementById('engine').value,
    voice: document.getElementById('voice').value,
    text: document.getElementById('text').value,
    upload: true,
  };
  return fetch('/api/tts', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)})
    .then(function(r){ return r.text(); })
    .then(function(t){ document.getElementById('ttsout').textContent = t; })
    .catch(function(e){ document.getElementById('ttsout').textContent = String(e); });
}

// boot status

// Emergency hash: #close-monitor will force-close and disable monitor (useful if iOS gets stuck)
try{
  if ((window.location.hash||'') === '#close-monitor'){
    emergencyKillMonitor();
    // clear hash so back button doesn't keep killing
    try{ history.replaceState(null,'', window.location.pathname + window.location.search); }catch(e){}
  }
}catch(e){}

try{
  var __bootEl = document.getElementById('boot');
  if (__bootEl) __bootEl.textContent = 'Build: ' + (window.__SF_BUILD||'?') + ' • JS: running';
}catch(_e){}

var initTab = getTabFromHash() || getQueryParam('tab');
if (initTab==='library' || initTab==='history' || initTab==='advanced') { try{ showTab(initTab); }catch(e){} }

refreshAll();
// Start streaming immediately so the Metrics tab is instant.
setMonitorEnabled(loadMonitorPref());
setDebugUiEnabled(loadDebugPref());
loadHistory();

try{
  if (__bootEl) __bootEl.textContent = 'Build: ' + (window.__SF_BUILD||'?') + ' • JS: ok';
}catch(_e){}
</script>


  

  <div id='monitorDock' class='dock' onclick='openMonitor()'>
    <div class='dockInner'>
      <div style='font-weight:950;'>Monitor</div>
      <div class='dockStats' id='dockStats'>Monitor off</div>
    </div>
  </div>

<div id='monitorBackdrop' class='sheetBackdrop hide' style='display:none' onclick='closeMonitorEv(event)' ontouchend='closeMonitorEv(event)'></div>
  <div id='monitorSheet' class='sheet hide' style='display:none' role='dialog' aria-modal='true'>
    <div class='sheetInner'>
      <div class='sheetHandle'></div>
      <div class='row' style='justify-content:space-between;'>
        <div>
          <div class='sheetTitle'>System monitor</div>
          <div id='monSub' class='muted'>Connecting…</div>
        </div>
        <div class='row'>
          <button id='monCloseBtn' class='secondary' type='button' onclick='closeMonitorEv(event)'>Close</button>
        </div>
      </div>

      <div class='grid2' style='margin-top:10px;'>
        <div class='meter'>
          <div class='k'>CPU</div>
          <div class='v' id='monCpu'>—</div>
          <div class='bar' id='barCpu'><div></div></div>
        </div>
        <div class='meter'>
          <div class='k'>RAM</div>
          <div class='v' id='monRam'>—</div>
          <div class='bar' id='barRam'><div></div></div>
        </div>
      </div>

      <div style='font-weight:950;margin-top:12px;'>GPUs</div>
      <div id='monGpus' class='gpuGrid' style='margin-top:8px;'></div>

      <div style='font-weight:950;margin-top:12px;'>Processes</div>
      <div class='muted'>Live from Tinybox (top CPU/RAM/GPU mem).</div>
      <pre id='monProc' class='term' style='margin-top:8px;max-height:42vh;overflow:auto;-webkit-overflow-scrolling:touch;'>Loading…</pre>
    </div>

      

</body>
</html>"""

    return html.replace("__BUILD__", str(build)).replace("__VOICE_SERVERS__", voice_servers_html)


@app.get('/api/ping')
def api_ping():
    r = requests.get(GATEWAY_BASE + '/ping', timeout=4)
    r.raise_for_status()
    return r.json()


@app.get('/api/metrics')
def api_metrics():
    return _get('/v1/metrics')


@app.get('/api/metrics/stream')
def api_metrics_stream():
    def gen():
        # Keep-alive + periodic samples. EventSource will auto-reconnect.
        while True:
            try:
                m = _get('/v1/metrics')
                data = json.dumps(m, separators=(',', ':'))
                yield f"data: {data}\n\n"
            except Exception as e:
                # Don't leak secrets; just emit a small error payload.
                yield f"data: {json.dumps({'ok': False, 'error': type(e).__name__})}\n\n"
            time.sleep(1.0)

    headers = {
        'Cache-Control': 'no-store',
        'X-Accel-Buffering': 'no',
    }
    return StreamingResponse(gen(), media_type='text/event-stream', headers=headers)






@app.get('/api/voices')
def api_voices_list():
    try:
        conn = db_connect()
        try:
            db_init(conn)
            return {'ok': True, 'voices': list_voices_db(conn)}
        finally:
            conn.close()
    except Exception as e:
        return {'ok': False, 'error': f'voices_failed: {type(e).__name__}: {e}'}


@app.post('/api/voices')
def api_voices_create(payload: dict[str, Any]):
    try:
        voice_id = validate_voice_id(str(payload.get('id') or ''))
        engine = str(payload.get('engine') or '')
        voice_ref = str(payload.get('voice_ref') or '')
        display_name = str(payload.get('display_name') or payload.get('name') or voice_id)
        enabled = bool(payload.get('enabled', True))
        sample_text = str(payload.get('sample_text') or '')
        sample_url = str(payload.get('sample_url') or '')

        conn = db_connect()
        try:
            db_init(conn)
            upsert_voice_db(conn, voice_id, engine, voice_ref, display_name, enabled, sample_text, sample_url)
        finally:
            conn.close()
        return {'ok': True}
    except Exception as e:
        return {'ok': False, 'error': f'create_failed: {type(e).__name__}: {e}'}


@app.get('/api/voices/{voice_id}')
def api_voices_get(voice_id: str):
    try:
        voice_id = validate_voice_id(voice_id)
        conn = db_connect()
        try:
            db_init(conn)
            v = get_voice_db(conn, voice_id)
        finally:
            conn.close()
        return {'ok': True, 'voice': v}
    except Exception as e:
        return {'ok': False, 'error': f'get_failed: {type(e).__name__}: {e}'}


@app.put('/api/voices/{voice_id}')
def api_voices_update(voice_id: str, payload: dict[str, Any]):
    try:
        voice_id = validate_voice_id(voice_id)
        conn = db_connect()
        try:
            db_init(conn)
            existing = get_voice_db(conn, voice_id)
            engine = str(payload.get('engine') if 'engine' in payload else existing.get('engine') or '')
            voice_ref = str(payload.get('voice_ref') if 'voice_ref' in payload else existing.get('voice_ref') or '')
            display_name = str(payload.get('display_name') if 'display_name' in payload else existing.get('display_name') or voice_id)
            enabled = bool(payload.get('enabled') if 'enabled' in payload else existing.get('enabled', True))
            sample_text = str(payload.get('sample_text') if 'sample_text' in payload else existing.get('sample_text') or '')
            sample_url = str(payload.get('sample_url') if 'sample_url' in payload else existing.get('sample_url') or '')
            upsert_voice_db(conn, voice_id, engine, voice_ref, display_name, enabled, sample_text, sample_url)
        finally:
            conn.close()
        return {'ok': True}
    except Exception as e:
        return {'ok': False, 'error': f'update_failed: {type(e).__name__}: {e}'}


@app.post('/api/voices/{voice_id}/disable')
def api_voices_disable(voice_id: str):
    try:
        voice_id = validate_voice_id(voice_id)
        conn = db_connect()
        try:
            db_init(conn)
            set_voice_enabled_db(conn, voice_id, False)
        finally:
            conn.close()
        return {'ok': True}
    except Exception as e:
        return {'ok': False, 'error': f'disable_failed: {type(e).__name__}: {e}'}


@app.delete('/api/voices/{voice_id}')
def api_voices_delete(voice_id: str):
    try:
        voice_id = validate_voice_id(voice_id)
        conn = db_connect()
        try:
            db_init(conn)
            delete_voice_db(conn, voice_id)
        finally:
            conn.close()
        return {'ok': True}
    except Exception as e:
        return {'ok': False, 'error': f'delete_failed: {type(e).__name__}: {e}'}


@app.get('/api/library/stories')
def api_library_stories():
    try:
        conn = db_connect()
        try:
            db_init(conn)
            return {'ok': True, 'stories': list_stories_db(conn)}
        finally:
            conn.close()
    except Exception as e:
        return {'ok': False, 'error': f'library_failed: {type(e).__name__}: {e}'}


@app.get('/api/library/story/{story_id}')
def api_library_story(story_id: str):
    try:
        conn = db_connect()
        try:
            db_init(conn)
            story = get_story_db(conn, story_id)
        finally:
            conn.close()
    except FileNotFoundError:
        return Response(content='not found', status_code=404)
    except Exception as e:
        return {'ok': False, 'error': f'library_failed: {type(e).__name__}: {e}'}
    return {'ok': True, 'story': story}


@app.post('/api/library/story')
def api_library_story_create(payload: dict[str, Any]):
    try:
        story_id = validate_story_id(str(payload.get('id') or ''))
        title = str(payload.get('title') or story_id)
        story_md = str(payload.get('story_md') or '')
        characters = payload.get('characters') or []
        conn = db_connect()
        try:
            db_init(conn)
            upsert_story_db(conn, story_id, title, story_md, characters)
        finally:
            conn.close()
        return {'ok': True, 'id': story_id}
    except Exception as e:
        return {'ok': False, 'error': f'create_failed: {type(e).__name__}: {e}'}


@app.put('/api/library/story/{story_id}')
def api_library_story_update(story_id: str, payload: dict[str, Any]):
    try:
        story_id = validate_story_id(story_id)
        conn = db_connect()
        try:
            db_init(conn)
            existing = get_story_db(conn, story_id)
            meta = existing.get('meta') or {}

            title = str(payload['title']) if 'title' in payload else str(meta.get('title') or story_id)
            story_md = str(payload['story_md']) if 'story_md' in payload else str(existing.get('story_md') or '')
            characters = payload['characters'] if 'characters' in payload else list(existing.get('characters') or [])

            upsert_story_db(conn, story_id, title, story_md, characters)
        finally:
            conn.close()
        return {'ok': True}
    except Exception as e:
        return {'ok': False, 'error': f'update_failed: {type(e).__name__}: {e}'}


@app.delete('/api/library/story/{story_id}')
def api_library_story_delete(story_id: str):
    try:
        story_id = validate_story_id(story_id)
        conn = db_connect()
        try:
            db_init(conn)
            delete_story_db(conn, story_id)
        finally:
            conn.close()
        return {'ok': True}
    except Exception as e:
        return {'ok': False, 'error': f'delete_failed: {type(e).__name__}: {e}'}


@app.get('/api/history')
def api_history(limit: int = 60):
    try:
        conn = db_connect()
        try:
            db_init(conn)
            jobs = db_list_jobs(conn, limit=limit)
        finally:
            conn.close()
        return {'ok': True, 'jobs': jobs}
    except Exception as e:
        # Avoid leaking DATABASE_URL or secrets; keep message short.
        return {'ok': False, 'error': f'{type(e).__name__}: {str(e)[:200]}'}


@app.post('/api/tts')
def api_tts(payload: dict[str, Any]):
    r = requests.post(GATEWAY_BASE + '/v1/tts', json=payload, headers=_h(), timeout=120)
    try:
        body = r.json()
    except Exception:
        body = r.text
    return {"status": r.status_code, "body": body}
