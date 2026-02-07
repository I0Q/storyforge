from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import requests
from fastapi import FastAPI
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
    body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;padding:18px;max-width:780px;margin:0 auto;}
    .card{border:1px solid #ddd;border-radius:14px;padding:12px;margin:12px 0;}
    .row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;}
    button{padding:10px 12px;border-radius:12px;border:1px solid #d1d5db;background:#0b63ce;color:#fff;font-weight:800;cursor:pointer;}
    button.secondary{background:#fff;color:#0b63ce;}
    pre{background:#0b1020;color:#d7e1ff;padding:12px;border-radius:12px;overflow:auto;}
    input,textarea{width:100%;padding:10px;border:1px solid #ddd;border-radius:12px;}
    textarea{min-height:90px;}
    .muted{color:#666;font-size:12px;}
  </style>
</head>
<body>
  <h2>StoryForge (App Platform)</h2>
  <div class='muted'>This is a test UI. It calls the VPC gateway and shows Tinybox metrics.</div>

  <div class='card'>
    <div class='row'>
      <button class='secondary' onclick='refresh()'>Refresh metrics</button>
      <button class='secondary' onclick='ping()'>Gateway ping</button>
    </div>
    <pre id='metrics'>Loading…</pre>
  </div>

  <div class='card'>
    <div style='font-weight:900;margin-bottom:6px;'>Voice gen (mock call)</div>
    <div class='muted'>TTS will work once Tinybox /v1/tts is implemented.</div>
    <div style='margin-top:10px;'>
      <label>Engine</label>
      <input id='engine' value='tortoise'/>
      <label style='display:block;margin-top:8px;'>Voice ID / Ref</label>
      <input id='voice' value='emma'/>
      <label style='display:block;margin-top:8px;'>Text</label>
      <textarea id='text'>Hello from App Platform.</textarea>
      <div class='row' style='margin-top:10px;'>
        <button onclick='tts()'>Call /v1/tts</button>
      </div>
      <pre id='ttsout' style='margin-top:10px;'></pre>
    </div>
  </div>

<script>
async function refresh(){
  const r = await fetch('/api/metrics');
  const j = await r.json();
  document.getElementById('metrics').textContent = JSON.stringify(j, null, 2);
}
async function ping(){
  const r = await fetch('/api/ping');
  const j = await r.json();
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
refresh();
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


@app.post('/api/tts')
def api_tts(payload: dict[str, Any]):
    r = requests.post(GATEWAY_BASE + '/v1/tts', json=payload, headers=_h(), timeout=120)
    try:
        body = r.json()
    except Exception:
        body = r.text
    return {"status": r.status_code, "body": body}
