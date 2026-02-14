from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import json
import time
import threading
from datetime import datetime
import html as pyhtml

import requests
from fastapi import Body, FastAPI, HTTPException, Request, UploadFile, File

from .auth import register_passphrase_auth
from .ui_refactor_shared import base_css
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
from .todos_db import (
    list_todos_db,
    add_todo_db,
    set_todo_status_db,
    archive_done_todos_db,
)
from .voices_db import (
    validate_voice_id,
    list_voices_db,
    get_voice_db,
    upsert_voice_db,
    set_voice_enabled_db,
    delete_voice_db,
)

from .voice_meta import analyze_voice_metadata
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse
from fastapi import Response

APP_NAME = "storyforge"
APP_BUILD = int(os.environ.get("SF_BUILD", "0") or 0) or int(time.time())

GATEWAY_BASE = os.environ.get("GATEWAY_BASE", "http://10.108.0.3:8791").rstrip("/")
GATEWAY_TOKEN = os.environ.get("GATEWAY_TOKEN", "")
SF_JOB_TOKEN = os.environ.get("SF_JOB_TOKEN", "").strip()

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


# Cache hardening: avoid stale HTML/JS during rapid iteration (Cloudflare/Safari).
@app.middleware("http")
async def _no_store_cache_mw(request: Request, call_next):
    resp = await call_next(request)
    try:
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
    except Exception:
        pass
    return resp


register_passphrase_auth(app)
register_library_pages(app)
register_library_viewer(app)

# Incremental refactor: extract the dashboard (/) CSS verbatim into a constant.
# This should not change rendered output.
INDEX_BASE_CSS = base_css("""\

    :root{--bg:#0b1020;--card:#0f1733;--text:#e7edff;--muted:#a8b3d8;--line:#24305e;--accent:#4aa3ff;--good:#26d07c;--warn:#ffcc00;--bad:#ff4d4d;}
    body.noScroll{overflow:hidden;}
    html,body{overscroll-behavior-y:none;}
    body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--text);padding:18px;max-width:920px;margin:0 auto;overflow-x:hidden;}

    /* iOS-friendly toggle switches */
    .switch{position:relative;display:inline-block;width:52px;height:30px;vertical-align:middle;}
    .switch input{opacity:0;width:0;height:0;}
    .slider{position:absolute;cursor:pointer;top:0;left:0;right:0;bottom:0;background:rgba(168,179,216,0.25);border:1px solid rgba(36,48,94,.65);transition:.18s;border-radius:999px;}
    .slider:before{position:absolute;content:"";height:24px;width:24px;left:3px;bottom:2px;background:white;transition:.18s;border-radius:999px;}
    .switch input:checked + .slider{background:rgba(74,163,255,0.55);border-color:rgba(74,163,255,0.9);}
    .switch input:checked + .slider:before{transform:translateX(22px);}
    html.monOn body{padding-bottom:calc(18px + 74px + env(safe-area-inset-bottom));}
    body.monOff{padding-bottom:18px;}
    body.monOff .dock{will-change:transform;display:none}
    body.monOff #monitorBackdrop{display:none}
    body.monOff #monitorSheet{display:none}
    a{color:var(--accent);text-decoration:none}
    code{font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;}
    .navBar{position:sticky;top:0;z-index:1200;background:rgba(11,16,32,0.96);backdrop-filter:blur(8px);border-bottom:1px solid rgba(36,48,94,.55);padding:14px 0 10px 0;margin-bottom:10px;}
    .top{display:grid;grid-template-columns:minmax(0,1fr) auto;column-gap:12px;row-gap:10px;align-items:start;}
    .brandRow{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;}
    .pageName{color:var(--muted);font-weight:900;font-size:12px;}
    .menuWrap{position:relative;display:inline-block;}
    .userBtn{width:38px;height:38px;border-radius:999px;border:1px solid var(--line);background:transparent;color:var(--text);font-weight:950;display:inline-flex;align-items:center;justify-content:center;}
    .userBtn:hover{background:rgba(255,255,255,0.06);}
    .menuCard{position:absolute;right:0;top:46px;min-width:240px;max-width:calc(100vw - 36px);background:var(--card);border:1px solid var(--line);border-radius:16px;padding:12px;display:none;z-index:60;box-shadow:0 18px 60px rgba(0,0,0,.45);}
    .menuCard.show{display:block;}
    .menuCard .uTop{display:flex;gap:10px;align-items:center;margin-bottom:10px;}
    .menuCard .uAvatar{width:36px;height:36px;border-radius:999px;background:#0b1020;border:1px solid var(--line);display:flex;align-items:center;justify-content:center;}
    .menuCard .uName{font-weight:950;}
    .menuCard .uSub{color:var(--muted);font-size:12px;margin-top:2px;}
    .menuCard .uActions{display:flex;gap:10px;justify-content:flex-end;margin-top:10px;}

    /* Mobile: render the user menu as a bottom sheet so it doesn't distort the header */
    @media (max-width:520px){
      .menuCard{position:fixed;left:14px;right:14px;top:auto;bottom:calc(14px + env(safe-area-inset-bottom));min-width:0;max-width:none;}
    }

    h1{font-size:20px;margin:0;}
    .brandLink{color:inherit;text-decoration:none;}
    .brandLink:active{opacity:0.9;}
    .muted{color:var(--muted);font-size:12px;}
    .boot{margin:8px 0 10px 0;margin-top:10px;padding:10px 12px;border-radius:14px;border:1px dashed rgba(168,179,216,.35);background:rgba(7,11,22,.35);display:flex;align-items:center;gap:10px;}
    body.debugOff #boot{display:none}
    .boot strong{color:var(--text);}
    .tabs{display:flex;gap:10px;margin-top:14px;flex-wrap:wrap;}
    .tab{padding:10px 12px;border-radius:12px;border:1px solid var(--line);background:transparent;color:var(--text);font-weight:900;cursor:pointer}
    .tab.active{background:var(--card);}

    /* non-blocking deploy/update bar */
    .updateBar{margin-top:8px;border:1px dashed rgba(168,179,216,.28);background:rgba(7,11,22,.28);border-radius:14px;padding:10px 12px;}
    .updateBar.hide{display:none;}
    .updateTrack{height:8px;border-radius:999px;border:1px solid rgba(36,48,94,.75);background:#0b1020;overflow:hidden;margin-top:8px;}
    .updateProg{height:100%;width:35%;background:linear-gradient(90deg, rgba(74,163,255,.15), rgba(74,163,255,.95), rgba(74,163,255,.15));background-size:200% 100%;animation:sfIndet 1.2s linear infinite;}
    @keyframes sfIndet{0%{transform:translateX(-60%);}100%{transform:translateX(260%);}}

    .card{border:1px solid var(--line);border-radius:16px;padding:12px;margin:12px 0;background:var(--card);}
    .todoItem{display:block;margin:6px 0;line-height:1.35;}
    .todoItem input{transform:scale(1.1);margin-right:10px;}
    .todoItem span{vertical-align:middle;}
    .row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;}

    /* swipe-delete pattern (voices + todos) */
    .swipe{display:block;overflow-x:auto;overflow-y:hidden;-webkit-overflow-scrolling:touch;scrollbar-width:none;}
    .swipe::-webkit-scrollbar{display:none;}
    .swipeInner{display:flex;min-width:100%;}
    .swipeMain{min-width:100%;}
    .swipeKill{flex:0 0 auto;display:flex;align-items:center;justify-content:center;padding-left:10px;pointer-events:auto;}
    .swipeDelBtn{background:transparent;border:1px solid rgba(255,77,77,.35);color:var(--bad);font-weight:950;border-radius:12px;padding:10px 12px;pointer-events:auto;}
    .rowEnd{justify-content:flex-end;}
    button{padding:10px 12px;border-radius:12px;border:1px solid var(--line);background:#163a74;color:#fff;font-weight:950;cursor:pointer;}
    button.secondary{background:transparent;color:var(--text);}

    /* switch */
    .switch{position:relative;display:inline-block;width:52px;height:30px;flex:0 0 auto;}
    .switch input{display:none;}
    .slider{position:absolute;cursor:pointer;inset:0;background:#0a0f20;border:1px solid rgba(255,255,255,0.12);transition:.18s;border-radius:999px;}
    .slider:before{position:absolute;content:'';height:24px;width:24px;left:3px;top:2px;background:white;transition:.18s;border-radius:999px;}
    .switch input:checked + .slider{background:#1f6feb;border-color:rgba(31,111,235,.35);}
    .switch input:checked + .slider:before{transform:translateX(22px);}
    input,textarea,select{width:100%;padding:10px;border:1px solid var(--line);border-radius:12px;background:#0b1020;color:var(--text);}
    textarea{min-height:90px;}
    select{appearance:none;-webkit-appearance:none;background-image:linear-gradient(45deg,transparent 50%,var(--muted) 50%),linear-gradient(135deg,var(--muted) 50%,transparent 50%);background-position:calc(100% - 18px) calc(50% - 2px),calc(100% - 13px) calc(50% - 2px);background-size:5px 5px,5px 5px;background-repeat:no-repeat;padding-right:34px;}
    pre{background:#070b16;color:#d7e1ff;padding:12px;border-radius:12px;overflow:auto;border:1px solid var(--line)}
    .term{font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;font-size:12px;line-height:1.25;white-space:pre;}

    /* SFML code viewer (line numbers + basic highlighting) */
    .codeBox{background:#070b16;border:1px solid var(--line);border-radius:14px;overflow:auto;}
    .codeWrap{font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;font-size:12px;line-height:1.35;min-width:100%;}
    .codeLine{display:grid;grid-template-columns:44px 1fr;gap:12px;padding:2px 12px;}
    .codeLn{color:rgba(168,179,216,0.55);text-align:right;user-select:none;}
    .codeTxt{white-space:pre;}
    .tok-c{color:rgba(168,179,216,0.55)}
    .tok-kw{color:#7dd3fc;font-weight:900}
    .tok-a{color:#a78bfa;font-weight:900}
    .tok-s{color:#f9a8d4}
    .tok-id{color:#fbbf24}

    .job{border:1px solid var(--line);border-radius:14px;padding:12px;background:#0b1020;margin:10px 0;}
    .job .title{font-weight:950;font-size:14px;}
    .pill{display:inline-block;padding:3px 8px;border-radius:999px;font-size:12px;font-weight:900;border:1px solid var(--line);color:var(--muted)}
    .pill.good{color:var(--good);border-color:rgba(38,208,124,.35)}
    .pill.bad{color:var(--bad);border-color:rgba(255,77,77,.35)}
    .pill.warn{color:var(--warn);border-color:rgba(255,204,0,.35)}
    .kvs{display:grid;grid-template-columns:120px 1fr;gap:8px 12px;margin-top:8px;font-size:13px;}
    .kvs > div{min-width:0;align-self:center;}
    .kvs > div:nth-child(2n){width:100%;}
    .provKvs .k{padding-top:2px;}
    .provKvs input,.provKvs select{max-width:100%;display:block;}
    .provSection{grid-column:1 / -1;margin-top:10px;padding-top:10px;border-top:1px solid rgba(255,255,255,0.08);font-weight:950;}
    .provHint{grid-column:1 / -1;color:var(--muted);font-size:12px;margin-top:-2px;}
    .gpuChip{border:1px solid rgba(255,255,255,0.10);background:transparent;color:var(--muted);}
    .gpuChip.on{border-color:rgba(74,163,255,0.55);color:var(--text);background:rgba(74,163,255,0.12);}
    .gpuChip.claimed{opacity:0.55;}

    /* inline checkbox pills */
    .checkLine{display:flex;align-items:center;gap:8px;}
    .checkLine input[type=checkbox]{width:18px;height:18px;accent-color:#1f6feb;}
    .checkPill{display:inline-flex;align-items:center;gap:8px;padding:6px 10px;border-radius:999px;background:rgba(255,255,255,0.04);}
    .fadeLine{position:relative;display:flex;align-items:center;gap:8px;min-width:0;}
    .fadeText{flex:1;min-width:0;white-space:nowrap;overflow-x:auto;overflow-y:hidden;color:var(--muted);-webkit-overflow-scrolling:touch;scrollbar-width:none;}
    .fadeText::-webkit-scrollbar{display:none;}
        .copyBtn{border:1px solid var(--line);background:transparent;color:var(--text);font-weight:900;border-radius:10px;padding:6px;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;width:34px;height:30px;}
    .copyBtn:active{transform:translateY(1px);}
    .copyBtn svg{width:18px;height:18px;stroke:currentColor;fill:none;stroke-width:2;}
    .copyBtn:hover{background:rgba(255,255,255,0.06);}
    .kvs div.k{color:var(--muted)}
    .hide{display:none}

    .switch{position:relative;display:inline-block;width:52px;height:30px;flex:0 0 auto;}
    .switch input{display:none;}
    .slider{position:absolute;cursor:pointer;inset:0;background:#0a0f20;border:1px solid rgba(255,255,255,0.12);transition:.18s;border-radius:999px;}
    .slider:before{position:absolute;content:'';height:24px;width:24px;left:3px;top:2px;background:white;transition:.18s;border-radius:999px;}
    .switch input:checked + .slider{background:#1f6feb;border-color:rgba(31,111,235,.35);}
    .switch input:checked + .slider:before{transform:translateX(22px);}

    /* bottom dock */
    .dock{display:none;position:fixed;left:0;right:0;bottom:0;z-index:1500;background:rgba(15,23,51,.92);backdrop-filter:blur(10px);border-top:1px solid var(--line);padding:10px 12px calc(10px + env(safe-area-inset-bottom)) 12px;}
    html.monOn .dock{display:block;}
    .dockInner{max-width:920px;margin:0 auto;display:flex;justify-content:space-between;align-items:center;gap:10px;}
    .dockStats{color:var(--muted);font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:70%;}
    body.sheetOpen .dock{pointer-events:none;}

    /* bottom sheet */
    .sheetBackdrop{display:none;position:fixed;inset:0;background:rgba(0,0,0,.55);backdrop-filter:blur(3px);z-index:2000;touch-action:none;}
    .sheet{will-change:transform;display:none;position:fixed;left:0;right:0;bottom:0;z-index:2001;background:var(--card);border-top:1px solid var(--line);border-top-left-radius:18px;border-top-right-radius:18px;max-height:78vh;box-shadow:0 -18px 60px rgba(0,0,0,.45);overflow:hidden;}
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

""")

# Shared CSS for Voices pages (edit + generate). Keep content verbatim.
COMMON_VARS_HEADER_CSS = base_css("""\

    :root{--bg:#0b1020;--card:#0f1733;--text:#e7edff;--muted:#a8b3d8;--line:#24305e;--accent:#4aa3ff;--bad:#ff4d4d;}
    a{color:var(--accent);text-decoration:none}

    /* header */
    .navBar{position:sticky;top:0;z-index:1200;background:rgba(11,16,32,0.96);backdrop-filter:blur(8px);border-bottom:1px solid rgba(36,48,94,.55);padding:14px 0 10px 0;margin-bottom:10px;}
    .top{display:grid;grid-template-columns:minmax(0,1fr) auto;column-gap:12px;row-gap:10px;align-items:start;}
    .brandRow{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;}
    .pageName{color:var(--muted);font-weight:900;font-size:12px;}

    /* user menu */
    .menuWrap{position:relative;display:inline-block;}
    .userBtn{width:38px;height:38px;border-radius:999px;border:1px solid var(--line);background:transparent;color:var(--text);font-weight:950;display:inline-flex;align-items:center;justify-content:center;}
    .userBtn:hover{background:rgba(255,255,255,0.06);}
    .menuCard{position:absolute;right:0;top:46px;min-width:240px;max-width:calc(100vw - 36px);background:var(--card);border:1px solid var(--line);border-radius:16px;padding:12px;display:none;z-index:60;box-shadow:0 18px 60px rgba(0,0,0,.45);}
    .menuCard.show{display:block;}
    .menuCard .uTop{display:flex;gap:10px;align-items:center;margin-bottom:10px;}
    .menuCard .uAvatar{width:36px;height:36px;border-radius:999px;background:#0b1020;border:1px solid var(--line);display:flex;align-items:center;justify-content:center;}
    .menuCard .uName{font-weight:950;}
    .menuCard .uSub{color:var(--muted);font-size:12px;margin-top:2px;}
    .menuCard .uActions{display:flex;gap:10px;justify-content:flex-end;margin-top:10px;}

    /* layout helpers */
    .rowBetween{justify-content:space-between;}
    .headActions{justify-content:flex-end;align-items:center;flex-wrap:nowrap;}

    h1{font-size:20px;margin:0;}
    .muted{color:var(--muted);font-size:12px;}

    /* Mobile: bottom-sheet menu */
    @media (max-width:520px){
      .menuCard{position:fixed;left:14px;right:14px;top:auto;bottom:calc(14px + env(safe-area-inset-bottom));min-width:0;max-width:none;}
    }

""")

VOICES_BASE_CSS = (
    base_css("""\

    html,body{overscroll-behavior-y:none;}
    *{box-sizing:border-box;}
    body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--text);padding:18px;max-width:920px;margin:0 auto;overflow-x:hidden;}

""")
    + COMMON_VARS_HEADER_CSS
    + base_css("""\

    .err{color:var(--bad);font-weight:950;margin-top:10px;}

    /* layout */
    .card{border:1px solid var(--line);border-radius:16px;padding:12px;margin:12px 0;background:var(--card);}
    .row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;}
    .fadeLine{position:relative;display:flex;align-items:center;gap:8px;min-width:0;}
    .fadeText{flex:1;min-width:0;white-space:nowrap;overflow-x:auto;overflow-y:hidden;color:var(--muted);-webkit-overflow-scrolling:touch;scrollbar-width:none;}
    .fadeText::-webkit-scrollbar{display:none;}
    .rowEnd{justify-content:flex-end;margin-left:auto;}
    button{padding:10px 12px;border-radius:12px;border:1px solid var(--line);background:#163a74;color:#fff;font-weight:950;cursor:pointer;}
    button.secondary{background:transparent;color:var(--text);}

    /* shared icon button (used by debug banner copy button, job url copy buttons, etc.) */
    .copyBtn{border:1px solid var(--line);background:transparent;color:var(--text);font-weight:900;border-radius:10px;padding:6px;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;width:34px;height:30px;}
    .copyBtn:active{transform:translateY(1px);}
    .copyBtn svg{display:block;width:18px;height:18px;stroke:currentColor;fill:none;stroke-width:2;}
    .copyBtn:hover{background:rgba(255,255,255,0.06);}
    input,textarea,select{width:100%;padding:10px;border:1px solid var(--line);border-radius:12px;background:#0b1020;color:var(--text);font-size:16px;}
    textarea{min-height:90px;}
    .hide{display:none;}

    /* Debug banner (Build/JS) */
    .boot{margin:8px 0 10px 0;margin-top:10px;padding:10px 12px;border-radius:14px;border:1px dashed rgba(168,179,216,.35);background:rgba(7,11,22,.35);display:flex;align-items:center;gap:10px;}
    body.debugOff #boot{display:none}
    .boot strong{color:var(--text);}

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
    .sheetInner{padding:12px 14px;max-height:78vh;overflow-y:auto;-webkit-overflow-scrolling:touch;overscroll-behavior:contain;}
    .sheetHandle{width:46px;height:5px;border-radius:999px;background:rgba(255,255,255,.18);margin:2px auto 10px auto;}
    .sheetTitle{font-weight:950;}
    #monitorSheet button{touch-action:manipulation;}

    .grid2{display:grid;grid-template-columns:1fr 1fr;gap:10px;}
    .meter{background:#0b1020;border:1px solid var(--line);border-radius:14px;padding:10px;}
    .meter .k{color:var(--muted);font-size:12px;font-weight:900;}
    .meter .v{font-weight:950;margin-top:4px;}
    .bar{height:10px;background:#0a0f20;border:1px solid rgba(255,255,255,.08);border-radius:999px;overflow:hidden;margin-top:8px;}
    .bar > div{height:100%;width:0%;background:linear-gradient(90deg,#4aa3ff,#26d07c);}
    .bar.warn > div{background:linear-gradient(90deg,#ffcc00,#ff7a00);}
    .bar.bad > div{background:linear-gradient(90deg,#ff4d4d,#ff2e83);}
    .bar.small{height:8px;margin-top:6px;}

    .gpuGrid{display:grid;grid-template-columns:repeat(2, minmax(0, 1fr));gap:8px;}
    .gpuCard{background:#0b1020;border:1px solid var(--line);border-radius:14px;padding:10px;min-width:0;}
    .gpuHead{display:flex;justify-content:space-between;align-items:baseline;gap:8px;}
    .gpuHead .l{font-weight:950;}
    .gpuHead .r{color:var(--muted);font-size:12px;white-space:nowrap;}
    .gpuRow{display:flex;justify-content:space-between;align-items:baseline;margin-top:6px;}
    .gpuRow .k{color:var(--muted);font-size:12px;font-weight:900;}
    .gpuRow .v{font-weight:950;font-size:13px;}

    @media (max-width:520px){
      .grid2{grid-template-columns:1fr;}
      .gpuGrid{grid-template-columns:1fr 1fr;}
    }

""")
)

VOICE_EDIT_EXTRA_CSS = base_css("""\

    /* user menu */
    .menuWrap{position:relative;display:inline-block;}
    .userBtn{width:38px;height:38px;border-radius:999px;border:1px solid var(--line);background:transparent;color:var(--text);font-weight:950;display:inline-flex;align-items:center;justify-content:center;}
    .userBtn:hover{background:rgba(255,255,255,0.06);}
    .menuCard{position:absolute;right:0;top:46px;min-width:240px;max-width:calc(100vw - 36px);background:var(--card);border:1px solid var(--line);border-radius:16px;padding:12px;display:none;z-index:60;box-shadow:0 18px 60px rgba(0,0,0,.45);}
    .menuCard.show{display:block;}
    .menuCard .uTop{display:flex;gap:10px;align-items:center;margin-bottom:10px;}
    .menuCard .uAvatar{width:36px;height:36px;border-radius:999px;background:#0b1020;border:1px solid var(--line);display:flex;align-items:center;justify-content:center;}
    .menuCard .uName{font-weight:950;}
    .menuCard .uSub{color:var(--muted);font-size:12px;margin-top:2px;}
    .menuCard .uActions{display:flex;gap:10px;justify-content:flex-end;margin-top:10px;}

    /* Mobile: bottom-sheet menu */
    @media (max-width:520px){
      .menuCard{position:fixed;left:14px;right:14px;top:auto;bottom:calc(14px + env(safe-area-inset-bottom));min-width:0;max-width:none;}
    }

    /* switch */
    .switch{position:relative;display:inline-block;width:52px;height:30px;flex:0 0 auto;}
    .switch input{display:none;}
    .slider{position:absolute;cursor:pointer;inset:0;background:#0a0f20;border:1px solid rgba(255,255,255,0.12);transition:.18s;border-radius:999px;}
    .slider:before{position:absolute;content:'';height:24px;width:24px;left:3px;top:2px;background:white;transition:.18s;border-radius:999px;}
    .switch input:checked + .slider{background:#1f6feb;border-color:rgba(31,111,235,.35);}
    .switch input:checked + .slider:before{transform:translateX(22px);}

    /* traits */
    .traitsGrid{display:grid;grid-template-columns:110px 1fr;gap:8px 10px;margin-top:10px;}
    .traitsGrid .k{color:var(--muted);font-size:12px;}
    .traitsGrid .v{min-width:0;}
    .chips{display:flex;gap:8px;flex-wrap:wrap;}
    .chip{display:inline-flex;align-items:center;gap:6px;padding:6px 10px;border-radius:999px;border:1px solid rgba(255,255,255,0.12);background:rgba(255,255,255,0.04);font-weight:950;font-size:12px;}
    .chip.bad{border-color:rgba(255,90,90,0.35);color:var(--bad);}
    .chip.ok{border-color:rgba(80,200,120,0.35);}
    .chip.male{border-color:rgba(80,160,255,0.75);background:rgba(80,160,255,0.26);color:rgba(210,235,255,0.98);}
    .chip.female{border-color:rgba(255,120,200,0.75);background:rgba(255,120,200,0.26);color:rgba(255,225,245,0.98);}
    .chip.age-child{border-color:rgba(255,210,80,0.45);background:rgba(255,210,80,0.14);}
    .chip.age-teen{border-color:rgba(160,120,255,0.45);background:rgba(160,120,255,0.14);}
    .chip.age-adult{border-color:rgba(80,200,120,0.45);background:rgba(80,200,120,0.12);}
    .chip.age-elder{border-color:rgba(255,160,80,0.45);background:rgba(255,160,80,0.14);}
    details.rawBox summary{cursor:pointer;color:var(--muted);}

    /* SFML code viewer (line numbers + basic highlighting) */
    .codeBox{background:#070b16;border:1px solid var(--line);border-radius:14px;overflow:auto;}
    .codeWrap{font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;font-size:12px;line-height:1.35;min-width:100%;}
    .codeLine{display:grid;grid-template-columns:44px 1fr;gap:12px;padding:2px 12px;}
    .codeLn{color:rgba(168,179,216,0.55);text-align:right;user-select:none;}
    .codeTxt{white-space:pre;}
    .tok-c{color:rgba(168,179,216,0.55)}
    .tok-kw{color:#7dd3fc;font-weight:900}
    .tok-a{color:#a78bfa;font-weight:900}
    .tok-s{color:#f9a8d4}
    .tok-id{color:#fbbf24}

""")

VOICE_NEW_EXTRA_CSS = base_css("""\

    textarea{resize:none;}
    .k{color:var(--muted);font-size:12px;margin-top:12px;}
    audio{width:100%;margin-top:10px;}

""")

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

# Monitor JS expects the same function names used on the main page.
# NOTE: This duplicates logic so standalone pages can include the same monitor dock.
MONITOR_JS = """
<script>
let metricsES=null; let monitorEnabled=true; let lastMetrics=null;
// Some pages include extra monitor helpers (poll fallback). Provide safe no-ops so missing helpers don't crash.
try{ if (typeof window.stopMetricsPoll !== 'function') window.stopMetricsPoll = function(){}; }catch(e){}
try{ if (typeof window.startMetricsPoll !== 'function') window.startMetricsPoll = function(){}; }catch(e){}
function loadMonitorPref(){ try{ var v=localStorage.getItem('sf_monitor_enabled'); if(v===null) return true; return v==='1'; }catch(e){ return true; } }
function saveMonitorPref(on){ try{ localStorage.setItem('sf_monitor_enabled', on?'1':'0'); }catch(e){} }
function stopMetricsStream(){ if(metricsES){ try{ metricsES.close(); }catch(e){} metricsES=null; } }
function setBar(elId,pct){ var el=document.getElementById(elId); if(!el) return; var p=Math.max(0,Math.min(100,pct||0)); var f=el.querySelector('div'); if(f) f.style.width=p.toFixed(0)+'%'; el.classList.remove('warn','bad'); if(p>=85) el.classList.add('bad'); else if(p>=60) el.classList.add('warn'); }
function fmtPct(x){ if(x==null) return '-'; return (Number(x).toFixed(1))+'%'; }
function fmtTs(ts){ if(!ts) return '-'; try{ return new Date(ts*1000).toLocaleString(); }catch(e){ return String(ts); } }
function updateDockFromMetrics(m){ var el=document.getElementById('dockStats'); if(!el) return; var b=(m&&m.body)?m.body:(m||{}); var cpu=(b.cpu_pct!=null)?Number(b.cpu_pct).toFixed(1)+'%':'-'; var rt=Number(b.ram_total_mb||0), ru=Number(b.ram_used_mb||0); var rp=rt?(ru/rt*100):0; var ram=rt?rp.toFixed(1)+'%':'-'; var gpus=Array.isArray(b.gpus)?b.gpus:(b.gpu?[b.gpu]:[]); var maxGpu=null; if(gpus.length){ maxGpu=0; for(var i=0;i<gpus.length;i++){ var u=Number((gpus[i]||{}).util_gpu_pct||0); if(u>maxGpu) maxGpu=u; } } var gpu=(maxGpu==null)?'-':maxGpu.toFixed(1)+'%'; el.textContent='CPU '+cpu+' • RAM '+ram+' • GPU '+gpu; }
function renderGpus(b){ var el=document.getElementById('monGpus'); if(!el) return; var gpus=Array.isArray(b.gpus)?b.gpus:(b.gpu?[b.gpu]:[]); if(!gpus.length){ el.innerHTML='<div class="muted">No GPU data</div>'; return; } el.innerHTML=gpus.slice(0,8).map(function(g,i){ g=g||{}; var idx=(g.index!=null)?g.index:i; var util=Number(g.util_gpu_pct||0); var power=(g.power_w!=null)?Number(g.power_w).toFixed(0)+'W':null; var temp=(g.temp_c!=null)?Number(g.temp_c).toFixed(0)+'C':null; var right=[power,temp].filter(Boolean).join(' • '); var vt=Number(g.vram_total_mb||0), vu=Number(g.vram_used_mb||0); return "<div class='gpuCard'>"+"<div class='gpuHead'><div class='l'>GPU "+idx+"</div><div class='r'>"+(right||'')+"</div></div>"+"<div class='gpuRow'><div class='k'>Util</div><div class='v'>"+fmtPct(util)+"</div></div>"+"<div class='bar small' id='barGpu"+idx+"'><div></div></div>"+"<div class='gpuRow' style='margin-top:10px'><div class='k'>VRAM</div><div class='v'>"+(vt?((vu/1024).toFixed(1)+' / '+(vt/1024).toFixed(1)+' GB'):'-')+"</div></div>"+"<div class='bar small' id='barVram"+idx+"'><div></div></div>"+"</div>"; }).join(''); gpus.slice(0,8).forEach(function(g,i){ g=g||{}; var idx=(g.index!=null)?g.index:i; setBar('barGpu'+idx, Number(g.util_gpu_pct||0)); var vt=Number(g.vram_total_mb||0), vu=Number(g.vram_used_mb||0); setBar('barVram'+idx, vt?(vu/vt*100):0); }); }
function updateMonitorFromMetrics(m){ var b=(m&&m.body)?m.body:(m||{}); var cpu=Number(b.cpu_pct||0); var c=document.getElementById('monCpu'); if(c) c.textContent=fmtPct(cpu); setBar('barCpu',cpu); var rt=Number(b.ram_total_mb||0), ru=Number(b.ram_used_mb||0); var rp=rt?(ru/rt*100):0; var r=document.getElementById('monRam'); if(r) r.textContent=rt?(ru.toFixed(0)+' / '+rt.toFixed(0)+' MB ('+rp.toFixed(1)+'%)'):'-'; setBar('barRam',rp); renderGpus(b); var sub=document.getElementById('monSub'); if(sub) sub.textContent='Tinybox time: '+(b.ts?fmtTs(b.ts):'-'); updateDockFromMetrics(m); try{ var procs=Array.isArray(b.processes)?b.processes:[]; var pre=document.getElementById('monProc'); if(pre){ if(!procs.length) pre.textContent='(no process data)'; else{ var lines=['PID     %CPU   %MEM   GPU   ELAPSED   COMMAND','-----------------------------------------------']; for(var i=0;i<procs.length;i++){ var p=procs[i]||{}; var pid=String(p.pid||'').padEnd(7,' '); var cpuS=String(Number(p.cpu_pct||0).toFixed(1)).padStart(5,' '); var memS=String(Number(p.mem_pct||0).toFixed(1)).padStart(5,' '); var gpuS=(p.gpu_mem_mb!=null?String(Number(p.gpu_mem_mb).toFixed(0))+'MB':'-').padStart(6,' '); var et=String(p.elapsed||'').padEnd(9,' '); var cmd=String(p.args||p.command||p.name||''); lines.push(pid+'  '+cpuS+'  '+memS+'  '+gpuS+'  '+et+'  '+cmd);} pre.textContent=lines.join(String.fromCharCode(10)); } } }catch(e){} }
function startMetricsStream(){ if(!monitorEnabled) return; stopMetricsStream(); try{ var ds=document.getElementById('dockStats'); if(ds) ds.textContent='Connecting…'; }catch(e){} try{ metricsES=new EventSource('/api/metrics/stream'); metricsES.onmessage=function(ev){ try{ var m=JSON.parse(ev.data||'{}'); lastMetrics=m; updateMonitorFromMetrics(m);}catch(e){} }; metricsES.onerror=function(_e){ try{ var ds=document.getElementById('dockStats'); if(ds) ds.textContent='Monitor error'; }catch(e){} }; }catch(e){} }
function setMonitorEnabled(on){ monitorEnabled=!!on; saveMonitorPref(monitorEnabled); try{ document.documentElement.classList.toggle('monOn', !!monitorEnabled); }catch(e){} if(!monitorEnabled){ stopMetricsStream(); try{ var ds=document.getElementById('dockStats'); if(ds) ds.textContent='Monitor off'; }catch(e){} return; } startMetricsStream(); }
function openMonitor(){ if(!monitorEnabled) return; var b=document.getElementById('monitorBackdrop'); var sh=document.getElementById('monitorSheet'); if(b){ b.classList.remove('hide'); b.style.display='block'; } if(sh){ sh.classList.remove('hide'); sh.style.display='block'; } try{ document.body.classList.add('sheetOpen'); }catch(e){} startMetricsStream(); if(lastMetrics) updateMonitorFromMetrics(lastMetrics); }
function closeMonitor(){ var b=document.getElementById('monitorBackdrop'); var sh=document.getElementById('monitorSheet'); if(b){ b.classList.add('hide'); b.style.display='none'; } if(sh){ sh.classList.add('hide'); sh.style.display='none'; } try{ document.body.classList.remove('sheetOpen'); }catch(e){} }
function closeMonitorEv(ev){ try{ if(ev && ev.stopPropagation) ev.stopPropagation(); }catch(e){} closeMonitor(); return false; }
function bindMonitorClose(){ try{ var btn=document.getElementById('monCloseBtn'); if(btn && !btn.__bound){ btn.__bound=true; btn.addEventListener('touchend', function(ev){ closeMonitorEv(ev); }, {passive:false}); btn.addEventListener('click', function(ev){ closeMonitorEv(ev); }); } }catch(e){} }
try{ document.addEventListener('DOMContentLoaded', function(){ bindMonitorClose(); setMonitorEnabled(loadMonitorPref()); }); }catch(e){}
try{ bindMonitorClose(); setMonitorEnabled(loadMonitorPref()); }catch(e){}
</script>
"""

