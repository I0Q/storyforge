from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import json
import time

import requests
from fastapi import FastAPI

from .db import db_connect, db_init, db_list_jobs
from fastapi.responses import HTMLResponse, StreamingResponse

APP_NAME = "storyforge"

GATEWAY_BASE = os.environ.get("GATEWAY_BASE", "http://10.108.0.3:8791").rstrip("/")
GATEWAY_TOKEN = os.environ.get("GATEWAY_TOKEN", "")

app = FastAPI(title=APP_NAME, version="0.1")


def _h() -> dict[str, str]:
    if not GATEWAY_TOKEN:
        return {}
    return {"Authorization": "Bearer " + GATEWAY_TOKEN}


def _get(path: str) -> dict[str, Any]:
    r = requests.get(GATEWAY_BASE + path, headers=_h(), timeout=8)
    r.raise_for_status()
    return r.json()


@app.get("/", response_class=HTMLResponse)
def index():
    return """<!doctype html>
<html>
<head>
  <meta charset='utf-8'/>
  <meta name='viewport' content='width=device-width, initial-scale=1'/>
  <title>StoryForge</title>
  <style>
    :root{--bg:#0b1020;--card:#0f1733;--text:#e7edff;--muted:#a8b3d8;--line:#24305e;--accent:#4aa3ff;--good:#26d07c;--warn:#ffcc00;--bad:#ff4d4d;}
    body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--text);padding:18px 18px 86px 18px;max-width:920px;margin:0 auto;}
    a{color:var(--accent);text-decoration:none}
    code{font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;}
    .top{display:flex;justify-content:space-between;align-items:flex-end;gap:12px;flex-wrap:wrap;}
    h1{font-size:20px;margin:0;}
    .muted{color:var(--muted);font-size:12px;}
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
    .job{border:1px solid var(--line);border-radius:14px;padding:12px;background:#0b1020;margin:10px 0;}
    .job .title{font-weight:950;font-size:14px;}
    .pill{display:inline-block;padding:3px 8px;border-radius:999px;font-size:12px;font-weight:900;border:1px solid var(--line);color:var(--muted)}
    .pill.good{color:var(--good);border-color:rgba(38,208,124,.35)}
    .pill.bad{color:var(--bad);border-color:rgba(255,77,77,.35)}
    .pill.warn{color:var(--warn);border-color:rgba(255,204,0,.35)}
    .kvs{display:grid;grid-template-columns:120px 1fr;gap:6px 10px;margin-top:8px;font-size:13px;}
    .kvs div.k{color:var(--muted)}
    .hide{display:none}

    /* bottom dock */
    .dock{position:fixed;left:0;right:0;bottom:0;z-index:1500;background:rgba(15,23,51,.92);backdrop-filter:blur(10px);border-top:1px solid var(--line);padding:10px 12px;}
    .dockInner{max-width:920px;margin:0 auto;display:flex;justify-content:space-between;align-items:center;gap:10px;}
    .dockStats{color:var(--muted);font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:70%;}

    /* bottom sheet */
    .sheetBackdrop{position:fixed;inset:0;background:rgba(0,0,0,.55);backdrop-filter:blur(3px);z-index:2000;}
    .sheet{position:fixed;left:0;right:0;bottom:0;z-index:2001;background:var(--card);border-top:1px solid var(--line);border-top-left-radius:18px;border-top-right-radius:18px;max-height:78vh;box-shadow:0 -18px 60px rgba(0,0,0,.45);}
    .sheetInner{padding:12px 14px;}
    .sheetHandle{width:44px;height:5px;border-radius:999px;background:rgba(255,255,255,.25);margin:6px auto 10px auto;}
    .sheetTitle{font-weight:950;}
    .grid2{display:grid;grid-template-columns:1fr 1fr;gap:10px;}
    .gpuGrid{display:grid;grid-template-columns:1fr 1fr;gap:8px;}
    .gpuCard{background:#0b1020;border:1px solid var(--line);border-radius:14px;padding:10px;}
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
</head>
<body>
  <div class='top'>
    <div>
      <h1>StoryForge</h1>
      <div class='muted'>Cloud control plane (App Platform) + Tinybox compute via VPC gateway.</div>
    </div>
    <div class='row'>
            <button class='secondary' onclick='refreshAll()'>Refresh</button>
    </div>
  </div>

  <div class='tabs'>
    <button id='tab-history' class='tab active' onclick='showTab("history")'>History</button>
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
          <button class='secondary' onclick='loadHistory()'>Reload</button>
        </div>
      </div>
      <div id='jobs'>Loading…</div>
      <div style='height:10px'></div>
      <div style='font-weight:950;'>Processes</div>
      <div class='muted'>Live from Tinybox compute node (top CPU/RAM/GPU).</div>
      <div id='proc' class='muted' style='margin-top:8px'>Loading…</div>
    </div>
  </div>

  <div id='pane-advanced' class='hide'>
    <div class='card'>
      <div style='font-weight:950;margin-bottom:6px;'>Monitor</div>
      <div class='muted'>Toggle realtime monitor dock (controls SSE connection).</div>
      <div class='row' style='margin-top:10px;'>
        <button id='monToggle' class='secondary' onclick='toggleMonitor()'>Disable monitor</button>
      </div>
      <div style='height:14px'></div>
      <div style='font-weight:950;margin-bottom:6px;'>TTS (gateway passthrough)</div>
      <div class='muted'>This will work once Tinybox <code>/v1/tts</code> is implemented.</div>
      <div style='margin-top:10px;'>
        <label>Engine</label>
        <input id='engine' value='tortoise'/>
        <label style='display:block;margin-top:8px;'>Voice ID / Ref</label>
        <input id='voice' value='emma'/>
        <label style='display:block;margin-top:8px;'>Text</label>
        <textarea id='text'>Hello from StoryForge cloud.</textarea>
        <div class='row' style='margin-top:10px;'>
          <button onclick='tts()'>Call /v1/tts</button>
        </div>
        <pre id='ttsout' style='margin-top:10px;'></pre>
      </div>
    </div>
  </div>

<script>
function showTab(name){
  for (const n of ['history','advanced']){
    document.getElementById('pane-'+n).classList.toggle('hide', n!==name);
    document.getElementById('tab-'+n).classList.toggle('active', n===name);
  }
}

function pill(state){
  const s=(state||'unknown').toLowerCase();
  let cls='pill';
  if (s==='completed' || s==='done' || s==='success') cls+=' good';
  else if (s==='aborted' || s==='error' || s==='failed') cls+=' bad';
  else if (s==='running' || s==='queued') cls+=' warn';
  return `<span class="${cls}">${s}</span>`;
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

async function loadHistory(){
  const el=document.getElementById('jobs');
  el.textContent='Loading…';
  const r=await fetch('/api/history?limit=60');
  const j=await r.json();
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
        <div class='k'>mp3</div><div class='muted'>${job.mp3_url||'—'}</div>
        <div class='k'>sfml</div><div class='muted'>${job.sfml_url||'—'}</div>
      </div>
    </div>`;
  }).join('');
}

let metricsES = null;
let monitorEnabled = true;
let lastMetrics = null;

function renderMetrics(m){
  lastMetrics = m;
  const pre=document.getElementById('metrics'); if (pre) pre.textContent = JSON.stringify(m, null, 2);
}


function renderProc(m){
  const el = document.getElementById('proc');
  if (!el) return;
  const b = m?.body || m || {};
  const procs = b.processes || b.procs || null;
  if (!procs || !Array.isArray(procs) || procs.length===0){
    el.innerHTML = '<div class="muted">No process list available yet.</div>';
    return;
  }
  // Expect list of {pid,name,cpu_pct,ram_mb,gpu_mem_mb}
  el.innerHTML = procs.slice(0,12).map(p=>{
    const pid = p.pid ?? '—';
    const name = (p.name || p.cmd || '').toString();
    const cpu = (p.cpu_pct!=null)? Number(p.cpu_pct).toFixed(1)+'%':'—';
    const ram = (p.ram_mb!=null)? Number(p.ram_mb).toFixed(0)+' MB':'—';
    const gmem = (p.gpu_mem_mb!=null)? Number(p.gpu_mem_mb).toFixed(0)+' MB':null;
    return `<div class='job' style='margin:8px 0;'>
      <div class='row' style='justify-content:space-between;'>
        <div class='title' style='max-width:70%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;'>${name || '(unknown)'}</div>
        <div class='pill'>pid ${pid}</div>
      </div>
      <div class='kvs'>
        <div class='k'>cpu</div><div>${cpu}</div>
        <div class='k'>ram</div><div>${ram}</div>
        ${gmem ? `<div class='k'>gpu mem</div><div>${gmem}</div>` : ``}
      </div>
    </div>`;
  }).join('');
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


function setMonitorEnabled(on){
  monitorEnabled = !!on;
  const dock = document.getElementById('monitorDock');
  const backdrop = document.getElementById('monitorBackdrop');
  const sheet = document.getElementById('monitorSheet');
  const btn = document.getElementById('monToggle');

  if (!monitorEnabled){
    stopMetricsStream();
    if (dock) dock.classList.add('hide');
    if (backdrop) backdrop.classList.add('hide');
    if (sheet) sheet.classList.add('hide');
    if (btn){ btn.textContent = 'Enable monitor'; btn.classList.remove('secondary'); }
    return;
  }

  if (dock) dock.classList.remove('hide');
  if (btn){ btn.textContent = 'Disable monitor'; btn.classList.add('secondary'); }
  const ds=document.getElementById('dockStats'); if (ds) ds.textContent='Connecting…';
  startMetricsStream();
}

function toggleMonitor(){
  setMonitorEnabled(!monitorEnabled);
}


async function refreshAll(){
  await Promise.allSettled([loadHistory()]);
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
  document.getElementById('monitorBackdrop')?.classList.remove('hide');
  document.getElementById('monitorSheet')?.classList.remove('hide');
  const ds=document.getElementById('dockStats'); if (ds) ds.textContent='Connecting…';
  startMetricsStream();
  // render last metrics immediately if we have them
  if (lastMetrics) updateMonitorFromMetrics(lastMetrics);
}

function closeMonitor(){
  document.getElementById('monitorBackdrop')?.classList.add('hide');
  document.getElementById('monitorSheet')?.classList.add('hide');
}

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
  document.getElementById('monSub').textContent = `Last update: ${ts}`;
    updateDockFromMetrics(m);
}

async function tts(){
  const payload = {
    engine: document.getElementById('engine').value,
    voice: document.getElementById('voice').value,
    text: document.getElementById('text').value,
    upload: true,
  };
  const r = await fetch('/api/tts', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
  const t = await r.text();
  document.getElementById('ttsout').textContent = t;
}

refreshAll();
// Start streaming immediately so the Metrics tab is instant.
setMonitorEnabled(true);
loadHistory();
</script>


  

  <div id='monitorDock' class='dock' onclick='openMonitor()'>
    <div class='dockInner'>
      <div style='font-weight:950;'>Monitor</div>
      <div class='dockStats' id='dockStats'>Monitor off</div>
    </div>
  </div>

<div id='monitorBackdrop' class='sheetBackdrop hide' onclick='closeMonitor()'></div>
  <div id='monitorSheet' class='sheet hide' role='dialog' aria-modal='true'>
    <div class='sheetInner'>
      <div class='sheetHandle'></div>
      <div class='row' style='justify-content:space-between;'>
        <div>
          <div class='sheetTitle'>System monitor</div>
          <div id='monSub' class='muted'>Connecting…</div>
        </div>
        <div class='row'>
          <button class='secondary' onclick='closeMonitor()'>Close</button>
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
      <div id='monGpus' class='grid2' style='margin-top:8px;'></div
  </div>

</body>
</html>"""


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
