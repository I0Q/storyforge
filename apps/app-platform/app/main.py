from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import requests
from fastapi import FastAPI

from .db import db_connect, db_init, db_list_jobs
from fastapi.responses import HTMLResponse

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
    body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--text);padding:18px;max-width:920px;margin:0 auto;}
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
  </style>
</head>
<body>
  <div class='top'>
    <div>
      <h1>StoryForge</h1>
      <div class='muted'>Cloud control plane (App Platform) + Tinybox compute via VPC gateway.</div>
    </div>
    <div class='row'>
      <button class='secondary' onclick='ping()'>Gateway ping</button>
      <button class='secondary' onclick='refreshAll()'>Refresh</button>
    </div>
  </div>

  <div class='tabs'>
    <button id='tab-history' class='tab active' onclick='showTab("history")'>History</button>
    <button id='tab-metrics' class='tab' onclick='showTab("metrics")'>Metrics</button>
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
    </div>
  </div>

  <div id='pane-metrics' class='hide'>
    <div class='card'>
      <div class='row' style='justify-content:space-between;'>
        <div>
          <div style='font-weight:950;'>Tinybox metrics</div>
          <div class='muted'>Live via App Platform → VPC gateway → Tailscale → Tinybox.</div>
        </div>
        <div class='row'>
          <button class='secondary' onclick='loadMetrics()'>Reload</button>
        </div>
      </div>
      <pre id='metrics'>Loading…</pre>
    </div>
  </div>

  <div id='pane-advanced' class='hide'>
    <div class='card'>
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
  for (const n of ['history','metrics','advanced']){
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

async function loadMetrics(){
  const r=await fetch('/api/metrics');
  const j=await r.json();
  document.getElementById('metrics').textContent=JSON.stringify(j, null, 2);
}

async function refreshAll(){
  await Promise.allSettled([loadHistory(), loadMetrics()]);
}

async function ping(){
  const r=await fetch('/api/ping');
  const j=await r.json();
  alert('gateway: ' + JSON.stringify(j));
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
</script>
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