DEBUG_BANNER_HTML = """
  <div id='boot' class='boot muted'>
    <span id='bootText'><strong>Build</strong>: __BUILD__ • JS: booting…</span>
    <button class='copyBtn' type='button' onclick='copyBoot()' aria-label='Copy build + error' style='margin-left:auto'>
      <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
        <path stroke="currentColor" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" d="M11 7H7a2 2 0 00-2 2v9a2 2 0 002 2h10a2 2 0 002-2v-9a2 2 0 00-2-2h-4M11 7V5a2 2 0 114 0v2M11 7h4"/>
      </svg>
    </button>
  </div>
"""

DEBUG_BANNER_BOOT_JS = """
<script>
// minimal boot script (runs even if the main app script has a syntax error)
window.__SF_BUILD = '__BUILD__';
window.__SF_BOOT_TS = Date.now();
window.__SF_LAST_ERR = '';

// Cache-bust HTML on iOS/Safari/CF edge caching: only when Debug UI is enabled.
// IMPORTANT: avoid refresh loops. Only auto-add ?v=... once per tab/session, and only if v is missing.
try{
  var dbg = null;
  try{ dbg = localStorage.getItem('sf_debug_ui'); }catch(e){}
  var debugOn = (dbg===null || dbg==='' || dbg==='1');
  if (debugOn){
    var u = new URL(window.location.href);
    var v = u.searchParams.get('v');
    if (!v){
      var key = 'sf_reload_once';
      var did = false;
      try{ did = (sessionStorage.getItem(key) === '1'); }catch(e){}
      if (!did){
        try{ sessionStorage.setItem(key, '1'); }catch(e){}
        u.searchParams.set('v', String(window.__SF_BUILD||''));
        window.location.replace(u.toString());
      }
    }
  }
}catch(e){}

function __sfEnsureBootBanner(){
  // Ensure we always have a dedicated #bootText span + copy button.
  try{
    var boot = document.getElementById('boot');
    if (!boot) return null;
    var t = document.getElementById('bootText');
    if (t) return t;

    boot.innerHTML = `<span id='bootText'><strong>Build</strong>: ${window.__SF_BUILD} • JS: ok</span>` +
      `<button class='copyBtn' type='button' onclick='copyBoot()' aria-label='Copy build + error' style='margin-left:auto'>` +
      `<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">` +
      `<path stroke="currentColor" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" d="M11 7H7a2 2 0 00-2 2v9a2 2 0 002 2h10a2 2 0 002-2v-9a2 2 0 00-2-2h-4M11 7V5a2 2 0 114 0v2M11 7h4"/>` +
      `</svg>` +
      `</button>`;

    return document.getElementById('bootText');
  }catch(e){
    return null;
  }
}

function __sfSetDebugInfo(msg){
  try{
    window.__SF_LAST_ERR = msg || '';
    var t = __sfEnsureBootBanner();
    if (t) t.textContent = 'Build: ' + window.__SF_BUILD + ' • JS: ' + (window.__SF_LAST_ERR || 'ok');
  }catch(e){}
}

window.addEventListener('error', function(ev){
  var m = 'unknown';
  try{ m = (ev && (ev.message||ev.type)) ? (ev.message||ev.type) : 'unknown'; }catch(_e){}
  __sfSetDebugInfo('error: ' + m);
});
window.addEventListener('unhandledrejection', function(_ev){
  __sfSetDebugInfo('promise error');
});

try{
  document.addEventListener('DOMContentLoaded', function(){
    try{ if (!window.__SF_LAST_ERR) __sfSetDebugInfo('ok'); }catch(e){}
  });
}catch(e){}

function __sfTryBootBanner(n){
  try{
    // If the banner HTML is rendered later in the page, we may run before #boot exists.
    if (document.getElementById('bootText')){ __sfSetDebugInfo(window.__SF_LAST_ERR || ''); return; }
    if ((n||0) >= 30) return; // ~3s max
    setTimeout(function(){ __sfTryBootBanner((n||0)+1); }, 100);
  }catch(e){}
}

// Copy helper (works even if the main JS bundle is broken)
function __sfCopyText(txt){
  try{
    txt = String(txt||'');
    if (!txt) return;
    if (navigator.clipboard && navigator.clipboard.writeText){
      navigator.clipboard.writeText(txt).catch(function(){
        try{
          var ta=document.createElement('textarea');
          ta.value=txt; ta.style.position='fixed'; ta.style.left='-9999px'; ta.style.top='0';
          document.body.appendChild(ta);
          ta.focus(); ta.select();
          try{ document.execCommand('copy'); }catch(_e){}
          ta.remove();
        }catch(_e){}
      });
      return;
    }
  }catch(e){}
  try{
    var ta=document.createElement('textarea');
    ta.value=txt; ta.style.position='fixed'; ta.style.left='-9999px'; ta.style.top='0';
    document.body.appendChild(ta);
    ta.focus(); ta.select();
    try{ document.execCommand('copy'); }catch(_e){}
    ta.remove();
  }catch(e){}
}

function copyBoot(){
  try{
    var t = (document.getElementById('bootText') || document.getElementById('boot'));
    var txt = t ? (t.textContent || '') : '';
    __sfCopyText(txt);
    try{
      if (typeof toastSet === 'function'){
        toastSet('Copied', 'ok', 1200);
        if (window.__sfToastInit) window.__sfToastInit();
      }
    }catch(_e){}
  }catch(e){}
}

try{
  // Kick once now + again after DOM ready to avoid "booting" getting stuck.
  __sfTryBootBanner(0);
  document.addEventListener('DOMContentLoaded', function(){ __sfTryBootBanner(0); });
}catch(e){}
</script>
"""

TODO_BASE_CSS = (
    COMMON_VARS_HEADER_CSS
    + base_css("""\

    body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--text);padding:18px;max-width:920px;margin:0 auto;}
    .menuWrap{position:relative;display:inline-block;}
    .userBtn{width:38px;height:38px;border-radius:999px;border:1px solid var(--line);background:transparent;color:var(--text);font-weight:950;display:inline-flex;align-items:center;justify-content:center;}
    .userBtn:hover{background:rgba(255,255,255,0.06);}
    .menuCard{position:absolute;right:0;top:46px;min-width:240px;max-width:calc(100vw - 36px);background:var(--card);border:1px solid var(--line);border-radius:16px;padding:12px;display:none;z-index:60;box-shadow:0 18px 60px rgba(0,0,0,.45);}
    .menuCard.show{display:block;}
    .menuCard .uTop{display:flex;gap:10px;align-items:center;margin-bottom:10px;}
    .menuCard .uAvatar{width:36px;height:36px;border-radius:999px;background:#0b1020;border:1px solid var(--line);display:flex;align-items:center;justify-content:center;}
    .menuCard .uName{font-weight:950;}
    .menuCard .uSub{color:var(--muted);font-size:12px;margin-top:2px;}
    .menuCard .uActions{display:flex;gap:10px;justify-content:flex-end;margin-top:10px;}

    /* Mobile: bottom-sheet menu */
    @media (max-width:520px){
      .menuCard{position:fixed;left:14px;right:14px;top:auto;bottom:calc(14px + env(safe-area-inset-bottom));min-width:0;max-width:none;}
    }

    .err{color:var(--bad);font-weight:950;margin:10px 0;}
    .bar{display:flex;justify-content:space-between;align-items:center;gap:12px;margin:12px 0;}
    .right{display:flex;justify-content:flex-end;align-items:center;gap:10px;margin-left:auto;}
    button{padding:10px 12px;border-radius:12px;border:1px solid var(--line);background:#163a74;color:#fff;font-weight:950;cursor:pointer;}
    button.secondary{background:transparent;color:var(--text);}

    /* iOS-like switch */
    .switch{position:relative;display:inline-block;width:52px;height:30px;flex:0 0 auto;}
    .switch input{display:none;}
    .slider{position:absolute;cursor:pointer;inset:0;background:#0a0f20;border:1px solid rgba(255,255,255,0.12);transition:.18s;border-radius:999px;}
    .slider:before{position:absolute;content:'';height:24px;width:24px;left:3px;top:2px;background:white;transition:.18s;border-radius:999px;}
    .switch input:checked + .slider{background:#1f6feb;border-color:rgba(31,111,235,.35);}
    .switch input:checked + .slider:before{transform:translateX(22px);}

    .card{border:1px solid var(--line);border-radius:16px;padding:12px;margin:12px 0;background:var(--card);}

    .catHead{display:flex;justify-content:space-between;align-items:baseline;margin:18px 0 8px 0;}
    .catTitle{font-weight:950;font-size:16px;}
    .catCount{color:var(--muted);font-weight:800;font-size:12px;}

    .todoItem{display:block;margin:10px 0;}
    /* swipe-delete (implemented as horizontal scroll) */
    .todoSwipe{display:block;overflow-x:auto;overflow-y:hidden;-webkit-overflow-scrolling:touch;scrollbar-width:none;}
    .todoSwipe::-webkit-scrollbar{display:none;}
    .todoSwipeInner{display:flex;min-width:100%;}
    .todoMain{min-width:100%;display:flex;gap:10px;align-items:flex-start;}
    .todoKill{flex:0 0 auto;display:flex;align-items:center;justify-content:center;padding-left:10px;}
    .todoId{color:var(--muted);font-size:12px;font-weight:900;margin-left:8px;white-space:nowrap;}
    .todoHiBtn{border:1px solid rgba(255,255,255,0.18);background:rgba(255,255,255,0.04);color:var(--muted);font-weight:950;border-radius:999px;padding:6px 10px;font-size:12px;line-height:1;cursor:pointer;}
    .todoHiBtn:active{transform:translateY(1px);}
    .todoItem.hi{ }
    .todoItem.hi .todoText{color:var(--text);}
    .todoDelBtn{background:transparent;border:1px solid rgba(255,77,77,.35);color:var(--bad);font-weight:950;border-radius:12px;padding:10px 12px;}
    .todoItem.hi .todoHiBtn{border-color:rgba(74,163,255,0.95);color:#ffffff;background:linear-gradient(180deg, rgba(74,163,255,0.95), rgba(31,111,235,0.85));box-shadow:0 8px 18px rgba(31,111,235,0.22);}
    .todoItem input{margin-top:3px;transform:scale(1.15);} 
    .todoTextWrap{min-width:0;}
    .todoText{line-height:1.25;}
    .todoMeta{color:var(--muted);font-size:12px;margin-top:4px;}
    .todoPlain{margin:8px 0;color:var(--muted);}

""")
)

def _todo_api_check(request: Request):
    # Token-gated write API for the assistant only (no UI writes).
    token = os.environ.get('TODO_API_TOKEN', '').strip()
    if not token:
        return 'disabled'
    got = (request.headers.get('x-sf-todo-token') or '').strip()
    if not got:
        auth = (request.headers.get('authorization') or '').strip()
        if auth.lower().startswith('bearer '):
            got = auth[7:].strip()
    if got != token:
        return 'unauthorized'
    return None



def _h() -> dict[str, str]:
    if not GATEWAY_TOKEN:
        return {}
    return {"Authorization": "Bearer " + GATEWAY_TOKEN}


def _get(path: str, timeout_s: float = 20.0) -> dict[str, Any]:
    r = requests.get(GATEWAY_BASE + path, headers=_h(), timeout=float(timeout_s))
    # Normalize upstream failures into readable errors (don't leak headers/tokens).
    if r.status_code >= 400:
        txt = ""
        try:
            txt = (r.text or "")[:200]
        except Exception:
            txt = ""
        raise HTTPException(status_code=502, detail={"error": "upstream_http", "status": int(r.status_code), "body": txt})
    try:
        return r.json()
    except Exception:
        # Avoid opaque 500s when the upstream returns non-JSON.
        txt = ""
        try:
            txt = (r.text or "")[:200]
        except Exception:
            txt = ""
        raise HTTPException(status_code=502, detail={"error": "upstream_non_json", "status": int(r.status_code), "body": txt})


@app.get("/", response_class=HTMLResponse)
def index(response: Response):
    build = APP_BUILD
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
                mon_btn = (
                    "<div class='row' style='justify-content:space-between;margin-top:10px'>"
                    "<div class='muted' style='font-weight:950'>System monitoring</div>"
                    "<label class='switch'>"
                    "<input id='monToggleChk' type='checkbox' onchange='toggleMonitor()' />"
                    "<span class='slider'></span>"
                    "</label>"
                    "</div>"
                )

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
  <style>__INDEX_BASE_CSS__</style>
  __DEBUG_BANNER_BOOT_JS__
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
  <div class='navBar'>
  <div class='top'>
    <div>
      <div class='brandRow'><h1><a class='brandLink' href='/'>StoryForge</a></h1><div id='pageName' class='pageName'>Jobs</div></div>
      <div id='updateBar' class='updateBar hide'>
        <div class='muted' style='font-weight:950'>Updating StoryForge…</div>
        <div class='updateTrack'><div id='updateProg' class='updateProg'></div></div>
        <div id='updateSub' class='muted'>Reconnecting…</div>
      </div>

    </div>
    <div class='row rowEnd'>
      <a id='todoBtn' href='/todo' class='hide'><button class='secondary' type='button'>TODO</button></a>
      <div class='menuWrap'>
        <button class='userBtn' type='button' onclick='toggleMenu()' aria-label='User menu'>
          <svg viewBox='0 0 24 24' width='20' height='20' aria-hidden='true' style='stroke:currentColor;fill:none;stroke-width:2'>
            <path stroke-linecap='round' stroke-linejoin='round' d='M20 21a8 8 0 10-16 0'/>
            <path stroke-linecap='round' stroke-linejoin='round' d='M12 11a4 4 0 100-8 4 4 0 000 8z'/>
          </svg>
        </button>
        <div id='topMenu' class='menuCard'>
          <div class='uTop'>
            <div class='uAvatar'>
              <svg viewBox='0 0 24 24' width='18' height='18' aria-hidden='true' style='stroke:currentColor;fill:none;stroke-width:2'>
                <path stroke-linecap='round' stroke-linejoin='round' d='M20 21a8 8 0 10-16 0'/>
                <path stroke-linecap='round' stroke-linejoin='round' d='M12 11a4 4 0 100-8 4 4 0 000 8z'/>
              </svg>
            </div>
            <div>
              <div class='uName'>User</div>
              <div class='uSub'>Admin</div>
            </div>
          </div>
          <div class='uActions'>
            <a href='/logout'><button class='secondary' type='button'>Log out</button></a>
          </div>
        </div>
      </div>

    </div>
  </div>

  </div>

  __DEBUG_BANNER_HTML__

  <div class='tabs'>
    <button id='tab-history' class='tab active' onclick='showTab("history")'>Jobs</button>
    <button id='tab-library' class='tab' onclick='showTab("library")'>Library</button>
    <button id='tab-voices' class='tab' onclick='showTab("voices")'>Voices</button>
    <button id='tab-production' class='tab' onclick='showTab("production")'>Production</button>
        <button id='tab-advanced' class='tab' onclick='showTab("advanced")'>Settings</button>
  </div>

  <div id='pane-history'>
    <div class='card'>
      <div class='row' style='justify-content:space-between;'>
        <div>
          <div style='font-weight:950;'>Recent jobs</div>
        </div>
        <div class='row' style='justify-content:flex-end;'>



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
        <div class='row' style='justify-content:flex-end;'>


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
        <div class='row' style='justify-content:flex-end;'>


          <button class='secondary' onclick='closeStory()'>Close</button>
        </div>
      </div>

      <div style='font-weight:950;margin-top:12px;'>Characters</div>
      <pre id='libChars' class='term' style='margin-top:8px;'>-</pre>

      <div style='font-weight:950;margin-top:12px;'>Narrative (Markdown)</div>
      <pre id='libStory' class='term' style='margin-top:8px;white-space:pre-wrap;'>-</pre>

      <div class='row' style='margin-top:12px;'>
        <button class='secondary' onclick='copyStory()'>Copy story text</button>
      </div>
    </div>
  </div>


  <div id='pane-voices' class='hide'>
    <div class='card'>
      <div style='font-weight:950;margin-bottom:6px;'>Voices</div>
      <div class='muted'>CRUD for voice metadata (samples can be generated later).</div>

      <div class='row' style='margin-top:10px;'>
        <a href='/voices/new'><button class='secondary' type='button'>Generate new voice model</button></a>
      </div>

      <div id='voicesList' style='margin-top:10px' class='muted'>Loading…</div>
    </div>
  </div>

  <div id='pane-production' class='hide'>
    <div class='card'>
      <div style='font-weight:950;margin-bottom:6px;'>Production</div>
      <div class='muted'>Step 1: select a library story. Step 2: suggest voice casting from roster. Step 3 unlocks after saving casting.</div>

      <div class='muted' style='margin-top:12px'>1) Story</div>
      <select id='prodStorySel' style='margin-top:8px;width:100%'></select>

      <div class='muted' style='margin-top:12px'>2) Voice casting suggestion</div>
      <div class='row' style='margin-top:8px;justify-content:flex-end;gap:10px;flex-wrap:wrap'>
        <button type='button' class='secondary' onclick='prodSuggestCasting()'>Suggest casting</button>
        <button type='button' id='prodSaveBtn' onclick='prodSaveCasting()' disabled>Save casting</button>
      </div>

      <div id='prodOut' class='muted' style='margin-top:10px'></div>
      <div id='prodAssignments' style='margin-top:10px'></div>

      <div class='muted' style='margin-top:14px'>3) Generate markup (SFML)</div>
      <div class='row' style='margin-top:8px;justify-content:flex-end;gap:10px;flex-wrap:wrap'>
        <button type='button' id='prodStep3Btn' disabled onclick='prodGenerateSfml()'>Generate SFML</button>
        <button type='button' class='secondary' onclick='prodCopySfml()'>Copy SFML</button>
      </div>

      <div id='prodSfmlBox' class='codeBox hide' style='margin-top:10px'></div>
    </div>
  </div>

  <div id='pane-advanced' class='hide'>

    <div class='card'>
      <div class='row' style='justify-content:space-between;align-items:baseline;gap:10px'>
        <div style='font-weight:950;margin-bottom:6px;'>Providers</div>
        <a href='/settings/providers/new'><button type='button' class='secondary'>Add provider</button></a>
      </div>

      <div id='providersBox' class='muted' style='margin-top:10px'>Loading…</div>

      <div class='row' style='margin-top:10px;gap:10px;flex-wrap:wrap;justify-content:flex-end'>
        <button type='button' onclick='saveProviders()'>Save</button>
      </div>
    </div>

    <div class='card'>
      <div style='font-weight:950;margin-bottom:6px;'>Debug UI</div>
      <div class='muted'>Hide/show the build + JS error banner.</div>
      <div class='row' style='margin-top:10px;'>
        <button id='dbgToggle' class='secondary' onclick='toggleDebugUi()'>Disable debug</button>
      </div>
    </div>

  </div>

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
function toastSet(msg, kind, ms){
  try{
    localStorage.setItem('sf_toast_msg', String(msg||''));
    localStorage.setItem('sf_toast_kind', String(kind||'info'));
    localStorage.setItem('sf_toast_until', String(Date.now() + (ms||2600)));
  }catch(e){}
}
function toastShowNow(msg, kind, ms){
  try{ toastSet(msg, kind, ms); }catch(e){}
  try{ if (window.__sfToastInit) window.__sfToastInit(); }catch(e){}
}

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
  for (var i=0;i<['history','library','voices','production','advanced'].length;i++){
    var n=['history','library','voices','production','advanced'][i];
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

  try{ var pn=document.getElementById('pageName'); if(pn){ pn.textContent = (name==='history'?'Jobs':(name==='library'?'Library':(name==='voices'?'Voices':(name==='production'?'Production':'Settings')))); } }catch(e){}

  // lazy-load tab content
  try{
    if (name==='history') { try{ bindJobsLazyScroll(); }catch(e){}; loadHistory(true); }
    else if (name==='library') loadLibrary();
    else if (name==='voices') loadVoices();
    else if (name==='production') loadProduction();
  }catch(_e){}
}

