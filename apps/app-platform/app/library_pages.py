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
    .top{display:grid;grid-template-columns:minmax(0,1fr) auto;column-gap:12px;row-gap:10px;align-items:start;}
    .brandRow{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;}
    .pageName{color:var(--muted);font-weight:900;font-size:12px;}
    .menuWrap{position:relative;display:inline-block;}
    .userBtn{width:38px;height:38px;border-radius:999px;border:1px solid var(--line);background:transparent;color:var(--text);font-weight:950;display:inline-flex;align-items:center;justify-content:center;}
    .userBtn:hover{background:rgba(255,255,255,0.06);}
    .menuCard{position:absolute;right:0;top:46px;min-width:240px;max-width:calc(100vw - 36px);background:var(--card);border:1px solid var(--line);border-radius:16px;padding:12px;display:none;z-index:60;box-shadow:0 18px 60px rgba(0,0,0,.45);}
    .menuCard.show{display:block;}

    /* Mobile: render the user menu as a bottom sheet so it doesn't distort the header */
    @media (max-width:520px){
      .menuCard{position:fixed;left:14px;right:14px;top:auto;bottom:calc(14px + env(safe-area-inset-bottom));min-width:0;max-width:none;}
    }
    .menuCard .uTop{display:flex;gap:10px;align-items:center;margin-bottom:10px;}
    .menuCard .uAvatar{width:36px;height:36px;border-radius:999px;background:#0b1020;border:1px solid var(--line);display:flex;align-items:center;justify-content:center;}
    .menuCard .uName{font-weight:950;}
    .menuCard .uSub{color:var(--muted);font-size:12px;margin-top:2px;}
    .menuCard .uActions{display:flex;gap:10px;justify-content:flex-end;margin-top:10px;}

    @media (max-width:520px){
      .top{align-items:flex-start;}
      .rowEnd{margin-left:0;width:100%;justify-content:flex-start;}
    }
    h1{font-size:20px;margin:0;}
    .muted{color:var(--muted);font-size:12px;}
    .card{border:1px solid var(--line);border-radius:16px;padding:12px;margin:12px 0;background:var(--card);}
    .row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;}
    .rowBetween{justify-content:space-between;}
    .rowEnd{justify-content:flex-end;margin-left:auto;}
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

    /* Debug banner + copy button (match main page) */
    .boot{margin:8px 0 10px 0;margin-top:10px;padding:10px 12px;border-radius:14px;border:1px dashed rgba(168,179,216,.35);background:rgba(7,11,22,.35);display:flex;align-items:center;gap:10px;}
    .boot strong{color:var(--text);}
    .copyBtn{border:1px solid var(--line);background:transparent;color:var(--text);font-weight:900;border-radius:10px;padding:6px;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;width:34px;height:30px;}
    .copyBtn:active{transform:translateY(1px);}
    .copyBtn svg{display:block;width:18px;height:18px;stroke:currentColor;fill:none;stroke-width:2;}
    .copyBtn:hover{background:rgba(255,255,255,0.06);}

    /* No-wrap horizontally-scrollable text row (match main page) */
    .fadeLine{position:relative;display:flex;align-items:center;gap:8px;min-width:0;}
    .fadeText{flex:1;min-width:0;white-space:nowrap;overflow-x:auto;overflow-y:hidden;color:var(--muted);-webkit-overflow-scrolling:touch;scrollbar-width:none;}
    .fadeText::-webkit-scrollbar{display:none;}
  
