from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import json
import time
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
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse
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

# Incremental refactor: extract the dashboard (/) CSS verbatim into a constant.
# This should not change rendered output.
INDEX_BASE_CSS = base_css("""\

    :root{--bg:#0b1020;--card:#0f1733;--text:#e7edff;--muted:#a8b3d8;--line:#24305e;--accent:#4aa3ff;--good:#26d07c;--warn:#ffcc00;--bad:#ff4d4d;}
    body.noScroll{overflow:hidden;}
    html,body{overscroll-behavior-y:none;}
    body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--text);padding:18px;max-width:920px;margin:0 auto;overflow-x:hidden;}
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
    .card{border:1px solid var(--line);border-radius:16px;padding:12px;margin:12px 0;background:var(--card);}
    .todoItem{display:block;margin:6px 0;line-height:1.35;}
    .todoItem input{transform:scale(1.1);margin-right:10px;}
    .todoItem span{vertical-align:middle;}
    .row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;}
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
    .rowEnd{justify-content:flex-end;margin-left:auto;}
    button{padding:10px 12px;border-radius:12px;border:1px solid var(--line);background:#163a74;color:#fff;font-weight:950;cursor:pointer;}
    button.secondary{background:transparent;color:var(--text);}
    input,textarea,select{width:100%;padding:10px;border:1px solid var(--line);border-radius:12px;background:#0b1020;color:var(--text);font-size:16px;}
    textarea{min-height:90px;}
    .hide{display:none;}

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

""")

VOICE_NEW_EXTRA_CSS = base_css("""\

    textarea{resize:none;}
    .k{color:var(--muted);font-size:12px;margin-top:12px;}
    audio{width:100%;margin-top:10px;}

""")

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
    r.raise_for_status()
    try:
        return r.json()
    except Exception:
        # Avoid opaque 500s when the upstream returns non-JSON.
        # (Don't include any auth headers/tokens; only surface a tiny body snippet.)
        txt = ""
        try:
            txt = (r.text or "")[:200]
        except Exception:
            txt = ""
        raise HTTPException(status_code=502, detail={"error": "upstream_non_json", "status": int(r.status_code), "body": txt})


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

  <div id='boot' class='boot muted'>
    <span id='bootText'><strong>Build</strong>: __BUILD__ • JS: booting…</span>
    <button class='copyBtn' type='button' onclick='copyBoot()' aria-label='Copy build + error' style='margin-left:auto'>
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path stroke-linecap="round" stroke-linejoin="round" d="M11 7H7a2 2 0 00-2 2v9a2 2 0 002 2h10a2 2 0 002-2v-9a2 2 0 00-2-2h-4M11 7V5a2 2 0 114 0v2M11 7h4"/>
      </svg>
    </button>
  </div>

  <div class='tabs'>
    <button id='tab-history' class='tab active' onclick='showTab("history")'>Jobs</button>
    <button id='tab-library' class='tab' onclick='showTab("library")'>Library</button>
    <button id='tab-voices' class='tab' onclick='showTab("voices")'>Voices</button>
        <button id='tab-advanced' class='tab' onclick='showTab("advanced")'>Settings</button>
  </div>

  <div id='pane-history'>
    <div class='card'>
      <div class='row' style='justify-content:space-between;'>
        <div>
          <div style='font-weight:950;'>Recent jobs</div>
          <div class='muted'>Read-only from managed Postgres (migrated from Tinybox monitor).</div>
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

  <div id='pane-advanced' class='hide'>

    <div class='card'>
      <div style='font-weight:950;margin-bottom:6px;'>Voice servers</div>
      <div class='muted'>Configured endpoints used for voice/TTS work.</div>
      <div style='margin-top:10px'>__VOICE_SERVERS__</div>
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
// minimal boot script (runs even if the main app script has a syntax error)
window.__SF_BUILD = '__BUILD__';
window.__SF_BOOT_TS = Date.now();
window.__SF_LAST_ERR = '';