function getTabFromHash(){
  try{
    var h = (window.location.hash || '').replace('#','');
    if (h==='tab-history') return 'history';
    if (h==='tab-library') return 'library';
    if (h==='tab-voices') return 'voices';
    if (h==='tab-production') return 'production';
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
  if (!v) return;
  try{
    var p = copyToClipboard(v);
    // Show toast immediately (even if clipboard API is blocked, this still confirms the tap).
    try{ toastSet('Copied', 'ok', 1200); window.__sfToastInit && window.__sfToastInit(); }catch(e){}
    return p;
  }catch(e){
    try{ toastSet('Copy failed', 'err', 1800); window.__sfToastInit && window.__sfToastInit(); }catch(_e){}
  }
}

window.__SF_LAST_API_FAIL = 0;

function fetchJsonAuthed(url, opts){
  return fetch(url, opts).then(function(r){
    if (r.status === 401){
      window.location.href = '/login';
      throw new Error('unauthorized');
    }
    return r.text().then(function(t){
      if (!r.ok){
        try{ window.__SF_LAST_API_FAIL = Date.now(); }catch(_e){}
        throw new Error('HTTP ' + r.status + ' ' + (t || '').slice(0,200));
      }
      try{
        return JSON.parse(t || 'null');
      }catch(e){
        try{ window.__SF_LAST_API_FAIL = Date.now(); }catch(_e){}
        return {ok:false, error:'bad_json', status:r.status, body:(t||'').slice(0,300)};
      }
    });
  }).catch(function(e){
    try{ window.__SF_LAST_API_FAIL = Date.now(); }catch(_e){}
    throw e;
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

function toggleMenu(){
  var m=document.getElementById('topMenu');
  if (!m) return;
  if (m.classList.contains('show')) m.classList.remove('show');
  else m.classList.add('show');
}
function toggleUserMenu(){ return toggleMenu(); }

document.addEventListener('click', function(ev){
  try{
    var m=document.getElementById('topMenu');
    if (!m) return;
    var w=ev.target && ev.target.closest ? ev.target.closest('.menuWrap') : null;
    if (!w) m.classList.remove('show');
  }catch(e){}
});

function copyBoot(){
  try{
    var t = (document.getElementById('bootText') || document.getElementById('boot'));
    var txt = t ? (t.textContent || '') : '';
    if (!txt) return;
    if (typeof copyToClipboard==='function') copyToClipboard(txt);
    try{ toastSet('Copied', 'ok', 1200); window.__sfToastInit && window.__sfToastInit(); }catch(e){}
  }catch(e){}
}

function copyDebugInfo(){
  // Kept for backwards compatibility (older HTML may still call it).
  try{
    var b = (window.__SF_BUILD || '').trim();
    var e = (window.__SF_LAST_ERR || '').trim();
    var txt = 'Build: ' + (b || '?') + '\\nJS: ' + (e || '(none)');
    if (typeof copyToClipboard==='function') copyToClipboard(txt);
    try{ toastSet('Copied', 'ok', 1200); window.__sfToastInit && window.__sfToastInit(); }catch(_e){}
  }catch(_e){}
}


function fmtTs(ts){
  if (!ts) return '-';
  try{
    const d=new Date(ts*1000);
    return d.toLocaleString();
  }catch(e){
    return String(ts);
  }
}

function safeJson(s){
  try{ if(!s) return null; return JSON.parse(String(s)); }catch(e){ return null; }
}

function pauseJobsStream(ms){
  try{
    ms = parseInt(String(ms||'0'),10) || 0;
    window.__SF_JOBS_STREAM_PAUSED_UNTIL = Date.now() + Math.max(0, ms);
    try{ if (jobsES){ jobsES.close(); jobsES=null; } }catch(e){}
    if (ms>0){
      setTimeout(function(){
        try{
          if (Date.now() >= (window.__SF_JOBS_STREAM_PAUSED_UNTIL||0)) startJobsStream();
        }catch(e){}
      }, ms+50);
    }
  }catch(e){}
}

function jobPlay(jobId, url){
  try{
    if (!url || !jobId) return;

    // Jobs page uses SSE and re-renders the list, which can kill inline audio.
    // Pause the jobs stream while audio is playing.
    try{ pauseJobsStream(5*60*1000); }catch(e){}

    // Close any other open players
    try{
      var olds=document.querySelectorAll('.jobPlayer');
      for (var i=0;i<olds.length;i++){
        try{ var a0=olds[i].querySelector('audio'); if (a0) a0.pause(); }catch(e){}
        try{ olds[i].remove(); }catch(e){}
      }
    }catch(e){}

    var card=document.querySelector('[data-jobid="'+String(jobId)+'"]');
    if (!card) return;

    var box=document.createElement('div');
    box.className='jobPlayer';
    box.style.marginTop='10px';
    box.style.padding='10px';
    box.style.border='1px solid rgba(255,255,255,0.10)';
    box.style.borderRadius='12px';
    box.style.background='rgba(255,255,255,0.03)';

    var a=document.createElement('audio');
    a.controls=true;
    a.style.width='100%';
    a.src=String(url);
    a.onended = function(){ try{ window.__SF_JOBS_STREAM_PAUSED_UNTIL = 0; startJobsStream(); }catch(e){} };
    a.onpause = function(){ try{ /* allow manual pause without restarting immediately */ }catch(e){} };

    box.appendChild(a);
    card.appendChild(box);

    try{
      var p = a.play();
      if (p && typeof p.catch === 'function') p.catch(function(_e){});
    }catch(e){}
  }catch(e){}
}

function saveJobToRoster(jobId){
  try{
    var card=document.querySelector('[data-jobid="'+jobId+'"]');
    var meta = safeJson(card ? card.getAttribute('data-meta') : '');
    var url = card ? String(card.getAttribute('data-url')||'') : '';
    if (!meta || !url){ alert('Missing job metadata'); return; }

    var rid = String(meta.roster_id||meta.id||'').trim();
    if (!rid) rid = slugify(String(meta.display_name||'voice'));
    var payload={
      id: rid,
      display_name: String(meta.display_name||rid),
      engine: String(meta.engine||''),
      voice_ref: String(meta.voice_ref||meta.voice||''),
      sample_text: String(meta.sample_text||meta.text||''),
      sample_url: url,
      enabled: true,
    };

    var btn = card ? card.querySelector('.saveRosterBtn') : null;
    if (btn) btn.textContent='Saving…';
    fetchJsonAuthed('/api/voices', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)})
      .then(function(j){
        if (!j || !j.ok){ throw new Error((j&&j.error)||'save_failed'); }
        try{ localStorage.setItem('sf_job_saved_'+String(jobId||''), '1'); }catch(_e){}
        try{ toastSet('Saved to roster', 'ok', 1400); window.__sfToastInit && window.__sfToastInit(); }catch(_e){}
        if (btn){ btn.textContent='Saved'; btn.disabled=true; }
      })
      .catch(function(e){ if(btn){ btn.textContent='Save to roster'; btn.disabled=false; } alert('Save failed: '+String(e)); });
  }catch(e){ alert('Save failed'); }
}

function ensureJobsStream(on){
  try{
    on = !!on;
    if (!on){
      try{ if (jobsES){ jobsES.close(); jobsES=null; } }catch(e){}
      return;
    }
    try{ startJobsStream(); }catch(e){}
  }catch(e){}
}

function renderJobs(jobs){
  const el=document.getElementById('jobs');
  if (!el) return;
  if (!jobs || !jobs.length){
    el.innerHTML = "<div class='muted'>No jobs yet.</div>";
    try{ ensureJobsStream(false); }catch(e){}
    return;
  }

  const hasRunning = jobs.some(j => String(j.state||'')==='running');
  try{ ensureJobsStream(hasRunning); }catch(e){}

  el.innerHTML = jobs.map(job=>{
    const total = Number(job.total_segments||0);
    const done = Number(job.segments_done||0);
    const pct = total ? Math.max(0, Math.min(100, (done/total*100))) : 0;
    const isDone = (String(job.state||'') === 'completed' || String(job.state||'') === 'failed');
    const progText = total ? `${done} / ${total} (${pct.toFixed(0)}%)` : '-';
    const progBar = (!isDone && total) ? `<div class='bar small' style='margin-top:6px'><div style='width:${pct.toFixed(1)}%'></div></div>` : '';

    const meta = safeJson(job.meta_json||'') || null;
    const isSample = (String(job.kind||'') === 'tts_sample') || (String(job.title||'').indexOf('TTS (')===0);
    const playable = (String(job.state||'')==='completed' && job.mp3_url);

    const actions = (isSample && playable) ? (
      `<div style='margin-top:10px;display:flex;gap:10px;flex-wrap:wrap;'>`
      + `<button type='button' class='secondary' onclick="jobPlay('${escAttr(job.id||'')}','${escAttr(job.mp3_url||'')}')">Play</button>`
      + (function(){
          try{
            var saved = false;
            try{ saved = (localStorage.getItem('sf_job_saved_'+String(job.id||'')) === '1'); }catch(_e){}
            if (saved){
              return `<button type='button' class='saveRosterBtn' disabled>Saved</button>`;
            }
          }catch(_e){}
          return (meta ? `<button type='button' class='saveRosterBtn' onclick="saveJobToRoster('${escAttr(job.id||'')}')">Save to roster</button>` : `<button type='button' class='saveRosterBtn' onclick="alert('This older job is missing metadata. Re-run Test sample once and then Save will appear here.')">Save to roster</button>`);
        })()
      + `</div>`
    ) : '';

    const voiceName = (meta && (meta.display_name || meta.voice_name || meta.name || meta.roster_id || meta.id)) ? String(meta.display_name || meta.voice_name || meta.name || meta.roster_id || meta.id) : '';
    const cardTitle = isSample ? ((job.title ? String(job.title) : 'Voice sample') + (voiceName ? (' • ' + voiceName) : '')) : (job.title||job.id);

    const errRow = (String(job.state||'')==='failed' && (job.sfml_url||'')) ? (
      `<div class='k'>error</div><div class='term' style='white-space:pre-wrap'>${escapeHtml(String(job.sfml_url||'').slice(0,1600))}</div>`
    ) : '';

    const isVoiceMeta = (String(job.kind||'') === 'voice_meta');

    // Common fields for all jobs
    let rows = ''
      + `<div class='k'>id</div><div>${escapeHtml(String(job.id||''))}</div>`
      + `<div class='k'>started</div><div>${fmtTs(job.started_at)}</div>`
      + `<div class='k'>finished</div><div>${fmtTs(job.finished_at)}</div>`
      + `<div class='k'>progress</div><div>${progText}${progBar}</div>`;

    // Variable fields by job type
    if (isSample){
      rows += `<div class='k'>audio</div><div class='fadeLine'><div class='fadeText' title='${job.mp3_url||""}'>${job.mp3_url||'-'}</div>${job.mp3_url?`<button class="copyBtn" data-copy="${job.mp3_url}" onclick="copyFromAttr(this)" aria-label="Copy">${copyIconSvg()}</button>`:''}</div>`;
    } else if (isVoiceMeta){
      try{
        const vid2 = (meta && meta.voice_id) ? String(meta.voice_id) : '';
        const eng2 = (meta && meta.engine) ? String(meta.engine) : '';
        const vref2 = (meta && meta.voice_ref) ? String(meta.voice_ref) : '';
        if (vid2) rows += `<div class='k'>voice</div><div><a href='/voices/${encodeURIComponent(vid2)}/edit' style='color:var(--text);text-decoration:underline'>${escapeHtml(vid2)}</a></div>`;
        if (eng2) rows += `<div class='k'>engine</div><div>${escapeHtml(eng2)}</div>`;
        if (vref2) rows += `<div class='k'>voice_ref</div><div class='fadeLine'><div class='fadeText' title='${escapeHtml(vref2)}'>${escapeHtml(vref2)}</div></div>`;
      }catch(e){}
    } else {
      // Generic jobs: only show URLs when present
      if (job.mp3_url){
        rows += `<div class='k'>mp3</div><div class='fadeLine'><div class='fadeText' title='${job.mp3_url||""}'>${job.mp3_url||'-'}</div>${job.mp3_url?`<button class="copyBtn" data-copy="${job.mp3_url}" onclick="copyFromAttr(this)" aria-label="Copy">${copyIconSvg()}</button>`:''}</div>`;
      }
      if (job.sfml_url){
        rows += `<div class='k'>sfml</div><div class='fadeLine'><div class='fadeText' title='${job.sfml_url||""}'>${job.sfml_url||'-'}</div>${job.sfml_url?`<button class="copyBtn" data-copy="${job.sfml_url}" onclick="copyFromAttr(this)" aria-label="Copy">${copyIconSvg()}</button>`:''}</div>`;
      }
    }

    // Status-specific fields
    rows += errRow;

    // Variable action buttons
    const metaActions = isVoiceMeta ? (function(){
      try{
        const vid2 = (meta && meta.voice_id) ? String(meta.voice_id) : '';
        if (!vid2) return '';
        return `<div style='margin-top:10px;display:flex;gap:10px;flex-wrap:wrap;'>`
          + `<a href='/voices/${encodeURIComponent(vid2)}/edit'><button type='button' class='secondary'>Open voice</button></a>`
          + `</div>`;
      }catch(e){ return ''; }
    })() : '';
    return `<div class='job' data-jobid='${escAttr(job.id||'')}' data-url='${escAttr(job.mp3_url||'')}' data-meta='${escAttr(job.meta_json||'')}'>
      <div class='row' style='justify-content:space-between;'>
        <div class='title'>${escapeHtml(cardTitle)}</div>
        <div>${pill(job.state)}</div>
      </div>
      <div class='kvs'>${rows}</div>
      ${actions}
      ${metaActions}
    </div>`;
  }).join('');
}

let __SF_JOBS = [];
let __SF_JOBS_NEXT_BEFORE = null;
let __SF_JOBS_LOADING = false;
let __SF_JOBS_DONE = false;

function loadHistory(reset){
  const el=document.getElementById('jobs');
  if (reset){
    __SF_JOBS = [];
    __SF_JOBS_NEXT_BEFORE = null;
    __SF_JOBS_LOADING = false;
    __SF_JOBS_DONE = false;
    if (el) el.textContent='Loading…';
  }
  if (__SF_JOBS_LOADING || __SF_JOBS_DONE) return Promise.resolve();
  __SF_JOBS_LOADING = true;

  var url = '/api/history?limit=20';
  if (__SF_JOBS_NEXT_BEFORE){ url += '&before=' + encodeURIComponent(String(__SF_JOBS_NEXT_BEFORE)); }

  return fetchJsonAuthed(url).then(function(j){
    __SF_JOBS_LOADING = false;
    if (!j || !j.ok){
      if (el && !__SF_JOBS.length) el.innerHTML=`<div class='muted'>Error: ${(j&&j.error)||'unknown'}</div>`;
      return;
    }
    var arr = (j.jobs || []);
    if (!arr.length){
      __SF_JOBS_DONE = true;
      return;
    }
    __SF_JOBS = __SF_JOBS.concat(arr);
    __SF_JOBS_NEXT_BEFORE = j.next_before || null;
    renderJobs(__SF_JOBS);
  }).catch(function(e){
    __SF_JOBS_LOADING = false;
    if (el && !__SF_JOBS.length) el.innerHTML = `<div class='muted'>Loading failed: ${String(e)}</div>`;
  });
}

function bindJobsLazyScroll(){
  try{
    if (window.__SF_JOBS_LAZY_BOUND) return;
    window.__SF_JOBS_LAZY_BOUND = true;
    window.addEventListener('scroll', function(){
      try{
        var near = (window.innerHeight + window.scrollY) >= (document.body.offsetHeight - 800);
        if (near) loadHistory(false);
      }catch(e){}
    }, {passive:true});
  }catch(e){}
}

// Live job updates
let jobsES = null;
function startJobsStream(){
  try{ if ((window.__SF_JOBS_STREAM_PAUSED_UNTIL||0) > Date.now()) return; }catch(e){}
  try{ if (jobsES){ jobsES.close(); jobsES=null; } }catch(e){}
  try{
    jobsES = new EventSource('/api/jobs/stream');
    jobsES.onmessage = function(ev){
      try{
        var j = JSON.parse(ev.data || '{}');
        if (j && j.ok && Array.isArray(j.jobs)) renderJobs(j.jobs);
      }catch(e){}
    };
  }catch(e){}
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
  var todo=document.getElementById('todoBtn');
  if (todo) todo.classList.toggle('hide', !!(!on));

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
  try{ if (typeof stopMetricsPoll==='function') try{ if (typeof stopMetricsPoll==='function') stopMetricsPoll(); }catch(e){} }catch(e){}
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
  const chk = document.getElementById('monToggleChk');
  if (chk) chk.checked = !!monitorEnabled;

  try{ document.documentElement.classList.toggle('monOn', !!monitorEnabled); }catch(e){}

  if (!monitorEnabled){
    stopMetricsStream();
    try{ if (typeof stopMetricsPoll==='function') try{ if (typeof stopMetricsPoll==='function') stopMetricsPoll(); }catch(e){} }catch(e){}
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

function escAttr(s){
  // escape for HTML attributes / single-quoted contexts
  try{
    return String(s||'')
      .replace(/&/g,'&amp;')
      .replace(/</g,'&lt;')
      .replace(/>/g,'&gt;')
      .replace(/"/g,'&quot;')
      .replace(/'/g,'&#39;');
  }catch(e){
    return '';
  }
}

function parseGpuList(s){
  try{
    s = String(s||'');
    if (!s.trim()) return [];
    return s.split(',').map(function(x){ return parseInt(String(x).trim(),10); }).filter(function(n){ return !isNaN(n); });
  }catch(e){
    return [];
  }
}


function onEngineToggle(cb){
  try{
    if (!cb) return;
    var pid = String(cb.getAttribute('data-pid')||'');
    var eng = String(cb.getAttribute('data-engine')||'');
    if (!pid || !eng) return;

    var hidden = document.querySelector('input[type=hidden][data-pid="'+pid+'"][data-k="voice_engines"]');
    var cur = [];
    try{ cur = parseGpuList(hidden ? hidden.value : '').map(String); }catch(e){ cur=[]; }
    // parseGpuList returns ints; we want strings; fallback:
    if (!cur.length){
      try{ cur = String(hidden ? hidden.value : '').split(',').map(function(x){return String(x||'').trim();}).filter(Boolean); }catch(e){ cur=[]; }
    }

    var on = !!cb.checked;
    var i = cur.indexOf(eng);
    if (on && i<0) cur.push(eng);
    if (!on && i>=0) cur.splice(i,1);

    // Guardrail: require at least one engine selected
    if (!cur.length){
      cb.checked = true;
      try{ toastSet('Pick at least 1 voice engine', 'bad', 1800); window.__sfToastInit && window.__sfToastInit(); }catch(e){}
      return;
    }

    if (hidden) hidden.value = cur.join(',');
  }catch(e){}
}

// --- GPU chips (rewrite): pure JS state + event delegation ---
window.__SF_GPU_STATE = window.__SF_GPU_STATE || {};

function _gpuUniqSorted(a){
  try{
    var m={}, out=[];
    a = Array.isArray(a) ? a : [];
    for (var i=0;i<a.length;i++){
      var n=parseInt(String(a[i]),10);
      if (isNaN(n)) continue;
      if (!m[n]){ m[n]=1; out.push(n); }
    }
    out.sort(function(x,y){return x-y;});
    return out;
  }catch(e){
    return [];
  }
}

function _gpuGet(pid){
  var st = (window.__SF_GPU_STATE && window.__SF_GPU_STATE[pid]) ? window.__SF_GPU_STATE[pid] : null;
  if (!st){ st = {voice:[], llm:[]}; window.__SF_GPU_STATE[pid]=st; }
  st.voice = _gpuUniqSorted(st.voice);
  st.llm = _gpuUniqSorted(st.llm);
  return st;
}

function _gpuSetFromProvider(pid, voiceArr, llmArr){
  var st = _gpuGet(pid);
  st.voice = _gpuUniqSorted(voiceArr);
  st.llm = _gpuUniqSorted(llmArr);
  // enforce exclusivity: if overlap exists, keep voice and drop from llm
  for (var i=0;i<st.voice.length;i++){
    var n=st.voice[i];
    var j=st.llm.indexOf(n);
    if (j>=0) st.llm.splice(j,1);
  }
}

function _gpuWriteHidden(pid){
  try{
    var st=_gpuGet(pid);
    var vHidden=document.querySelector('input[type=hidden][data-pid="'+pid+'"][data-k="voice_gpus"]');
    if (vHidden) vHidden.value = st.voice.join(',');
    var lHidden=document.querySelector('input[type=hidden][data-pid="'+pid+'"][data-k="llm_gpus"]');
    if (lHidden) lHidden.value = st.llm.join(',');
  }catch(e){}
}

function _gpuRenderPid(pid){
  try{
    var st=_gpuGet(pid);
    var chips=document.querySelectorAll('.gpuChip[data-pid="'+pid+'"]');
    for (var i=0;i<chips.length;i++){
      var role=String(chips[i].getAttribute('data-role')||'');
      var n=parseInt(String(chips[i].getAttribute('data-gpu')||''),10);
      if (isNaN(n)) continue;
      var on = (role==='voice') ? (st.voice.indexOf(n)>=0) : (st.llm.indexOf(n)>=0);
      var claimedOther = (role==='voice') ? (st.llm.indexOf(n)>=0) : (st.voice.indexOf(n)>=0);
      chips[i].classList.toggle('on', !!on);
      chips[i].classList.toggle('claimed', !!claimedOther);
    }
    _gpuWriteHidden(pid);
  }catch(e){}
}

function gpuToggle(pid, role, n){
  try{
    var st=_gpuGet(pid);
    role = String(role||'');
    n = parseInt(String(n||''),10);
    if (isNaN(n)) return;
    var mine = (role==='llm') ? st.llm : st.voice;
    var other = (role==='llm') ? st.voice : st.llm;

    var idx = mine.indexOf(n);
    if (idx>=0){
      // uncheck
      mine.splice(idx,1);
    } else {
      // check + last-click-wins: remove from other
      mine.push(n);
      var j = other.indexOf(n);
      if (j>=0) other.splice(j,1);
    }
    st.voice=_gpuUniqSorted(st.voice);
    st.llm=_gpuUniqSorted(st.llm);
    _gpuRenderPid(pid);
  }catch(e){}
}

function initGpuChips(){
  try{
    if (window.__SF_GPU_CHIPS_INIT) return;
    window.__SF_GPU_CHIPS_INIT = true;
    document.addEventListener('click', function(ev){
      try{
        var t = ev.target;
        var chip = t && t.closest ? t.closest('.gpuChip') : null;
        if (!chip) return;
        ev.preventDefault();
        var pid=String(chip.getAttribute('data-pid')||'');
        var role=String(chip.getAttribute('data-role')||'');
        var n=chip.getAttribute('data-gpu');
        gpuToggle(pid, role, n);
      }catch(e){}
    }, {passive:false});
  }catch(e){}
}

function __provId(p){
  return String((p&&p.id)||'').trim();
}

function __provTitle(p){
  var kind=String((p&&p.kind)||'');
  var name=String((p&&p.name)||'');
  return name || (kind ? kind : 'provider');
}

function renderProviders(providers){
  var el=document.getElementById('providersBox');
  if (!el) return;
  providers = Array.isArray(providers) ? providers : [];
  if (!providers.length){
    el.innerHTML = "<div class='muted'>No providers yet. Add Tinybox/OpenAI/Google above.</div>";
    return;
  }

  var enabledModels = [
    {id:'google/gemma-2-9b-it', label:'Gemma 2 9B Instruct', kind:'llm'},
  ];

  el.innerHTML = providers.map(function(p, idx){
    // GPU chips init (event delegation)
    try{ initGpuChips(); }catch(e){}
    var id = __provId(p) || ('p'+idx);
    var kind = String(p.kind||'');
    var name = String(p.name||'');

    var monOn = !!(p.monitoring_enabled);
    var voiceOn = !!(p.voice_enabled);
    var llmOn = !!(p.llm_enabled);

    var voiceEng = Array.isArray(p.voice_engines) ? p.voice_engines : ['xtts','tortoise'];


    var gatewayBase = String(p.gateway_base || '');

    var voiceG = Array.isArray(p.voice_gpus) ? p.voice_gpus : [0,1];
    var llmG = Array.isArray(p.llm_gpus) ? p.llm_gpus : [2];
    // init state store (single source of truth)
    try{ _gpuSetFromProvider(id, voiceG, llmG); }catch(e){}
    var llmModel = String(p.llm_model || 'google/gemma-2-9b-it');

    var header = "<div class='row provHead' data-pid='"+escAttr(id)+"' onclick='toggleProvBtn(this)' style='justify-content:space-between;cursor:pointer;'>"+
      "<div><div style='font-weight:950'>"+escapeHtml(name||kind||'Provider')+"</div><div class='muted'>"+escapeHtml(kind)+" • id: <code>"+escapeHtml(id)+"</code></div></div>"+
      "<div class='row' style='justify-content:flex-end;gap:10px;flex-wrap:wrap'>"+
      "</div>"+
    "</div>";

    var body = "<div class='kvs provKvs' style='margin-top:10px'>"+
      (kind==='tinybox' ? ("<div class='k'>Gateway</div><div style='min-width:0'><input data-pid='"+escAttr(id)+"' data-k='gateway_base' value='"+escAttr(gatewayBase)+"' placeholder='http://159.65.251.41:8791' style='display:block;max-width:100%;width:100%;box-sizing:border-box;min-width:0' /></div>") : "")+
      "<div class='k'>System monitor</div><div><label class='switch'><input type='checkbox' data-pid='"+escAttr(id)+"' data-k='monitoring_enabled' "+(monOn?'checked':'')+" onchange='onProvMonitorToggle(this); event.stopPropagation();'/><span class='slider'></span></label></div>"+

      "<div class='provSection'>Voice service</div>"+
      ""+
      "<div class='k'>Enabled engines</div><div class='checkLine'>"+
        "<input type='hidden' data-pid='"+escAttr(id)+"' data-k='voice_engines' value='"+escAttr(voiceEng.join(','))+"'/>"+
        "<label class='checkPill'><input type='checkbox' class='engCb' data-pid='"+escAttr(id)+"' data-engine='xtts' "+(voiceEng.indexOf('xtts')>=0?'checked':'')+" onchange='onEngineToggle(this)'/>xtts</label>"+
        "<label class='checkPill'><input type='checkbox' class='engCb' data-pid='"+escAttr(id)+"' data-engine='tortoise' "+(voiceEng.indexOf('tortoise')>=0?'checked':'')+" onchange='onEngineToggle(this)'/>tortoise</label>"+
      "</div>"+
      "<div class='k'>Split min chars</div><div><input data-pid='"+escAttr(id)+"' data-k='tortoise_split_min_text' value='"+escAttr(String(p.tortoise_split_min_text||100))+"' placeholder='100' style='width:96px;max-width:100%;min-width:0' /></div>"+
      "<div class='k'>Max CPU threads / process</div><div><input data-pid='"+escAttr(id)+"' data-k='voice_threads' value='"+escAttr(String(p.voice_threads||16))+"' placeholder='16' style='width:96px;max-width:100%;min-width:0' /></div>"+
      "<div class='k'>Voice GPUs</div><div>"+
        "<input type='hidden' data-pid='"+escAttr(id)+"' data-k='voice_gpus' value='"+escAttr(voiceG.join(','))+"'/>"+
        "<div class='row' style='gap:8px;flex-wrap:wrap'>"+
          [0,1,2,3].map(function(n){
            var on = (voiceG.indexOf(n)>=0);
            var claimed = (llmG.indexOf(n)>=0);
            var cls = 'pill gpuChip' + (on ? ' on' : '') + (claimed ? ' claimed' : '');
            return "<button type='button' class='"+cls+"' data-pid='"+escAttr(id)+"' data-role='voice' data-gpu='"+n+"'>GPU "+n+"</button>";
          }).join('')+
        "</div>"+
      "</div>"+

      "<div class='provSection'>LLM service</div>"+
      "<div class='provHint'>Choose a model and which GPU(s) it can use.</div>"+
      "<div class='k'>LLM model</div><div><select data-pid='"+escAttr(id)+"' data-k='llm_model' style='width:220px;max-width:100%;min-width:0'>"+
          enabledModels.map(function(m){
            var sel = (String(m.id)===llmModel) ? 'selected' : '';
            return "<option value='"+escAttr(m.id)+"' "+sel+">"+escapeHtml(m.label)+"</option>";
          }).join('')+
        "</select>"+
        "<div id='llmReload_"+escAttr(id)+"' class='muted hide' style='margin-top:8px'>Reloading LLM…</div>"+
      "</div>"+
      "<div class='k'>LLM GPUs</div><div>"+
        "<input type='hidden' data-pid='"+escAttr(id)+"' data-k='llm_gpus' value='"+escAttr(llmG.join(','))+"'/>"+
        "<div class='row' style='gap:8px;flex-wrap:wrap'>"+
          [0,1,2,3].map(function(n){
            var on = (llmG.indexOf(n)>=0);
            var claimed = (voiceG.indexOf(n)>=0);
            var cls = 'pill gpuChip' + (on ? ' on' : '') + (claimed ? ' claimed' : '');
            return "<button type='button' class='"+cls+"' data-pid='"+escAttr(id)+"' data-role='llm' data-gpu='"+n+"'>GPU "+n+"</button>";
          }).join('')+
        "</div>"+
      "</div>"+
    "</div>";

    var isOpen = (idx === 0);
    return "<div class='job'>" + header + "<div id='provBody_"+escAttr(id)+"' style='display:"+(isOpen?'block':'none')+"'>" + body + "</div></div>";
  }).join('');
}

function toggleProv(id){
  try{
    var b=document.getElementById('provBody_'+id);
    if (!b) return;
    b.style.display = (b.style.display==='none' || b.style.display==='') ? 'block' : 'none';
  }catch(e){}
}

function toggleProvBtn(btn){
  try{
    var id = btn && btn.getAttribute ? (btn.getAttribute('data-pid')||'') : '';
    if (!id) return;
    toggleProv(id);
  }catch(e){}
}

function onProvMonitorToggle(inputEl){
  try{
    var on = !!(inputEl && inputEl.checked);
    // Keep behavior consistent with the existing global monitor preference.
    try{ saveMonitorPref(on); }catch(e){}
    try{ setMonitorEnabled(on); }catch(e){}
  }catch(e){}
}

function removeProviderBtn(btn){
  try{
    var id = btn && btn.getAttribute ? (btn.getAttribute('data-pid')||'') : '';
    if (!id) return;
    removeProvider(id);
  }catch(e){}
}

function collectProvidersFromUI(){
  // Start from the last loaded providers snapshot.
  var arr = (window.__SF_PROVIDERS && Array.isArray(window.__SF_PROVIDERS)) ? window.__SF_PROVIDERS : [];
  // Clone
  arr = arr.map(function(p){
    try{ return JSON.parse(JSON.stringify(p||{})); }catch(e){ return (p||{}); }
  });

  var inputs = document.querySelectorAll('#providersBox [data-pid]');
  for (var i=0;i<inputs.length;i++){
    var el=inputs[i];
    var pid=el.getAttribute('data-pid');
    var k=el.getAttribute('data-k');
    if (!pid || !k) continue;
    var p = null;
    for (var j=0;j<arr.length;j++){
      if (String(arr[j].id||'')===pid){ p=arr[j]; break; }
    }
    if (!p) continue;

    if (el.type==='checkbox'){
      p[k] = !!el.checked;
    } else if (k==='voice_gpus' || k==='llm_gpus'){
      p[k] = parseGpuList(el.value);
    } else if (k==='voice_engines'){
      try{ p[k] = String(el.value||'').split(',').map(function(x){return String(x||'').trim();}).filter(Boolean); }catch(e){ p[k]=[]; }
    } else if (k==='voice_threads' || k==='tortoise_split_min_text'){
      var n = parseInt(String(el.value||'').trim(),10);
      if (isNaN(n)) n = 0;
      p[k] = n;
    } else {
      p[k] = String(el.value||'').trim();
    }
  }
  return arr;
}

function reloadProviders(){
  var el=document.getElementById('providersBox');
  if (el) el.textContent='Loading…';
  return fetchJsonAuthed('/api/settings/providers').then(function(j){
    if (!j || !j.ok){ if(el) el.innerHTML="<div class='muted'>Error: "+escapeHtml((j&&j.error)||'unknown')+"</div>"; return; }
    window.__SF_PROVIDERS = (j.providers || []);
    renderProviders(window.__SF_PROVIDERS);

    // show reloading hint if set
    try{
      var raw = sessionStorage.getItem('sf_llm_reloading') || '';
      if (raw){
        var st = JSON.parse(raw);
        if (st && st.ts && (Date.now() - st.ts) < 180000){
          // only applies to the first provider card for now
          var provId = (j.providers && j.providers[0] && j.providers[0].id) ? String(j.providers[0].id) : '';
          if (provId){
            var el2 = document.getElementById('llmReload_'+provId);
            if (el2) el2.classList.remove('hide');
          }
        } else {
          sessionStorage.removeItem('sf_llm_reloading');
        }
      }
    }catch(e){}
  }).catch(function(e){ if(el) el.innerHTML="<div class='muted'>Load failed: "+escapeHtml(String(e))+"</div>"; });
}

function saveProviders(){
  var arr = collectProvidersFromUI();
  return fetchJsonAuthed('/api/settings/providers', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({providers: arr})})
    .then(function(j){
      if (!j || !j.ok) throw new Error((j&&j.error)||'save_failed');
      try{ toastSet('Saved', 'ok', 1200); window.__sfToastInit && window.__sfToastInit(); }catch(e){}

      // If LLM was reconfigured, show a persistent hint (vLLM restart + model load can take 30-120s).
      try{
        if (j && j.llm_reconfigure && j.llm_reconfigure.ok){
          var g = (j.llm_reconfigure.gpus||[]).join(',');
          try{ sessionStorage.setItem('sf_llm_reloading', JSON.stringify({ts:Date.now(), gpus:g})); }catch(e){}
          try{ toastSet('Reloading LLM on GPU(s) '+g+'… (may take ~1–2 min)', 'info', 2600); window.__sfToastInit && window.__sfToastInit(); }catch(e){}
        }
      }catch(e){}

      return reloadProviders();
    })
    .catch(function(e){ alert('Save failed: '+String(e)); });
}

function __newId(prefix){
  return (prefix||'p') + '_' + (Date.now().toString(36)) + '_' + (Math.random().toString(16).slice(2,8));
}

function addProviderTinybox(){
  var arr = (window.__SF_PROVIDERS && Array.isArray(window.__SF_PROVIDERS)) ? window.__SF_PROVIDERS : [];
  arr = arr.slice();
  arr.unshift({
    id: __newId('tinybox'),
    kind: 'tinybox',
    name: 'Tinybox',
    gateway_base: '',
    monitoring_enabled: true,
    voice_enabled: true,
    voice_gpus: [0,1],
    llm_enabled: false,
    llm_model: 'google/gemma-2-9b-it',
    llm_gpus: [2],
  });
  window.__SF_PROVIDERS = arr;
  renderProviders(arr);
}

function addProviderOpenAI(){
  var arr = (window.__SF_PROVIDERS && Array.isArray(window.__SF_PROVIDERS)) ? window.__SF_PROVIDERS : [];
  arr = arr.slice();
  arr.unshift({id: __newId('openai'), kind:'openai', name:'OpenAI', llm_enabled:false, voice_enabled:false, monitoring_enabled:false});
  window.__SF_PROVIDERS = arr;
  renderProviders(arr);
}

function addProviderGoogle(){
  var arr = (window.__SF_PROVIDERS && Array.isArray(window.__SF_PROVIDERS)) ? window.__SF_PROVIDERS : [];
  arr = arr.slice();
  arr.unshift({id: __newId('google'), kind:'google', name:'Google', llm_enabled:false, voice_enabled:false, monitoring_enabled:false});
  window.__SF_PROVIDERS = arr;
  renderProviders(arr);
}

function removeProvider(id){
  if (!confirm('Remove provider ' + id + '?')) return;
  var arr = (window.__SF_PROVIDERS && Array.isArray(window.__SF_PROVIDERS)) ? window.__SF_PROVIDERS : [];
  arr = arr.filter(function(p){ return String(p.id||'')!==String(id||''); });
  window.__SF_PROVIDERS = arr;
  renderProviders(arr);
}

function loadProduction(){
  try{
    var sel=document.getElementById('prodStorySel');
    var out=document.getElementById('prodOut');
    if (out) out.textContent='Loading stories…';

    return fetchJsonAuthed('/api/library/stories').then(function(j){
      if (!j || !j.ok){ throw new Error((j&&j.error)||'library_failed'); }
      var stories = j.stories || [];
      if (!sel) return;
      sel.innerHTML = stories.map(function(st){
        var id = String(st.id||'');
        var title = String(st.title||st.id||'');
        return "<option value='"+escAttr(id)+"'>"+escapeHtml(title)+"</option>";
      }).join('');
      if (out) out.textContent = stories.length ? '' : 'No stories found.';

      // reset current state + render
      try{ window.__SF_PROD.story_id = String(sel.value||''); window.__SF_PROD.assignments=[]; window.__SF_PROD.roster=[]; window.__SF_PROD.saved=false; }catch(_e){}
      prodRenderAssignments();

      // Load saved casting for initial selection
      try{ prodLoadCasting(String(sel.value||'')); }catch(_e){}

      // story change handler
      try{
        sel.onchange = function(){
          var sid = String(sel.value||'');
          window.__SF_PROD.story_id = sid;
          window.__SF_PROD.assignments=[];
          window.__SF_PROD.roster=[];
          window.__SF_PROD.saved=false;
          if (out) out.textContent='';
          prodRenderAssignments();
          prodLoadCasting(sid);
        };
      }catch(_e){}

    }).catch(function(e){ if(out) out.innerHTML='<div class="err">'+escapeHtml(String(e&&e.message?e.message:e))+'</div>'; });
  }catch(e){}
}

function prodLoadCasting(storyId){
  try{
    var out=document.getElementById('prodOut');
    var sid = String(storyId||'').trim();
    if (!sid) return;
    fetchJsonAuthed('/api/production/casting/'+encodeURIComponent(sid)).then(function(j){
      if (!j || !j.ok) return;
      window.__SF_PROD.story_id = sid;
      window.__SF_PROD.roster = j.roster || [];
      window.__SF_PROD.assignments = (j.assignments||[]).map(function(a){ return {character:String(a.character||''), voice_id:String(a.voice_id||''), reason:String(a.reason||''), _editing:false}; });
      window.__SF_PROD.saved = !!j.saved;
      if (out && j.saved) out.textContent='Casting loaded.';
      prodRenderAssignments();
    }).catch(function(_e){});
  }catch(e){}
}

window.__SF_PROD = window.__SF_PROD || { roster:[], assignments:[], story_id:'', saved:false };

function prodRenderAssignments(){
  try{
    var box=document.getElementById('prodAssignments');
    var saveBtn=document.getElementById('prodSaveBtn');
    var step3=document.getElementById('prodStep3Btn');
    if (!box) return;

    var st = window.__SF_PROD || {};
    var roster = Array.isArray(st.roster) ? st.roster : [];
    var assigns = Array.isArray(st.assignments) ? st.assignments : [];

    // helper: roster option list
    function optList(selected){
      return roster.map(function(v){
        var id=String(v.id||'');
        var nm=String(v.name||v.id||'');
        var t=[];
        if (v.gender && v.gender!=='unknown') t.push(v.gender);
        if (v.age && v.age!=='unknown') t.push(v.age);
        if (v.pitch && v.pitch!=='unknown') t.push('pitch '+v.pitch);
        var label = nm + (t.length?(' • '+t.join(' • ')):'');
        var sel = (String(selected||'')===id) ? ' selected' : '';
        return "<option value='"+escAttr(id)+"'"+sel+">"+escapeHtml(label)+"</option>";
      }).join('');
    }

    function cardFor(a, idx){
      var ch = String(a.character||'');
      var vid = String(a.voice_id||'');
      var reason = String(a.reason||'');
      var editing = !!a._editing;
      var voiceName = '';
      try{
        var v = roster.find(function(x){ return String(x.id||'')===vid; });
        voiceName = v ? String(v.name||v.id||'') : vid;
      }catch(_e){}

      var top = "<div class='row' style='justify-content:space-between;gap:10px'>"
        + "<div style='font-weight:950'>"+escapeHtml(ch||('Character '+(idx+1)))+"</div>"
        + "<div>" + (editing ? "<button class='secondary' type='button' onclick='prodCancelEdit("+idx+")'>Cancel</button>" : "<button class='secondary' type='button' onclick='prodEditAssign("+idx+")'>Edit</button>") + "</div>"
        + "</div>";

      var body = '';
      if (editing){
        body += "<div class='muted' style='margin-top:8px'>Voice</div>";
        body += "<select style='margin-top:6px;width:100%' onchange='prodSetVoice("+idx+", this.value)'>" + optList(vid) + "</select>";
      }else{
        body += "<div class='muted' style='margin-top:8px'>Voice</div>";
        body += "<div style='margin-top:6px'>"+escapeHtml(voiceName||'—')+"</div>";
      }
      if (reason){
        body += "<div class='muted' style='margin-top:8px'>Reason</div>";
        body += "<div style='margin-top:6px'>"+escapeHtml(reason)+"</div>";
      }

      return "<div class='job' style='padding:14px'>" + top + body + "</div>";
    }

    if (!assigns.length){
      box.innerHTML = "<div class='muted'>No casting yet.</div>";
    }else{
      box.innerHTML = assigns.map(cardFor).join("");
    }

    // Save enabled when we have assignments and not saved.
    var canSave = (!!(st.story_id) && assigns.length);
    try{ if (saveBtn) saveBtn.disabled = (!canSave); }catch(_e){}
    try{ if (step3) step3.disabled = (!st.saved); }catch(_e){}
  }catch(e){}
}

function prodEditAssign(i){
  try{ window.__SF_PROD.assignments[i]._editing=true; window.__SF_PROD.saved=false; prodRenderAssignments(); }catch(e){}
}
function prodCancelEdit(i){
  try{ window.__SF_PROD.assignments[i]._editing=false; prodRenderAssignments(); }catch(e){}
}
function prodSetVoice(i, voiceId){
  try{ window.__SF_PROD.assignments[i].voice_id = String(voiceId||''); window.__SF_PROD.saved=false; }catch(e){}
}

function prodSuggestCasting(){
  try{
    var sel=document.getElementById('prodStorySel');
    var out=document.getElementById('prodOut');
    var saveBtn=document.getElementById('prodSaveBtn');
    var storyId = sel ? String(sel.value||'').trim() : '';
    if (!storyId){ if(out) out.innerHTML='<div class="err">Pick a story</div>'; return; }
    if (out) out.textContent='Suggesting casting…';
    if (saveBtn) saveBtn.disabled = true;

    fetchJsonAuthed('/api/production/suggest_casting', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({story_id: storyId})})
      .then(function(j){
        if (!j || !j.ok){ throw new Error((j&&j.error)||'suggest_failed'); }
        if (out) out.textContent='';
        window.__SF_PROD.story_id = storyId;
        window.__SF_PROD.roster = j.roster || [];
        window.__SF_PROD.assignments = ((j.suggestions||{}).assignments || []).map(function(a){
          return { character: String(a.character||''), voice_id: String(a.voice_id||''), reason: String(a.reason||''), _editing:false };
        });
        window.__SF_PROD.saved = false;
        prodRenderAssignments();
      })
      .catch(function(e){ if(out) out.innerHTML='<div class="err">'+escapeHtml(String(e&&e.message?e.message:e))+'</div>'; });
  }catch(e){}
}

function prodSaveCasting(){
  try{
    var out=document.getElementById('prodOut');
    var box=document.getElementById('prodSfmlBox');
    var st = window.__SF_PROD || {};
    if (!st.story_id) { if(out) out.innerHTML='<div class="err">Pick a story</div>'; return; }
    var assigns = Array.isArray(st.assignments) ? st.assignments : [];
    if (!assigns.length){ if(out) out.innerHTML='<div class="err">No assignments</div>'; return; }

    if (out) out.textContent='Saving casting…';
    var payload = { story_id: String(st.story_id), assignments: assigns.map(function(a){ return {character:a.character, voice_id:a.voice_id}; }) };

    fetchJsonAuthed('/api/production/casting_save', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)})
      .then(function(j){
        if (!j || !j.ok){ throw new Error((j&&j.error)||'save_failed'); }
        if (out) out.textContent='Saved.';
        window.__SF_PROD.saved = true;
        window.__SF_PROD.sfml = '';
        // exit edit mode
        try{ window.__SF_PROD.assignments.forEach(function(a){ a._editing=false; }); }catch(_e){}
        try{ if (box){ box.classList.add('hide'); box.innerHTML=''; } }catch(_e){}
        prodRenderAssignments();
      })
      .catch(function(e){ if(out) out.innerHTML='<div class="err">'+escapeHtml(String(e&&e.message?e.message:e))+'</div>'; });
  }catch(e){}
}

function prodGenerateSfml(){
  try{
    var out=document.getElementById('prodOut');
    var st = window.__SF_PROD || {};
    if (!st.saved){ if(out) out.innerHTML='<div class="err">Save casting first</div>'; return; }
    var sid = String(st.story_id||'').trim();
    if (!sid){ if(out) out.innerHTML='<div class="err">Pick a story</div>'; return; }

    if (out) out.textContent='Generating SFML…';
    fetchJsonAuthed('/api/production/sfml_generate', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({story_id:sid})})
      .then(function(j){
        if (!j || !j.ok || !j.sfml){ throw new Error((j&&j.error)||'sfml_failed'); }
        window.__SF_PROD.sfml = String(j.sfml||'');
        if (out) out.textContent='';
        prodRenderSfml(window.__SF_PROD.sfml);
      })
      .catch(function(e){ if(out) out.innerHTML='<div class="err">'+escapeHtml(String(e&&e.message?e.message:e))+'</div>'; });
  }catch(e){}
}

function prodCopySfml(){
  try{
    var txt = String((window.__SF_PROD||{}).sfml || '');
    if (!txt){ alert('No SFML yet.'); return; }
    copyToClipboard(txt);
    try{ toastShowNow('Copied SFML', 'ok', 1400); }catch(_e){}
  }catch(e){}
}

function prodRenderSfml(sfml){
  try{
    var box=document.getElementById('prodSfmlBox');
    if (!box) return;

    var raw = String(sfml||'');
    // IMPORTANT: this JS lives inside a Python triple-quoted string.
    // Use double-escaped newlines so we don't embed literal CR/LF into the JS source.
    raw = raw.split("\\r\\n").join("\\n");
    var lines = raw.split("\\n");

    function esc(s){ return escapeHtml(String(s||'')); }
    function span(cls, txt){ return '<span class="'+cls+'">'+txt+'</span>'; }

    function hilite(line){
      var s = String(line||'');
      var t = s.trim();
      if (!t) return '';
      if (t.startsWith('#')) return span('tok-c', esc(s));

      // scene
      if (t.toLowerCase().startsWith('scene ')){
        var rest = t.slice(5).trim();
        var parts = rest.split(' ').filter(Boolean);
        var out = span('tok-kw','scene') + ' ';
        for (var i=0;i<parts.length;i++){
          var p=String(parts[i]||'');
          if (p.startsWith('id=')) out += span('tok-a','id')+'='+span('tok-id',esc(p.slice(3)));
          else if (p.startsWith('title=')) out += span('tok-a','title')+'='+span('tok-s',esc(p.slice(6)));
          else out += esc(p);
          if (i<parts.length-1) out += ' ';
        }
        return out;
      }

      // say
      if (t.toLowerCase().startsWith('say ')){
        var colon = t.indexOf(':');
        var head = (colon>=0)?t.slice(0,colon).trim():t;
        var text = (colon>=0)?t.slice(colon+1).trim():'';
        var parts = head.split(' ').filter(Boolean);
        var out = span('tok-kw','say');
        if (parts.length>1) out += ' ' + span('tok-id', esc(parts[1]));
        // voice=...
        for (var i=2;i<parts.length;i++){
          var p=String(parts[i]||'');
          if (p.startsWith('voice=')) out += ' ' + span('tok-a','voice')+'='+span('tok-id', esc(p.slice(6)));
          else out += ' ' + esc(p);
        }
        out += ':';
        if (text) out += ' ' + esc(text);
        return out;
      }

      return esc(s);
    }

    var html = '<div class="codeWrap">' + lines.map(function(ln, i){
      return '<div class="codeLine"><div class="codeLn">'+String(i+1)+'</div><div class="codeTxt">'+hilite(ln)+'</div></div>';
    }).join('') + '</div>';

    box.innerHTML = html;
    box.classList.remove('hide');
  }catch(e){}
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
      var idEnc = encodeURIComponent(String(v.id||''));
      var nm = v.display_name || v.id;
      // Traits (from voice_traits_json)
      var traitsHtml = '';
      try{
        var vtj = safeJson(v.voice_traits_json||'') || null;
        var vt = vtj ? (vtj.voice_traits||{}) : {};
        var m = vtj ? (vtj.measured||{}) : {};
        var f = m ? (m.features||{}) : {};

        function chip(txt, cls){
          txt = String(txt||'').trim();
          if (!txt) return '';
          return "<span class='chip "+(cls||"")+"' style='margin-right:8px;margin-bottom:8px'>"+escapeHtml(txt)+"</span>";
        }

        var chips = '';

        // gender chip (no label)
        var g = String(vt.gender||'unknown');
        if (g && g!=='unknown') chips += chip(String(g), g==='male'?'male':(g==='female'?'female':''));

        // age chip (no label)
        var a = String(vt.age||'unknown');
        if (a && a!=='unknown') chips += chip(String(a), 'age-' + a);

        // tone chips (no "tone" label)
        if (Array.isArray(vt.tone) && vt.tone.length){
          for (var i=0;i<Math.min(3, vt.tone.length);i++) chips += chip(String(vt.tone[i]), '');
        }

        // pitch/f0/ref chips
        var pitch = String(vt.pitch||'');
        if (pitch && pitch!=='unknown') chips += chip('pitch ' + pitch, '');

        if (f && f.f0_hz_median!=null){
          chips += chip('f0 ' + Number(f.f0_hz_median).toFixed(0) + ' Hz', '');
        }

        if (v.voice_ref) chips += chip('ref ' + String(v.voice_ref), '');

        traitsHtml = chips ? ("<div class='chips' style='margin-top:8px'>" + chips + "</div>") : '';
      }catch(e){ traitsHtml=''; }
      var en = (v.enabled!==false);
      var pill = en ? "<span class='pill good'>enabled</span>" : "<span class='pill bad'>disabled</span>";

      var playBtn = '';
      if (v.sample_url){
        playBtn = "<button class='secondary' data-vid='" + idEnc + "' data-sample='" + escAttr(v.sample_url||'') + "' onclick='playVoiceEl(this)'>Play</button>";
      }

      var card = "<div class='job'>"
        + "<div class='row' style='justify-content:space-between;'>"
        + "<div class='title'>" + escapeHtml(nm) + "</div>"
        + "<div>" + pill + "</div>"
        + "</div>"
        + traitsHtml
        + "<div class='row' style='margin-top:10px'>"
        + playBtn
        + "<button class='secondary' data-vid='" + idEnc + "' onclick='goVoiceEdit(this)'>Edit</button>"
        + "</div>"
        + "<div id='audWrap-" + idEnc + "' class='hide' style='margin-top:10px;padding:10px;border:1px solid var(--line);border-radius:14px;background:#0b1020'>"
        + "<audio id='aud-" + idEnc + "' controls style='width:100%'></audio>"
        + "</div>"
        + "</div>";

      return "<div class='swipe voiceSwipe'>"
        + "<div class='swipeInner'>"
        + "<div class='swipeMain'>" + card + "</div>"
        + "<div class='swipeKill'><button class='swipeDelBtn' type='button' data-vid='" + idEnc + "' onclick='deleteVoiceBtn(this)'>Delete</button></div>"
        + "</div>"
        + "</div>";
    }).join('');
  }).catch(function(e){
    if (el) el.innerHTML = "<div class='muted'>Error loading voices: " + escapeHtml(String(e)) + "</div>";
  });
}