"""

# Shared monitor UI (dock + bottom sheet) so all pages match the main template.
LIBRARY_BASE_CSS += """

    /* bottom dock */
    .dock{display:block;position:fixed;left:0;right:0;bottom:0;z-index:1500;background:rgba(15,23,51,.92);backdrop-filter:blur(10px);border-top:1px solid var(--line);padding:10px 12px calc(10px + env(safe-area-inset-bottom)) 12px;}
    .dockInner{max-width:920px;margin:0 auto;display:flex;justify-content:space-between;align-items:center;gap:10px;}
    .dockStats{color:var(--muted);font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:70%;}
    body.sheetOpen .dock{pointer-events:none;}

    /* bottom sheet */
    .sheetBackdrop{display:none;position:fixed;inset:0;background:rgba(0,0,0,.55);backdrop-filter:blur(3px);z-index:2000;touch-action:none;}
    .sheet{will-change:transform;display:none;position:fixed;left:0;right:0;bottom:0;z-index:2001;background:var(--card);border-top:1px solid var(--line);border-top-left-radius:18px;border-top-right-radius:18px;max-height:78vh;box-shadow:0 -18px 60px rgba(0,0,0,.45);overflow:hidden;}
    html.monOn .sheetBackdrop{display:block;}
    html.monOn .sheet{display:block;}
    .sheetInner{max-width:920px;margin:0 auto;padding:12px;}
    .sheetHandle{width:46px;height:5px;border-radius:999px;background:rgba(255,255,255,.18);margin:2px auto 10px auto;}
    .sheetTitle{font-weight:950;}

    .grid2{display:grid;grid-template-columns:1fr 1fr;gap:10px;}
    .meter .k{color:var(--muted);font-size:12px;font-weight:900;}
    .meter .v{font-weight:950;margin-top:4px;}
    .bar{height:10px;background:#0a0f20;border:1px solid rgba(255,255,255,.08);border-radius:999px;overflow:hidden;margin-top:8px;}
    .bar > div{height:100%;width:0%;background:linear-gradient(90deg,#4aa3ff,#26d07c);}
    .bar.warn > div{background:linear-gradient(90deg,#ffcc00,#ff7a00);}
    .bar.bad > div{background:linear-gradient(90deg,#ff4d4d,#ff2e83);}
    .bar.small{height:8px;margin-top:6px;}

    .gpuGrid{display:grid;grid-template-columns:1fr 1fr;gap:10px;}
    .gpuCard{border:1px solid rgba(255,255,255,0.10);border-radius:14px;background:#0b1020;padding:10px;}
    .gpuHead{display:flex;justify-content:space-between;gap:10px;}
    .gpuHead .l{font-weight:950;}
    .gpuHead .r{color:var(--muted);font-size:12px;white-space:nowrap;}
    .gpuRow{display:flex;justify-content:space-between;gap:10px;margin-top:8px;}
    .gpuRow .k{color:var(--muted);font-size:12px;font-weight:900;}
    .gpuRow .v{font-weight:950;}

    @media (max-width:520px){
      .grid2{grid-template-columns:1fr;}
      .gpuGrid{grid-template-columns:1fr 1fr;}
    }
"""

MONITOR_HTML = """
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
        <div class='row' style='justify-content:flex-end;'>
          <button id='monCloseBtn' class='secondary' type='button' onclick='closeMonitorEv(event)'>Close</button>
        </div>
      </div>

      <div class='grid2' style='margin-top:10px;'>
        <div class='meter'>
          <div class='k'>CPU</div>
          <div class='v' id='monCpu'>-</div>
          <div class='bar' id='barCpu'><div></div></div>
        </div>
        <div class='meter'>
          <div class='k'>RAM</div>
          <div class='v' id='monRam'>-</div>
          <div class='bar' id='barRam'><div></div></div>
        </div>
      </div>

      <div style='font-weight:950;margin-top:12px;'>GPUs</div>
      <div id='monGpus' class='gpuGrid' style='margin-top:8px;'></div>

      <div style='font-weight:950;margin-top:12px;'>Processes</div>
      <div class='muted'>Live from Tinybox (top CPU/RAM/GPU mem).</div>
      <pre id='monProc' class='term' style='margin-top:8px;max-height:42vh;overflow:auto;-webkit-overflow-scrolling:touch;'>Loading…</pre>
    </div>
  </div>
"""

MONITOR_JS = """
<script>
let metricsES = null;
let monitorEnabled = true;
let lastMetrics = null;

function loadMonitorPref(){
  try{ var v = localStorage.getItem('sf_monitor_enabled'); if (v === null) return true; return v === '1'; }catch(e){ return true; }
}
function saveMonitorPref(on){ try{ localStorage.setItem('sf_monitor_enabled', on ? '1' : '0'); }catch(e){} }
function stopMetricsStream(){ if (metricsES){ try{ metricsES.close(); }catch(e){} metricsES=null; } }
function setBar(elId, pct){
  var el=document.getElementById(elId); if (!el) return;
  var p=Math.max(0, Math.min(100, pct||0));
  var fill=el.querySelector('div'); if (fill) fill.style.width=p.toFixed(0)+'%';
  el.classList.remove('warn','bad');
  if (p>=85) el.classList.add('bad'); else if (p>=60) el.classList.add('warn');
}
function fmtPct(x){ if (x==null) return '-'; return (Number(x).toFixed(1)) + '%'; }
function fmtTs(ts){ if(!ts) return '-'; try{ return new Date(ts*1000).toLocaleString(); }catch(e){ return String(ts);} }

function updateDockFromMetrics(m){
  var el=document.getElementById('dockStats'); if(!el) return;
  var b=(m && m.body) ? m.body : (m||{});
  var cpu=(b.cpu_pct!=null)?Number(b.cpu_pct).toFixed(1)+'%':'-';
  var rt=Number(b.ram_total_mb||0), ru=Number(b.ram_used_mb||0);
  var rp=rt?(ru/rt*100):0; var ram=rt?rp.toFixed(1)+'%':'-';
  var gpus=Array.isArray(b.gpus)?b.gpus:(b.gpu?[b.gpu]:[]);
  var maxGpu=null; if(gpus.length){ maxGpu=0; for(var i=0;i<gpus.length;i++){ var u=Number((gpus[i]||{}).util_gpu_pct||0); if(u>maxGpu) maxGpu=u; } }
  var gpu=(maxGpu==null)?'-':maxGpu.toFixed(1)+'%';
  el.textContent='CPU '+cpu+' • RAM '+ram+' • GPU '+gpu;
}

function renderGpus(b){
  var el=document.getElementById('monGpus'); if(!el) return;
  var gpus=Array.isArray(b.gpus)?b.gpus:(b.gpu?[b.gpu]:[]);
  if(!gpus.length){ el.innerHTML='<div class="muted">No GPU data</div>'; return; }
  el.innerHTML=gpus.slice(0,8).map(function(g,i){
    g=g||{}; var idx=(g.index!=null)?g.index:i;
    var util=Number(g.util_gpu_pct||0);
    var power=(g.power_w!=null)?Number(g.power_w).toFixed(0)+'W':null;
    var temp=(g.temp_c!=null)?Number(g.temp_c).toFixed(0)+'C':null;
    var right=[power,temp].filter(Boolean).join(' • ');
    var vt=Number(g.vram_total_mb||0), vu=Number(g.vram_used_mb||0);
    var vp=vt?(vu/vt*100):0;
    return "<div class='gpuCard'>"+
      "<div class='gpuHead'><div class='l'>GPU "+idx+"</div><div class='r'>"+(right||'')+"</div></div>"+
      "<div class='gpuRow'><div class='k'>Util</div><div class='v'>"+fmtPct(util)+"</div></div>"+
      "<div class='bar small' id='barGpu"+idx+"'><div></div></div>"+
      "<div class='gpuRow' style='margin-top:10px'><div class='k'>VRAM</div><div class='v'>"+(vt?((vu/1024).toFixed(1)+' / '+(vt/1024).toFixed(1)+' GB'):'-')+"</div></div>"+
      "<div class='bar small' id='barVram"+idx+"'><div></div></div>"+
      "</div>";
  }).join('');
  gpus.slice(0,8).forEach(function(g,i){
    g=g||{}; var idx=(g.index!=null)?g.index:i;
    setBar('barGpu'+idx, Number(g.util_gpu_pct||0));
    var vt=Number(g.vram_total_mb||0), vu=Number(g.vram_used_mb||0);
    setBar('barVram'+idx, vt?(vu/vt*100):0);
  });
}

function updateMonitorFromMetrics(m){
  var b=(m && m.body) ? m.body : (m||{});
  var cpu=Number(b.cpu_pct||0);
  var c=document.getElementById('monCpu'); if(c) c.textContent=fmtPct(cpu);
  setBar('barCpu', cpu);
  var rt=Number(b.ram_total_mb||0), ru=Number(b.ram_used_mb||0);
  var rp=rt?(ru/rt*100):0;
  var r=document.getElementById('monRam'); if(r) r.textContent=rt?(ru.toFixed(0)+' / '+rt.toFixed(0)+' MB ('+rp.toFixed(1)+'%)'):'-';
  setBar('barRam', rp);
  renderGpus(b);
  var sub=document.getElementById('monSub'); if(sub) sub.textContent='Tinybox time: '+(b.ts?fmtTs(b.ts):'-');
  updateDockFromMetrics(m);
  try{
    var procs=Array.isArray(b.processes)?b.processes:[];
    var pre=document.getElementById('monProc');
    if(pre){
      if(!procs.length) pre.textContent='(no process data)';
      else{
        var lines=['PID     %CPU   %MEM   GPU   ELAPSED   COMMAND','-----------------------------------------------'];
        for(var i=0;i<procs.length;i++){
          var p=procs[i]||{};
          var pid=String(p.pid||'').padEnd(7,' ');
          var cpuS=String(Number(p.cpu_pct||0).toFixed(1)).padStart(5,' ');
          var memS=String(Number(p.mem_pct||0).toFixed(1)).padStart(5,' ');
          var gpuS=(p.gpu_mem_mb!=null?String(Number(p.gpu_mem_mb).toFixed(0))+'MB':'-').padStart(6,' ');
          var et=String(p.elapsed||'').padEnd(9,' ');
          var cmd=String(p.args||p.command||p.name||'');
          lines.push(pid+'  '+cpuS+'  '+memS+'  '+gpuS+'  '+et+'  '+cmd);
        }
        pre.textContent=lines.join('\\n');
      }
    }
  }catch(e){}
}

function startMetricsStream(){
  if(!monitorEnabled) return;
  stopMetricsStream();
  try{ var ds=document.getElementById('dockStats'); if(ds) ds.textContent='Connecting…'; }catch(e){}
  try{
    metricsES = new EventSource('/api/metrics/stream');
    metricsES.onmessage=function(ev){ try{ var m=JSON.parse(ev.data||'{}'); lastMetrics=m; updateMonitorFromMetrics(m);}catch(e){} };
    metricsES.onerror=function(_e){ try{ var ds=document.getElementById('dockStats'); if(ds) ds.textContent='Monitor error'; }catch(e){} };
  }catch(e){}
}

function setMonitorEnabled(on){
  monitorEnabled=!!on;
  saveMonitorPref(monitorEnabled);
  try{ document.documentElement.classList.toggle('monOn', !!monitorEnabled); }catch(e){}
  if(!monitorEnabled){ stopMetricsStream(); try{ var ds=document.getElementById('dockStats'); if(ds) ds.textContent='Monitor off'; }catch(e){} return; }
  startMetricsStream();
}

function openMonitor(){
  if(!monitorEnabled) return;
  var b=document.getElementById('monitorBackdrop');
  var sh=document.getElementById('monitorSheet');
  if(b){ b.classList.remove('hide'); b.style.display='block'; }
  if(sh){ sh.classList.remove('hide'); sh.style.display='block'; }
  try{ document.body.classList.add('sheetOpen'); }catch(e){}
  startMetricsStream();
  if(lastMetrics) updateMonitorFromMetrics(lastMetrics);
}

function closeMonitor(){
  var b=document.getElementById('monitorBackdrop');
  var sh=document.getElementById('monitorSheet');
  if(b){ b.classList.add('hide'); b.style.display='none'; }
  if(sh){ sh.classList.add('hide'); sh.style.display='none'; }
  try{ document.body.classList.remove('sheetOpen'); }catch(e){}
}

function closeMonitorEv(ev){ try{ if(ev && ev.stopPropagation) ev.stopPropagation(); }catch(e){} closeMonitor(); return false; }

function bindMonitorClose(){
  try{
    var btn=document.getElementById('monCloseBtn');
    if(btn && !btn.__bound){
      btn.__bound=true;
      btn.addEventListener('touchend', function(ev){ closeMonitorEv(ev); }, {passive:false});
      btn.addEventListener('click', function(ev){ closeMonitorEv(ev); });
    }
  }catch(e){}
}

try{ document.addEventListener('DOMContentLoaded', function(){ bindMonitorClose(); setMonitorEnabled(loadMonitorPref()); }); }catch(e){}
try{ bindMonitorClose(); setMonitorEnabled(loadMonitorPref()); }catch(e){}
</script>
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
{MONITOR_HTML}
{MONITOR_JS}
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