function __sfEnsureBootBanner(){
  // Some code paths may accidentally set #boot.textContent (which nukes children).
  // Ensure we always have a dedicated #bootText span + copy button.
  try{
    var boot = document.getElementById('boot');
    if (!boot) return null;
    var t = document.getElementById('bootText');
    if (t) return t;

    boot.innerHTML = "<span id='bootText'><strong>Build</strong>: " + window.__SF_BUILD + " • JS: ok</span>" +
      "<button class='copyBtn' type='button' onclick='copyBoot()' aria-label='Copy build + error' style='margin-left:auto'>" +
      "<svg viewBox=\\\"0 0 24 24\\\" aria-hidden=\\\"true\\\"><path stroke-linecap=\\\"round\\\" stroke-linejoin=\\\"round\\\" d=\\\"M11 7H7a2 2 0 00-2 2v9a2 2 0 002 2h10a2 2 0 002-2v-9a2 2 0 00-2-2h-4M11 7V5a2 2 0 114 0v2M11 7h4\\\"/></svg>" +
      "</button>";

    return document.getElementById('bootText');
  }catch(e){
    return null;
  }
}

function __sfSetDebugInfo(msg){
  try{
    window.__SF_LAST_ERR = msg || '';
    var el=document.getElementById('dbgInfo');
    if (el) el.textContent = 'Build: ' + window.__SF_BUILD + '\\nJS: ' + (window.__SF_LAST_ERR || '(none)');

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

try{ __sfSetDebugInfo(''); }catch(e){}
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
  for (var i=0;i<['history','library','voices','advanced'].length;i++){
    var n=['history','library','voices','advanced'][i];
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

  try{ var pn=document.getElementById('pageName'); if(pn){ pn.textContent = (name==='history'?'Jobs':(name==='library'?'Library':(name==='voices'?'Voices':'Settings'))); } }catch(e){}

  // lazy-load tab content
  try{
    if (name==='history') loadHistory();
    else if (name==='library') loadLibrary();
    else if (name==='voices') loadVoices();
  }catch(_e){}
}

function getTabFromHash(){
  try{
    var h = (window.location.hash || '').replace('#','');
    if (h==='tab-history') return 'history';
    if (h==='tab-library') return 'library';
    if (h==='tab-voices') return 'voices';
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
        <div class='k'>mp3</div><div class='fadeLine'><div class='fadeText' title='${job.mp3_url||""}'>${job.mp3_url||'-'}</div>${job.mp3_url?`<button class="copyBtn" data-copy="${job.mp3_url}" onclick="copyFromAttr(this)" aria-label="Copy">${copyIconSvg()}</button>`:''}</div>
        <div class='k'>sfml</div><div class='fadeLine'><div class='fadeText' title='${job.sfml_url||""}'>${job.sfml_url||'-'}</div>${job.sfml_url?`<button class="copyBtn" data-copy="${job.sfml_url}" onclick="copyFromAttr(this)" aria-label="Copy">${copyIconSvg()}</button>`:''}</div>
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
        + "<button class='secondary' data-vid='" + encodeURIComponent(v.id) + "' onclick='playVoiceEl(this)'>Play</button>"
        + "<button class='secondary' data-vid='" + encodeURIComponent(v.id) + "' onclick='goVoiceEdit(this)'>Edit</button>"
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
    var id = decodeURIComponent(idEnc||'');
    if (!id) return;
    var a = document.getElementById('aud-' + idEnc);
    if (a && a.src){
      try{ a.play(); }catch(e){}
      return;
    }
    // If no sample yet, generate then play.
    return fetchJsonAuthed('/api/voices/' + encodeURIComponent(id) + '/sample', {method:'POST'})
      .then(function(j){
        if (j && j.ok && j.sample_url){
          var a2 = document.getElementById('aud-' + idEnc);
          if (a2){ a2.src = j.sample_url; a2.classList.remove('hide'); try{ a2.play(); }catch(e){} }
          return loadVoices();
        }
        alert((j && j.error) ? j.error : 'Play failed');
      }).catch(function(e){ alert(String(e)); });
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

var initTab = getTabFromHash() || getQueryParam('tab');
if (initTab==='library' || initTab==='history' || initTab==='voices' || initTab==='advanced') { try{ showTab(initTab); }catch(e){} }

refreshAll();
// Start streaming immediately so the Metrics tab is instant.
setMonitorEnabled(loadMonitorPref());
setDebugUiEnabled(loadDebugPref());
loadHistory();
loadVoices();

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
    html = html.replace('__INDEX_BASE_CSS__', INDEX_BASE_CSS)


    return html.replace("__BUILD__", str(build)).replace("__VOICE_SERVERS__", voice_servers_html)





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
    # Best-effort ask Tinybox provider; fallback.
    try:
        r = requests.get(GATEWAY_BASE + '/v1/engines', timeout=4, headers={'Authorization': f'Bearer {GATEWAY_TOKEN}'} if GATEWAY_TOKEN else None)
        if r.status_code == 200:
            j = r.json()
            if isinstance(j, dict) and j.get('ok') and isinstance(j.get('engines'), list):
                return {'ok': True, 'engines': j['engines']}
    except Exception:
        pass
    return {'ok': True, 'engines': ['xtts', 'tortoise']}


@app.get('/api/voice_provider/presets')
def api_voice_provider_presets():
    # Requires passphrase session auth (middleware).
    try:
        r = requests.get(GATEWAY_BASE + '/v1/voice-clips', timeout=4, headers={'Authorization': f'Bearer {GATEWAY_TOKEN}'} if GATEWAY_TOKEN else None)
        if r.status_code == 200:
            j = r.json()
            if isinstance(j, dict) and j.get('ok') and isinstance(j.get('clips'), list):
                return {'ok': True, 'clips': j['clips']}
    except Exception:
        pass
    return {'ok': True, 'clips': []}




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
    enabled_checked = 'checked' if bool(v.get('enabled', True)) else ''

    html = """<!doctype html>
<html>
<head>
  <meta charset='utf-8'/>
  <meta name='viewport' content='width=device-width, initial-scale=1'/>
  <title>StoryForge - Edit Voice</title>
  <style>__VOICES_BASE_CSS____VOICE_EDIT_EXTRA_CSS__</style>
</head>
<body>
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
    <div style='font-weight:950;margin-bottom:6px;'>Provider fields</div>

    <div class='muted'>Engine</div>
    <input id='engine' value='__ENG__' placeholder='xtts' />

    <div class='muted' style='margin-top:12px'>voice_ref</div>
    <input id='voice_ref' value='__VREF__' placeholder='speaker_03' />

    <div class='muted' style='margin-top:12px'>Sample text</div>
    <textarea id='sample_text' placeholder='Hello…'>__STXT__</textarea>

    <div class='row' style='margin-top:12px'>
      <button class='secondary' type='button' onclick='testSample()'>Test sample</button>
      <button type='button' onclick='save()'>Save</button>
    </div>

    <div id='out' class='muted' style='margin-top:10px'>-</div>
    <audio id='audio' controls class='hide'></audio>
  </div>

<script>
function escJs(s){ return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function $(id){ return document.getElementById(id); }
function val(id){ var el=$(id); return el?String(el.value||''):''; }
function chk(id){ var el=$(id); return !!(el && el.checked); }

function save(){
  var out=$('out'); if(out) out.textContent='Saving…';
  var payload={
    display_name: val('display_name'),
    engine: val('engine'),
    voice_ref: val('voice_ref'),
    sample_text: val('sample_text'),
    enabled: chk('enabled')
  };
  fetch('/api/voices/__VID_RAW__', {method:'PUT', headers:{'Content-Type':'application/json'}, credentials:'include', body: JSON.stringify(payload)})
    .then(function(r){ return r.json().catch(function(){return {ok:false,error:'bad_json'};}); })
    .then(function(j){
      if (j && j.ok){ if(out) out.textContent='Saved.'; setTimeout(function(){ window.location.href='/#tab-voices'; }, 250); return; }
      if(out) out.innerHTML='<div class="err">'+escJs((j&&j.error)||'save failed')+'</div>';
    }).catch(function(e){ if(out) out.innerHTML='<div class="err">'+escJs(String(e))+'</div>'; });
}

function testSample(){
  var out=$('out'); if(out) out.textContent='Generating…';
  var payload={engine: val('engine'), voice: val('voice_ref'), text: val('sample_text') || ('Hello. This is ' + (val('display_name')||'a voice') + '.'), upload:true};
  fetch('/api/tts', {method:'POST', headers:{'Content-Type':'application/json'}, credentials:'include', body: JSON.stringify(payload)})
    .then(function(r){ return r.json().catch(function(){return {ok:false,error:'bad_json'};}); })
    .then(function(j){
      var url = (j && (j.url || j.sample_url)) ? (j.url || j.sample_url) : '';
      if (!url){ if(out) out.innerHTML='<div class="err">No URL returned</div>'; return; }
      if(out) out.innerHTML = "<div class='muted'>Sample: <code>" + escJs(url) + "</code></div>";
      var a=$('audio');
      if (a){ a.src=url; a.classList.remove('hide'); try{ a.play(); }catch(e){} }
    }).catch(function(e){ if(out) out.innerHTML='<div class="err">'+escJs(String(e))+'</div>'; });
}
</script>
</body>
</html>"""

    html = (html
        .replace('__VID__', vid)
        .replace('__DN__', dn)
        .replace('__ENG__', eng)
        .replace('__VREF__', vref)
        .replace('__STXT__', stxt)
        .replace('__ENABLED__', enabled_checked)
        .replace('__VID_RAW__', voice_id)
    )
    html = (html
        .replace('__VOICES_BASE_CSS__', VOICES_BASE_CSS)
        .replace('__VOICE_EDIT_EXTRA_CSS__', VOICE_EDIT_EXTRA_CSS)
    )
    return html
@app.get('/voices/new', response_class=HTMLResponse)
def voices_new_page(response: Response):
    response.headers['Cache-Control'] = 'no-store'
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
  <div class='navBar'>
    <div class='top'>
      <div>
        <div class='brandRow'><h1><a class='brandLink' href='/'>StoryForge</a></h1><div class='pageName'>Generate voice</div></div>
        <div class='muted'>Pick an engine, provide a clip (upload / preset / URL), choose sample text, then save.</div>
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

  <div class='card'>
    <div style='font-weight:950;margin-bottom:6px;'>Training</div>

    <div class='k'>Voice name</div>
    <input id='voiceName' placeholder='Luna' />

    <div class='k'>Engine</div>
    <select id='engineSel'></select>

    <div class='k'>Voice clip</div>
    <select id='clipMode'>
      <option value='upload'>Upload</option>
      <option value='preset'>Choose preset</option>
      <option value='url'>Paste URL</option>
    </select>

    <div id='clipUploadRow' style='margin-top:8px'>
      <input id='clipFile' type='file' accept='audio/*' />
      <div class='muted' style='margin-top:6px'>Uploads to Spaces.</div>
    </div>
    <div id='clipPresetRow' class='hide' style='margin-top:8px'>
      <select id='clipPreset'></select>
      <div class='muted' style='margin-top:6px'>Presets come from Tinybox.</div>
    </div>
    <div id='clipUrlRow' class='hide' style='margin-top:8px'>
      <input id='clipUrl' placeholder='https://…/clip.wav' />
    </div>

    <div class='k'>Sample text</div>
    <textarea id='sampleText' placeholder='Hello…'>Hello. This is a test sample for a new voice.</textarea>

    <div class='row' style='margin-top:12px'>
      <button type='button' class='secondary' onclick='startTrain()'>Generate model</button>
    </div>

    <div id='out' class='muted' style='margin-top:10px'>-</div>
  </div>

  <div class='card'>
    <div style='font-weight:950;margin-bottom:6px;'>Save to roster</div>

    <div class='k'>id</div>
    <input id='id' placeholder='luna' />

    <div class='k'>display name</div>
    <input id='name' placeholder='Luna' />

    <div class='k'>engine</div>
    <input id='engine' placeholder='xtts' />

    <div class='k'>voice_ref</div>
    <input id='voice_ref' placeholder='provider voice ref' />

    <div class='k'>sample text</div>
    <textarea id='text' placeholder='Hello…'>Hello. This is Luna.</textarea>

    <div class='row' style='margin-top:12px'>
      <button class='secondary' type='button' onclick='testSample()'>Test sample</button>
      <button type='button' onclick='saveVoice()'>Save voice</button>
    </div>

    <audio id='audio' controls class='hide'></audio>
  </div>

<script>
function esc(s){ return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function $(id){ return document.getElementById(id); }
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
  });
}catch(e){}

function setVis(){
  var m=(($('clipMode')||{}).value||'upload');
  var u=$('clipUploadRow'), p=$('clipPresetRow'), r=$('clipUrlRow');
  if(u) u.classList.toggle('hide', m!=='upload');
  if(p) p.classList.toggle('hide', m!=='preset');
  if(r) r.classList.toggle('hide', m!=='url');
}

function loadEngines(){
  return jsonFetch('/api/voice_provider/engines').then(function(j){
    var sel=$('engineSel'); if(!sel) return;
    sel.innerHTML='';
    var arr=(j&&j.engines)||[];
    if (!arr.length){ arr=['xtts','tortoise']; }
    for(var i=0;i<arr.length;i++){
      var o=document.createElement('option');
      o.value=String(arr[i]);
      o.textContent=String(arr[i]);
      sel.appendChild(o);
    }
  });
}

function loadPresets(){
  return jsonFetch('/api/voice_provider/presets').then(function(j){
    var sel=$('clipPreset'); if(!sel) return;
    sel.innerHTML='';
    var arr=(j&&j.clips)||[];
    for(var i=0;i<arr.length;i++){
      var c=arr[i]||{};
      var o=document.createElement('option');
      o.value=String(c.url||c.path||'');
      o.textContent=String(c.name||c.url||c.path||'');
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

function startTrain(){
  var out=$('out'); if(out) out.textContent='Starting training…';
  var name=String((($('voiceName')||{}).value||'')).trim();
  var engine=String((($('engineSel')||{}).value||'')).trim();
  var sample=String((($('sampleText')||{}).value||'')).trim();
  return getClipUrl().then(function(url){
    var payload={name:name, engine:engine, clip_url:String(url||''), sample_text:sample};
    return jsonFetch('/api/voices/train', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
  }).then(function(j){
    if (!j || !j.ok){ if(out) out.innerHTML='<div class="err">Train failed: '+esc((j&&j.error)||'unknown')+'</div>'; return; }
    if(out) out.textContent='Training complete (placeholder). voice_ref set.';
    // Fill save fields
    if($('engine')) $('engine').value = String(j.engine||engine||'');
    if($('voice_ref')) $('voice_ref').value = String(j.voice_ref||'');
    if($('name') && name) $('name').value = name;
    if($('text') && sample) $('text').value = sample;
  }).catch(function(e){ if(out) out.innerHTML='<div class="err">'+esc(String(e))+'</div>'; });
}

function val(id){ var el=$(id); return el?el.value:''; }

function testSample(){
  var payload={engine: val('engine'), voice: val('voice_ref'), text: val('text') || ('Hello. This is ' + (val('name')||val('id')||'a voice') + '.'), upload:true};
  var out=$('out'); if(out) out.textContent='Generating…';
  return jsonFetch('/api/tts', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)})
    .then(function(j){
      var url = (j && (j.url || j.sample_url)) ? (j.url || j.sample_url) : '';
      if (!url){ if(out) out.innerHTML='<div class="err">No URL returned</div>'; return; }
      if(out) out.innerHTML = "<div class='muted'>Sample: <code>" + esc(url) + "</code></div>";
      var a=$('audio');
      if (a){ a.src=url; a.classList.remove('hide'); try{ a.play(); }catch(e){} }
    }).catch(function(e){ if(out) out.innerHTML='<div class="err">'+esc(String(e))+'</div>'; });
}

function saveVoice(){
  var payload={id: val('id'), display_name: val('name'), engine: val('engine'), voice_ref: val('voice_ref'), sample_text: val('text')};
  var out=$('out'); if(out) out.textContent='Saving…';
  return jsonFetch('/api/voices', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)})
    .then(function(j){
      if (!j || !j.ok){ if(out) out.innerHTML='<div class="err">'+esc(j && j.error ? j.error : 'save failed')+'</div>'; return; }
      if(out) out.textContent='Saved.';
      window.location.href='/#tab-voices';
    }).catch(function(e){ if(out) out.innerHTML='<div class="err">'+esc(String(e))+'</div>'; });
}

try{ document.addEventListener('DOMContentLoaded', function(){
  try{ loadEngines(); }catch(e){}
  try{ loadPresets(); }catch(e){}
  try{ setVis(); }catch(e){}
  var cm=$('clipMode'); if(cm) cm.addEventListener('change', setVis);
}); }catch(e){}
</script>
</body>
</html>'''
    html = (html
        .replace('__VOICES_BASE_CSS__', VOICES_BASE_CSS)
        .replace('__VOICE_NEW_EXTRA_CSS__', VOICE_NEW_EXTRA_CSS)
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
        return _get('/v1/metrics', timeout_s=4.0)
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
                m = _get('/v1/metrics', timeout_s=4.0)
                data = json.dumps(m, separators=(',', ':'))
                yield f"data: {data}\n\n"
            except Exception as e:
                # Don't leak secrets; just emit a small error payload.
                yield f"data: {json.dumps({'ok': False, 'error': type(e).__name__})}\n\n"
            time.sleep(2.0)

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

        payload = {'engine': engine, 'voice': voice_ref, 'text': text, 'upload': True}
        r = requests.post(GATEWAY_BASE + '/v1/tts', json=payload, headers=_h(), timeout=120)
        r.raise_for_status()
        j = r.json()
        sample_url = str(j.get('url') or j.get('sample_url') or '')

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