function deleteVoiceBtn(btn){
  try{
    var idEnc = btn ? String(btn.getAttribute('data-vid')||'') : '';
    deleteVoice(idEnc);
  }catch(e){}
}

function deleteVoice(idEnc){
  try{
    var id = decodeURIComponent(String(idEnc||''));
    if (!id) return;
    if (!confirm('Delete voice ' + id + '? This also deletes its clip from Spaces.')) return;
    fetchJsonAuthed('/api/voices/' + encodeURIComponent(id), {method:'DELETE'})
      .then(function(j){
        if (!j || !j.ok){ throw new Error((j&&j.error)||'delete_failed'); }
        try{ toastSet('Deleted', 'ok', 1400); window.__sfToastInit && window.__sfToastInit(); }catch(e){}
        return loadVoices();
      })
      .catch(function(e){ alert('Delete failed: ' + String(e)); });
  }catch(e){}
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







function goVoiceEdit(btn){
  try{
    var idEnc = btn ? (btn.getAttribute('data-vid')||'') : '';
    var id = decodeURIComponent(idEnc||'');
    if (!id) return;
    window.location.href = '/voices/' + encodeURIComponent(id) + '/edit';
  }catch(e){}
}
function editVoiceEl(btn){
  try{
    var idEnc = btn ? (btn.getAttribute('data-vid')||'') : '';
    return editVoice(idEnc);
  }catch(e){}
}

function editVoice(idEnc){
  var id = decodeURIComponent(idEnc||'');
  if (!id) return;
  var nm = prompt('Display name:', '');
  if (nm==null) return;
  nm = String(nm||'').trim();
  if (!nm) return;
  return fetchJsonAuthed('/api/voices/' + encodeURIComponent(id), {method:'PUT', headers:{'Content-Type':'application/json'}, body: JSON.stringify({display_name: nm})})
    .then(function(j){
      if (j && j.ok){
        try{ toastSet('Saved', 'ok', 2200); window.__sfToastInit && window.__sfToastInit(); }catch(e){}
        return loadVoices();
      }
      alert((j && j.error) ? j.error : 'Save failed');
    })
    .catch(function(e){ alert(String(e)); });
}
function playVoiceEl(btn){
  try{
    var idEnc = btn ? (btn.getAttribute('data-vid')||'') : '';
    var sample = btn ? String(btn.getAttribute('data-sample')||'').trim() : '';
    if (!idEnc || !sample) return;

    var wrap = document.getElementById('audWrap-' + idEnc);
    var a = document.getElementById('aud-' + idEnc);
    if (wrap) wrap.classList.remove('hide');
    if (a){
      if (!a.src) a.src = sample;
      try{ a.play(); }catch(e){}
    }
  }catch(e){}
}

function genSampleEl(btn){
  try{
    var idEnc = btn ? (btn.getAttribute('data-vid')||'') : '';
    var id = decodeURIComponent(idEnc||'');
    if (!id) return;
    return fetchJsonAuthed('/api/voices/' + encodeURIComponent(id) + '/sample', {method:'POST'})
      .then(function(j){
        if (j && j.ok && j.sample_url){
          var a = document.getElementById('aud-' + idEnc);
          if (a){ a.src = j.sample_url; a.classList.remove('hide'); }
          try{ toastSet('Sample generated', 'ok', 2000); window.__sfToastInit && window.__sfToastInit(); }catch(e){}
          return loadVoices();
        }
        alert((j && j.error) ? j.error : 'Generate failed');
      }).catch(function(e){ alert(String(e)); });
  }catch(e){}
}

function renameVoiceEl(btn){
  try{
    var idEnc = btn ? (btn.getAttribute('data-vid')||'') : '';
    var id = decodeURIComponent(idEnc||'');
    if (!id) return;
    return fetchJsonAuthed('/api/voices/' + encodeURIComponent(id) + '/sample', {method:'POST'})
      .then(function(j){
        if (j && j.ok){
          try{ toastSet('Sample generated', 'ok', 2000); window.__sfToastInit && window.__sfToastInit(); }catch(e){}
          return loadVoices();
        }
        alert((j && j.error) ? j.error : 'Generate failed');
      }).catch(function(e){ alert(String(e)); });
  }catch(e){}
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
  try{ var p = loadHistory();
loadVoices(); if (p && p.catch) p.catch(function(_e){}); }catch(_e){}
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
  if (x==null) return '-';
  return (Number(x).toFixed(1)) + '%';
}

function openMonitor(){
  try{ window.__sfScrollY = window.scrollY || 0; }catch(e){}
  if (!monitorEnabled) return;
  try{ bindMonitorClose(); }catch(e){}
  var b=document.getElementById('monitorBackdrop');
  var sh=document.getElementById('monitorSheet');
  if (b){ b.classList.remove('hide'); b.style.display='block'; }
  if (sh){ sh.classList.remove('hide'); sh.style.display='block'; }
  try{ document.documentElement.classList.add('noScroll'); }catch(e){}
  try{ document.body.classList.add('noScroll'); }catch(e){}
  try{ document.body.style.position='fixed'; document.body.style.top = '-' + String(window.__sfScrollY||0) + 'px'; document.body.style.left='0'; document.body.style.right='0'; document.body.style.width='100%'; }catch(e){}
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
  try{ document.documentElement.classList.remove('noScroll'); }catch(e){}
  try{ document.body.classList.remove('noScroll'); }catch(e){}
  try{ document.body.style.position=''; document.body.style.top=''; document.body.style.left=''; document.body.style.right=''; document.body.style.width=''; }catch(e){}
  try{ window.scrollTo(0, window.__sfScrollY||0); }catch(e){}
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
        <div class='v'>${vt ? `${(vu/1024).toFixed(1)} / ${(vt/1024).toFixed(1)} GB` : '-'}</div>
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
  const cpu = (b.cpu_pct!=null) ? Number(b.cpu_pct).toFixed(1)+'%' : '-';
  const rt = Number(b.ram_total_mb||0); const ru = Number(b.ram_used_mb||0);
  const rp = rt ? (ru/rt*100) : 0;
  const ram = rt ? rp.toFixed(1)+'%' : '-';
  const gpus = Array.isArray(b?.gpus) ? b.gpus : (b?.gpu ? [b.gpu] : []);
  let maxGpu = null;
  if (gpus.length){
    maxGpu = 0;
    for (const g of gpus){
      const u = Number(g.util_gpu_pct||0);
      if (u > maxGpu) maxGpu = u;
    }
  }
  const gpu = (maxGpu==null) ? '-' : maxGpu.toFixed(1)+'%';
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
  document.getElementById('monRam').textContent = rt ? `${ru.toFixed(0)} / ${rt.toFixed(0)} MB (${rp.toFixed(1)}%)` : '-';
  setBar('barRam', rp);
  renderGpus(b);

  const ts = b.ts ? fmtTs(b.ts) : '-';
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
  var __bootText = __sfEnsureBootBanner();
  if (__bootText) __bootText.textContent = 'Build: ' + (window.__SF_BUILD||'?') + ' • JS: running';
}catch(_e){}

function setUpdateBar(on, msg){
  try{
    var bar=document.getElementById('updateBar');
    var sub=document.getElementById('updateSub');
    if (!bar) return;
    if (on){
      bar.classList.remove('hide');
      if (sub) sub.textContent = msg || 'Reconnecting…';
    }else{
      bar.classList.add('hide');
    }
  }catch(e){}
}

function startUpdateWatch(){
  try{
    var cur = String(window.__SF_BUILD||'');

    function tick(){
      // Show a non-blocking updating bar when the app is temporarily failing.
      try{
        var lastFail = Number(window.__SF_LAST_API_FAIL||0);
        if (lastFail && (Date.now()-lastFail) < 15000) setUpdateBar(true, 'Updating… reconnecting');
        else setUpdateBar(false, '');
      }catch(_e){}

      // Poll build. If changed, auto-reload with ?v=<new>.
      fetch('/api/build', {cache:'no-store'}).then(function(r){
        if (!r.ok) throw new Error('HTTP '+r.status);
        return r.json();
      }).then(function(j){
        if (!j || !j.ok || !j.build) return;
        var srv = String(j.build||'');
        if (srv && cur && srv !== cur){
          setUpdateBar(true, 'Update deployed. Reloading…');
          try{
            var u = new URL(window.location.href);
            u.searchParams.set('v', srv);
            window.location.replace(u.toString());
          }catch(_e){
            window.location.reload();
          }
        }
      }).catch(function(_e){
        try{ window.__SF_LAST_API_FAIL = Date.now(); }catch(__e){}
        setUpdateBar(true, 'Updating… reconnecting');
      });
    }

    tick();
    setInterval(tick, 5000);
  }catch(e){}
}

var initTab = getTabFromHash() || getQueryParam('tab');
if (initTab==='library' || initTab==='history' || initTab==='voices' || initTab==='production' || initTab==='advanced') { try{ showTab(initTab); }catch(e){} }

refreshAll();
// Start streaming immediately so the Metrics tab is instant.
setMonitorEnabled(loadMonitorPref());
setDebugUiEnabled(loadDebugPref());
try{ bindJobsLazyScroll(); }catch(e){}
loadHistory(true);
loadVoices();
// Jobs SSE will only run while jobs are in state=running.
try{ startJobsStream(); }catch(e){}
reloadProviders();
try{ startUpdateWatch(); }catch(e){}

try{
  var __bootText2 = __sfEnsureBootBanner();
  if (__bootText2) __bootText2.textContent = 'Build: ' + (window.__SF_BUILD||'?') + ' • JS: ok';
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



</body>
</html>"""
    return (html
        .replace("__INDEX_BASE_CSS__", INDEX_BASE_CSS)
        .replace("__DEBUG_BANNER_HTML__", DEBUG_BANNER_HTML)
        .replace("__DEBUG_BANNER_BOOT_JS__", DEBUG_BANNER_BOOT_JS)
        .replace("__BUILD__", str(build))
        .replace("__VOICE_SERVERS__", voice_servers_html)
    )





@app.post('/api/upload/voice_clip')
def api_upload_voice_clip(file: UploadFile = File(...)):
    # Requires passphrase session auth (middleware).
    try:
        data = file.file.read()
        if not data or len(data) < 16:
            return {'ok': False, 'error': 'empty_file'}
        if len(data) > 50 * 1024 * 1024:
            return {'ok': False, 'error': 'file_too_large'}
        from .spaces_upload import upload_bytes
        _key, url = upload_bytes(
            data,
            key_prefix='voices/clips',
            filename=file.filename or 'clip.wav',
            content_type=file.content_type or 'application/octet-stream',
        )
        return {'ok': True, 'url': url}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


@app.get('/api/voice_provider/engines')
def api_voice_provider_engines():
    # Requires passphrase session auth (middleware).
    if not GATEWAY_TOKEN:
        return {'ok': False, 'error': 'gateway_token_missing'}
    try:
        r = requests.get(
            GATEWAY_BASE + '/v1/engines',
            timeout=12,
            headers={'Authorization': f'Bearer {GATEWAY_TOKEN}'},
        )
        if r.status_code != 200:
            return {'ok': False, 'error': 'upstream_http', 'status': int(r.status_code)}
        j = r.json()
        if isinstance(j, dict) and j.get('ok') and isinstance(j.get('engines'), list):
            engs = [str(x) for x in (j.get('engines') or []) if str(x).strip()]
            # Apply provider engine allowlist if set (Tinybox provider).
            try:
                p = _get_tinybox_provider() or {}
                allow = p.get('voice_engines') if isinstance(p, dict) else None
                if isinstance(allow, list) and allow:
                    allow2 = {str(x).strip() for x in allow if str(x).strip()}
                    engs = [e for e in engs if e in allow2]
            except Exception:
                pass
            return {'ok': True, 'engines': engs or ['xtts', 'tortoise']}
        return {'ok': False, 'error': 'bad_upstream_shape'}
    except Exception as e:
        return {'ok': False, 'error': f'engines_failed:{type(e).__name__}'}


@app.get('/api/voice_provider/presets')
def api_voice_provider_presets():
    # Requires passphrase session auth (middleware).
    if not GATEWAY_TOKEN:
        return {'ok': False, 'error': 'gateway_token_missing'}
    try:
        r = requests.get(
            GATEWAY_BASE + '/v1/voice-clips',
            timeout=20,
            headers={'Authorization': f'Bearer {GATEWAY_TOKEN}'},
        )
        if r.status_code != 200:
            body = ''
            try:
                body = (r.text or '')[:200]
            except Exception:
                body = ''
            return {'ok': False, 'error': 'upstream_http', 'status': int(r.status_code), 'body': body}
        j = r.json()
        if isinstance(j, dict) and j.get('ok') and isinstance(j.get('clips'), list):
            return {'ok': True, 'clips': j['clips']}
        return {'ok': False, 'error': 'bad_upstream_shape'}
    except Exception as e:
        return {'ok': False, 'error': f'presets_failed:{type(e).__name__}'}




@app.post('/api/voice_provider/preset_to_spaces')
def api_preset_to_spaces(payload: dict = Body(default={})):
    # payload: {path:"/abs/path/on/tinybox"}
    try:
        path = str((payload or {}).get('path') or '').strip()
        if not path or not path.startswith('/'):
            return {'ok': False, 'error': 'bad_path'}
        # Fetch bytes from Tinybox (authenticated)
        h = {'Authorization': f'Bearer {GATEWAY_TOKEN}'} if GATEWAY_TOKEN else None
        r = requests.get(GATEWAY_BASE + '/v1/voice-clips/file', params={'path': path}, headers=h, timeout=12)
        if r.status_code != 200:
            return {'ok': False, 'error': 'fetch_failed', 'status': r.status_code}
        data = r.content
        if not data or len(data) < 16:
            return {'ok': False, 'error': 'empty_file'}
        # Upload to Spaces
        from .spaces_upload import upload_bytes
        fn = (path.rsplit('/', 1)[-1] or 'clip.wav')
        ct = r.headers.get('content-type') or 'application/octet-stream'
        _key, url = upload_bytes(data, key_prefix='voices/clips', filename=fn, content_type=ct)
        return {'ok': True, 'url': url}
    except Exception as e:
        return {'ok': False, 'error': str(e)}
@app.post('/api/voices/train')
def api_voices_train(payload: dict = Body(default={})):
    # Requires passphrase session auth (middleware).
    # Delegates to Tinybox provider if available.
    try:
        r = requests.post(
            GATEWAY_BASE + '/v1/voices/train',
            json=payload or {},
            timeout=20,
            headers={'Authorization': f'Bearer {GATEWAY_TOKEN}'} if GATEWAY_TOKEN else None,
        )
        try:
            return r.json()
        except Exception:
            return {'ok': False, 'error': 'bad_json'}
    except Exception as e:
        return {'ok': False, 'error': str(e)}
@app.get('/voices', response_class=HTMLResponse)
def voices_root(response: Response):
    # Legacy route: keep compatibility with older links.
    response.headers['Cache-Control'] = 'no-store'
    return RedirectResponse(url='/#tab-voices', status_code=302)


@app.get('/voices/{voice_id}/edit', response_class=HTMLResponse)
def voices_edit_page(voice_id: str, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    build = APP_BUILD
    try:
        voice_id = validate_voice_id(voice_id)
        conn = db_connect()
        try:
            db_init(conn)
            v = get_voice_db(conn, voice_id)
        finally:
            conn.close()
    except Exception as e:
        return HTMLResponse('<pre>failed: ' + pyhtml.escape(str(e)) + '</pre>', status_code=500)

    def esc(x: str) -> str:
        return pyhtml.escape(str(x or ''))

    vid = esc(voice_id)
    dn = esc(v.get('display_name') or '')
    eng = esc(v.get('engine') or '')
    vref = esc(v.get('voice_ref') or '')
    stxt = esc(v.get('sample_text') or '')
    surl = esc(v.get('sample_url') or '')
    enabled_checked = 'checked' if bool(v.get('enabled', True)) else ''
    vtraits_json = str(v.get('voice_traits_json') or '').strip()

    html = """<!doctype html>
<html>
<head>
  <meta charset='utf-8'/>
  <meta name='viewport' content='width=device-width, initial-scale=1'/>
  <title>StoryForge - Edit Voice</title>
  <style>__VOICES_BASE_CSS____VOICE_EDIT_EXTRA_CSS__</style>
</head>
<body>
  __DEBUG_BANNER_BOOT_JS__
  <div class='navBar'>
    <div class='top'>
      <div>
        <div class='brandRow'><h1><a class='brandLink' href='/'>StoryForge</a></h1><div class='pageName'>Edit voice</div></div>
        <div class='muted'><code>__VID__</code></div>
      </div>
      <div class='row headActions'>
        <a href='/#tab-voices'><button class='secondary' type='button'>Back</button></a>
        <div class='menuWrap'>
          <button class='userBtn' type='button' onclick='toggleMenu()' aria-label='User menu'>
            <svg viewBox='0 0 24 24' width='20' height='20' aria-hidden='true' style='stroke:currentColor;fill:none;stroke-width:2'>
              <path stroke-linecap='round' stroke-linejoin='round' d='M20 21a8 8 0 10-16 0'/>
              <path stroke-linecap='round' stroke-linejoin='round' d='M12 11a4 4 0 100-8 4 4 0 000 8z'/>
            </svg>
          </button>
          <div id='topMenu' class='menuCard'>
            <div class='uTop'>
              <div class='uAvatar'>
                <svg viewBox='0 0 24 24' width='18' height='18' aria-hidden='true' style='stroke:currentColor;fill:none;stroke-width:2'>
                  <path stroke-linecap='round' stroke-linejoin='round' d='M20 21a8 8 0 10-16 0'/>
                  <path stroke-linecap='round' stroke-linejoin='round' d='M12 11a4 4 0 100-8 4 4 0 000 8z'/>
                </svg>
              </div>
              <div>
                <div class='uName'>User</div>
                <div class='uSub'>Admin</div>
              </div>
            </div>
            <div class='uActions'>
              <a href='/logout'><button class='secondary' type='button'>Log out</button></a>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>

  __DEBUG_BANNER_HTML__

  <div class='card'>
    <div style='font-weight:950;margin-bottom:6px;'>Basic fields</div>

    <div class='muted'>Display name</div>
    <input id='display_name' value='__DN__' />

    <div class='muted' style='margin-top:12px'>Enabled</div>
    <label class='switch'>
      <input id='enabled' type='checkbox' __ENABLED__ />
      <span class='slider'></span>
    </label>
    <div class='muted' style='margin-top:6px'>Show in curated list</div>

  </div>

  <div class='card'>
    <div style='font-weight:950;margin-bottom:6px;'>Provider fields (read-only)</div>

    <div class='muted'>Engine</div>
    <div class='term' style='margin-top:8px;'>__ENG__</div>

    <div class='row' style='justify-content:space-between;align-items:baseline;margin-top:12px'>
      <div class='muted'>Sample text</div>
      <button class='secondary' type='button' onclick='playSample()'>Play</button>
    </div>
    <div class='term' id='sample_text' style='margin-top:8px;white-space:pre-wrap;'>__STXT__</div>
    <audio id='audio' class='hide' controls style='width:100%;margin-top:10px'></audio>

    <div class='muted' style='margin-top:12px'>sample_url</div>
    <div class='fadeLine' style='margin-top:8px'>
      <div class='fadeText' id='sample_url_text' title='__SURL__'>__SURL__</div>
      <button class='copyBtn' type='button' onclick='copySampleUrl()' aria-label='Copy sample url' title='Copy sample url'>
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <path stroke="currentColor" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" d="M11 7H7a2 2 0 00-2 2v9a2 2 0 002 2h10a2 2 0 002-2v-9a2 2 0 00-2-2h-4M11 7V5a2 2 0 114 0v2M11 7h4"/>
        </svg>
      </button>
    </div>
    <input id='sample_url' type='hidden' value='__SURL__' />

    <div class='muted' style='margin-top:12px'>voice_ref</div>
    <div class='fadeLine' style='margin-top:8px'>
      <div class='fadeText' id='voice_ref' title='__VREF__'>__VREF__</div>
      <button class='copyBtn' type='button' onclick='copyVoiceRef()' aria-label='Copy voice ref' title='Copy voice ref'>
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <path stroke="currentColor" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" d="M11 7H7a2 2 0 00-2 2v9a2 2 0 002 2h10a2 2 0 002-2v-9a2 2 0 00-2-2h-4M11 7V5a2 2 0 114 0v2M11 7h4"/>
        </svg>
      </button>
    </div>

  </div>

  <div class='card'>
    <div class='row' style='justify-content:space-between;align-items:baseline;gap:10px'>
      <div style='font-weight:950;margin-bottom:6px;'>Voice traits</div>
      <button type='button' class='secondary' onclick='analyzeMeta()'>Analyze voice</button>
    </div>
    <div class='muted'>Auto-generated metadata for matching characters to voices.</div>
    <input id='voice_traits_json' type='hidden' value='__VTRAITS__' />
    <div id='traitsBox' class='term' style='margin-top:10px'>Loading…</div>
    <details class='rawBox' style='margin-top:10px'>
      <summary>Raw JSON</summary>
      <pre class='term' style='white-space:pre-wrap;max-height:240px;overflow:auto;-webkit-overflow-scrolling:touch'>__VTRAITS__</pre>
    </details>
  </div>

  <div class='card'>
    <div class='row' style='margin-top:0;justify-content:space-between;gap:10px;flex-wrap:wrap'>
      <button type='button' class='secondary' onclick='deleteThisVoice()' style='border-color: rgba(255,77,77,.35); color: var(--bad);'>Delete</button>
      <div class='row' style='gap:10px;justify-content:flex-end;margin-left:auto'>
        <button type='button' onclick='save()'>Save</button>
      </div>
    </div>

    <div id='out' class='muted' style='margin-top:10px'></div>
  </div>

<script>
function escJs(s){ return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function escapeHtml(s){
  try{ return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;'); }catch(e){ return String(s||''); }
}
function $(id){ return document.getElementById(id); }
function val(id){ var el=$(id); if(!el) return ''; return (el.value!=null) ? String(el.value||'') : String(el.textContent||''); }
function chk(id){ var el=$(id); return !!(el && el.checked); }

function updateSampleTextCount(){
  try{
    var ta=$('sampleText');
    var c=$('sampleTextCount');
    if (!ta || !c) return;
    var n = (String(ta.value||'')||'').length;
    c.textContent = String(n) + ' chars';
  }catch(e){}
}

function deleteThisVoice(){
  try{
    if (!confirm('Delete this voice? This also deletes any associated sample/clip in Spaces.')) return;
    var out=$('out'); if(out) out.textContent='Deleting…';
    fetch('/api/voices/__VID_RAW__', {method:'DELETE', credentials:'include'})
      .then(function(r){ return r.json().catch(function(){return {ok:false,error:'bad_json'};}); })
      .then(function(j){
        if (j && j.ok){
          try{ toastSet('Deleted', 'ok', 1400); window.__sfToastInit && window.__sfToastInit(); }catch(e){}
          window.location.href='/#tab-voices';
          return;
        }
        if(out) out.innerHTML='<div class="err">'+escJs((j&&j.error)||'delete failed')+'</div>';
      })
      .catch(function(e){ if(out) out.innerHTML='<div class="err">'+escJs(String(e))+'</div>'; });
  }catch(e){}
}


function renderTraits(){

  try{
    var box=$('traitsBox');
    var hid=$('voice_traits_json');
    if (!box || !hid) return;
    var raw = String(hid.value||'').trim();
    if (!raw || raw==='—'){
      box.innerHTML = '<div class="muted">No metadata yet. Tap <b>Analyze voice</b>.</div>';
      return;
    }
    // raw is JSON string stored in DB; it's HTML-escaped in the template but should still be valid JSON.
    var obj=null;
    try{ obj = JSON.parse(raw); }catch(e){
      // try unescape common entities
      try{
        var tmp=document.createElement('textarea');
        tmp.innerHTML = raw;
        obj = JSON.parse(tmp.value);
      }catch(_e){ obj=null; }
    }
    if (!obj){
      box.innerHTML = '<div class="err">Could not parse voice traits JSON.</div>';
      return;
    }

    var vt = obj.voice_traits || {};
    var m = obj.measured || {};
    var f = m.features || {};

    function fmtNum(x, d){
      try{
        var n = Number(x);
        if (!isFinite(n)) return '';
        return n.toFixed(d==null?2:d);
      }catch(e){ return ''; }
    }
    function chip(txt, cls){
      txt = String(txt||'').trim();
      if (!txt) return '';
      return '<span class="chip '+(cls||'')+'">'+escapeHtml(txt)+'</span>';
    }

    var tone = Array.isArray(vt.tone) ? vt.tone : [];
    var toneHtml = tone.length ? tone.map(t=>chip(t,'')).join('') : '<span class="muted">—</span>';

    var dur = (m.duration_s!=null) ? fmtNum(m.duration_s,2)+'s' : '';
    var lufs = (m.lufs_i!=null) ? fmtNum(m.lufs_i,1)+' LUFS' : '';

    var f0 = (f.f0_hz_median!=null) ? fmtNum(f.f0_hz_median,0)+' Hz' : '';
    var f0r = (f.f0_hz_p10!=null && f.f0_hz_p90!=null) ? (fmtNum(f.f0_hz_p10,0)+'–'+fmtNum(f.f0_hz_p90,0)+' Hz') : '';

    box.innerHTML = ''
      + '<div class="traitsGrid">'
      + '<div class="k">gender</div><div class="v">'+escapeHtml(String(vt.gender||'unknown'))+'</div>'
      + '<div class="k">age</div><div class="v">'+escapeHtml(String(vt.age||'unknown'))+'</div>'
      + '<div class="k">pitch</div><div class="v">'+escapeHtml(String(vt.pitch||'unknown'))+(f0?(' • '+escapeHtml(f0)):'')+(f0r?(' <span class="muted">('+escapeHtml(f0r)+')</span>'):'')+'</div>'
      + '<div class="k">accent</div><div class="v">'+escapeHtml(String(vt.accent||''))+'</div>'
      + '<div class="k">tone</div><div class="v"><div class="chips">'+toneHtml+'</div></div>'
      + '<div class="k">duration</div><div class="v">'+(dur?escapeHtml(dur):'<span class="muted">—</span>')+'</div>'
      + '<div class="k">loudness</div><div class="v">'+(lufs?escapeHtml(lufs):'<span class="muted">—</span>')+'</div>'
      + '<div class="k">engine</div><div class="v">'+escapeHtml(String(m.engine||''))+'</div>'
      + '<div class="k">voice_ref</div><div class="v">'+escapeHtml(String(m.voice_ref||''))+'</div>'
      + (m.tortoise_voice?('<div class="k">tortoise</div><div class="v">'+escapeHtml(String(m.tortoise_voice||''))+'</div>'):'')
      + '</div>';
  }catch(e){}
}

function analyzeMeta(){

  try{
    var out=$('out'); if(out) out.textContent='Analyzing voice…';
    fetch('/api/voices/__VID_RAW__/analyze_metadata', {method:'POST', headers:{'Content-Type':'application/json'}, credentials:'include', body: JSON.stringify({})})
      .then(function(r){ return r.json().catch(function(){return {ok:false,error:'bad_json'};}); })
      .then(function(j){
        if (j && j.ok){
          if(out) out.textContent='Voice analysis job started.';
          try{ toastSet('Analyzing voice…', 'info', 1800); window.__sfToastInit && window.__sfToastInit(); }catch(e){}
          setTimeout(function(){ window.location.href='/#tab-history'; }, 250);
          return;
        }
        if(out) out.innerHTML='<div class="err">'+escJs((j&&j.error)||'analyze failed')+'</div>';
      })
      .catch(function(e){ if(out) out.innerHTML='<div class="err">'+escJs(String(e))+'</div>'; });
  }catch(e){ }
}

function save(){
  var out=$('out'); if(out) out.textContent='Saving…';
  var payload={
    display_name: val('display_name'),
    enabled: chk('enabled')
  };
  fetch('/api/voices/__VID_RAW__', {method:'PUT', headers:{'Content-Type':'application/json'}, credentials:'include', body: JSON.stringify(payload)})
    .then(function(r){ return r.json().catch(function(){return {ok:false,error:'bad_json'};}); })
    .then(function(j){
      if (j && j.ok){ if(out) out.textContent='Saved.'; setTimeout(function(){ window.location.href='/#tab-voices'; }, 250); return; }
      if(out) out.innerHTML='<div class="err">'+escJs((j&&j.error)||'save failed')+'</div>';
    }).catch(function(e){ if(out) out.innerHTML='<div class="err">'+escJs(String(e))+'</div>'; });
}

function __copyText(txt){
  try{
    txt = String(txt||'');
    if (!txt) return;
    if (navigator.clipboard && navigator.clipboard.writeText){
      navigator.clipboard.writeText(txt).catch(function(){
        try{
          var ta=document.createElement('textarea');
          ta.value=txt; ta.style.position='fixed'; ta.style.left='-9999px'; ta.style.top='0';
          document.body.appendChild(ta);
          ta.focus(); ta.select();
          try{ document.execCommand('copy'); }catch(_e){}
          ta.remove();
        }catch(_e){}
      });
      return;
    }
  }catch(e){}
  try{
    var ta=document.createElement('textarea');
    ta.value=txt; ta.style.position='fixed'; ta.style.left='-9999px'; ta.style.top='0';
    document.body.appendChild(ta);
    ta.focus(); ta.select();
    try{ document.execCommand('copy'); }catch(_e){}
    ta.remove();
  }catch(e){}
}

function copySampleUrl(){
  try{
    var su=$('sample_url');
    var txt = su ? String(su.value||'').trim() : '';
    __copyText(txt);
    try{ if (typeof toastSet === 'function'){ toastSet('Copied', 'ok', 1200); if (window.__sfToastInit) window.__sfToastInit(); } }catch(e){}
  }catch(e){}
}

function playSample(){
  try{
    var a=$('audio');
    var su=$('sample_url');
    var existing = su ? String(su.value||'').trim() : '';
    if (existing){
      if (a){ a.src=existing; a.classList.remove('hide'); try{ a.play(); }catch(e){} }
      return;
    }

    var out=$('out'); if(out) out.textContent='Generating sample…';
    fetch('/api/voices/__VID_RAW__/sample', {method:'POST', headers:{'Content-Type':'application/json'}, credentials:'include', body: JSON.stringify({})})
      .then(function(r){ return r.json().catch(function(){return {ok:false,error:'bad_json'};}); })
      .then(function(j){
        if (!j || !j.ok || !j.sample_url){ throw new Error((j&&j.error)||'no_sample_url'); }
        try{ if (su) su.value = String(j.sample_url||''); }catch(e){}
        try{ var t=$('sample_url_text'); if (t) { t.textContent = String(j.sample_url||''); t.title = String(j.sample_url||''); } }catch(e){}
        if (a){ a.src=String(j.sample_url||''); a.classList.remove('hide'); try{ a.play(); }catch(e){} }
        if(out) out.textContent='';
      })
      .catch(function(e){ if(out) out.innerHTML='<div class="err">'+escJs(String(e&&e.message?e.message:e))+'</div>'; });
  }catch(e){}
}

function copyVoiceRef(){
  try{
    var txt = val('voice_ref');
    __copyText(txt);
    try{ if (typeof toastSet==='function'){ toastSet('Copied', 'ok', 1200); if (window.__sfToastInit) window.__sfToastInit(); } }catch(_e){}
  }catch(e){}
}

try{ document.addEventListener('DOMContentLoaded', function(){ try{ renderTraits(); }catch(e){} }); }catch(e){}
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
  

<script>
let metricsES = null;
let monitorEnabled = true;
let lastMetrics = null;

function loadMonitorPref(){
  try{
    var v = localStorage.getItem('sf_monitor_enabled');
    if (v === null) return true;
    return v === '1';
  }catch(e){
    return true;
  }
}

function saveMonitorPref(on){
  try{ localStorage.setItem('sf_monitor_enabled', on ? '1' : '0'); }catch(e){}
}

function stopMetricsStream(){
  if (metricsES){
    try{ metricsES.close(); }catch(e){}
    metricsES = null;
  }
}

var metricsPoll = null;
function stopMetricsPoll(){
  if (metricsPoll){
    try{ clearInterval(metricsPoll); }catch(e){}
    metricsPoll = null;
  }
}

function startMetricsPoll(){
  if (!monitorEnabled) return;
  try{ if (typeof stopMetricsPoll==='function') try{ if (typeof stopMetricsPoll==='function') stopMetricsPoll(); }catch(e){} }catch(e){}
  metricsPoll = setInterval(function(){
    try{
      jsonFetch('/api/metrics').then(function(m){
        lastMetrics = m;
        if (m && m.ok===false){
          try{ var ds=document.getElementById('dockStats'); if (ds) ds.textContent='Monitor error'; }catch(e){}
          try{ var sub=document.getElementById('monSub'); if (sub) sub.textContent = String((m&&m.error)||'Monitor error'); }catch(e){}
          return;
        }
        updateMonitorFromMetrics(m);
      }).catch(function(_e){});
    }catch(e){}
  }, 2000);
}

function setBar(elId, pct){
  var el=document.getElementById(elId);
  if (!el) return;
  var p=Math.max(0, Math.min(100, pct||0));
  var fill=el.querySelector('div');
  if (fill) fill.style.width = p.toFixed(0) + '%';
  el.classList.remove('warn','bad');
  if (p >= 85) el.classList.add('bad');
  else if (p >= 60) el.classList.add('warn');
}

function fmtPct(x){
  if (x==null) return '-';
  return (Number(x).toFixed(1)) + '%';
}

function fmtTs(ts){
  if (!ts) return '-';
  try{
    var d=new Date(ts*1000);
    return d.toLocaleString();
  }catch(e){
    return String(ts);
  }
}

function updateDockFromMetrics(m){
  var el = document.getElementById('dockStats');
  if (!el) return;
  var b = (m && m.body) ? m.body : (m || {});
  var cpu = (b.cpu_pct!=null) ? Number(b.cpu_pct).toFixed(1)+'%' : '-';
  var rt = Number(b.ram_total_mb||0); var ru = Number(b.ram_used_mb||0);
  var rp = rt ? (ru/rt*100) : 0;
  var ram = rt ? rp.toFixed(1)+'%' : '-';
  var gpus = Array.isArray(b && b.gpus) ? b.gpus : (b && b.gpu ? [b.gpu] : []);
  var maxGpu = null;
  if (gpus.length){
    maxGpu = 0;
    for (var i=0;i<gpus.length;i++){
      var u = Number((gpus[i]||{}).util_gpu_pct||0);
      if (u > maxGpu) maxGpu = u;
    }
  }
  var gpu = (maxGpu==null) ? '-' : maxGpu.toFixed(1)+'%';
  el.textContent = 'CPU ' + cpu + ' • RAM ' + ram + ' • GPU ' + gpu;
}

function renderGpus(b){
  var el = document.getElementById('monGpus');
  if (!el) return;
  var gpus = Array.isArray(b && b.gpus) ? b.gpus : (b && b.gpu ? [b.gpu] : []);
  if (!gpus.length){
    el.innerHTML = '<div class="muted">No GPU data</div>';
    return;
  }

  el.innerHTML = gpus.slice(0,8).map(function(g,i){
    g = g || {};
    var idx = (g.index!=null) ? g.index : i;
    var util = Number(g.util_gpu_pct||0);
    var power = (g.power_w!=null) ? Number(g.power_w).toFixed(0)+'W' : null;
    var temp = (g.temp_c!=null) ? Number(g.temp_c).toFixed(0)+'C' : null;
    var right = [power, temp].filter(Boolean).join(' • ');
    var vt = Number(g.vram_total_mb||0);
    var vu = Number(g.vram_used_mb||0);
    var vp = vt ? (vu/vt*100) : 0;

    return "<div class='gpuCard'>"+
      "<div class='gpuHead'><div class='l'>GPU "+idx+"</div><div class='r'>"+(right||'')+"</div></div>"+
      "<div class='gpuRow'><div class='k'>Util</div><div class='v'>"+fmtPct(util)+"</div></div>"+
      "<div class='bar small' id='barGpu"+idx+"'><div></div></div>"+
      "<div class='gpuRow' style='margin-top:10px'><div class='k'>VRAM</div><div class='v'>"+(vt ? ((vu/1024).toFixed(1)+' / '+(vt/1024).toFixed(1)+' GB') : '-')+"</div></div>"+
      "<div class='bar small' id='barVram"+idx+"'><div></div></div>"+
    "</div>";
  }).join('');

  gpus.slice(0,8).forEach(function(g,i){
    g=g||{};
    var idx = (g.index!=null) ? g.index : i;
    var util = Number(g.util_gpu_pct||0);
    var vt = Number(g.vram_total_mb||0);
    var vu = Number(g.vram_used_mb||0);
    var vp = vt ? (vu/vt*100) : 0;
    setBar('barGpu'+idx, util);
    setBar('barVram'+idx, vp);
  });
}

function updateMonitorFromMetrics(m){
  var b = (m && m.body) ? m.body : (m || {});
  var cpu = Number(b.cpu_pct || 0);
  var c=document.getElementById('monCpu'); if(c) c.textContent = fmtPct(cpu);
  setBar('barCpu', cpu);

  var rt = Number(b.ram_total_mb || 0);
  var ru = Number(b.ram_used_mb || 0);
  var rp = rt ? (ru/rt*100) : 0;
  var r=document.getElementById('monRam'); if(r) r.textContent = rt ? (ru.toFixed(0) + ' / ' + rt.toFixed(0) + ' MB (' + rp.toFixed(1) + '%)') : '-';
  setBar('barRam', rp);
  renderGpus(b);

  var ts = b.ts ? fmtTs(b.ts) : '-';
  var sub=document.getElementById('monSub'); if(sub) sub.textContent = 'Tinybox time: ' + ts;
  updateDockFromMetrics(m);

  // processes
  try{
    var procs = Array.isArray(b.processes) ? b.processes : [];
    var pre=document.getElementById('monProc');
    if (pre){
      if (!procs.length) pre.textContent = '(no process data)';
      else {
        var lines=[];
        lines.push('PID     %CPU   %MEM   GPU   ELAPSED   COMMAND');
        lines.push('-----------------------------------------------');
        for (var i=0;i<procs.length;i++){
          var p=procs[i]||{};
          var pid=String(p.pid||'').padEnd(7,' ');
          var cpuS=(Number(p.cpu_pct||0).toFixed(1)+'').padStart(5,' ');
          var memS=(Number(p.mem_pct||0).toFixed(1)+'').padStart(5,' ');
          var gpuS=(p.gpu_mem_mb!=null?Number(p.gpu_mem_mb).toFixed(0)+'MB':'-').padStart(6,' ');
          var et=String(p.elapsed||'').padEnd(9,' ');
          var cmd=String(p.args||p.command||p.name||'');
          lines.push(pid+'  '+cpuS+'  '+memS+'  '+gpuS+'  '+et+'  '+cmd);
        }
        pre.textContent = lines.join(String.fromCharCode(10));
      }
    }
  }catch(e){}
}

function startMetricsStream(){
  if (!monitorEnabled) return;
  stopMetricsStream();
  try{ if (typeof stopMetricsPoll==='function') try{ if (typeof stopMetricsPoll==='function') stopMetricsPoll(); }catch(e){} }catch(e){}
  try{
    var ds=document.getElementById('dockStats'); if (ds) ds.textContent='Connecting…';
    metricsES = new EventSource('/api/metrics/stream');
    metricsES.onmessage = function(ev){
      try{
        var m = JSON.parse(ev.data || '{}');
        lastMetrics = m;
        if (m && m.ok===false){
          try{ var ds=document.getElementById('dockStats'); if (ds) ds.textContent='Monitor error'; }catch(e){}
          try{ var sub=document.getElementById('monSub'); if (sub) sub.textContent = String((m&&m.error)||'Monitor error'); }catch(e){}
          return;
        }
        updateMonitorFromMetrics(m);
      }catch(e){}
    };
    metricsES.onerror = function(_e){
      try{ var ds=document.getElementById('dockStats'); if (ds) ds.textContent='Monitor error'; }catch(e){}
      try{ var sub=document.getElementById('monSub'); if (sub) sub.textContent = 'Monitor error'; }catch(e){}
      try{ if (typeof startMetricsPoll==='function') try{ if (typeof startMetricsPoll==='function') startMetricsPoll(); }catch(e){} }catch(e){}
    };
  }catch(e){}
}

function setMonitorEnabled(on){
  monitorEnabled = !!on;
  saveMonitorPref(monitorEnabled);
  try{ document.documentElement.classList.toggle('monOn', !!monitorEnabled); }catch(e){}
  if (!monitorEnabled){
    stopMetricsStream();
    try{ if (typeof stopMetricsPoll==='function') try{ if (typeof stopMetricsPoll==='function') stopMetricsPoll(); }catch(e){} }catch(e){}
    try{ var ds=document.getElementById('dockStats'); if (ds) ds.textContent='Monitor off'; }catch(e){}
    return;
  }
  startMetricsStream();
}

function openMonitor(){
  if (!monitorEnabled) return;
  var b=document.getElementById('monitorBackdrop');
  var sh=document.getElementById('monitorSheet');
  if (b){ b.classList.remove('hide'); b.style.display='block'; }
  if (sh){ sh.classList.remove('hide'); sh.style.display='block'; }
  try{ document.body.classList.add('sheetOpen'); }catch(e){}
  startMetricsStream();
  if (lastMetrics) updateMonitorFromMetrics(lastMetrics);
}

function closeMonitor(){
  var b=document.getElementById('monitorBackdrop');
  var sh=document.getElementById('monitorSheet');
  if (b){ b.classList.add('hide'); b.style.display='none'; }
  if (sh){ sh.classList.add('hide'); sh.style.display='none'; }
  try{ document.body.classList.remove('sheetOpen'); }catch(e){}
}

function closeMonitorEv(ev){
  try{ if (ev && ev.stopPropagation) ev.stopPropagation(); }catch(e){}
  closeMonitor();
  return false;
}

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

try{ document.addEventListener('DOMContentLoaded', function(){ bindMonitorClose(); setMonitorEnabled(loadMonitorPref()); }); }catch(e){}
try{ bindMonitorClose(); setMonitorEnabled(loadMonitorPref()); }catch(e){}
</script>
  </body>
</html>"""

    html = (html
        .replace('__VID__', vid)
        .replace('__DN__', dn)
        .replace('__ENG__', eng)
        .replace('__VREF__', vref)
        .replace('__STXT__', stxt)
        .replace('__SURL__', surl)
        .replace('__ENABLED__', enabled_checked)
        .replace('__VID_RAW__', voice_id)
        .replace('__VTRAITS__', esc(vtraits_json) if vtraits_json else '—')
    )
    html = (html
        .replace('__VOICES_BASE_CSS__', VOICES_BASE_CSS)
        .replace('__VOICE_EDIT_EXTRA_CSS__', VOICE_EDIT_EXTRA_CSS)
        .replace('__DEBUG_BANNER_HTML__', DEBUG_BANNER_HTML)
        .replace('__DEBUG_BANNER_BOOT_JS__', DEBUG_BANNER_BOOT_JS)
        .replace('__BUILD__', str(build))
    )
    return html


@app.get('/settings/providers/new')
def settings_new_provider_page(response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return HTMLResponse(
        """<!doctype html>
<html>
<head>
  <meta charset='utf-8'/>
  <meta name='viewport' content='width=device-width, initial-scale=1'/>
  <title>StoryForge - Add provider</title>
  <style>__INDEX_BASE_CSS__</style>
</head>
<body>
  <div class='navBar'>
    <div class='top'>
      <div>
        <div class='brandRow'><h1><a class='brandLink' href='/'>StoryForge</a></h1><div class='pageName'>Add provider</div></div>
        <div class='muted'>Coming soon. Providers will be added here later.</div>
      </div>
      <div class='row headActions'>
        <a href='/#tab-advanced'><button class='secondary' type='button'>Back</button></a>
      </div>
    </div>
  </div>

  <div class='card'>
    <div style='font-weight:950;margin-bottom:6px;'>Add provider</div>
    <div class='muted'>This is a placeholder page. We'll implement provider creation here later.</div>
  </div>
</body>
</html>""".replace('__INDEX_BASE_CSS__', INDEX_BASE_CSS)
    )


@app.get('/voices/new', response_class=HTMLResponse)
def voices_new_page(response: Response):
    response.headers['Cache-Control'] = 'no-store'
    build = APP_BUILD
    # Separate screen for generating/testing a voice before saving.
    html = '''<!doctype html>
<html>
<head>
  <meta charset='utf-8'/>
  <meta name='viewport' content='width=device-width, initial-scale=1'/>
  <title>StoryForge - Generate voice</title>
  <style>__VOICES_BASE_CSS____VOICE_NEW_EXTRA_CSS__</style>
</head>
<body>
  __DEBUG_BANNER_BOOT_JS__
  <div class='navBar'>
    <div class='top'>
      <div>
        <div class='brandRow'><h1><a class='brandLink' href='/'>StoryForge</a></h1><div class='pageName'>Generate voice</div></div>
      </div>
      <div class='row headActions'>
        <a href='/#tab-voices'><button class='secondary' type='button'>Back</button></a>
        <div class='menuWrap'>
          <button class='userBtn' type='button' onclick='toggleMenu()' aria-label='User menu'>
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
              <div>
                <div class='uName'>User</div>
                <div class='uSub'>Admin</div>
              </div>
            </div>
            <div class='uActions'>
              <a href='/logout'><button class='secondary' type='button'>Log out</button></a>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>

  __DEBUG_BANNER_HTML__

  <div class='card'>
    <div style='font-weight:950;margin-bottom:6px;'>Generate voice</div>

    <div class='k'>Voice name</div>
    <div class='row' style='gap:10px;flex-wrap:nowrap'>
      <input id='voiceName' placeholder='Luna' style='flex:1;min-width:0' />
      <button type='button' class='copyBtn' onclick='genVoiceName()' aria-label='Random voice name' title='Random voice name'>
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <path stroke="currentColor" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z"/>
          <path stroke="currentColor" fill="currentColor" d="M8.5 9.5a1 1 0 110-2 1 1 0 010 2z"/>
          <path stroke="currentColor" fill="currentColor" d="M15.5 16.5a1 1 0 110-2 1 1 0 010 2z"/>
          <path stroke="currentColor" fill="currentColor" d="M15.5 9.5a1 1 0 110-2 1 1 0 010 2z"/>
          <path stroke="currentColor" fill="currentColor" d="M8.5 16.5a1 1 0 110-2 1 1 0 010 2z"/>
          <path stroke="currentColor" fill="currentColor" d="M12 13a1 1 0 110-2 1 1 0 010 2z"/>
        </svg>
      </button>
    </div>

    <div class='k'>Engine</div>
    <select id='engineSel'>
      <option value='tortoise' selected>tortoise</option>
      <option value='xtts'>xtts</option>
    </select>

    <div id='tortoiseBox' class='hide'>
      <div class='k'>Tortoise voice</div>
      <div class='row' style='gap:10px;flex-wrap:nowrap'>
        <select id='tortoiseVoice' style='flex:1;min-width:0'></select>
        <select id='tortoiseGender' style='flex:0 0 140px'>
          <option value='any' selected>Any</option>
          <option value='female'>Female</option>
          <option value='male'>Male</option>
        </select>
      </div>
      <div class='k'>Quality</div>
      <select id='tortoisePreset'>
        <option value='ultrafast'>ultrafast</option>
        <option value='fast'>fast</option>
        <option value='standard' selected>standard</option>
        <option value='high_quality'>high_quality</option>
      </select>
    </div>

    <div id='clipBox'>
      <div class='k'>Voice clip</div>
      <div class='row' style='gap:10px;flex-wrap:nowrap'>
        <select id='clipMode' style='flex:0 0 160px'>
          <option value='preset' selected>Choose preset</option>
          <option value='upload'>Upload</option>
          <option value='url'>Paste URL</option>
        </select>

        <div id='clipPresetRow' class='hide' style='flex:1;min-width:0'>
          <select id='clipPreset'></select>
        </div>

        <div id='clipUploadRow' class='hide' style='flex:1;min-width:0'>
          <input id='clipFile' type='file' accept='audio/*' />
        </div>

        <div id='clipUrlRow' class='hide' style='flex:1;min-width:0'>
          <input id='clipUrl' placeholder='https://…/clip.wav' />
        </div>
      </div>
    </div>

    <div class='k'>Sample text <span class='muted' id='sampleTextCount' style='margin-left:8px'>0 chars</span></div>
    <div class='row' style='gap:10px;flex-wrap:nowrap'>
      <textarea id='sampleText' placeholder='Hello…' style='flex:1;min-width:0'>Hello. This is a test sample for a new voice.</textarea>
      <button type='button' class='copyBtn' onclick='genSampleText()' aria-label='Random sample text' title='Random sample text' style='align-self:stretch'>
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <path stroke="currentColor" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z"/>
          <path stroke="currentColor" fill="currentColor" d="M8.5 9.5a1 1 0 110-2 1 1 0 010 2z"/>
          <path stroke="currentColor" fill="currentColor" d="M15.5 16.5a1 1 0 110-2 1 1 0 010 2z"/>
          <path stroke="currentColor" fill="currentColor" d="M15.5 9.5a1 1 0 110-2 1 1 0 010 2z"/>
          <path stroke="currentColor" fill="currentColor" d="M8.5 16.5a1 1 0 110-2 1 1 0 010 2z"/>
          <path stroke="currentColor" fill="currentColor" d="M12 13a1 1 0 110-2 1 1 0 010 2z"/>
        </svg>
      </button>
    </div>

    <div class='row' style='margin-top:12px'>
      <button type='button' onclick='trainAndSave()'>Generate</button>
    </div>

    <div id='out' class='muted' style='margin-top:10px'></div>
  </div>

<script>
function esc(s){ return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function escAttr(s){
  // escape for HTML attributes / single-quoted contexts
  try{
    return String(s||'')
      .replace(/&/g,'&amp;')
      .replace(/</g,'&lt;')
      .replace(/>/g,'&gt;')
      .replace(/"/g,'&quot;')
      .replace(/'/g,'&#39;');
  }catch(e){
    return '';
  }
}

function $(id){ return document.getElementById(id); }

function updateSampleTextCount(){
  try{
    var ta=$('sampleText');
    var c=$('sampleTextCount');
    if (!ta || !c) return;
    var txt = String(ta.value||'');
    var chars = txt.length;
    var words = 0;
    try{ words = txt.trim() ? txt.trim().split(/\s+/).length : 0; }catch(e){ words = 0; }
    c.textContent = String(chars) + ' chars • ' + String(words) + ' words';
  }catch(e){}
}

function jsonFetch(url, opts){
  opts = opts || {};
  opts.credentials = 'include';
  return fetch(url, opts).then(function(r){
    if (r.status===401){ window.location.href='/login'; return Promise.reject(new Error('unauthorized')); }
    return r.json().catch(function(){ return {ok:false,error:'bad_json'}; });
  });
}

// user menu
function toggleMenu(){
  var m=document.getElementById('topMenu');
  if (!m) return;
  if (m.classList.contains('show')) m.classList.remove('show');
  else m.classList.add('show');
}
try{
  document.addEventListener('click', function(ev){
    try{
      var m=document.getElementById('topMenu');
      if (!m) return;
      var w=ev.target && ev.target.closest ? ev.target.closest('.menuWrap') : null;
      if (!w) m.classList.remove('show');
    }catch(e){}
    try{ setEngineUi(); }catch(e){}
  });
}catch(e){}

function setVis(){
  var m=(($('clipMode')||{}).value||'upload');
  var u=$('clipUploadRow'), p=$('clipPresetRow'), r=$('clipUrlRow');
  if(u) u.classList.toggle('hide', m!=='upload');
  if(p) p.classList.toggle('hide', m!=='preset');
  if(r) r.classList.toggle('hide', m!=='url');
}

// Tortoise built-in voices (from Tinybox tortoise install)
var TORTOISE_VOICES = [
  'angie','applejack','daniel','deniro','emma','freeman','geralt','halle','jlaw','lj','mol','myself','pat','pat2','rainbow','snakes','tim_reynolds','tom','weaver','william',
  'train_atkins','train_daws','train_dotrice','train_dreams','train_empire','train_grace','train_kennard','train_lescault','train_mouse'
];
var TORTOISE_GENDER = {
  'angie':'female','emma':'female','halle':'female','jlaw':'female','mol':'female','rainbow':'female','applejack':'female','train_grace':'female',
  'daniel':'male','deniro':'male','freeman':'male','geralt':'male','lj':'male','myself':'male','pat':'male','pat2':'male','snakes':'male','tim_reynolds':'male','tom':'male','weaver':'male','william':'male',
  'train_atkins':'male','train_daws':'male','train_dotrice':'male','train_dreams':'male','train_empire':'male','train_kennard':'male','train_lescault':'male','train_mouse':'male'
};

function loadTortoiseVoices(){
  var sel=$('tortoiseVoice');
  if(!sel) return;
  var gsel=$('tortoiseGender');
  var g = gsel ? String(gsel.value||'any') : 'any';
  var voices = TORTOISE_VOICES.slice();
  if (g==='female' || g==='male') voices = voices.filter(function(v){ return (TORTOISE_GENDER[v]||'any')===g; });
  if (!voices.length) voices = TORTOISE_VOICES.slice();
  var cur = '';
  try{ cur = String(sel.value||'').trim(); }catch(e){}
  sel.innerHTML='';
  for (var i=0;i<voices.length;i++){
    var o=document.createElement('option');
    o.value=voices[i];
    o.textContent=voices[i];
    sel.appendChild(o);
  }
  if (cur){ try{ sel.value=cur; }catch(e){} }
}

function setEngineUi(){
  var eng = String((($('engineSel')||{}).value||'')).trim();
  var tb=$('tortoiseBox');
  if (tb) tb.classList.toggle('hide', eng!=='tortoise');

  // Hide clip UI entirely when tortoise is selected
  try{
    var showClip = (eng!=='tortoise');
    var cb = $('clipBox');
    if (cb) cb.classList.toggle('hide', !showClip);
    if (!showClip){
      if ($('clipPresetRow')) $('clipPresetRow').classList.add('hide');
      if ($('clipUploadRow')) $('clipUploadRow').classList.add('hide');
      if ($('clipUrlRow')) $('clipUrlRow').classList.add('hide');
    } else {
      // Ensure the correct inline clip control is visible (preset/upload/url)
      try{ setVis(); }catch(e){}
    }
  }catch(e){}
}

function loadEngines(){
  return jsonFetch('/api/voice_provider/engines').then(function(j){
    var sel=$('engineSel'); if(!sel) return;
    var prev = '';
    try{ prev = String(sel.value||'').trim(); }catch(e){}

    sel.innerHTML='';
    var arr=(j&&j.engines)||[];
    if (!arr.length){ arr=['tortoise','xtts']; }
    for(var i=0;i<arr.length;i++){
      var o=document.createElement('option');
      o.value=String(arr[i]);
      o.textContent=String(arr[i]);
      sel.appendChild(o);
    }
    // default to tortoise if available; otherwise keep previous selection
    try{
      var hasT = false;
      for (var k=0;k<sel.options.length;k++){ if (String(sel.options[k].value)==='tortoise') { hasT=true; break; } }
      if (hasT) sel.value = 'tortoise';
      else if (prev) sel.value = prev;
    }catch(e){}

    // Force UI sync even if async timing is weird on iOS
    try{ setEngineUi(); }catch(e){}
    try{ setTimeout(function(){ try{ setEngineUi(); }catch(e){} }, 0); }catch(e){}
    try{ setTimeout(function(){ try{ setEngineUi(); }catch(e){} }, 200); }catch(e){}
  });
}

function loadPresets(){
  function runOnce(){ return jsonFetch('/api/voice_provider/presets'); }
  return runOnce().catch(function(_e){ return new Promise(function(res){ setTimeout(res, 600); }).then(runOnce); }).then(function(j){
    var sel=$('clipPreset'); if(!sel) return;
    sel.innerHTML='';

    if (!j || j.ok===false){
      var msg = String((j&&j.error)?j.error:'unknown');
      var st = (j&&j.status!=null) ? (' ' + String(j.status)) : '';
      sel.innerHTML = "<option value=''>No presets (error"+st+")</option>";
      var out=$('out');
      if (out){
        out.innerHTML = "<div class='err'>Presets failed: " + esc(msg) + (st?(' (HTTP '+esc(String(j.status))+')'):'') + "</div>";
      }
      return;
    }

    var arr=(j&&j.clips)||[];
    if (!arr.length){
      sel.innerHTML = "<option value=''>No presets available</option>";
      return;
    }
    function presetLabel(c){
      try{
        var nm = String((c&&c.name)||'').trim();
        var male = {'awb':1,'bdl':1,'jmk':1,'ksp':1,'rms':1};
        var female = {'clb':1,'slt':1};
        if (nm && male[nm]) return nm + ' (male)';
        if (nm && female[nm]) return nm + ' (female)';
        return String((c&&c.name) || (c&&c.url) || (c&&c.path) || '');
      }catch(e){
        return String((c&&c.name) || (c&&c.url) || (c&&c.path) || '');
      }
    }

    for(var i=0;i<arr.length;i++){
      var c=arr[i]||{};
      var o=document.createElement('option');
      o.value=String(c.url||c.path||'');
      o.textContent=presetLabel(c);
      sel.appendChild(o);
    }
  });
}

function uploadClip(){
  var f = (($('clipFile')||{}).files||[])[0];
  if(!f) return Promise.reject('no_file');
  var fd=new FormData();
  fd.append('file', f);
  return fetch('/api/upload/voice_clip', {method:'POST', body: fd, credentials:'include'})
    .then(function(r){ return r.json().catch(function(){ return {ok:false,error:'bad_json'}; }); })
    .then(function(j){ if(j&&j.ok&&j.url) return j.url; throw ((j&&j.error)||'upload_failed'); });
}

function getClipUrl(){
  var m=(($('clipMode')||{}).value||'upload');
  if(m==='url'){
    var u=String((($('clipUrl')||{}).value||'')).trim();
    if (!u) return Promise.reject('missing_url');
    return Promise.resolve(u);
  }
  if(m==='preset'){
    var v=String((($('clipPreset')||{}).value||'')).trim();
    if (!v) return Promise.reject('missing_preset');
    // If provider returns a Tinybox path, copy it to Spaces first.
    if (v.indexOf('/')===0){
      return jsonFetch('/api/voice_provider/preset_to_spaces', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({path:v})})
        .then(function(j){
          if (!j || !j.ok || !j.url) throw new Error((j&&j.error)||'preset_to_spaces_failed');
          return String(j.url);
        });
    }
    return Promise.resolve(v);
  }
  return uploadClip();
}

function slugify(s){
  try{
    s = String(s||'').toLowerCase();
    s = s.replace(/[^a-z0-9]+/g,'-');
    s = s.replace(/^-+|-+$/g,'');
    return s || 'voice';
  }catch(e){
    return 'voice';
  }
}


function genVoiceName(){
  var out=$('out');
  var el=$('voiceName');
  var btn=null;
  try{ btn = document.querySelector("button[onclick='genVoiceName()']"); }catch(e){}

  var origVal = el ? String(el.value||'') : '';
  var frames = ['Picking a color', 'Picking a color.', 'Picking a color..', 'Picking a color...'];
  var i=0; var timer=null;
  function startAnim(){
    try{
      if (el){ el.disabled=true; el.value = frames[0]; }
      if (btn){ btn.disabled=true; }
      timer = setInterval(function(){
        try{ i=(i+1)%frames.length; if (el) el.value = frames[i]; }catch(e){}
      }, 280);
    }catch(e){}
  }
  function stopAnim(){
    try{ if (timer) clearInterval(timer); }catch(e){}
    timer=null;
    try{ if (el) el.disabled=false; }catch(e){}
    try{ if (btn) btn.disabled=false; }catch(e){}
  }

  startAnim();
  function runOnce(){
    return jsonFetch('/api/voices/random_name', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({})});
  }

  return runOnce()
    .catch(function(_e){ return new Promise(function(res){ setTimeout(res, 500); }).then(runOnce); })
    .then(function(j){
      stopAnim();
      if (!j || !j.ok || !j.name){
        if (el) el.value = origVal;
        throw new Error((j&&j.error)||'name_failed');
      }
      if (el) el.value = String(j.name||'').trim();
      if (out) out.textContent='';
    })
    .catch(function(e){
      stopAnim();
      if (el) el.value = origVal;
      if (out) out.innerHTML='<div class="err">'+esc(String(e&&e.message?e.message:e))+'</div>';
    });
}

function genSampleText(){
  var out=$('out');
  var ta=$('sampleText');
  var btn=null;
  try{ btn = document.querySelector("button[onclick='genSampleText()']"); }catch(e){}

  var origVal = ta ? String(ta.value||'') : '';
  var origPh = ta ? String(ta.placeholder||'') : '';

  // Put the loading animation in the textarea itself.
  var frames = [
    'Generating sample text',
    'Generating sample text.',
    'Generating sample text..',
    'Generating sample text...',
  ];
  var i=0;
  var timer=null;

  function startAnim(){
    try{
      if (ta){ ta.disabled=true; ta.value = frames[0]; }
      try{ updateSampleTextCount(); }catch(e){}
      if (btn){ btn.disabled=true; }
      timer = setInterval(function(){
        try{
          i = (i+1) % frames.length;
          if (ta) ta.value = frames[i];
          try{ updateSampleTextCount(); }catch(e){}
        }catch(e){}
      }, 350);
    }catch(e){}
  }
  function stopAnim(){
    try{ if (timer) clearInterval(timer); }catch(e){}
    timer=null;
    try{ if (ta){ ta.disabled=false; } }catch(e){}
    try{ if (btn){ btn.disabled=false; } }catch(e){}
  }

  startAnim();

  // Safari sometimes surfaces generic "TypeError: Load failed" for network/proxy failures.
  // Do a small retry to smooth over transient disconnects.
  function runOnce(){
    return jsonFetch('/api/voices/sample_text_random', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({})});
  }

  return runOnce()
    .catch(function(_e){ return new Promise(function(res){ setTimeout(res, 500); }).then(runOnce); })
    .then(function(j){
      stopAnim();
      if (!j || !j.ok || !j.text){
        if (ta){ ta.value = origVal; ta.placeholder = origPh; }
        try{ updateSampleTextCount(); }catch(e){}
        throw new Error((j&&j.error)||'sample_text_failed');
      }
      if (ta) ta.value = String(j.text||'');
      try{ updateSampleTextCount(); }catch(e){}
      if (out) out.textContent='';
    })
    .catch(function(e){
      stopAnim();
      if (ta){ ta.value = origVal; ta.placeholder = origPh; }
      try{ updateSampleTextCount(); }catch(_e){}
      if (out) out.innerHTML='<div class="err">'+esc(String(e&&e.message?e.message:e))+'</div>';
    });
}

function trainAndSave(){
  // New UX: generating a sample should NOT auto-save to roster.
  // Queue a job, redirect to Jobs, then user can Play + Save from the job card.
  var out=$('out'); if(out) out.textContent='Queuing job…';

  var displayName = String((($('voiceName')||{}).value||'')).trim();
  var engine = String((($('engineSel')||{}).value||'')).trim();
  var rid = String((($('id')||{}).value||'')).trim();
  if (!rid) rid = slugify(displayName);
  if ($('id')) $('id').value = rid;

  if (!displayName){ if(out) out.innerHTML='<div class="err">Missing voice name</div>'; return; }
  if (!engine){ if(out) out.innerHTML='<div class="err">Missing engine</div>'; return; }

  // Reuse testSample path (which queues /api/tts_job and redirects to History)
  return testSample();
}

function val(id){ var el=$(id); return el?el.value:''; }

function testSample(){
  var engine = String(val('engineSel') || '').trim();
  if (!engine) engine = String(val('engine') || '').trim();

  // Prefer using the last trained voice_ref if present; otherwise, try current preset/url/upload.
  var vref = String(val('voice_ref') || '').trim();
  var out=$('out'); if(out) out.textContent='Generating…';

  function go(voiceRef){
    var payload={engine: engine, voice: String(voiceRef||''), text: String(val('sampleText')||val('text')||'') || ('Hello. This is ' + (val('voiceName')||val('id')||'a voice') + '.'), upload:true};

    // Run as a job so progress is visible on the Jobs/History tab.
    // Provide some metadata so the completed job can offer "Save to roster".
    payload.display_name = String(val('voiceName')||val('id')||'').trim() || 'Voice';
    payload.roster_id = String(val('id')||'').trim() || slugify(payload.display_name);

    // If engine=tortoise, attach the selected tortoise settings (best-effort).
    try{
      if (engine==='tortoise'){
        var ts = window.__SF_LAST_TORTOISE || {};
        payload.tortoise_voice = String(ts.voice||'').trim();
        payload.tortoise_gender = String(ts.gender||'').trim();
        payload.tortoise_preset = String(ts.preset||'').trim();
      }
    }catch(_e){}

    return jsonFetch('/api/tts_job', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)})
      .then(function(j){
        if (!j || !j.ok || !j.job_id){ if(out) out.innerHTML='<div class="err">'+esc((j&&j.error)||'tts_job_failed')+'</div>'; return; }
        // Jump straight to Jobs/History so you can watch it.
        window.location.href = '/#tab-history';
      }).catch(function(e){ if(out) out.innerHTML='<div class="err">'+esc(String(e))+'</div>'; });
  }

  if (vref) return go(vref).catch(function(e){ if(out) out.innerHTML='<div class="err">'+esc(String(e))+'</div>'; });

  // If using tortoise, voice_ref is a built-in voice name (not a clip URL).
  if (engine==='tortoise'){
    var tv = 'tom';
    var tg = 'any';
    var tp = 'standard';
    try{
      tv = String((($('tortoiseVoice')||{}).value||'')).trim() || 'tom';
      tg = String((($('tortoiseGender')||{}).value||'any')).trim() || 'any';
      tp = String((($('tortoisePreset')||{}).value||'standard')).trim() || 'standard';
    }catch(_e){}
    // Persist for later "Save to roster" from the job card.
    try{ window.__SF_LAST_TORTOISE = {voice: tv, gender: tg, preset: tp}; }catch(_e){}

    // Send selected voice now (Cloud -> Tinybox uses this as tortoise --ref)
    return go(tv).catch(function(e){ if(out) out.innerHTML='<div class="err">'+esc(String(e))+'</div>'; });
  }

  // No trained voice_ref yet (xtts): derive from clip mode.
  return getClipUrl().then(function(url){ return go(url); })
    .catch(function(e){ if(out) out.innerHTML='<div class="err">'+esc(String(e))+'</div>'; });
}

try{ document.addEventListener('DOMContentLoaded', function(){
  try{ loadEngines(); }catch(e){}
  try{ loadPresets(); }catch(e){}
  try{ setVis(); }catch(e){}
  var cm=$('clipMode'); if(cm) cm.addEventListener('change', setVis);
  var eg=$('engineSel'); if(eg) eg.addEventListener('change', function(){ try{ setEngineUi(); }catch(e){}; try{ setVis(); }catch(e){} });
  var tg=$('tortoiseGender'); if(tg) tg.addEventListener('change', function(){ try{ loadTortoiseVoices(); }catch(e){} });
  try{ loadTortoiseVoices(); }catch(e){}
  try{ setEngineUi(); }catch(e){}
  try{ updateSampleTextCount(); }catch(e){}
  try{ var st=$('sampleText'); if (st) st.addEventListener('input', updateSampleTextCount); }catch(e){}

  // Suggest a random voice name on first load (only if empty)
  try{ var vn=$('voiceName'); if(vn && !String(vn.value||'').trim()){ genVoiceName(); } }catch(e){}

  // Mark JS as running for the debug banner.
  try{ if (typeof __sfSetDebugInfo === 'function') __sfSetDebugInfo('ok'); }catch(e){}
}); }catch(e){}
try{ if (typeof __sfSetDebugInfo === 'function') __sfSetDebugInfo('ok'); }catch(e){}
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
  

<script>
let metricsES = null;
let monitorEnabled = true;
let lastMetrics = null;

function loadMonitorPref(){
  try{
    var v = localStorage.getItem('sf_monitor_enabled');
    if (v === null) return true;
    return v === '1';
  }catch(e){
    return true;
  }
}

function saveMonitorPref(on){
  try{ localStorage.setItem('sf_monitor_enabled', on ? '1' : '0'); }catch(e){}
}

function stopMetricsStream(){
  if (metricsES){
    try{ metricsES.close(); }catch(e){}
    metricsES = null;
  }
}

var metricsPoll = null;
function stopMetricsPoll(){
  if (metricsPoll){
    try{ clearInterval(metricsPoll); }catch(e){}
    metricsPoll = null;
  }
}

function startMetricsPoll(){
  if (!monitorEnabled) return;
  try{ if (typeof stopMetricsPoll==='function') try{ if (typeof stopMetricsPoll==='function') stopMetricsPoll(); }catch(e){} }catch(e){}
  metricsPoll = setInterval(function(){
    try{
      jsonFetch('/api/metrics').then(function(m){
        lastMetrics = m;
        if (m && m.ok===false){
          try{ var ds=document.getElementById('dockStats'); if (ds) ds.textContent='Monitor error'; }catch(e){}
          try{ var sub=document.getElementById('monSub'); if (sub) sub.textContent = String((m&&m.error)||'Monitor error'); }catch(e){}
          return;
        }
        updateMonitorFromMetrics(m);
      }).catch(function(_e){});
    }catch(e){}
  }, 2000);
}

function setBar(elId, pct){
  var el=document.getElementById(elId);
  if (!el) return;
  var p=Math.max(0, Math.min(100, pct||0));
  var fill=el.querySelector('div');
  if (fill) fill.style.width = p.toFixed(0) + '%';
  el.classList.remove('warn','bad');
  if (p >= 85) el.classList.add('bad');
  else if (p >= 60) el.classList.add('warn');
}

function fmtPct(x){
  if (x==null) return '-';
  return (Number(x).toFixed(1)) + '%';
}

function fmtTs(ts){
  if (!ts) return '-';
  try{
    var d=new Date(ts*1000);
    return d.toLocaleString();
  }catch(e){
    return String(ts);
  }
}

function updateDockFromMetrics(m){
  var el = document.getElementById('dockStats');
  if (!el) return;
  var b = (m && m.body) ? m.body : (m || {});
  var cpu = (b.cpu_pct!=null) ? Number(b.cpu_pct).toFixed(1)+'%' : '-';
  var rt = Number(b.ram_total_mb||0); var ru = Number(b.ram_used_mb||0);
  var rp = rt ? (ru/rt*100) : 0;
  var ram = rt ? rp.toFixed(1)+'%' : '-';
  var gpus = Array.isArray(b && b.gpus) ? b.gpus : (b && b.gpu ? [b.gpu] : []);
  var maxGpu = null;
  if (gpus.length){
    maxGpu = 0;
    for (var i=0;i<gpus.length;i++){
      var u = Number((gpus[i]||{}).util_gpu_pct||0);
      if (u > maxGpu) maxGpu = u;
    }
  }
  var gpu = (maxGpu==null) ? '-' : maxGpu.toFixed(1)+'%';
  el.textContent = 'CPU ' + cpu + ' • RAM ' + ram + ' • GPU ' + gpu;
}

function renderGpus(b){
  var el = document.getElementById('monGpus');
  if (!el) return;
  var gpus = Array.isArray(b && b.gpus) ? b.gpus : (b && b.gpu ? [b.gpu] : []);
  if (!gpus.length){
    el.innerHTML = '<div class="muted">No GPU data</div>';
    return;
  }

  el.innerHTML = gpus.slice(0,8).map(function(g,i){
    g = g || {};
    var idx = (g.index!=null) ? g.index : i;
    var util = Number(g.util_gpu_pct||0);
    var power = (g.power_w!=null) ? Number(g.power_w).toFixed(0)+'W' : null;
    var temp = (g.temp_c!=null) ? Number(g.temp_c).toFixed(0)+'C' : null;
    var right = [power, temp].filter(Boolean).join(' • ');
    var vt = Number(g.vram_total_mb||0);
    var vu = Number(g.vram_used_mb||0);
    var vp = vt ? (vu/vt*100) : 0;

    return "<div class='gpuCard'>"+
      "<div class='gpuHead'><div class='l'>GPU "+idx+"</div><div class='r'>"+(right||'')+"</div></div>"+
      "<div class='gpuRow'><div class='k'>Util</div><div class='v'>"+fmtPct(util)+"</div></div>"+
      "<div class='bar small' id='barGpu"+idx+"'><div></div></div>"+
      "<div class='gpuRow' style='margin-top:10px'><div class='k'>VRAM</div><div class='v'>"+(vt ? ((vu/1024).toFixed(1)+' / '+(vt/1024).toFixed(1)+' GB') : '-')+"</div></div>"+
      "<div class='bar small' id='barVram"+idx+"'><div></div></div>"+
    "</div>";
  }).join('');

  gpus.slice(0,8).forEach(function(g,i){
    g=g||{};
    var idx = (g.index!=null) ? g.index : i;
    var util = Number(g.util_gpu_pct||0);
    var vt = Number(g.vram_total_mb||0);
    var vu = Number(g.vram_used_mb||0);
    var vp = vt ? (vu/vt*100) : 0;
    setBar('barGpu'+idx, util);
    setBar('barVram'+idx, vp);
  });
}

function updateMonitorFromMetrics(m){
  var b = (m && m.body) ? m.body : (m || {});
  var cpu = Number(b.cpu_pct || 0);
  var c=document.getElementById('monCpu'); if(c) c.textContent = fmtPct(cpu);
  setBar('barCpu', cpu);

  var rt = Number(b.ram_total_mb || 0);
  var ru = Number(b.ram_used_mb || 0);
  var rp = rt ? (ru/rt*100) : 0;
  var r=document.getElementById('monRam'); if(r) r.textContent = rt ? (ru.toFixed(0) + ' / ' + rt.toFixed(0) + ' MB (' + rp.toFixed(1) + '%)') : '-';
  setBar('barRam', rp);
  renderGpus(b);

  var ts = b.ts ? fmtTs(b.ts) : '-';
  var sub=document.getElementById('monSub'); if(sub) sub.textContent = 'Tinybox time: ' + ts;
  updateDockFromMetrics(m);

  // processes
  try{
    var procs = Array.isArray(b.processes) ? b.processes : [];
    var pre=document.getElementById('monProc');
    if (pre){
      if (!procs.length) pre.textContent = '(no process data)';
      else {
        var lines=[];
        lines.push('PID     %CPU   %MEM   GPU   ELAPSED   COMMAND');
        lines.push('-----------------------------------------------');
        for (var i=0;i<procs.length;i++){
          var p=procs[i]||{};
          var pid=String(p.pid||'').padEnd(7,' ');
          var cpuS=(Number(p.cpu_pct||0).toFixed(1)+'').padStart(5,' ');
          var memS=(Number(p.mem_pct||0).toFixed(1)+'').padStart(5,' ');
          var gpuS=(p.gpu_mem_mb!=null?Number(p.gpu_mem_mb).toFixed(0)+'MB':'-').padStart(6,' ');
          var et=String(p.elapsed||'').padEnd(9,' ');
          var cmd=String(p.args||p.command||p.name||'');
          lines.push(pid+'  '+cpuS+'  '+memS+'  '+gpuS+'  '+et+'  '+cmd);
        }
        pre.textContent = lines.join(String.fromCharCode(10));
      }
    }
  }catch(e){}
}

function startMetricsStream(){
  if (!monitorEnabled) return;
  stopMetricsStream();
  try{ if (typeof stopMetricsPoll==='function') try{ if (typeof stopMetricsPoll==='function') stopMetricsPoll(); }catch(e){} }catch(e){}
  try{
    var ds=document.getElementById('dockStats'); if (ds) ds.textContent='Connecting…';
    metricsES = new EventSource('/api/metrics/stream');
    metricsES.onmessage = function(ev){
      try{
        var m = JSON.parse(ev.data || '{}');
        lastMetrics = m;
        if (m && m.ok===false){
          try{ var ds=document.getElementById('dockStats'); if (ds) ds.textContent='Monitor error'; }catch(e){}
          try{ var sub=document.getElementById('monSub'); if (sub) sub.textContent = String((m&&m.error)||'Monitor error'); }catch(e){}
          return;
        }
        updateMonitorFromMetrics(m);
      }catch(e){}
    };
    metricsES.onerror = function(_e){
      try{ var ds=document.getElementById('dockStats'); if (ds) ds.textContent='Monitor error'; }catch(e){}
      try{ var sub=document.getElementById('monSub'); if (sub) sub.textContent = 'Monitor error'; }catch(e){}
      try{ if (typeof startMetricsPoll==='function') try{ if (typeof startMetricsPoll==='function') startMetricsPoll(); }catch(e){} }catch(e){}
    };
  }catch(e){}
}

function setMonitorEnabled(on){
  monitorEnabled = !!on;
  saveMonitorPref(monitorEnabled);
  try{ document.documentElement.classList.toggle('monOn', !!monitorEnabled); }catch(e){}
  if (!monitorEnabled){
    stopMetricsStream();
    try{ if (typeof stopMetricsPoll==='function') try{ if (typeof stopMetricsPoll==='function') stopMetricsPoll(); }catch(e){} }catch(e){}
    try{ var ds=document.getElementById('dockStats'); if (ds) ds.textContent='Monitor off'; }catch(e){}
    return;
  }
  startMetricsStream();
}

function openMonitor(){
  if (!monitorEnabled) return;
  var b=document.getElementById('monitorBackdrop');
  var sh=document.getElementById('monitorSheet');
  if (b){ b.classList.remove('hide'); b.style.display='block'; }
  if (sh){ sh.classList.remove('hide'); sh.style.display='block'; }
  try{ document.body.classList.add('sheetOpen'); }catch(e){}
  startMetricsStream();
  if (lastMetrics) updateMonitorFromMetrics(lastMetrics);
}

function closeMonitor(){
  var b=document.getElementById('monitorBackdrop');
  var sh=document.getElementById('monitorSheet');
  if (b){ b.classList.add('hide'); b.style.display='none'; }
  if (sh){ sh.classList.add('hide'); sh.style.display='none'; }
  try{ document.body.classList.remove('sheetOpen'); }catch(e){}
}

function closeMonitorEv(ev){
  try{ if (ev && ev.stopPropagation) ev.stopPropagation(); }catch(e){}
  closeMonitor();
  return false;
}

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

try{ document.addEventListener('DOMContentLoaded', function(){ bindMonitorClose(); setMonitorEnabled(loadMonitorPref()); }); }catch(e){}
try{ bindMonitorClose(); setMonitorEnabled(loadMonitorPref()); }catch(e){}
</script>
  </body>
</html>'''
    html = (html
        .replace('__VOICES_BASE_CSS__', VOICES_BASE_CSS)
        .replace('__VOICE_NEW_EXTRA_CSS__', VOICE_NEW_EXTRA_CSS)
        .replace('__DEBUG_BANNER_HTML__', DEBUG_BANNER_HTML)
        .replace('__DEBUG_BANNER_BOOT_JS__', DEBUG_BANNER_BOOT_JS)
        .replace('__BUILD__', str(build))
    )
    return html
@app.get('/todo', response_class=HTMLResponse)
def todo_page(request: Request, response: Response):
    response.headers['Cache-Control'] = 'no-store'

    items = []
    err = ''
    try:
        conn = db_connect()
        try:
            db_init(conn)
            items = list_todos_db(conn, limit=800)
        finally:
            conn.close()
    except Exception as e:
        err = f"db_failed: {type(e).__name__}: {e}"

    show_arch = False
    try:
        qp = dict(request.query_params)
        if (qp.get('arch') == '1') or (qp.get('archived') == '1'):
            show_arch = True
    except Exception:
        pass

    # Hide archived by default
    if not show_arch:
        items = [it for it in items if not it.get('archived')]

    def esc(x: str) -> str:
        return pyhtml.escape(str(x or ''))

    def fmt_ts(ts: Any) -> str:
        try:
            v = int(ts)
        except Exception:
            return ''
        if v <= 0:
            return ''
        try:
            # Server-local time. (Good enough for internal TODO display.)
            return datetime.fromtimestamp(v).strftime('%Y-%m-%d %H:%M')
        except Exception:
            return ''

    # Group by category
    groups: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for it in items:
        cat = (it.get('category') or '').strip() or 'General'
        if cat not in groups:
            groups[cat] = []
            order.append(cat)
        groups[cat].append(it)

    # Render rows with stable data-cat and a dedicated count span (JS updates counts live)
    body_parts: list[str] = []
    if err:
        body_parts.append(f"<div class='err'>{esc(err)}</div>")

    for cat in order:
        its = groups.get(cat, [])
        done_n = 0
        for it in its:
            st = (it.get('status') or 'open').lower()
            if st != 'open':
                done_n += 1
        total_n = len(its)
        cat_esc = esc(cat)
        body_parts.append(
            "<div class='catHead' data-cat='" + cat_esc + "'>"
            + "<div class='catTitle'>" + cat_esc + "</div>"
            + "<div class='catCount'>(<span class='done'>" + str(done_n) + "</span>/<span class='total'>" + str(total_n) + "</span>)</div>"
            + "</div>"
        )

        for it in its:
            st = (it.get('status') or 'open').lower()
            tid = it.get('id')
            txt = esc(it.get('text') or '')
            checked = 'checked' if st != 'open' else ''
            hi_cls = ' hi' if bool(it.get('highlighted')) else ''
            created_s = fmt_ts(it.get('created_at'))
            updated_s = fmt_ts(it.get('updated_at'))
            meta_parts = []
            if created_s:
                meta_parts.append('created ' + esc(created_s))
            if updated_s and updated_s != created_s:
                meta_parts.append('updated ' + esc(updated_s))
            meta_html = "<div class='todoMeta'>" + " • ".join(meta_parts) + "</div>" if meta_parts else ""
            # If id is missing, render as plain text
            if tid is None:
                box = '☑' if checked else '☐'
                body_parts.append(f"<div class='todoPlain'>{box} {txt}</div>")
                continue

            # Category is on the container; JS uses it to update counters.
            body_parts.append(
                "<div class='todoItem" + hi_cls + "' data-cat='" + cat_esc + "' data-id='" + str(int(tid)) + "'>"
                + "<div class='todoSwipe'><div class='todoSwipeInner'>"
                + "<label class='todoMain'>"
                + "<input type='checkbox' data-id='" + str(int(tid)) + "' " + checked + " onchange='onTodoToggle(this)' />"
                + "<button class='todoHiBtn' type='button' onclick=\"toggleHighlight(" + str(int(tid)) + ")\" title=\"Highlight\">#" + str(int(tid)) + "</button>"
                + "<div class='todoTextWrap'>"
                + "<div class='todoText'>" + txt + "</div>"
                + meta_html
                + "</div>"
                + "</label>"
                + "<div class='todoKill'><button class='todoDelBtn' type='button' onclick=\"try{event&&event.stopPropagation&&event.stopPropagation();}catch(e){} deleteTodo(" + str(int(tid)) + "); return false;\" ontouchend=\"try{event&&event.stopPropagation&&event.stopPropagation();}catch(e){} deleteTodo(" + str(int(tid)) + "); return false;\">Delete</button></div>"
                + "</div></div>"
                + "</div>"
            )

    body_html = "\n".join(body_parts) if body_parts else "<div class='muted'>No TODO items yet.</div>"

    arch_checked = 'checked' if show_arch else ''

    html = '''<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>StoryForge - TODO</title>
  <style>__TODO_BASE_CSS__</style>
</head>
<body>
  <div class="navBar">
    <div class="top">
      <div>
        <div class="brandRow"><h1><a class='brandLink' href='/'>StoryForge</a></h1><div class="pageName">TODO</div></div>
        <div class="muted">Internal tracker (check/uncheck requires login).</div>
      </div>
      <div class="right">
        <a href="/#tab-jobs"><button class="secondary" type="button">Back</button></a>
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

  <div class="bar">
    <div class="muted"></div>
    <div class="right">
      <div class="muted" style="font-weight:950">Archived</div>
      <label class="switch" aria-label="Toggle archived">
        <input id="archToggle" type="checkbox" __ARCH_CHECKED__ onchange="toggleArchived(this.checked)" />
        <span class="slider"></span>
      </label>
      <button class="secondary" type="button" onclick="archiveDone()">Archive done</button>
      <button class="secondary" type="button" onclick="clearHighlights()">Clear highlights</button>
    </div>
  </div>

  <div class="card">__BODY_HTML__</div>

<script>
function toggleArchived(on){
  try{ window.location.href = on ? '/todo?arch=1' : '/todo'; }catch(e){}
}

function updateCatCount(cat){
  try{
    var head = document.querySelector(".catHead[data-cat='"+cat+"']");
    if (!head) return;
    var items = document.querySelectorAll(".todoItem[data-cat='"+cat+"'] input[type=checkbox]");
    var done = 0; var total = items.length;
    for (var i=0;i<items.length;i++){ if (items[i].checked) done++; }
    var d = head.querySelector('span.done');
    var t = head.querySelector('span.total');
    if (d) d.textContent = String(done);
    if (t) t.textContent = String(total);
  }catch(e){}
}

function onTodoToggle(cb){
  try{
    var id = cb.getAttribute('data-id');
    var wrap = cb.closest ? cb.closest('.todoItem') : null;
    var cat = wrap ? (wrap.getAttribute('data-cat') || '') : '';
    if (cat) updateCatCount(cat);

    var checked = !!cb.checked;
    var url = checked ? ('/api/todos/'+id+'/done_auth') : ('/api/todos/'+id+'/open_auth');
    var xhr = new XMLHttpRequest();
    xhr.open('POST', url, true);
    xhr.withCredentials = true;
    xhr.setRequestHeader('Content-Type','application/json');
    xhr.onreadystatechange = function(){
      if (xhr.readyState===4){
        if (xhr.status!==200){
          // revert
          try{ cb.checked = !checked; }catch(e){}
          if (cat) updateCatCount(cat);
        }
      }
    };
    xhr.send('{}');
  }catch(e){}
}

function toggleHighlight(id){
  try{
    var url = '/api/todos/' + encodeURIComponent(String(id)) + '/toggle_highlight_auth';
    var xhr = new XMLHttpRequest();
    xhr.open('POST', url, true);
    xhr.withCredentials = true;
    xhr.setRequestHeader('Content-Type','application/json');
    xhr.onreadystatechange = function(){
      if (xhr.readyState===4){
        if (xhr.status===200){
          try{
            var j = JSON.parse(xhr.responseText||'{}');
            if (j && j.ok){
              var el = document.querySelector(".todoItem[data-id='"+String(id)+"']");
              if (el){
                if (j.highlighted) el.classList.add('hi');
                else el.classList.remove('hi');
              }
              return;
            }
          }catch(e){}
        }
      }
    };
    xhr.send('{}');
  }catch(e){}
}

function deleteTodo(id){
  if (!confirm('Delete this todo?')) return;
  try{
    var url = '/api/todos/' + encodeURIComponent(String(id)) + '/delete_auth';
    var xhr = new XMLHttpRequest();
    xhr.open('POST', url, true);
    xhr.withCredentials = true;
    xhr.setRequestHeader('Content-Type','application/json');
    xhr.onreadystatechange = function(){
      if (xhr.readyState===4){
        if (xhr.status===200){
          try{
            var j = JSON.parse(xhr.responseText||'{}');
            if (j && j.ok){
              try{
                var el = document.querySelector(".todoItem[data-id='"+String(id)+"']");
                if (el && el.parentNode) el.parentNode.removeChild(el);
              }catch(e){}
              try{ recomputeCounts(); }catch(e){}
              return;
            }
          }catch(e){}
        }
        alert('Delete failed');
      }
    };
    xhr.send('{}');
  }catch(e){ alert('Delete failed'); }
}


function clearHighlights(){
  try{
    var xhr=new XMLHttpRequest();
    xhr.open('POST','/api/todos/clear_highlights_auth',true);
    xhr.withCredentials = true;
    xhr.setRequestHeader('Content-Type','application/json');
    xhr.onreadystatechange=function(){
      if (xhr.readyState===4){
        if (xhr.status===200){
          try{
            var els=document.querySelectorAll('.todoItem.hi');
            for (var i=0;i<els.length;i++){ els[i].classList.remove('hi'); }
          }catch(e){}
        } else {
          alert('Clear highlights failed');
        }
      }
    };
    xhr.send('{}');
  }catch(e){ alert('Clear highlights failed'); }
}

function archiveDone(){
  if (!confirm('Archive all completed items?')) return;
  try{
    var xhr=new XMLHttpRequest();
    xhr.open('POST','/api/todos/archive_done_auth',true);
    xhr.withCredentials = true;
    xhr.setRequestHeader('Content-Type','application/json');
    xhr.onreadystatechange=function(){
      if (xhr.readyState===4){
        if (xhr.status===200){
          try{ location.reload(); }catch(e){}
        } else {
          alert('Archive failed');
        }
      }
    };
    xhr.send('{}');
  }catch(e){}
}
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
  

<script>
let metricsES = null;
let monitorEnabled = true;
let lastMetrics = null;

function loadMonitorPref(){
  try{
    var v = localStorage.getItem('sf_monitor_enabled');
    if (v === null) return true;
    return v === '1';
  }catch(e){
    return true;
  }
}

function saveMonitorPref(on){
  try{ localStorage.setItem('sf_monitor_enabled', on ? '1' : '0'); }catch(e){}
}

function stopMetricsStream(){
  if (metricsES){
    try{ metricsES.close(); }catch(e){}
    metricsES = null;
  }
}

var metricsPoll = null;
function stopMetricsPoll(){
  if (metricsPoll){
    try{ clearInterval(metricsPoll); }catch(e){}
    metricsPoll = null;
  }
}

function startMetricsPoll(){
  if (!monitorEnabled) return;
  try{ if (typeof stopMetricsPoll==='function') try{ if (typeof stopMetricsPoll==='function') stopMetricsPoll(); }catch(e){} }catch(e){}
  metricsPoll = setInterval(function(){
    try{
      jsonFetch('/api/metrics').then(function(m){
        lastMetrics = m;
        if (m && m.ok===false){
          try{ var ds=document.getElementById('dockStats'); if (ds) ds.textContent='Monitor error'; }catch(e){}
          try{ var sub=document.getElementById('monSub'); if (sub) sub.textContent = String((m&&m.error)||'Monitor error'); }catch(e){}
          return;
        }
        updateMonitorFromMetrics(m);
      }).catch(function(_e){});
    }catch(e){}
  }, 2000);
}

function setBar(elId, pct){
  var el=document.getElementById(elId);
  if (!el) return;
  var p=Math.max(0, Math.min(100, pct||0));
  var fill=el.querySelector('div');
  if (fill) fill.style.width = p.toFixed(0) + '%';
  el.classList.remove('warn','bad');
  if (p >= 85) el.classList.add('bad');
  else if (p >= 60) el.classList.add('warn');
}

function fmtPct(x){
  if (x==null) return '-';
  return (Number(x).toFixed(1)) + '%';
}

function fmtTs(ts){
  if (!ts) return '-';
  try{
    var d=new Date(ts*1000);
    return d.toLocaleString();
  }catch(e){
    return String(ts);
  }
}

function updateDockFromMetrics(m){
  var el = document.getElementById('dockStats');
  if (!el) return;
  var b = (m && m.body) ? m.body : (m || {});
  var cpu = (b.cpu_pct!=null) ? Number(b.cpu_pct).toFixed(1)+'%' : '-';
  var rt = Number(b.ram_total_mb||0); var ru = Number(b.ram_used_mb||0);
  var rp = rt ? (ru/rt*100) : 0;
  var ram = rt ? rp.toFixed(1)+'%' : '-';
  var gpus = Array.isArray(b && b.gpus) ? b.gpus : (b && b.gpu ? [b.gpu] : []);
  var maxGpu = null;
  if (gpus.length){
    maxGpu = 0;
    for (var i=0;i<gpus.length;i++){
      var u = Number((gpus[i]||{}).util_gpu_pct||0);
      if (u > maxGpu) maxGpu = u;
    }
  }
  var gpu = (maxGpu==null) ? '-' : maxGpu.toFixed(1)+'%';
  el.textContent = 'CPU ' + cpu + ' • RAM ' + ram + ' • GPU ' + gpu;
}

function renderGpus(b){
  var el = document.getElementById('monGpus');
  if (!el) return;
  var gpus = Array.isArray(b && b.gpus) ? b.gpus : (b && b.gpu ? [b.gpu] : []);
  if (!gpus.length){
    el.innerHTML = '<div class="muted">No GPU data</div>';
    return;
  }

  el.innerHTML = gpus.slice(0,8).map(function(g,i){
    g = g || {};
    var idx = (g.index!=null) ? g.index : i;
    var util = Number(g.util_gpu_pct||0);
    var power = (g.power_w!=null) ? Number(g.power_w).toFixed(0)+'W' : null;
    var temp = (g.temp_c!=null) ? Number(g.temp_c).toFixed(0)+'C' : null;
    var right = [power, temp].filter(Boolean).join(' • ');
    var vt = Number(g.vram_total_mb||0);
    var vu = Number(g.vram_used_mb||0);
    var vp = vt ? (vu/vt*100) : 0;

    return "<div class='gpuCard'>"+
      "<div class='gpuHead'><div class='l'>GPU "+idx+"</div><div class='r'>"+(right||'')+"</div></div>"+
      "<div class='gpuRow'><div class='k'>Util</div><div class='v'>"+fmtPct(util)+"</div></div>"+
      "<div class='bar small' id='barGpu"+idx+"'><div></div></div>"+
      "<div class='gpuRow' style='margin-top:10px'><div class='k'>VRAM</div><div class='v'>"+(vt ? ((vu/1024).toFixed(1)+' / '+(vt/1024).toFixed(1)+' GB') : '-')+"</div></div>"+
      "<div class='bar small' id='barVram"+idx+"'><div></div></div>"+
    "</div>";
  }).join('');

  gpus.slice(0,8).forEach(function(g,i){
    g=g||{};
    var idx = (g.index!=null) ? g.index : i;
    var util = Number(g.util_gpu_pct||0);
    var vt = Number(g.vram_total_mb||0);
    var vu = Number(g.vram_used_mb||0);
    var vp = vt ? (vu/vt*100) : 0;
    setBar('barGpu'+idx, util);
    setBar('barVram'+idx, vp);
  });
}

function updateMonitorFromMetrics(m){
  var b = (m && m.body) ? m.body : (m || {});
  var cpu = Number(b.cpu_pct || 0);
  var c=document.getElementById('monCpu'); if(c) c.textContent = fmtPct(cpu);
  setBar('barCpu', cpu);

  var rt = Number(b.ram_total_mb || 0);
  var ru = Number(b.ram_used_mb || 0);
  var rp = rt ? (ru/rt*100) : 0;
  var r=document.getElementById('monRam'); if(r) r.textContent = rt ? (ru.toFixed(0) + ' / ' + rt.toFixed(0) + ' MB (' + rp.toFixed(1) + '%)') : '-';
  setBar('barRam', rp);
  renderGpus(b);

  var ts = b.ts ? fmtTs(b.ts) : '-';
  var sub=document.getElementById('monSub'); if(sub) sub.textContent = 'Tinybox time: ' + ts;
  updateDockFromMetrics(m);

  // processes
  try{
    var procs = Array.isArray(b.processes) ? b.processes : [];
    var pre=document.getElementById('monProc');
    if (pre){
      if (!procs.length) pre.textContent = '(no process data)';
      else {
        var lines=[];
        lines.push('PID     %CPU   %MEM   GPU   ELAPSED   COMMAND');
        lines.push('-----------------------------------------------');
        for (var i=0;i<procs.length;i++){
          var p=procs[i]||{};
          var pid=String(p.pid||'').padEnd(7,' ');
          var cpuS=(Number(p.cpu_pct||0).toFixed(1)+'').padStart(5,' ');
          var memS=(Number(p.mem_pct||0).toFixed(1)+'').padStart(5,' ');
          var gpuS=(p.gpu_mem_mb!=null?Number(p.gpu_mem_mb).toFixed(0)+'MB':'-').padStart(6,' ');
          var et=String(p.elapsed||'').padEnd(9,' ');
          var cmd=String(p.args||p.command||p.name||'');
          lines.push(pid+'  '+cpuS+'  '+memS+'  '+gpuS+'  '+et+'  '+cmd);
        }
        pre.textContent = lines.join(String.fromCharCode(10));
      }
    }
  }catch(e){}
}

function startMetricsStream(){
  if (!monitorEnabled) return;
  stopMetricsStream();
  try{ if (typeof stopMetricsPoll==='function') try{ if (typeof stopMetricsPoll==='function') stopMetricsPoll(); }catch(e){} }catch(e){}
  try{
    var ds=document.getElementById('dockStats'); if (ds) ds.textContent='Connecting…';
    metricsES = new EventSource('/api/metrics/stream');
    metricsES.onmessage = function(ev){
      try{
        var m = JSON.parse(ev.data || '{}');
        lastMetrics = m;
        if (m && m.ok===false){
          try{ var ds=document.getElementById('dockStats'); if (ds) ds.textContent='Monitor error'; }catch(e){}
          try{ var sub=document.getElementById('monSub'); if (sub) sub.textContent = String((m&&m.error)||'Monitor error'); }catch(e){}
          return;
        }
        updateMonitorFromMetrics(m);
      }catch(e){}
    };
    metricsES.onerror = function(_e){
      try{ var ds=document.getElementById('dockStats'); if (ds) ds.textContent='Monitor error'; }catch(e){}
      try{ var sub=document.getElementById('monSub'); if (sub) sub.textContent = 'Monitor error'; }catch(e){}
      try{ if (typeof startMetricsPoll==='function') try{ if (typeof startMetricsPoll==='function') startMetricsPoll(); }catch(e){} }catch(e){}
    };
  }catch(e){}
}

function setMonitorEnabled(on){
  monitorEnabled = !!on;
  saveMonitorPref(monitorEnabled);
  try{ document.documentElement.classList.toggle('monOn', !!monitorEnabled); }catch(e){}
  if (!monitorEnabled){
    stopMetricsStream();
    try{ if (typeof stopMetricsPoll==='function') try{ if (typeof stopMetricsPoll==='function') stopMetricsPoll(); }catch(e){} }catch(e){}
    try{ var ds=document.getElementById('dockStats'); if (ds) ds.textContent='Monitor off'; }catch(e){}
    return;
  }
  startMetricsStream();
}

function openMonitor(){
  if (!monitorEnabled) return;
  var b=document.getElementById('monitorBackdrop');
  var sh=document.getElementById('monitorSheet');
  if (b){ b.classList.remove('hide'); b.style.display='block'; }
  if (sh){ sh.classList.remove('hide'); sh.style.display='block'; }
  try{ document.body.classList.add('sheetOpen'); }catch(e){}
  startMetricsStream();
  if (lastMetrics) updateMonitorFromMetrics(lastMetrics);
}

function closeMonitor(){
  var b=document.getElementById('monitorBackdrop');
  var sh=document.getElementById('monitorSheet');
  if (b){ b.classList.add('hide'); b.style.display='none'; }
  if (sh){ sh.classList.add('hide'); sh.style.display='none'; }
  try{ document.body.classList.remove('sheetOpen'); }catch(e){}
}

function closeMonitorEv(ev){
  try{ if (ev && ev.stopPropagation) ev.stopPropagation(); }catch(e){}
  closeMonitor();
  return false;
}

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

try{ document.addEventListener('DOMContentLoaded', function(){ bindMonitorClose(); setMonitorEnabled(loadMonitorPref()); }); }catch(e){}
try{ bindMonitorClose(); setMonitorEnabled(loadMonitorPref()); }catch(e){}
</script>
  </body>
</html>'''

    html = html.replace('__BODY_HTML__', body_html).replace('__ARCH_CHECKED__', arch_checked)
    html = html.replace('__TODO_BASE_CSS__', TODO_BASE_CSS)
    return html



@app.post('/api/todos')
def api_todos_add(request: Request, payload: dict = Body(default={})):
    err = _todo_api_check(request)
    if err == 'disabled':
        raise HTTPException(status_code=503, detail='todo api disabled')
    if err:
        raise HTTPException(status_code=403, detail='forbidden')

    text = (payload or {}).get('text') or ''
    category = (payload or {}).get('category') or ''
    status = (payload or {}).get('status') or 'open'

    if not str(text).strip():
        raise HTTPException(status_code=400, detail='text required')

    conn = db_connect()
    try:
        db_init(conn)
        tid = add_todo_db(conn, text=str(text).strip(), status=str(status or 'open'), category=str(category or '').strip())
        return {'ok': True, 'id': tid}
    finally:
        conn.close()




@app.post('/api/todos/{todo_id}/done_auth')
def api_todos_done_auth(todo_id: int):
    # Requires passphrase session auth (middleware).
    conn = db_connect()
    try:
        db_init(conn)
        set_todo_status_db(conn, todo_id=int(todo_id), status='done')
        return {'ok': True}
    finally:
        conn.close()


@app.post('/api/todos/{todo_id}/open_auth')
def api_todos_open_auth(todo_id: int):
    conn = db_connect()
    try:
        db_init(conn)
        set_todo_status_db(conn, todo_id=int(todo_id), status='open')
        return {'ok': True}
    finally:
        conn.close()
@app.post('/api/todos/{todo_id}/done')
def api_todos_done(todo_id: int, request: Request):
    err = _todo_api_check(request)
    if err == 'disabled':
        raise HTTPException(status_code=503, detail='todo api disabled')
    if err:
        raise HTTPException(status_code=403, detail='forbidden')

    conn = db_connect()
    try:
        db_init(conn)
        set_todo_status_db(conn, todo_id=int(todo_id), status='done')
        return {'ok': True}
    finally:
        conn.close()

@app.post('/api/todos/{todo_id}/delete_auth')
def api_todos_delete_auth(todo_id: int):
    # Requires passphrase session auth (middleware).
    conn = db_connect()
    try:
        db_init(conn)
        from .todos_db import delete_todo_db
        ok = delete_todo_db(conn, todo_id=int(todo_id))
        return {'ok': bool(ok)}
    finally:
        conn.close()

@app.post('/api/todos/{todo_id}/toggle_highlight_auth')
def api_todos_toggle_highlight_auth(todo_id: int):
    conn = db_connect()
    try:
        db_init(conn)
        from .todos_db import toggle_todo_highlight_db
        v = toggle_todo_highlight_db(conn, todo_id=int(todo_id))
        return {'ok': True, 'highlighted': bool(v)}
    finally:
        conn.close()




@app.post('/api/todos/{todo_id}/open')
def api_todos_open(todo_id: int, request: Request):
    err = _todo_api_check(request)
    if err == 'disabled':
        raise HTTPException(status_code=503, detail='todo api disabled')
    if err:
        raise HTTPException(status_code=403, detail='forbidden')

    conn = db_connect()
    try:
        db_init(conn)
        set_todo_status_db(conn, todo_id=int(todo_id), status='open')
        return {'ok': True}
    finally:
        conn.close()

@app.post('/api/todos/{todo_id}/delete')
def api_todos_delete(todo_id: int, request: Request):
    err = _todo_api_check(request)
    if err == 'disabled':
        raise HTTPException(status_code=503, detail='todo api disabled')
    if err:
        raise HTTPException(status_code=403, detail='forbidden')

    conn = db_connect()
    try:
        db_init(conn)
        from .todos_db import delete_todo_db
        ok = delete_todo_db(conn, todo_id=int(todo_id))
        return {'ok': bool(ok)}
    finally:
        conn.close()

@app.post('/api/todos/{todo_id}/highlight')
def api_todos_highlight(todo_id: int, request: Request):
    err = _todo_api_check(request)
    if err == 'disabled':
        raise HTTPException(status_code=503, detail='todo api disabled')
    if err:
        raise HTTPException(status_code=403, detail='forbidden')

    conn = db_connect()
    try:
        db_init(conn)
        from .todos_db import set_todo_highlight_db
        set_todo_highlight_db(conn, todo_id=int(todo_id), highlighted=True)
        return {'ok': True}
    finally:
        conn.close()

@app.post('/api/todos/{todo_id}/unhighlight')
def api_todos_unhighlight(todo_id: int, request: Request):
    err = _todo_api_check(request)
    if err == 'disabled':
        raise HTTPException(status_code=503, detail='todo api disabled')
    if err:
        raise HTTPException(status_code=403, detail='forbidden')

    conn = db_connect()
    try:
        db_init(conn)
        from .todos_db import set_todo_highlight_db
        set_todo_highlight_db(conn, todo_id=int(todo_id), highlighted=False)
        return {'ok': True}
    finally:
        conn.close()

@app.post('/api/todos/clear_highlights')
def api_todos_clear_highlights(request: Request):
    err = _todo_api_check(request)
    if err == 'disabled':
        raise HTTPException(status_code=503, detail='todo api disabled')
    if err:
        raise HTTPException(status_code=403, detail='forbidden')

    conn = db_connect()
    try:
        db_init(conn)
        from .todos_db import clear_todo_highlights_db
        n = clear_todo_highlights_db(conn)
        return {'ok': True, 'cleared': int(n)}
    finally:
        conn.close()







@app.post('/api/todos/clear_highlights_auth')
def api_todos_clear_highlights_auth():
    conn = db_connect()
    try:
        db_init(conn)
        from .todos_db import clear_todo_highlights_db
        n = clear_todo_highlights_db(conn)
        return {'ok': True, 'cleared': int(n)}
    finally:
        conn.close()
@app.post('/api/todos/archive_done_auth')
def api_todos_archive_done_auth():
    conn = db_connect()
    try:
        db_init(conn)
        n = archive_done_todos_db(conn)
        return {'ok': True, 'archived': n}
    finally:
        conn.close()
@app.get('/api/ping')
def api_ping():
    r = requests.get(GATEWAY_BASE + '/ping', timeout=4)
    r.raise_for_status()
    return r.json()


@app.get('/api/metrics')
def api_metrics():
    try:
        # Keep this endpoint snappy; it is polled by the UI.
        return _get('/v1/metrics', timeout_s=12.0)
    except HTTPException as e:
        return {"ok": False, "error": e.detail}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__}


@app.get('/api/metrics/stream')
def api_metrics_stream():
    def gen():
        # Keep-alive + periodic samples. EventSource will auto-reconnect.
        while True:
            try:
                m = _get('/v1/metrics', timeout_s=12.0)
                data = json.dumps(m, separators=(',', ':'))
                yield f"data: {data}\n\n"
            except Exception as e:
                # Don't leak secrets; emit a small error payload.
                yield f"data: {json.dumps({'ok': False, 'error': f'metrics_failed:{type(e).__name__}'})}\n\n"
            time.sleep(2.0)

    headers = {
        'Cache-Control': 'no-store',
        'X-Accel-Buffering': 'no',
    }
    return StreamingResponse(gen(), media_type='text/event-stream', headers=headers)


@app.get('/api/jobs/stream')
def api_jobs_stream():
    def gen():
        # Live jobs stream for progress bars.
        while True:
            try:
                conn = db_connect()
                try:
                    db_init(conn)
                    jobs = db_list_jobs(conn, limit=60)
                finally:
                    conn.close()
                data = json.dumps({'ok': True, 'jobs': jobs}, separators=(',', ':'))
                yield f"data: {data}\n\n"
            except Exception:
                yield f"data: {json.dumps({'ok': False, 'error': 'jobs_failed'})}\n\n"
            time.sleep(1.5)

    headers = {
        'Cache-Control': 'no-store',
        'X-Accel-Buffering': 'no',
    }
    return StreamingResponse(gen(), media_type='text/event-stream', headers=headers)


def _require_job_token(request: Request) -> None:
    if not SF_JOB_TOKEN:
        raise HTTPException(status_code=500, detail='SF_JOB_TOKEN not configured')
    tok = (request.headers.get('x-sf-job-token') or '').strip()
    if not tok or tok != SF_JOB_TOKEN:
        raise HTTPException(status_code=401, detail='unauthorized')


@app.post('/api/jobs/update')
def api_jobs_update(request: Request, payload: dict[str, Any] = Body(default={})):  # noqa: B008
    """Update a job record (used by external workers like Tinybox).

    Auth: x-sf-job-token
    Payload supports: id (required), title, state, started_at, finished_at,
    total_segments, segments_done, mp3_url, sfml_url.
    """
    _require_job_token(request)
    try:
        job_id = str((payload or {}).get('id') or '').strip()
        if not job_id:
            return {'ok': False, 'error': 'missing_id'}

        fields = {
            'title': payload.get('title'),
            'state': payload.get('state'),
            'started_at': payload.get('started_at'),
            'finished_at': payload.get('finished_at'),
            'total_segments': payload.get('total_segments'),
            'segments_done': payload.get('segments_done'),
            'mp3_url': payload.get('mp3_url'),
            'sfml_url': payload.get('sfml_url'),
        }

        conn = db_connect()
        try:
            db_init(conn)
            cur = conn.cursor()
            # Ensure exists
            cur.execute(
                "INSERT INTO jobs (id,title,state,created_at) VALUES (%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING",
                (job_id, str(fields.get('title') or job_id), str(fields.get('state') or 'running'), int(time.time())),
            )
            # Patch
            sets = []
            vals = []
            for k, v in fields.items():
                if v is None:
                    continue
                sets.append(f"{k}=%s")
                if k in ('started_at', 'finished_at', 'total_segments', 'segments_done'):
                    try:
                        vals.append(int(v))
                    except Exception:
                        vals.append(0)
                else:
                    vals.append(str(v))
            if sets:
                vals.append(job_id)
                cur.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id=%s", tuple(vals))
            conn.commit()
        finally:
            try:
                conn.close()
            except Exception:
                pass

        return {'ok': True}
    except HTTPException:
        raise
    except Exception as e:
        return {'ok': False, 'error': f'update_failed: {type(e).__name__}: {e}'}






@app.get('/api/build')
def api_build():
    """Public build/version endpoint for non-blocking deploy UX."""
    return {'ok': True, 'build': int(APP_BUILD)}


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

        # Auto-generate a playable sample URL when possible (xtts + URL voice_ref).
        if (not sample_url) and engine and voice_ref and sample_text:
            try:
                # Reuse /api/tts behavior (Tinybox synth -> Spaces upload -> public URL)
                tts_resp = api_tts({'engine': engine, 'voice': voice_ref, 'text': sample_text, 'upload': True})
                if isinstance(tts_resp, dict):
                    body = tts_resp.get('body') if 'body' in tts_resp else None
                    if isinstance(body, dict) and body.get('ok') and body.get('url'):
                        sample_url = str(body.get('url') or '')
            except Exception:
                pass

        conn = db_connect()
        try:
            db_init(conn)
            upsert_voice_db(conn, voice_id, engine, voice_ref, display_name, enabled, sample_text, sample_url)
        finally:
            conn.close()

        # After saving to roster, kick off metadata analysis (best-effort, async).
        try:
            job_id = "voice_meta_" + voice_id + "_" + str(int(time.time()))
            meta = {
                'voice_id': voice_id,
                'engine': engine,
                'voice_ref': voice_ref,
                'sample_text': sample_text,
                'sample_url': sample_url,
                'tortoise_voice': str(payload.get('tortoise_voice') or '').strip(),
                'tortoise_gender': str(payload.get('tortoise_gender') or '').strip(),
                'tortoise_preset': str(payload.get('tortoise_preset') or '').strip(),
            }
            _job_patch(
                job_id,
                {
                    'title': f"Voice metadata ({display_name})",
                    'kind': 'voice_meta',
                    'meta_json': json.dumps(meta, separators=(',', ':')),
                    'state': 'running',
                    'started_at': int(time.time()),
                    'finished_at': 0,
                    'total_segments': 2,
                    'segments_done': 0,
                },
            )

            def worker():
                try:
                    _job_patch(job_id, {'segments_done': 1})
                    res = analyze_voice_metadata(
                        voice_id=voice_id,
                        engine=engine,
                        voice_ref=voice_ref,
                        sample_text=sample_text,
                        sample_url=sample_url,
                        tortoise_voice=str(payload.get('tortoise_voice') or '').strip(),
                        tortoise_gender=str(payload.get('tortoise_gender') or '').strip(),
                        tortoise_preset=str(payload.get('tortoise_preset') or '').strip(),
                        gateway_base=GATEWAY_BASE,
                        headers=_h(),
                    )
                    if not (isinstance(res, dict) and res.get('ok')):
                        msg = str((res or {}).get('error') or 'meta_failed')
                        det2 = (res or {}).get('detail')
                        if det2:
                            msg = msg + ' :: ' + str(det2)[:240]
                        raise RuntimeError(msg)
                    _job_patch(job_id, {'segments_done': 2, 'state': 'completed', 'finished_at': int(time.time())})
                except Exception as e:
                    det = ''
                    try:
                        import traceback

                        det = traceback.format_exc(limit=6)
                    except Exception:
                        det = ''
                    _job_patch(
                        job_id,
                        {
                            'state': 'failed',
                            'finished_at': int(time.time()),
                            'segments_done': 0,
                            'sfml_url': (f"error: {type(e).__name__}: {str(e)[:200]}" + ("\n" + det[:1400] if det else '')),
                        },
                    )

            import threading

            threading.Thread(target=worker, daemon=True).start()
        except Exception:
            pass

        return {'ok': True, 'sample_url': sample_url}
    except Exception as e:
        return {'ok': False, 'error': f'create_failed: {type(e).__name__}: {e}'}


@app.post('/api/voices/{voice_id}/analyze_metadata')
def api_voices_analyze_metadata(voice_id: str):
    """Kick off metadata analysis for an existing roster voice."""
    try:
        voice_id = validate_voice_id(voice_id)
        conn = db_connect()
        try:
            db_init(conn)
            v = get_voice_db(conn, voice_id)
        finally:
            conn.close()

        engine = str(v.get('engine') or '').strip()
        voice_ref = str(v.get('voice_ref') or '').strip()
        sample_text = str(v.get('sample_text') or '').strip()
        sample_url = str(v.get('sample_url') or '').strip()
        display_name = str(v.get('display_name') or voice_id)

        if not engine or not voice_ref or not sample_url:
            return {'ok': False, 'error': 'missing_required_fields'}

        job_id = "voice_meta_" + voice_id + "_" + str(int(time.time()))
        meta = {
            'voice_id': voice_id,
            'engine': engine,
            'voice_ref': voice_ref,
            'sample_text': sample_text,
            'sample_url': sample_url,
        }
        _job_patch(
            job_id,
            {
                'title': f"Voice metadata ({display_name})",
                'kind': 'voice_meta',
                'meta_json': json.dumps(meta, separators=(',', ':')),
                'state': 'running',
                'started_at': int(time.time()),
                'finished_at': 0,
                'total_segments': 2,
                'segments_done': 0,
            },
        )

        def worker():
            try:
                _job_patch(job_id, {'segments_done': 1})
                res = analyze_voice_metadata(
                    voice_id=voice_id,
                    engine=engine,
                    voice_ref=voice_ref,
                    sample_text=sample_text,
                    sample_url=sample_url,
                    gateway_base=GATEWAY_BASE,
                    headers=_h(),
                )
                if not (isinstance(res, dict) and res.get('ok')):
                    msg = str((res or {}).get('error') or 'meta_failed')
                    det2 = (res or {}).get('detail')
                    if det2:
                        msg = msg + ' :: ' + str(det2)[:240]
                    raise RuntimeError(msg)
                _job_patch(job_id, {'segments_done': 2, 'state': 'completed', 'finished_at': int(time.time())})
            except Exception as e:
                det = ''
                try:
                    import traceback

                    det = traceback.format_exc(limit=6)
                except Exception:
                    det = ''
                _job_patch(
                    job_id,
                    {
                        'state': 'failed',
                        'finished_at': int(time.time()),
                        'segments_done': 0,
                        'sfml_url': (f"error: {type(e).__name__}: {str(e)[:200]}" + ("\n" + det[:1400] if det else '')),
                    },
                )

        import threading

        threading.Thread(target=worker, daemon=True).start()
        return {'ok': True, 'job_id': job_id}
    except Exception as e:
        return {'ok': False, 'error': f'analyze_failed: {type(e).__name__}: {e}'}


@app.post('/api/production/suggest_casting')
def api_production_suggest_casting(payload: dict[str, Any] = Body(default={})):  # noqa: B008
    """Suggest a voice roster assignment for each character in a story."""
    try:
        import re
        story_id = str((payload or {}).get('story_id') or '').strip()
        if not story_id:
            return {'ok': False, 'error': 'missing_story_id'}

        conn = db_connect()
        try:
            db_init(conn)
            st = get_story_db(conn, story_id)
            voices = list_voices_db(conn, limit=500)
        finally:
            conn.close()

        chars = list(st.get('characters') or [])
        # ensure narrator present + first
        has_narr = any(str((c or {}).get('role') or '').lower() == 'narrator' or str((c or {}).get('name') or '').strip().lower() == 'narrator' for c in chars)
        if not has_narr:
            chars = ([{'name': 'Narrator', 'role': 'narrator', 'description': ''}] + chars)
        chars.sort(key=lambda c: (0 if str((c or {}).get('role') or '').lower() == 'narrator' or str((c or {}).get('name') or '').strip().lower() == 'narrator' else 1, str((c or {}).get('name') or '')))

        # Build compact voice roster summary
        vrows = []
        for v in voices:
            vid = str(v.get('id') or '')
            if not vid:
                continue
            dn = str(v.get('display_name') or vid)
            eng = str(v.get('engine') or '')
            vtj = str(v.get('voice_traits_json') or '').strip()
            traits = {}
            try:
                if vtj:
                    traits = json.loads(vtj).get('voice_traits') or {}
            except Exception:
                traits = {}
            vrows.append({
                'id': vid,
                'name': dn,
                'engine': eng,
                'gender': str(traits.get('gender') or 'unknown'),
                'age': str(traits.get('age') or 'unknown'),
                'pitch': str(traits.get('pitch') or 'unknown'),
                'tone': traits.get('tone') if isinstance(traits.get('tone'), list) else [],
                'ref': str(v.get('voice_ref') or ''),
            })

        # Prompt LLM
        prompt = {
            'task': 'Suggest voice casting from a roster for a story.',
            'story': {'id': story_id, 'title': (st.get('title') or story_id)},
            'characters': [{
                'name': str((c or {}).get('name') or ''),
                'role': str((c or {}).get('role') or ''),
                'description': str((c or {}).get('description') or ''),
                'voice_traits': (c or {}).get('voice_traits') if isinstance((c or {}).get('voice_traits'), dict) else {},
            } for c in chars],
            'roster': vrows,
            'rules': [
                'Return STRICT JSON only. No markdown.',
                'Output shape: {"assignments": [{"character":"Name","voice_id":"id","reason":"short"}] }',
                'Every character must have exactly one assignment.',
                'Prefer matching gender/age/pitch/tone when known, otherwise pick a distinct voice.',
                'Narrator must be included.',
            ],
        }

        req = {
            'model': 'google/gemma-2-9b-it',
            'messages': [{'role': 'user', 'content': 'Return ONLY strict JSON.\n\n' + json.dumps(prompt, separators=(',', ':'))}],
            'temperature': 0.3,
            'max_tokens': 700,
        }

        r = requests.post(GATEWAY_BASE + '/v1/llm', json=req, headers=_h(), timeout=120)
        r.raise_for_status()
        j = r.json()
        txt = ''
        try:
            ch0 = (((j or {}).get('choices') or [])[0] or {})
            msg = ch0.get('message') or {}
            txt = str(msg.get('content') or ch0.get('text') or '')
        except Exception:
            txt = ''
        txt = (txt or '').strip()
        if not txt:
            return {'ok': False, 'error': 'empty_llm_output'}

        # Extract JSON
        i0 = txt.find('{')
        i1 = txt.rfind('}')
        raw = txt[i0:i1+1] if i0 != -1 and i1 != -1 and i1 > i0 else txt
        raw = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", raw)
        raw = re.sub(r"```\s*$", "", raw).strip()
        raw = re.sub(r",\s*([}\]])", r"\1", raw)

        out = json.loads(raw)
        assigns = out.get('assignments') if isinstance(out, dict) else None
        if not isinstance(assigns, list):
            return {'ok': False, 'error': 'bad_llm_shape'}

        # return roster + characters for UI rendering
        return {'ok': True, 'suggestions': out, 'roster': vrows, 'characters': chars, 'story': {'id': story_id, 'title': (st.get('title') or story_id)}}
    except Exception as e:
        return {'ok': False, 'error': f'suggest_failed: {type(e).__name__}: {str(e)[:200]}'}


@app.get('/api/production/casting/{story_id}')
def api_production_casting_get(story_id: str):
    """Get saved casting (if any) for a story, plus roster for rendering."""
    try:
        story_id = str(story_id or '').strip()
        if not story_id:
            return {'ok': False, 'error': 'missing_story_id'}

        conn = db_connect()
        try:
            db_init(conn)
            voices = list_voices_db(conn, limit=500)

            # roster summary
            vrows = []
            for v in voices:
                vid = str(v.get('id') or '')
                if not vid:
                    continue
                dn = str(v.get('display_name') or vid)
                eng = str(v.get('engine') or '')
                vtj = str(v.get('voice_traits_json') or '').strip()
                traits = {}
                try:
                    if vtj:
                        traits = json.loads(vtj).get('voice_traits') or {}
                except Exception:
                    traits = {}
                vrows.append(
                    {
                        'id': vid,
                        'name': dn,
                        'engine': eng,
                        'gender': str(traits.get('gender') or 'unknown'),
                        'age': str(traits.get('age') or 'unknown'),
                        'pitch': str(traits.get('pitch') or 'unknown'),
                        'tone': traits.get('tone') if isinstance(traits.get('tone'), list) else [],
                        'ref': str(v.get('voice_ref') or ''),
                    }
                )

            cur = conn.cursor()
            cur.execute('SELECT casting, updated_at FROM sf_castings WHERE story_id=%s', (story_id,))
            row = cur.fetchone()
        finally:
            conn.close()

        if not row:
            return {'ok': True, 'saved': False, 'assignments': [], 'roster': vrows}

        casting = row[0] or {}
        assigns = []
        try:
            assigns = list((casting or {}).get('assignments') or [])
        except Exception:
            assigns = []
        return {'ok': True, 'saved': True, 'assignments': assigns, 'roster': vrows}
    except Exception as e:
        return {'ok': False, 'error': f'casting_get_failed: {type(e).__name__}: {str(e)[:200]}'}


@app.post('/api/production/sfml_generate')
def api_production_sfml_generate(payload: dict[str, Any] = Body(default={})):  # noqa: B008
    """Generate SFML (StoryForge Markup Language) from story + saved casting.

    SFML v0 directives:
      - scene id=<id> title="..."
      - say <character_id> voice=<voice_id>: <text>

    The output is plain text.
    """
    try:
        import re

        story_id = str((payload or {}).get('story_id') or '').strip()
        if not story_id:
            return {'ok': False, 'error': 'missing_story_id'}

        conn = db_connect()
        try:
            db_init(conn)
            st = get_story_db(conn, story_id)
            cur = conn.cursor()
            cur.execute('SELECT casting FROM sf_castings WHERE story_id=%s', (story_id,))
            row = cur.fetchone()
        finally:
            conn.close()

        if not row:
            return {'ok': False, 'error': 'casting_not_saved'}

        casting = row[0] or {}
        assigns = list((casting or {}).get('assignments') or [])
        if not assigns:
            return {'ok': False, 'error': 'empty_casting'}

        story_md = str(st.get('story_md') or '')
        title = str(st.get('title') or story_id)

        # Build a strict casting map (character -> voice_id)
        cmap = {}
        for a in assigns:
            try:
                ch = str((a or {}).get('character') or '').strip()
                vid = str((a or {}).get('voice_id') or '').strip()
                if ch and vid:
                    cmap[ch] = vid
            except Exception:
                pass

        # Ensure narrator exists in map
        if 'Narrator' in cmap and 'narrator' not in cmap:
            cmap['narrator'] = cmap['Narrator']
        if 'narrator' not in cmap:
            # best-effort: take any assignment whose character is narrator-ish
            for k, v in list(cmap.items()):
                if str(k).strip().lower() == 'narrator':
                    cmap['narrator'] = v
                    break

        prompt = {
            'format': 'SFML',
            'version': 0,
            'story': {'id': story_id, 'title': title, 'story_md': story_md},
            'casting_map': cmap,
            'rules': [
                'Output MUST be plain SFML text only. No markdown, no fences.',
                'Use only directives: scene, say.',
                'At least one scene.',
                'Every say line MUST include voice=<voice_id> from casting_map values.',
                'Narrator lines use character_id=narrator and voice=cmap["narrator"].',
                'Keep each say line to a single line; split long paragraphs into multiple say lines.',
                'Do not invent voice ids.',
                'Do not include JSON in the output.',
            ],
            'example': (
                '# SFML v0\n'
                'scene id=scene-1 title="Intro"\n'
                'say narrator voice=indigo-dawn: The lighthouse stood silent on the cliff.\n'
                'say maris voice=lunar-violet: I can hear the sea breathing below.\n'
            ),
        }

        req = {
            'model': 'google/gemma-2-9b-it',
            'messages': [
                {'role': 'user', 'content': 'Return ONLY SFML plain text.\n\n' + json.dumps(prompt, separators=(',', ':'))},
            ],
            'temperature': 0.3,
            'max_tokens': 1400,
        }

        r = requests.post(GATEWAY_BASE + '/v1/llm', json=req, headers=_h(), timeout=180)
        r.raise_for_status()
        j = r.json()
        txt = ''
        try:
            ch0 = (((j or {}).get('choices') or [])[0] or {})
            msg = ch0.get('message') or {}
            txt = str(msg.get('content') or ch0.get('text') or '')
        except Exception:
            txt = ''

        txt = (txt or '').strip()
        if not txt:
            return {'ok': False, 'error': 'empty_llm_output'}

        # Strip accidental markdown fences
        txt = re.sub(r'^```[a-zA-Z0-9_-]*\s*', '', txt).strip()
        txt = re.sub(r'```\s*$', '', txt).strip()

        # Cap size
        if len(txt) > 20000:
            txt = txt[:20000]

        return {'ok': True, 'sfml': txt}
    except Exception as e:
        return {'ok': False, 'error': f'sfml_generate_failed: {type(e).__name__}: {str(e)[:200]}'}


@app.post('/api/production/casting_save')
def api_production_casting_save(payload: dict[str, Any] = Body(default={})):  # noqa: B008
    """Save casting (character -> voice_id) for a story."""
    try:
        story_id = str((payload or {}).get('story_id') or '').strip()
        if not story_id:
            return {'ok': False, 'error': 'missing_story_id'}
        assigns = (payload or {}).get('assignments') or []
        if not isinstance(assigns, list) or not assigns:
            return {'ok': False, 'error': 'missing_assignments'}

        # Normalize
        norm = []
        for a in assigns:
            if not isinstance(a, dict):
                continue
            ch = str(a.get('character') or '').strip()
            vid = str(a.get('voice_id') or '').strip()
            if not ch or not vid:
                continue
            norm.append({'character': ch, 'voice_id': vid})
        if not norm:
            return {'ok': False, 'error': 'empty_assignments'}

        now = int(time.time())
        conn = db_connect()
        try:
            db_init(conn)
            cur = conn.cursor()
            cur.execute(
                """
INSERT INTO sf_castings (story_id, casting, created_at, updated_at)
VALUES (%s, %s::jsonb, %s, %s)
ON CONFLICT (story_id)
DO UPDATE SET casting=EXCLUDED.casting, updated_at=EXCLUDED.updated_at
""",
                (story_id, json.dumps({'assignments': norm}, separators=(',', ':')), now, now),
            )
            conn.commit()
        finally:
            conn.close()

        return {'ok': True}
    except Exception as e:
        return {'ok': False, 'error': f'casting_save_failed: {type(e).__name__}: {str(e)[:200]}'}


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
        deleted_keys: list[str] = []

        # Fetch voice first so we can delete any associated Spaces objects.
        conn = db_connect()
        try:
            db_init(conn)
            v = get_voice_db(conn, voice_id)
            delete_voice_db(conn, voice_id)
        finally:
            conn.close()

        # Best-effort delete related objects in Spaces.
        try:
            from .spaces_upload import delete_public_url

            for u in [
                (v or {}).get('sample_url') or '',
                (v or {}).get('voice_ref') or '',
            ]:
                try:
                    k = delete_public_url(str(u))
                    if k:
                        deleted_keys.append(k)
                except Exception:
                    pass
        except Exception:
            pass

        return {'ok': True, 'deleted_keys': deleted_keys}
    except Exception as e:
        return {'ok': False, 'error': f'delete_failed: {type(e).__name__}: {e}'}






@app.post('/api/voices/random_name')
def api_voices_random_name(payload: dict[str, Any] | None = None):
    # Generate a random voice display name (a color-ish name) via Tinybox LLM.
    try:
        payload = payload or {}
        prompt = (
            "Give a single creative color name suitable as a voice name. "
            "Examples: Midnight Teal, Ember Rose, Arctic Blue. "
            "Return ONLY the name, 1 to 3 words, letters and spaces only."
        )
        model = str(payload.get('model') or 'google/gemma-2-9b-it')
        req = {
            'model': model,
            'messages': [
                {'role': 'user', 'content': prompt},
            ],
            'temperature': float(payload.get('temperature') or 0.95),
            'max_tokens': int(payload.get('max_tokens') or 20),
        }
        r = requests.post(GATEWAY_BASE + '/v1/llm', json=req, headers=_h(), timeout=120)
        r.raise_for_status()
        j = r.json()
        if isinstance(j, dict) and j.get('ok') is False:
            raise RuntimeError(str(j.get('error') or 'llm_failed'))
        name = ''
        try:
            ch0 = (((j or {}).get('choices') or [])[0] or {})
            msg = ch0.get('message') or {}
            name = str(msg.get('content') or ch0.get('text') or '')
        except Exception:
            name = ''
        name = ' '.join(name.strip().split())
        # sanitize to letters/spaces only
        import re
        name = re.sub(r"[^A-Za-z ]+", "", name).strip()
        name = re.sub(r"\s+", " ", name).strip()
        if not name:
            raise RuntimeError('empty_name')
        words = name.split(' ')
        if len(words) > 3:
            name = ' '.join(words[:3]).strip()
        if len(name) > 32:
            name = name[:32].rsplit(' ', 1)[0].strip() or name[:32]
        return {'ok': True, 'name': name}
    except Exception as e:
        return {'ok': False, 'error': f'name_failed: {type(e).__name__}: {e}'}
@app.post('/api/voices/sample_text_random')
def api_voice_sample_text_random(payload: dict[str, Any] | None = None):
    """Generate a random sample text using the Tinybox LLM via gateway (/v1/llm)."""
    try:
        payload = payload or {}
        # Keep it short + TTS-friendly.
        # NOTE: our vLLM chat endpoint for Gemma rejects "system" role.
        # Put all instructions in the user message to stay compatible.
        import random

        themes = [
            "a confident tech product intro",
            "a cozy bedtime narrator line",
            "a fantasy story narrator line",
            "a dramatic audiobook hook",
            "a calm meditation instruction",
            "a playful cartoon announcement",
            "a serious documentary opener",
            "an enthusiastic sports commentary line",
            "a gentle nature description",
            "a witty one-liner",
            "a friendly podcast intro",
            "a mysterious noir narration",
        ]
        theme = random.choice(themes)
        nonce = os.urandom(3).hex()

        prompt = (
            "Write a short sample script for a text-to-speech voice demo. "
            "Generate 1-2 sentences (<= 220 characters) that sound natural when spoken aloud. "
            "Avoid numbers, URLs, and special characters. "
            "Return plain text only (no quotes, no markdown, no emojis). "
            f"Theme: {theme}. "
            f"Make it meaningfully different from typical 'sun/leaves/wind' samples. "
            f"Nonce: {nonce}."
        )
        model = str(payload.get('model') or 'google/gemma-2-9b-it')

        req = {
            'model': model,
            'messages': [
                {'role': 'user', 'content': prompt},
            ],
            'temperature': float(payload.get('temperature') or 1.1),
            'max_tokens': int(payload.get('max_tokens') or 90),
        }

        # First call to a cold model can take a while (download/compile).
        r = requests.post(GATEWAY_BASE + '/v1/llm', json=req, headers=_h(), timeout=120)
        r.raise_for_status()
        j = r.json()

        # Propagate structured gateway errors if present.
        if isinstance(j, dict) and j.get('ok') is False:
            raise RuntimeError(str(j.get('error') or 'llm_failed'))

        text = ''
        try:
            ch0 = (((j or {}).get('choices') or [])[0] or {})
            msg = ch0.get('message') or {}
            text = str(msg.get('content') or ch0.get('text') or '')
        except Exception:
            text = ''

        text = ' '.join(text.strip().split())
        if not text:
            # Include a tiny hint for debugging without dumping secrets.
            hint = ''
            try:
                if isinstance(j, dict):
                    hint = f" keys={sorted(list(j.keys()))[:8]}"
            except Exception:
                hint = ''
            raise RuntimeError('empty_llm_output' + hint)
        # hard cap
        if len(text) > 260:
            text = text[:260].rsplit(' ', 1)[0].strip() or text[:260]

        return {'ok': True, 'text': text}
    except Exception as e:
        return {'ok': False, 'error': f'sample_text_failed: {type(e).__name__}: {e}'}


@app.post('/api/voices/{voice_id}/sample')
def api_voice_sample(voice_id: str):
    try:
        voice_id = validate_voice_id(voice_id)
        conn = db_connect()
        try:
            db_init(conn)
            v = get_voice_db(conn, voice_id)
        finally:
            conn.close()

        engine = str(v.get('engine') or '')
        voice_ref = str(v.get('voice_ref') or '')
        text = str(v.get('sample_text') or '').strip() or f"Hello. This is {v.get('display_name') or voice_id}."

        # Use the Cloud /api/tts path so we always return a playable Spaces URL.
        tts_resp = api_tts({'engine': engine, 'voice': voice_ref, 'text': text, 'upload': True})
        body = tts_resp.get('body') if isinstance(tts_resp, dict) else None
        sample_url = ''
        if isinstance(body, dict) and body.get('ok') and body.get('url'):
            sample_url = str(body.get('url') or '')

        conn = db_connect()
        try:
            db_init(conn)
            upsert_voice_db(
                conn,
                voice_id,
                engine,
                voice_ref,
                str(v.get('display_name') or voice_id),
                bool(v.get('enabled', True)),
                text,
                sample_url,
            )
        finally:
            conn.close()

        return {'ok': True, 'sample_url': sample_url}
    except Exception as e:
        return {'ok': False, 'error': f'sample_failed: {type(e).__name__}: {e}'}

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


@app.put('/api/library/story/{story_id}/characters')
def api_library_story_characters_set(story_id: str, payload: dict[str, Any] | None = None):
    """Update only the characters JSON for a story."""
    try:
        story_id = validate_story_id(story_id)
        payload = payload or {}
        chars = payload.get('characters')
        if not isinstance(chars, list):
            return {'ok': False, 'error': 'bad_characters_shape'}

        # normalize minimal; keep voice_traits if present
        out_chars: list[dict[str, Any]] = []
        for c in chars:
            if not isinstance(c, dict):
                continue
            name = str(c.get('name') or '').strip()
            if not name:
                continue
            role = str(c.get('role') or '').strip()[:60]
            desc = str(c.get('description') or '').strip()[:400]
            vt = c.get('voice_traits') if isinstance(c.get('voice_traits'), dict) else None
            if vt is not None:
                vt2 = {
                    'gender': str(vt.get('gender') or '').strip().lower()[:16],
                    'age': str(vt.get('age') or '').strip().lower()[:16],
                    'pitch': str(vt.get('pitch') or '').strip().lower()[:16],
                    'accent': str(vt.get('accent') or '').strip()[:80],
                    'tone': [str(x).strip()[:40] for x in (vt.get('tone') or []) if str(x).strip()][:8] if isinstance(vt.get('tone'), list) else [],
                }
            else:
                vt2 = None

            row = {'name': name, 'role': role, 'description': desc}
            if vt2 is not None:
                row['voice_traits'] = vt2
            out_chars.append(row)

        # narrator first
        out_chars.sort(key=lambda c: (0 if str(c.get('role') or '').lower() == 'narrator' or str(c.get('name') or '').strip().lower() == 'narrator' else 1, str(c.get('name') or '')))

        conn = db_connect()
        try:
            db_init(conn)
            existing = get_story_db(conn, story_id)
            meta = existing.get('meta') or {}
            title = str(meta.get('title') or story_id)
            story_md = str(existing.get('story_md') or '')
            upsert_story_db(conn, story_id, title, story_md, out_chars)
        finally:
            conn.close()

        return {'ok': True, 'characters': out_chars}
    except Exception as e:
        return {'ok': False, 'error': f'characters_set_failed: {type(e).__name__}: {str(e)[:200]}'}


@app.post('/api/library/story/{story_id}/identify_characters')
def api_library_story_identify_characters(story_id: str, payload: dict[str, Any] | None = None):
    """Use the Tinybox LLM service to extract characters from a story and persist them."""
    try:
        story_id = validate_story_id(story_id)
        conn = db_connect()
        try:
            db_init(conn)
            existing = get_story_db(conn, story_id)
        finally:
            conn.close()

        title = str((existing.get('meta') or {}).get('title') or story_id)
        story_md = str(existing.get('story_md') or '')

        # Build prompt (no system role for gemma/vLLM)
        instr = (
            "You are extracting story characters for a story library and recommending voice traits for each. "
            "Return STRICT JSON only, no markdown, no commentary. "
            "Schema: {\"characters\": ["
            "{\"name\": str, \"role\": str, \"description\": str, "
            " \"voice_traits\": {"
            "   \"gender\": \"female|male|neutral|unknown\","
            "   \"age\": \"child|teen|adult|elder|unknown\","
            "   \"pitch\": \"low|medium|high\","
            "   \"tone\": [str, ...],"
            "   \"accent\": str"
            " }}"
            "]}. "
            "Include only characters that matter to the plot (2-8), but ALWAYS include a Narrator entry with role=\"narrator\" for unassigned lines. "
            "Use short descriptions. "
        )

        # Limit story to keep token usage bounded.
        s = story_md
        if len(s) > 8000:
            s = s[:8000]

        req = {
            'model': 'google/gemma-2-9b-it',
            'messages': [
                {
                    'role': 'user',
                    'content': instr + "\n\nTITLE: " + title + "\n\nSTORY:\n" + s,
                }
            ],
            'max_tokens': 600,
            'temperature': 0.2,
        }

        r = requests.post(GATEWAY_BASE + '/v1/llm', json=req, headers=_h(), timeout=180)
        j = None
        try:
            j = r.json()
        except Exception:
            j = None
        if not isinstance(j, dict):
            return {'ok': False, 'error': 'llm_bad_response'}

        # Parse completion
        txt = ''
        try:
            choices = j.get('choices') or []
            if choices and isinstance(choices, list):
                msg = choices[0].get('message') if isinstance(choices[0], dict) else None
                if isinstance(msg, dict) and msg.get('content'):
                    txt = str(msg.get('content') or '')
                elif choices[0].get('text'):
                    txt = str(choices[0].get('text') or '')
        except Exception:
            txt = ''
        txt = txt.strip()

        def _extract_json_obj(s: str) -> str:
            s = str(s or '').strip()
            if not s:
                return s
            # Find a balanced top-level {...} region.
            start = s.find('{')
            if start < 0:
                return s
            depth = 0
            in_str = False
            esc = False
            end = -1
            for i in range(start, len(s)):
                ch = s[i]
                if in_str:
                    if esc:
                        esc = False
                        continue
                    if ch == '\\':
                        esc = True
                        continue
                    if ch == '"':
                        in_str = False
                    continue
                else:
                    if ch == '"':
                        in_str = True
                        continue
                    if ch == '{':
                        depth += 1
                    elif ch == '}':
                        depth -= 1
                        if depth == 0:
                            end = i
                            break
            if end > start:
                return s[start : end + 1]
            # fallback: first..last
            i2 = s.rfind('}')
            if i2 > start:
                return s[start : i2 + 1]
            return s

        # Extract JSON object from text (best-effort + one repair attempt)
        obj = None
        raw0 = txt
        txt2 = _extract_json_obj(txt)
        try:
            obj = json.loads(txt2)
        except Exception:
            obj = None

        if obj is None:
            # Ask the LLM to repair into STRICT JSON
            try:
                fix_req = {
                    'model': 'google/gemma-2-9b-it',
                    'messages': [
                        {
                            'role': 'user',
                            'content': (
                                "Convert the following into STRICT JSON only (no markdown). "
                                "It MUST match schema {\"characters\":[{\"name\":str,\"role\":str,\"description\":str,\"voice_traits\":{\"gender\":str,\"age\":str,\"pitch\":str,\"tone\":[str],\"accent\":str}}]}. "
                                "Use double quotes everywhere. Do not include trailing commas.\n\n"
                                + raw0
                            ),
                        }
                    ],
                    'max_tokens': 700,
                    'temperature': 0.0,
                }
                r2 = requests.post(GATEWAY_BASE + '/v1/llm', json=fix_req, headers=_h(), timeout=180)
                j2 = r2.json() if r2 is not None else None
                txt_fix = ''
                try:
                    choices = (j2 or {}).get('choices') or []
                    if choices and isinstance(choices, list):
                        msg = choices[0].get('message') if isinstance(choices[0], dict) else None
                        if isinstance(msg, dict) and msg.get('content'):
                            txt_fix = str(msg.get('content') or '')
                        elif choices[0].get('text'):
                            txt_fix = str(choices[0].get('text') or '')
                except Exception:
                    txt_fix = ''
                txt_fix = txt_fix.strip()
                txt_fix2 = _extract_json_obj(txt_fix)
                obj = json.loads(txt_fix2)
            except Exception as e:
                return {'ok': False, 'error': f'bad_json_from_llm: {str(e)[:120]}', 'raw': raw0[:600]}

        chars = obj.get('characters') if isinstance(obj, dict) else None
        if not isinstance(chars, list):
            return {'ok': False, 'error': 'bad_characters_shape'}

        def _clean_enum(v: Any, allowed: set[str], default: str) -> str:
            try:
                s = str(v or '').strip().lower()
            except Exception:
                s = ''
            return s if s in allowed else default

        # Normalize
        out_chars: list[dict[str, Any]] = []
        for c in chars:
            if not isinstance(c, dict):
                continue
            name = str(c.get('name') or '').strip()
            if not name:
                continue
            role = str(c.get('role') or '').strip()[:60]
            desc = str(c.get('description') or '').strip()[:400]
            vt = c.get('voice_traits') if isinstance(c.get('voice_traits'), dict) else {}
            tone = []
            if isinstance(vt, dict) and isinstance(vt.get('tone'), list):
                tone = [str(x).strip() for x in (vt.get('tone') or []) if str(x).strip()]
            tone = tone[:8]

            voice_traits = {
                'gender': _clean_enum(vt.get('gender'), {'female', 'male', 'neutral', 'unknown'}, 'unknown'),
                'age': _clean_enum(vt.get('age'), {'child', 'teen', 'adult', 'elder', 'unknown'}, 'unknown'),
                'pitch': _clean_enum(vt.get('pitch'), {'low', 'medium', 'high'}, 'medium'),
                'tone': tone,
                'accent': str(vt.get('accent') or '').strip()[:80],
            }

            out_chars.append({'name': name, 'role': role, 'description': desc, 'voice_traits': voice_traits})

        # Ensure narrator exists
        has_narr = any(str(c.get('role') or '').strip().lower() == 'narrator' for c in out_chars)
        if not has_narr:
            out_chars.insert(
                0,
                {
                    'name': 'Narrator',
                    'role': 'narrator',
                    'description': 'Narrates lines not spoken by any character.',
                    'voice_traits': {
                        'gender': 'unknown',
                        'age': 'adult',
                        'pitch': 'medium',
                        'tone': ['clear', 'storytelling'],
                        'accent': '',
                    },
                },
            )

        out_chars = out_chars[:12]

        conn = db_connect()
        try:
            db_init(conn)
            upsert_story_db(conn, story_id, title, story_md, out_chars)
        finally:
            conn.close()

        return {'ok': True, 'characters': out_chars}
    except Exception as e:
        return {'ok': False, 'error': f'identify_failed: {type(e).__name__}: {str(e)[:200]}'}


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
def api_history(limit: int = 20, before: int | None = None):
    """Job history (paged).

    - limit: page size
    - before: created_at cursor (exclusive)
    """
    try:
        conn = db_connect()
        try:
            db_init(conn)
            jobs = db_list_jobs(conn, limit=int(limit), before=int(before) if before is not None else None)
        finally:
            conn.close()
        next_before = None
        try:
            if jobs:
                next_before = int(jobs[-1].get('created_at') or 0)
        except Exception:
            next_before = None
        return {'ok': True, 'jobs': jobs, 'next_before': next_before}
    except Exception as e:
        return {'ok': False, 'error': f'{type(e).__name__}: {str(e)[:200]}'}


def _settings_get(conn, key: str) -> dict[str, Any] | None:
    cur = conn.cursor()
    try:
        cur.execute("SET statement_timeout = '5000'")
    except Exception:
        pass
    cur.execute("SELECT value_json FROM sf_settings WHERE key=%s", (key,))
    r = cur.fetchone()
    if not r:
        return None
    try:
        return json.loads(r[0] or '{}') if (r[0] or '').strip() else {}
    except Exception:
        return {}


def _settings_set(conn, key: str, val: dict[str, Any]) -> None:
    cur = conn.cursor()
    now = int(time.time())
    try:
        cur.execute("SET statement_timeout = '5000'")
    except Exception:
        pass
    cur.execute(
        "INSERT INTO sf_settings (key,value_json,updated_at) VALUES (%s,%s,%s) "
        "ON CONFLICT (key) DO UPDATE SET value_json=EXCLUDED.value_json, updated_at=EXCLUDED.updated_at",
        (key, json.dumps(val or {}, separators=(',', ':')), now),
    )
    conn.commit()


def _default_providers() -> list[dict[str, Any]]:
    # Default single Tinybox provider; user can add more.
    return [
        {
            'id': 'tinybox_default',
            'kind': 'tinybox',
            'name': 'Tinybox',
            'gateway_base': GATEWAY_BASE,
            'monitoring_enabled': True,
            'voice_enabled': True,
            'voice_gpus': [0, 1],
            'llm_enabled': False,
            'llm_model': 'google/gemma-2-9b-it',
            'llm_gpus': [2],
        }
    ]


@app.get('/api/settings/providers')
def api_settings_providers_get():
    try:
        conn = db_connect()
        try:
            db_init(conn)
            s = _settings_get(conn, 'providers')
        finally:
            conn.close()
        providers = None
        if isinstance(s, dict):
            providers = s.get('providers')
        if not isinstance(providers, list) or not providers:
            providers = _default_providers()
        # sanitize minimal
        out = []
        for p in providers:
            if not isinstance(p, dict):
                continue
            pid = str(p.get('id') or '').strip()
            if not pid:
                continue
            out.append(p)
        return {'ok': True, 'providers': out}
    except Exception as e:
        return {'ok': False, 'error': f'{type(e).__name__}: {str(e)[:200]}'}


@app.post('/api/settings/providers')
def api_settings_providers_set(payload: dict[str, Any] = Body(default={})):  # noqa: B008
    try:
        providers = (payload or {}).get('providers')
        if not isinstance(providers, list):
            return {'ok': False, 'error': 'bad_providers'}

        # Basic validation + normalization
        norm = []
        for p in providers:
            if not isinstance(p, dict):
                continue
            pid = str(p.get('id') or '').strip()
            if not pid or len(pid) > 80:
                continue
            kind = str(p.get('kind') or '').strip()[:40]
            name = str(p.get('name') or '').strip()[:80]

            def _ints(x):
                if not isinstance(x, list):
                    return []
                out2 = []
                for v in x:
                    try:
                        out2.append(int(v))
                    except Exception:
                        pass
                return out2

            norm.append(
                {
                    'id': pid,
                    'kind': kind,
                    'name': name,
                    'gateway_base': str(p.get('gateway_base') or '').strip()[:200],
                    'monitoring_enabled': bool(p.get('monitoring_enabled', False)),
                    'voice_enabled': bool(p.get('voice_enabled', False)),
                    'voice_engines': [str(x).strip() for x in (p.get('voice_engines') or []) if str(x).strip() in ('xtts', 'tortoise')],
                    'voice_gpus': _ints(p.get('voice_gpus') or []),
                    'voice_threads': int(p.get('voice_threads') or 16) if str(p.get('voice_threads') or '').strip() else 16,
                    'tortoise_split_min_text': int(p.get('tortoise_split_min_text') or 100) if str(p.get('tortoise_split_min_text') or '').strip() else 100,
                    'llm_enabled': bool(p.get('llm_enabled', False)),
                    'llm_model': str(p.get('llm_model') or '').strip(),
                    'llm_gpus': _ints(p.get('llm_gpus') or []),
                }
            )

        # Detect LLM GPU changes (tinybox provider only) so we can reload vLLM.
        prev_llm_gpus: list[int] = []
        next_llm_gpus: list[int] = []
        try:
            conn = db_connect()
            try:
                db_init(conn)
                prev = _settings_get(conn, 'providers')
                prev_provs = (prev or {}).get('providers') if isinstance(prev, dict) else None
                if isinstance(prev_provs, list):
                    for pp in prev_provs:
                        if isinstance(pp, dict) and str(pp.get('kind') or '').strip() == 'tinybox':
                            v = pp.get('llm_gpus')
                            if isinstance(v, list):
                                prev_llm_gpus = [int(x) for x in v if str(x).strip().isdigit()]
                            break

                for np in norm:
                    if isinstance(np, dict) and str(np.get('kind') or '').strip() == 'tinybox':
                        v = np.get('llm_gpus')
                        if isinstance(v, list):
                            next_llm_gpus = [int(x) for x in v if str(x).strip().isdigit()]
                        break

                _settings_set(conn, 'providers', {'providers': norm})
            finally:
                conn.close()
        except Exception:
            # If DB read fails, still consider the save successful.
            prev_llm_gpus = []

        # If LLM GPUs changed, trigger vLLM reconfigure+restart on Tinybox.
        llm_reconf: dict[str, Any] | None = None
        try:
            if sorted(set(prev_llm_gpus)) != sorted(set(next_llm_gpus)) and next_llm_gpus:
                r = requests.post(
                    GATEWAY_BASE + '/v1/admin/vllm/reconfigure',
                    json={'gpus': sorted(set(next_llm_gpus))},
                    headers=_h(),
                    timeout=120,
                )
                # best-effort; don't fail settings save on restart issues
                try:
                    llm_reconf = r.json()
                except Exception:
                    llm_reconf = {'ok': False, 'error': 'bad_json'}
        except Exception as e:
            llm_reconf = {'ok': False, 'error': f'reconfigure_failed: {type(e).__name__}: {str(e)[:120]}'}

        out = {'ok': True}
        if llm_reconf is not None:
            out['llm_reconfigure'] = llm_reconf
        return out
    except Exception as e:
        return {'ok': False, 'error': f'{type(e).__name__}: {str(e)[:200]}'}


# Round-robin GPU selection state (best-effort, in-memory)
_GPU_RR: dict[str, int] = {}
_GPU_RR_LOCK = threading.Lock() if 'threading' in globals() else None


def _pick_rr_from_list(key: str, gpus: list[int]) -> int | None:
    try:
        gpus = [int(x) for x in (gpus or [])]
    except Exception:
        gpus = []
    if not gpus:
        return None
    # Stable order
    gpus = sorted(list(dict.fromkeys(gpus)))

    # Thread-safe if possible
    try:
        lock = _GPU_RR_LOCK
        if lock is None:
            import threading as _th
            lock = _th.Lock()
            globals()['_GPU_RR_LOCK'] = lock
        with lock:
            cur = int(_GPU_RR.get(key) or 0)
            gpu = gpus[cur % len(gpus)]
            _GPU_RR[key] = (cur + 1) % len(gpus)
            return int(gpu)
    except Exception:
        # fallback
        return int(gpus[0])


def _get_tinybox_provider() -> dict[str, Any] | None:
    try:
        conn = db_connect()
        try:
            db_init(conn)
            s = _settings_get(conn, 'providers')
        finally:
            conn.close()
        providers = None
        if isinstance(s, dict):
            providers = s.get('providers')
        if not isinstance(providers, list) or not providers:
            providers = _default_providers()
        for p in providers:
            if isinstance(p, dict) and str(p.get('kind') or '').strip() == 'tinybox':
                return p
    except Exception:
        return None
    return None


def _get_allowed_voice_gpus() -> list[int]:
    p = _get_tinybox_provider() or {}
    vg = p.get('voice_gpus') if isinstance(p, dict) else None
    lg = p.get('llm_gpus') if isinstance(p, dict) else None
    if not isinstance(vg, list):
        vg = []
    if not isinstance(lg, list):
        lg = []
    try:
        reserved = {int(x) for x in lg}
    except Exception:
        reserved = set()
    out: list[int] = []
    for x in vg:
        try:
            n = int(x)
        except Exception:
            continue
        if n in reserved:
            continue
        if n not in out:
            out.append(n)
    out.sort()
    return out


def _pick_voice_gpu_rr() -> int | None:
    p = _get_tinybox_provider() or {}
    pid = str(p.get('id') or 'tinybox')
    allowed = _get_allowed_voice_gpus()
    return _pick_rr_from_list('voice:' + pid, allowed)



def _split_tts_text(text: str, x: int = 100, max_chunks: int = 12) -> list[str]:
    """Split text into chunks using the agreed strategy.

    If len(text) <= x: return one chunk.

    Else repeat: find a split point near x using strong punctuation (. ; ! ? :) or newline.
    If none found, allow soft overflow to 1.25x, then whitespace fallback, then hard split at 1.5x.
    """

    t = str(text or '').strip()
    if not t:
        return []
    try:
        x = int(x)
    except Exception:
        x = 100
    if x <= 0:
        x = 100

    if len(t) <= x:
        return [t]

    def is_boundary(ch: str) -> bool:
        return ch in ('.', ';', '!', '?', ':', '\n')

    out: list[str] = []
    s = t
    try:
        max_chunks = int(max_chunks or 12)
    except Exception:
        max_chunks = 12
    if max_chunks < 1:
        max_chunks = 1

    while s and len(out) < max_chunks:
        s = s.lstrip()
        if not s:
            break
        if len(s) <= x or len(out) == max_chunks - 1:
            out.append(s.strip())
            break

        cut = None
        back = min(x, len(s) - 1)
        # A) preferred backward boundary <= x
        for i in range(back, 0, -1):
            if is_boundary(s[i - 1]):
                cut = i
                break

        # B) soft overflow up to 1.25x
        if cut is None:
            hi = min(int(x * 1.25), len(s) - 1)
            for i in range(back + 1, hi + 1):
                if is_boundary(s[i - 1]):
                    cut = i
                    break

        # C) whitespace fallback: next whitespace after 1.25x
        if cut is None:
            start = min(int(x * 1.25), len(s) - 1)
            ws = None
            for i in range(start, len(s)):
                if s[i].isspace():
                    ws = i
                    break
            if ws is not None and ws > 0:
                cut = ws

        # D) hard fallback: force split at 1.5x
        if cut is None:
            cut = min(int(x * 1.5), len(s))

        chunk = s[:cut].strip()
        rest = s[cut:].strip()
        if chunk:
            out.append(chunk)
        s = rest

    return [c for c in out if c]



def _concat_wavs(wavs: list[bytes]) -> bytes:
    import io
    import wave

    if not wavs:
        return b""
    params = None
    frames_all: list[bytes] = []
    for b in wavs:
        bio = io.BytesIO(b)
        with wave.open(bio, 'rb') as w:
            p = w.getparams()
            if params is None:
                params = p
            else:
                # Must match channels/sampwidth/framerate
                if (p.nchannels, p.sampwidth, p.framerate) != (params.nchannels, params.sampwidth, params.framerate):
                    raise RuntimeError('wav_params_mismatch')
            frames_all.append(w.readframes(w.getnframes()))

    out = io.BytesIO()
    with wave.open(out, 'wb') as wo:
        wo.setnchannels(params.nchannels)
        wo.setsampwidth(params.sampwidth)
        wo.setframerate(params.framerate)
        for fr in frames_all:
            wo.writeframes(fr)
    return out.getvalue()

def _job_patch(job_id: str, patch: dict[str, Any]) -> None:
    conn = db_connect()
    try:
        db_init(conn)
        cur = conn.cursor()
        # Ensure row exists
        cur.execute(
            "INSERT INTO jobs (id,title,kind,meta_json,state,created_at) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING",
            (
                job_id,
                str(patch.get('title') or job_id),
                str(patch.get('kind') or ''),
                str(patch.get('meta_json') or ''),
                str(patch.get('state') or 'running'),
                int(time.time()),
            ),
        )
        sets = []
        vals = []
        for k, v in (patch or {}).items():
            if k == 'id' or v is None:
                continue
            sets.append(f"{k}=%s")
            if k in ('started_at', 'finished_at', 'total_segments', 'segments_done', 'created_at'):
                try:
                    vals.append(int(v))
                except Exception:
                    vals.append(0)
            else:
                vals.append(str(v))
        if sets:
            vals.append(job_id)
            cur.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id=%s", tuple(vals))
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass


@app.post('/api/tts')
def api_tts(payload: dict[str, Any]):
    """Text-to-speech helper (sync).

    - Delegates synthesis to Tinybox via gateway (/v1/tts).
    - If Tinybox returns audio bytes (audio_b64), we upload to Spaces and return a public URL.

    Return shape is backward-compatible with older UI code that expects {status, body}.
    """
    r = requests.post(GATEWAY_BASE + '/v1/tts', json=payload, headers=_h(), timeout=900)
    try:
        body = r.json()
    except Exception:
        body = r.text

    # Upload returned audio to Spaces for browser playback
    try:
        if isinstance(body, dict) and body.get('ok') and body.get('audio_b64'):
            import base64
            from .spaces_upload import upload_bytes

            b = base64.b64decode(str(body.get('audio_b64') or ''), validate=False)
            ct = str(body.get('content_type') or 'audio/wav')
            ext = 'wav'
            if 'mpeg' in ct:
                ext = 'mp3'
            fn = f"sample.{ext}"
            _key, url = upload_bytes(b, key_prefix='tts/samples', filename=fn, content_type=ct)
            out = {'ok': True, 'url': url}
            return {'status': 200, 'body': out}
    except Exception as e:
        return {'status': 500, 'body': {'ok': False, 'error': f'spaces_upload_failed: {e}'}}

    return {"status": r.status_code, "body": body}


@app.post('/api/tts_job')
def api_tts_job(payload: dict[str, Any] = Body(default={})):  # noqa: B008
    """Run TTS as a background job so progress is visible on History/Jobs."""
    try:
        engine = str((payload or {}).get('engine') or '').strip()
        voice = str((payload or {}).get('voice') or '').strip()
        text = str((payload or {}).get('text') or '').strip()
        if not engine or not voice or not text:
            return {'ok': False, 'error': 'missing_required_fields'}

        job_id = "tts_" + str(int(time.time())) + "_" + os.urandom(4).hex()
        title = f"TTS ({engine})"
        now = int(time.time())
        total = 3

        meta = {
            'engine': engine,
            'voice_ref': voice,
            'text': text,
            'display_name': str((payload or {}).get('display_name') or '').strip() or 'Voice',
            'roster_id': str((payload or {}).get('roster_id') or '').strip() or '',
            'sample_text': text,
            # passthrough for roster metadata
            'tortoise_voice': str((payload or {}).get('tortoise_voice') or '').strip(),
            'tortoise_gender': str((payload or {}).get('tortoise_gender') or '').strip(),
            'tortoise_preset': str((payload or {}).get('tortoise_preset') or '').strip(),
        }

        # For tortoise, enforce a stable voice across all chunks.
        # Prefer explicit tortoise_voice from UI; otherwise fall back to voice_ref.
        if engine == 'tortoise':
            tv = str(meta.get('tortoise_voice') or '').strip() or str(voice or '').strip()
            meta['tortoise_voice_fixed'] = tv
            if not meta.get('tortoise_voice'):
                meta['tortoise_voice'] = tv

        _job_patch(
            job_id,
            {
                'title': title,
                'kind': 'tts_sample',
                'meta_json': json.dumps(meta, separators=(',', ':')),
                'state': 'running',
                'started_at': now,
                'finished_at': 0,
                'total_segments': total,
                'segments_done': 0,
            },
        )

        def worker():
            try:
                # stage 1
                _job_patch(job_id, {'segments_done': 1})

                # stage 2: synth
                # For tortoise, split long text into chunks and run each chunk as its own TTS call.
                chunks = [text]
                try:
                    if engine == 'tortoise':
                        p = _get_tinybox_provider() or {}
                        split_min_text = 480
                        threads = 16
                        try:
                            split_min_text = int((p or {}).get('tortoise_split_min_text') or 100)
                        except Exception:
                            split_min_text = 100
                        try:
                            threads = int((p or {}).get('tortoise_threads') or (p or {}).get('voice_threads') or 16)
                        except Exception:
                            threads = 16
                        if len(text) > split_min_text:
                            chunks = _split_tts_text(text, x=split_min_text, max_chunks=12) or [text]
                        else:
                            chunks = [text]
                    else:
                        threads = 16
                except Exception:
                    chunks = [text]

                # Update total to reflect chunked synth + upload
                try:
                    total2 = 1 + max(1, len(chunks)) + 1  # bookkeeping + synth_chunks + upload
                    _job_patch(job_id, {'total_segments': int(total2)})
                except Exception:
                    total2 = total

                import base64
                from concurrent.futures import ThreadPoolExecutor, as_completed

                wavs: list[bytes] = [b'' for _ in range(max(1, len(chunks)))]
                gpus_used: list[int] = []
                seg_done = 1

                allowed_gpus = []
                try:
                    allowed_gpus = _get_allowed_voice_gpus()
                except Exception:
                    allowed_gpus = []

                # Parallelize across enabled GPUs.
                workers = max(1, len(allowed_gpus) or 1)

                # Stable voice for tortoise chunking
                voice_fixed = voice
                try:
                    if engine == 'tortoise':
                        voice_fixed = str((meta.get('tortoise_voice_fixed') or meta.get('tortoise_voice') or voice) or '').strip() or voice
                except Exception:
                    voice_fixed = voice

                def do_one(i: int, chunk: str, gpu: int | None):
                    r = requests.post(
                        GATEWAY_BASE + '/v1/tts',
                        json={'engine': engine, 'voice': voice_fixed, 'text': chunk, 'upload': True, 'gpu': gpu, 'threads': threads},
                        headers=_h(),
                        timeout=1800,
                    )
                    r.raise_for_status()
                    j = r.json()
                    if not isinstance(j, dict) or not j.get('ok'):
                        err = str((j or {}).get('error') or 'tts_failed')
                        det = (j or {}).get('detail')
                        if det:
                            err = err + ' :: ' + str(det)
                        raise RuntimeError(err)
                    if not j.get('audio_b64'):
                        raise RuntimeError('no_audio_b64')
                    b = base64.b64decode(str(j.get('audio_b64') or ''), validate=False)
                    g = j.get('gpu')
                    try:
                        g = int(g) if g is not None else None
                    except Exception:
                        g = None
                    return (i, b, g)

                with ThreadPoolExecutor(max_workers=workers) as ex:
                    futs = []
                    for i, chunk in enumerate(chunks):
                        gpu = None
                        if allowed_gpus:
                            gpu = allowed_gpus[i % len(allowed_gpus)]
                        futs.append(ex.submit(do_one, i, chunk, gpu))

                    last_prog_ts = 0.0
                    for fut in as_completed(futs):
                        i, b, g = fut.result()
                        wavs[i] = b
                        if g is not None:
                            gpus_used.append(int(g))
                        seg_done += 1

                        # Throttle DB writes: progress updates at most ~1/sec.
                        try:
                            now_ts = time.time()
                            if (now_ts - last_prog_ts) >= 0.9:
                                _job_patch(job_id, {'segments_done': int(seg_done)})
                                last_prog_ts = now_ts
                        except Exception:
                            pass

                    # Ensure final progress is recorded for stage 2.
                    try:
                        _job_patch(job_id, {'segments_done': int(seg_done)})
                    except Exception:
                        pass

                # stage 3: upload concatenated wav to Spaces
                from .spaces_upload import upload_bytes

                b = _concat_wavs(wavs)
                if not b:
                    raise RuntimeError('empty_audio')

                _key, url = upload_bytes(b, key_prefix='tts/samples', filename='sample.wav', content_type='audio/wav')

                # record gpus used + effective voice used in job meta (best-effort)
                try:
                    meta2 = dict(meta)
                    meta2['gpus_used'] = gpus_used
                    try:
                        if engine == 'tortoise':
                            meta2['tortoise_voice_effective'] = str(voice_fixed or '')
                    except Exception:
                        pass
                    _job_patch(job_id, {'meta_json': json.dumps(meta2, separators=(',', ':'))})
                except Exception:
                    pass

                if not url:
                    raise RuntimeError('no_url')

                _job_patch(
                    job_id,
                    {
                        'segments_done': total,
                        'state': 'completed',
                        'finished_at': int(time.time()),
                        'mp3_url': url,
                    },
                )
            except Exception as e:
                det = ''
                try:
                    import traceback

                    det = traceback.format_exc(limit=6)
                except Exception:
                    det = ''
                _job_patch(
                    job_id,
                    {
                        'state': 'failed',
                        'finished_at': int(time.time()),
                        'segments_done': 0,
                        'mp3_url': '',
                        'sfml_url': (f"error: {type(e).__name__}: {str(e)[:200]}" + ("\n" + det[:1400] if det else '')),
                    },
                )

        import threading

        threading.Thread(target=worker, daemon=True).start()
        return {'ok': True, 'job_id': job_id}
    except Exception as e:
        return {'ok': False, 'error': f'tts_job_failed: {type(e).__name__}: {e}'}