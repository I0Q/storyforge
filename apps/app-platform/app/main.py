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
from fastapi import Body, FastAPI, HTTPException, Request, UploadFile, File, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.websockets import WebSocketDisconnect

from .auth import register_passphrase_auth
from .ui_header_shared import USER_MENU_HTML, USER_MENU_JS
from .ui_audio_shared import AUDIO_DOCK_JS
from .ui_debug_shared import DEBUG_PREF_APPLY_JS
from .ui_page_shared import render_page
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
# SF_DEPLOY_TOKEN reserved for future deploy pipeline rework
SF_DEPLOY_TOKEN = os.environ.get("SF_DEPLOY_TOKEN", "").strip()

# Web Push (browser/OS notifications)
VAPID_PUBLIC_KEY = os.environ.get('SF_VAPID_PUBLIC_KEY', '').strip()
VAPID_PRIVATE_KEY = os.environ.get('SF_VAPID_PRIVATE_KEY', '').strip()
VAPID_SUBJECT = os.environ.get('SF_VAPID_SUBJECT', 'mailto:admin@example.com').strip()


def _vapid_private_key_material() -> str:
    """Return a pywebpush-compatible VAPID private key.

    DO App Platform env vars sometimes flatten multiline secrets.
    Accept:
    - PEM (with real newlines or with literal "\\n")
    - base64url/raw VAPID key string (as accepted by pywebpush)
    """
    k = str(VAPID_PRIVATE_KEY or '').strip()
    if not k:
        return ''
    # If it looks like PEM but has escaped newlines, unescape them.
    if 'BEGIN ' in k and '\\n' in k:
        k = k.replace('\\n', '\n')
    # If it looks like PEM but is flattened into a single line, try to re-split.
    if k.startswith('-----BEGIN') and ('\n' not in k):
        # Best-effort: insert newlines around header/footer markers.
        k = k.replace('-----BEGIN EC PRIVATE KEY-----', '-----BEGIN EC PRIVATE KEY-----\n')
        k = k.replace('-----END EC PRIVATE KEY-----', '\n-----END EC PRIVATE KEY-----')
        k = k.replace('-----BEGIN PRIVATE KEY-----', '-----BEGIN PRIVATE KEY-----\n')
        k = k.replace('-----END PRIVATE KEY-----', '\n-----END PRIVATE KEY-----')
        # Also wrap base64 body to avoid extremely long lines (not strictly required).
        parts = k.split('\n')
        if len(parts) >= 3:
            hdr = parts[0]
            ftr = parts[-1]
            body = ''.join(parts[1:-1]).strip()
            if body:
                wrapped = '\n'.join([body[i:i+64] for i in range(0, len(body), 64)])
                k = hdr + '\n' + wrapped + '\n' + ftr
    return k

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

# Static assets (local, no CDN)
try:
    _static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")
except Exception:
    pass


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
    button.prodGoBtn{background:linear-gradient(180deg,#26d07c,#15b66a);border-color:rgba(38,208,124,.55);color:#062011;}
    button.prodGoBtn:disabled{opacity:.55;}

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
    .codeBox{background:#070b16;border:1px solid var(--line);border-radius:14px;max-height:55vh;overflow:auto;-webkit-overflow-scrolling:touch;overscroll-behavior:contain;}
    .codeBox{position:relative;}

    /* SFML fullscreen mode (pseudo-fullscreen for iOS) */
    .sfmlFsBtn{position:absolute;right:10px;top:10px;z-index:50;width:36px;height:36px;
      border-radius:12px;border:1px solid rgba(255,255,255,0.12);background:rgba(11,16,32,0.65);
      display:flex;align-items:center;justify-content:center;color:var(--text);cursor:pointer;
      -webkit-backdrop-filter: blur(6px); backdrop-filter: blur(6px);
      pointer-events:auto;
    }
    .sfmlFsBtn svg{width:18px;height:18px;}

    .sfmlFullBackdrop{position:fixed;inset:0;background:rgba(0,0,0,0.55);z-index:99990;}
    .sfmlFull{position:fixed !important;left:0;right:0;top:0;bottom:0;z-index:99991;
      margin:0 !important;border-radius:0 !important;
      height:auto !important;max-height:none !important;
      padding-top:calc(54px + env(safe-area-inset-top, 0px));
      padding-bottom:calc(12px + env(safe-area-inset-bottom, 0px));
    }
    .sfmlFull .sfmlFsBtn{position:fixed;
      right:calc(10px + env(safe-area-inset-right, 0px));
      top:calc(6px + env(safe-area-inset-top, 0px));
      z-index:100011;
    }

    .sfmlFullTopbar{position:fixed;left:0;right:0;top:0;z-index:100010;
      padding:10px 12px;
      padding-top:calc(10px + env(safe-area-inset-top, 0px));
      background:rgba(7,11,22,0.98);
      border-bottom:1px solid rgba(255,255,255,0.10);
      display:flex;align-items:center;gap:10px;
    }
    .sfmlFullTopbar .t{font-weight:950;}
    .sfmlFullTopbar .sp{flex:1 1 auto;}
    .sfmlFullTopbar .sfmlFsBtn{position:absolute;
      right:calc(10px + env(safe-area-inset-right, 0px));
      top:calc(6px + env(safe-area-inset-top, 0px));
      z-index:100011;
    }
    body.sfmlFullOn{overflow:hidden;}

    .codeWrap{font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;font-size:12px;line-height:1.35;min-width:100%;}
    .codeLine{display:grid;grid-template-columns:44px 1fr;gap:12px;padding:2px 12px;}
    .codeLn{color:rgba(168,179,216,0.55);text-align:right;user-select:none;}
    /* Wrap long lines so vertical scrolling is natural on mobile */
    .codeTxt{white-space:pre-wrap;word-break:break-word;overflow-wrap:anywhere;}

    /* editable overlay */
    .codeEdit{position:absolute;inset:0;width:100%;height:100%;padding:0;margin:0;border:0;background:transparent;resize:none;outline:none;
      font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;font-size:12px;line-height:1.35;
      color:transparent;caret-color:var(--text);
      white-space:pre-wrap;word-break:break-word;overflow-wrap:anywhere;
    }
    .codeEdit::selection{background:rgba(74,163,255,0.28);}
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

    /* voice color swatches */
    .swatch{width:16px;height:16px;border-radius:7px;border:1px solid rgba(255,255,255,0.18);box-shadow:0 6px 14px rgba(0,0,0,0.25);flex:0 0 auto;}
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
    .checkLine{display:flex;align-items:center;gap:8px;flex-wrap:wrap;}
    .checkLine input[type=checkbox]{width:18px;height:18px;accent-color:#1f6feb;}
    .checkPill{display:inline-flex;align-items:center;gap:8px;padding:6px 10px;border-radius:999px;background:rgba(255,255,255,0.04);line-height:1;}
    .checkPill input[type=radio], .checkPill input[type=checkbox]{width:18px;height:18px;accent-color:#1f6feb;margin:0;}

    /* Notifications job kinds */
    .notifPill{user-select:none;}
    .notifPill input[type=checkbox]{width:18px;height:18px;accent-color:#1f6feb;}
    .notifKindName{font-weight:700;font-size:13px;word-break:break-word;overflow-wrap:anywhere;}
    .fadeLine{position:relative;display:flex;align-items:center;gap:8px;min-width:0;}
    .fadeText{flex:1;min-width:0;white-space:nowrap;overflow-x:auto;overflow-y:hidden;color:var(--muted);-webkit-overflow-scrolling:touch;scrollbar-width:none;}
    .fadeText::-webkit-scrollbar{display:none;}
        .copyBtn{border:1px solid var(--line);background:transparent;color:var(--text);font-weight:900;border-radius:10px;padding:6px;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;width:34px;height:30px;}
    .copyBtn:active{transform:translateY(1px);}
    .copyBtn svg{width:18px;height:18px;stroke:currentColor;fill:none;stroke-width:2;}
    .copyBtn:hover{background:rgba(255,255,255,0.06);}
    .kvs div.k{color:var(--muted)}
    .hide{display:none}
    /* iOS Safari: <input type=color> won't open when display:none.
       Keep the input in DOM but visually hidden; tap the visible swatch and programmatically click(). */
    /* iOS color input: we intentionally show it briefly next to the swatch (display toggle).
       When hidden (wrapper display:none) it doesn't affect layout; when shown it renders as a tiny swatch. */
    .colorPickWrap{display:inline-block;}
    .colorPickHidden{
      -webkit-appearance:none;
      appearance:none;
      width:16px;
      height:16px;
      border-radius:999px;
      border:1px solid rgba(255,255,255,.16);
      padding:0;
      margin:0;
      background:transparent;
      vertical-align:middle;
      box-shadow:none;
      outline:none;
    }
    .colorPickHidden::-webkit-color-swatch-wrapper{padding:0;border:0;}
    .colorPickHidden::-webkit-color-swatch{border:0;border-radius:999px;}


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
    .brandLink{color:inherit;text-decoration:none;}

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

    /* voice color swatches */
    .swatch{width:16px;height:16px;border-radius:7px;border:1px solid rgba(255,255,255,0.18);box-shadow:0 6px 14px rgba(0,0,0,0.25);flex:0 0 auto;}

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

// Auto-reconnect SSE (iOS/Safari drops EventSource frequently)
let metricsReconnectTimer=null; let metricsReconnectBackoffMs=900;
let metricsIntervalSec=10; // closed dock default
let monitorSheetOpen=false;
function _metricsUrl(){ try{ return '/api/metrics/stream?interval=' + String(Math.max(1, Math.min(30, Number(metricsIntervalSec||10)))); }catch(e){ return '/api/metrics/stream?interval=10'; } }
function setMetricsInterval(sec){
  var s = 10;
  try{ s = Number(sec||10); }catch(e){ s = 10; }
  s = Math.max(1, Math.min(30, s));
  if (Number(metricsIntervalSec||0) === Number(s||0)) return;
  metricsIntervalSec = s;
  if (!monitorEnabled) return;
  // restart stream to apply interval
  startMetricsStream();
}
function _metricsScheduleReconnect(label){
  try{ if(metricsReconnectTimer) return; }catch(e){}
  try{ stopMetricsStream(); }catch(e){}
  try{ var ds=document.getElementById('dockStats'); if(ds) ds.textContent=label||'Reconnecting…'; }catch(e){}
  var delay = Math.max(400, Math.min(10000, Number(metricsReconnectBackoffMs||900)));
  metricsReconnectBackoffMs = Math.min(10000, Math.floor(delay*1.7));
  try{
    metricsReconnectTimer = setTimeout(function(){
      metricsReconnectTimer = null;
      if(!monitorEnabled) return;
      startMetricsStream();
    }, delay);
  }catch(e){}
}

function startMetricsStream(){
  if(!monitorEnabled) return;
  stopMetricsStream();
  try{ if(metricsReconnectTimer){ clearTimeout(metricsReconnectTimer); metricsReconnectTimer=null; } }catch(e){}
  try{ var ds=document.getElementById('dockStats'); if(ds) ds.textContent='Connecting…'; }catch(e){}
  try{
    metricsES=new EventSource(_metricsUrl());
    metricsES.onopen=function(){ metricsReconnectBackoffMs = 900; try{ var ds=document.getElementById('dockStats'); if(ds) ds.textContent='Connected'; }catch(e){} };
    metricsES.onmessage=function(ev){ try{ var m=JSON.parse(ev.data||'{}'); lastMetrics=m; updateMonitorFromMetrics(m);}catch(e){} };
    metricsES.onerror=function(_e){ _metricsScheduleReconnect('Monitor reconnecting…'); };
  }catch(e){ _metricsScheduleReconnect('Monitor reconnecting…'); }
}
function setMonitorEnabled(on){ monitorEnabled=!!on; saveMonitorPref(monitorEnabled); try{ document.documentElement.classList.toggle('monOn', !!monitorEnabled); }catch(e){} if(!monitorEnabled){ stopMetricsStream(); try{ if(metricsReconnectTimer){ clearTimeout(metricsReconnectTimer); metricsReconnectTimer=null; } }catch(e){} try{ var ds=document.getElementById('dockStats'); if(ds) ds.textContent='Monitor off'; }catch(e){} return; } startMetricsStream(); }
function openMonitor(){ if(!monitorEnabled) return; monitorSheetOpen=true; setMetricsInterval(1); var b=document.getElementById('monitorBackdrop'); var sh=document.getElementById('monitorSheet'); if(b){ b.classList.remove('hide'); b.style.display='block'; } if(sh){ sh.classList.remove('hide'); sh.style.display='block'; } try{ document.body.classList.add('sheetOpen'); }catch(e){} startMetricsStream(); if(lastMetrics) updateMonitorFromMetrics(lastMetrics); }
function closeMonitor(){ monitorSheetOpen=false; setMetricsInterval(10); var b=document.getElementById('monitorBackdrop'); var sh=document.getElementById('monitorSheet'); if(b){ b.classList.add('hide'); b.style.display='none'; } if(sh){ sh.classList.add('hide'); sh.style.display='none'; } try{ document.body.classList.remove('sheetOpen'); }catch(e){} }
function closeMonitorEv(ev){ try{ if(ev && ev.stopPropagation) ev.stopPropagation(); }catch(e){} closeMonitor(); return false; }
function bindMonitorClose(){ try{ var btn=document.getElementById('monCloseBtn'); if(btn && !btn.__bound){ btn.__bound=true; btn.addEventListener('touchend', function(ev){ closeMonitorEv(ev); }, {passive:false}); btn.addEventListener('click', function(ev){ closeMonitorEv(ev); }); } }catch(e){} }
try{ document.addEventListener('DOMContentLoaded', function(){ bindMonitorClose(); setMonitorEnabled(loadMonitorPref()); }); }catch(e){}
try{ bindMonitorClose(); setMonitorEnabled(loadMonitorPref()); }catch(e){}
</script>
"""

DEBUG_BANNER_HTML = """
  <div id='boot' class='boot muted'>
    <span id='bootText'><strong>Build</strong>: __BUILD__ • JS: booting…</span>
    <div id='bootDeploy' class='hide' style='flex:1 1 auto; min-width:200px; margin-left:12px'>
      <div class='muted' style='font-weight:950'>StoryForge updating...</div>
      <div class='updateTrack' style='margin-top:6px;position:relative'>
        <div class='updateProg'></div>
        <div id='bootDeployTimer' style='position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:950;font-size:12px;letter-spacing:0.2px;text-shadow:0 2px 10px rgba(0,0,0,0.6);pointer-events:none'>0:00</div>
      </div>
    </div>
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
</script>
<script src="/static/debug_boot.js?v=__BUILD__"></script>
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
  <link rel="manifest" href="/manifest.webmanifest" />
  <meta name="theme-color" content="#0b1020" />
  <link rel="stylesheet" href="/static/sfml_editor.css?v=5" />
  <script src="/static/sfml_editor.js?v=7"></script>
  __DEBUG_BANNER_BOOT_JS__
  __USER_MENU_JS__
  <script>
  // Register service worker for Web Push (required for iOS PWA push)
  (function(){
    try{
      if (!('serviceWorker' in navigator)) return;
      navigator.serviceWorker.register('/sw.js').catch(function(_e){});
    }catch(_e){}
  })();

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
      <!-- updating bar moved to debug area -->
    </div>
    <div class='row rowEnd'>
      <a id='todoBtn' href='/todo' class='hide'><button class='secondary' type='button'>TODO</button></a>
      __USER_MENU_HTML__

    </div>
  </div>

  </div>

  __DEBUG_BANNER_HTML__

  __AUDIO_DOCK_JS__

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
      <div style='font-weight:950;margin-bottom:6px;'>1) Story</div>
      <select id='prodStorySel' style='margin-top:8px;width:100%;font-size:16px;padding-top:12px;padding-bottom:12px;'></select>
    </div>

    <div class='card'>
      <div class='row' style='justify-content:space-between;gap:10px;align-items:center'>
        <div style='font-weight:950;margin-bottom:6px;'>2) Casting</div>
        <button type='button' class='secondary' onclick='prodSuggestCasting()'>Suggest casting</button>
      </div>
      <div class='row' style='justify-content:flex-start;gap:10px;flex-wrap:wrap;align-items:center;margin-top:6px'>
        <div class='muted' style='font-size:12px'>Casting engine</div>
        <label class='checkPill' style='padding:6px 10px;'><input type='radio' name='castEngine' value='tortoise' checked/>tortoise</label>
        <label class='checkPill' style='padding:6px 10px;'><input type='radio' name='castEngine' value='styletts2'/>styletts2</label>
      </div>

      <div id='prodBusy' class='updateBar hide' style='margin-top:10px'>
        <div class='muted' style='font-weight:950' id='prodBusyTitle'>Working…</div>
        <div class='updateTrack'><div class='updateProg'></div></div>
        <div id='prodBusySub' class='muted'>Please wait</div>
      </div>

      <div id='prodOut' class='muted' style='margin-top:10px'></div>
      <div id='prodAssignments' style='margin-top:10px'></div>
    </div>

    <div class='card'>
      <div class='row' style='justify-content:space-between;gap:10px;align-items:baseline'>
        <div style='font-weight:950;margin-bottom:6px;'>3) SFML</div>
        <div class='row' style='justify-content:flex-end;gap:10px;flex-wrap:wrap'>
          <button type='button' id='prodStep3Btn' disabled onclick='prodGenerateSfml()'>Generate SFML</button>
          <button type='button' id='prodProduceBtn' class='prodGoBtn' disabled onclick='prodProduceAudio()'>Produce</button>
        </div>
      </div>

      <div id='prodSfmlBusy' class='updateBar hide' style='margin-top:10px'>
        <div class='muted' style='font-weight:950' id='prodSfmlBusyTitle'>Working…</div>
        <div class='updateTrack'><div class='updateProg'></div></div>
        <div id='prodSfmlBusySub' class='muted'>Please wait</div>
      </div>

      <div class='muted' style='margin-top:8px'>Edit inline (autosaves on pause/blur).</div>
      <div id='prodSfmlBox' class='codeBox hide' style='margin-top:10px;max-height:none;height:55vh;'></div>
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
      <div style='font-weight:950;margin-bottom:6px;'>Notifications</div>
      <div class='muted'>Browser/OS push notifications for job completion (completed or failed). iOS requires Add to Home Screen.</div>
      <div id='notifOut' class='muted' style='margin-top:8px'>Loading…</div>
      <div class='row' style='margin-top:10px;gap:12px;flex-wrap:wrap'>
        <button id='notifEnableBtn' type='button' onclick='notifEnable()'>Enable on this device</button>
        <button id='notifDisableBtn' class='secondary' type='button' onclick='notifDisable()'>Disable on this device</button>
        <button id='notifTestBtn' class='secondary' type='button' onclick='notifTest()'>Send test notification</button>
      </div>
      <div style='margin-top:12px;font-weight:950;'>Job types</div>
      <div class='muted'>Select which job kinds trigger a push on completion.</div>
      <div id='notifKinds' style='margin-top:8px'></div>
      <div class='row' style='margin-top:10px;justify-content:flex-end'>
        <button class='secondary' type='button' onclick='notifSaveKinds()'>Save notification settings</button>
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

// If the boot banner script fails to run (some Safari edge cases), don't leave it stuck on 'booting…'.
try{
  setTimeout(function(){
    try{
      var bt=document.getElementById('bootText');
      if (!bt) return;
      var t=String(bt.textContent||'');
      if (t.indexOf('JS: booting')!==-1){
        bt.textContent = t.replace('JS: booting…','JS: ok').replace('JS: booting...','JS: ok');
      }
    }catch(_e){}
  }, 0);
}catch(_e){}

/* floating audio dock is injected from ui_audio_shared.py */

function showTab(name, opts){
  opts = opts || {};
  for (var i=0;i<['history','library','voices','production','advanced'].length;i++){
    var n=['history','library','voices','production','advanced'][i];
    document.getElementById('pane-'+n).classList.toggle('hide', n!==name);
    document.getElementById('tab-'+n).classList.toggle('active', n===name);
  }
  // persist in URL hash without triggering iOS scroll-to-top
  try{
    if (!opts.noHash){
      var h = '#tab-' + name;
      if (window.location.hash !== h){
        var y = 0;
        try{ y = window.scrollY || window.pageYOffset || 0; }catch(e){ y = 0; }
        try{
          if (history && history.replaceState) history.replaceState(null, '', h);
          else window.location.hash = h;
        }catch(_e){
          try{ window.location.hash = h; }catch(__e){}
        }
        // Some iOS builds still jump; restore.
        try{ setTimeout(function(){ try{ window.scrollTo(0, y); }catch(e){} }, 0); }catch(e){}
      }
    }
  }catch(_e){}

  try{ var pn=document.getElementById('pageName'); if(pn){ pn.textContent = (name==='history'?'Jobs':(name==='library'?'Library':(name==='voices'?'Voices':(name==='production'?'Production':'Settings')))); } }catch(e){}

  // lazy-load tab content
  try{
    if (name==='history') { try{ bindJobsLazyScroll(); }catch(e){}; loadHistory(true); }
    else if (name==='library') loadLibrary();
    else if (name==='voices') loadVoices();
    else if (name==='production') loadProduction();
    else if (name==='advanced') { try{ notifLoad(); }catch(e){} }
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
// toggleUserMenu is provided by ui_header_shared.USER_MENU_JS (fixed-position iOS-safe dropdown)

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

function jobAbort(jobId){
  try{
    jobId = String(jobId||'').trim();
    if (!jobId) return;
    if (!confirm('Abort job ' + jobId + '?')) return;
    fetchJsonAuthed('/api/jobs/abort', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({id: jobId})
    }).then(function(j){
      if (!j || !j.ok) throw new Error((j&&j.error)||'abort_failed');
      try{ toastShowNow('Aborted', 'ok', 1800); }catch(_e){}
      // refresh quickly
      try{ loadHistory(true); }catch(_e){}
    }).catch(function(e){
      try{ toastShowNow('Abort failed: ' + String(e&&e.message?e.message:e), 'err', 2400); }catch(_e){}
    });
  }catch(e){}
}

// --- Notifications (Web Push) ---
function notifDeviceId(){
  try{
    var k='sf_notif_device_id';
    var v=localStorage.getItem(k) || '';
    if (!v){
      v = 'dev_' + String(Date.now()) + '_' + String(Math.floor(Math.random()*1e9));
      localStorage.setItem(k, v);
    }
    return v;
  }catch(e){
    return 'dev_' + String(Date.now());
  }
}

function notifKindsList(){
  // Known job kinds (expand over time)
  return ['produce_audio','tts_sample','voice_meta','deploy','other'];
}

function notifRenderKinds(selected){
  try{
    selected = selected || {};
    var host=document.getElementById('notifKinds');
    if (!host) return;
    var kinds = notifKindsList();
    var h="<div class='checkLine' style='margin-top:6px'>";
    for (var i=0;i<kinds.length;i++){
      var k = kinds[i];
      var on = !!selected[k];
      // Render as pills (same visual language as provider engine pills)
      h += "<label class='checkPill notifPill'>"
        + "<input type='checkbox' data-kind='"+escAttr(k)+"' " + (on?'checked':'') + " />"
        + "<span class='notifKindName'>"+escapeHtml(k)+"</span>"
        + "</label>";
    }
    h += "</div>";
    host.innerHTML = h;
  }catch(e){}
}

function notifSelectedKinds(){
  var out=[];
  try{
    var host=document.getElementById('notifKinds');
    if (!host) return out;
    var els=host.querySelectorAll('input[type=checkbox][data-kind]');
    for (var i=0;i<els.length;i++){
      var el=els[i];
      if (el && el.checked){ out.push(String(el.getAttribute('data-kind')||'')); }
    }
  }catch(e){}
  return out;
}

function notifOut(msg, kind){
  try{
    var el=document.getElementById('notifOut');
    if (!el) return;
    el.className = 'muted';
    if (kind==='err') el.className = 'err';
    el.textContent = String(msg||'');
  }catch(e){}
}

function notifLoad(){
  notifOut('Loading…');
  // render default kinds first
  var defSel={};
  try{ var ks=notifKindsList(); for (var i=0;i<ks.length;i++) defSel[ks[i]] = (ks[i]==='produce_audio'); }catch(_e){}
  notifRenderKinds(defSel);

  return fetchJsonAuthed('/api/notifications/settings?device_id='+encodeURIComponent(notifDeviceId()))
    .then(function(j){
      if (!j || !j.ok){ throw new Error((j&&j.error)||'load_failed'); }
      var enabled = !!j.enabled;
      var kinds = Array.isArray(j.job_kinds) ? j.job_kinds : [];
      var sel={};
      for (var i=0;i<kinds.length;i++) sel[String(kinds[i])] = true;
      notifRenderKinds(sel);
      notifOut(enabled ? 'Notifications enabled on this device.' : 'Notifications not enabled on this device.');
    })
    .catch(function(e){
      notifOut('Notifications unavailable: '+String(e&&e.message?e.message:e), 'err');
    });
}

function notifSaveKinds(){
  try{
    var kinds = notifSelectedKinds();
    notifOut('Saving…');
    return fetchJsonAuthed('/api/notifications/settings', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({device_id:notifDeviceId(), job_kinds:kinds})})
      .then(function(j){
        if (!j || !j.ok) throw new Error((j&&j.error)||'save_failed');
        notifOut('Saved.');
      })
      .catch(function(e){ notifOut('Save failed: '+String(e&&e.message?e.message:e), 'err'); });
  }catch(e){ notifOut('Save failed', 'err'); }
}

function notifEnable(){
  // subscribe this device
  notifOut('Enabling…');
  if (!('serviceWorker' in navigator) || !('PushManager' in window)){
    notifOut('Push not supported in this browser.', 'err');
    return;
  }

  navigator.serviceWorker.ready.then(function(reg){
    return fetchJsonAuthed('/api/notifications/vapid_public').then(function(j){
      if (!j || !j.ok || !j.public_key){ throw new Error((j&&j.error)||'missing_vapid_public'); }
      function urlBase64ToUint8Array(base64String){
        base64String = String(base64String||'');
        var padding = '='.repeat((4 - base64String.length % 4) % 4);
        var base64 = (base64String + padding).replace(/\-/g, '+').replace(/_/g, '/');
        var rawData = atob(base64);
        var outputArray = new Uint8Array(rawData.length);
        for (var i = 0; i < rawData.length; ++i) outputArray[i] = rawData.charCodeAt(i);
        return outputArray;
      }
      return reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(j.public_key) });
    }).then(function(sub){
      var kinds = notifSelectedKinds();
      return fetchJsonAuthed('/api/notifications/subscribe', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({device_id:notifDeviceId(), subscription: sub, job_kinds: kinds, ua: (navigator.userAgent||'')})});
    }).then(function(resp){
      if (!resp || !resp.ok) throw new Error((resp&&resp.error)||'subscribe_failed');
      notifOut('Enabled.');
    });
  }).catch(function(e){
    notifOut('Enable failed: '+String(e&&e.message?e.message:e), 'err');
  });
}

function notifDisable(){
  notifOut('Disabling…');
  if (!('serviceWorker' in navigator)){
    notifOut('Disabled.');
    return;
  }
  navigator.serviceWorker.ready.then(function(reg){
    return reg.pushManager.getSubscription().then(function(sub){
      if (!sub) return null;
      return sub.unsubscribe().then(function(){ return sub; });
    }).then(function(sub){
      return fetchJsonAuthed('/api/notifications/unsubscribe', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({device_id:notifDeviceId(), endpoint: sub ? sub.endpoint : ''})});
    }).then(function(_j){
      notifOut('Disabled.');
    });
  }).catch(function(e){ notifOut('Disable failed: '+String(e&&e.message?e.message:e), 'err'); });
}

function notifTest(){
  notifOut('Sending test…');
  return fetchJsonAuthed('/api/notifications/test', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({device_id:notifDeviceId()})})
    .then(function(j){
      if (!j || !j.ok) throw new Error((j&&j.error)||'test_failed');
      notifOut('Test sent.');
    })
    .catch(function(e){ notifOut('Test failed: '+String(e&&e.message?e.message:e), 'err'); });
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
    __sfPlayAudio(String(url), 'Job ' + String(jobId));
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
      color_hex: String(meta.color_hex||''),
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

function saveJobToStoryAudio(jobId){
  try{
    var card=document.querySelector('[data-jobid="'+jobId+'"]');
    var meta = safeJson(card ? card.getAttribute('data-meta') : '');
    var url = card ? String(card.getAttribute('data-url')||'') : '';
    if (!meta || !url){ alert('Missing job metadata'); return; }

    var storyId = String(meta.story_id||'').trim();
    if (!storyId){ alert('Missing story_id on job'); return; }

    var payload = {job_id: String(jobId||''), story_id: storyId, mp3_url: url, meta_json: JSON.stringify(meta||{})};

    var btn = card ? card.querySelector('.saveStoryAudioBtn') : null;
    if (btn) btn.textContent='Saving…';

    fetchJsonAuthed('/api/library/story_audio/save', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)})
      .then(function(j){
        if (!j || !j.ok){ throw new Error((j&&j.error)||'save_failed'); }
        try{ localStorage.setItem('sf_story_audio_saved_'+String(jobId||''), '1'); }catch(_e){}
        try{ toastSet('Saved to library', 'ok', 1400); window.__sfToastInit && window.__sfToastInit(); }catch(_e){}
        if (btn){ btn.textContent='Saved'; btn.disabled=true; }
      })
      .catch(function(e){ if(btn){ btn.textContent='Save'; btn.disabled=false; } alert('Save failed: '+String(e)); });
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

function fmtDurSec(s){
  try{
    s = Number(s||0);
    if (!(s>=0)) return '-';
    var h = Math.floor(s/3600);
    var m = Math.floor((s%3600)/60);
    var ss = Math.floor(s%60);
    if (h>0) return String(h)+':' + String(m).padStart(2,'0') + ':' + String(ss).padStart(2,'0');
    return String(m)+':' + String(ss).padStart(2,'0');
  }catch(e){
    return '-';
  }
}

function jobElapsed(job){
  try{
    var st = Number(job.started_at||0);
    if (!st) return 0;
    var fin = Number(job.finished_at||0);
    var end = fin ? fin : Math.floor(Date.now()/1000);
    var d = end - st;
    if (d < 0) d = 0;
    return d;
  }catch(e){
    return 0;
  }
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
    let done = Number(job.segments_done||0);
    const isDone = (String(job.state||'') === 'completed' || String(job.state||'') === 'failed');
    // Defensive: if worker only reported total (or Safari missed updates), show 100% on terminal states.
    if (isDone && total && (!done || done < 0)) done = total;
    const pct = total ? Math.max(0, Math.min(100, (done/total*100))) : 0;
    const progText = total ? `${done} / ${total} (${pct.toFixed(0)}%)` : '-';
    const progBar = (!isDone && total) ? `<div class='bar small' style='margin-top:6px'><div style='width:${pct.toFixed(1)}%'></div></div>` : '';

    const meta = safeJson(job.meta_json||'') || null;
    const isSample = (String(job.kind||'') === 'tts_sample') || (String(job.title||'').indexOf('TTS (')===0);
    const isProduce = (String(job.kind||'') === 'produce_audio');
    const playable = (String(job.state||'')==='completed' && job.mp3_url);

    const actions = (function(){
      var h = '';

      const runningish = (String(job.state||'')==='running' || String(job.state||'')==='queued');
      const abortable = runningish && (isSample || isProduce || isVoiceMeta);
      if (abortable){
        h += `<div style='margin-top:10px;display:flex;gap:10px;flex-wrap:wrap;'>`
          + `<button type='button' class='secondary' onclick="jobAbort('${escAttr(job.id||'')}')">Abort</button>`
          + `</div>`;
      }

      if (!(playable && (isSample || isProduce))) return h;

      var btn2 = '';
      if (isSample){
        try{
          var saved = false;
          try{ saved = (localStorage.getItem('sf_job_saved_'+String(job.id||'')) === '1'); }catch(_e){}
          if (saved) btn2 = `<button type='button' class='saveRosterBtn' disabled>Saved</button>`;
          else btn2 = (meta ? `<button type='button' class='saveRosterBtn' onclick="saveJobToRoster('${escAttr(job.id||'')}')">Save to roster</button>` : `<button type='button' class='saveRosterBtn' onclick="alert('This older job is missing metadata. Re-run Test sample once and then Save will appear here.')">Save to roster</button>`);
        }catch(_e){ btn2=''; }
      }
      if (isProduce){
        try{
          var saved2 = false;
          try{ saved2 = (localStorage.getItem('sf_story_audio_saved_'+String(job.id||'')) === '1'); }catch(_e){}
          if (saved2) btn2 = `<button type='button' class='saveStoryAudioBtn' disabled>Saved</button>`;
          else btn2 = (meta ? `<button type='button' class='saveStoryAudioBtn' onclick="saveJobToStoryAudio('${escAttr(job.id||'')}')">Save</button>` : `<button type='button' class='saveStoryAudioBtn' onclick="alert('Missing metadata (story_id).')">Save</button>`);
        }catch(_e){ btn2=''; }
      }

      h += (
        `<div style='margin-top:10px;display:flex;gap:10px;flex-wrap:wrap;'>`
        + `<button type='button' class='secondary' onclick="jobPlay('${escAttr(job.id||'')}','${escAttr(job.mp3_url||'')}')">Play</button>`
        + btn2
        + `</div>`
      );
      return h;
    })();

    const voiceName = (meta && (meta.display_name || meta.voice_name || meta.name || meta.roster_id || meta.id)) ? String(meta.display_name || meta.voice_name || meta.name || meta.roster_id || meta.id) : '';
    const cardTitle = isSample ? ((job.title ? String(job.title) : 'Voice sample') + (voiceName ? (' • ' + voiceName) : '')) : (job.title||job.id);

    const errVal = (job && job.error_text) ? String(job.error_text||'') : '';
    const errRow = (String(job.state||'')==='failed' && errVal) ? (
      `<div class='k'>error</div><div class='term' style='white-space:pre-wrap'>${escapeHtml(errVal.slice(0,1600))}</div>`
    ) : '';

    const isVoiceMeta = (String(job.kind||'') === 'voice_meta');

    // Common fields for all jobs
    const elapsed = jobElapsed(job);
    let rows = ''
      + `<div class='k'>id</div><div>${escapeHtml(String(job.id||''))}</div>`
      + `<div class='k'>started</div><div>${fmtTs(job.started_at)}</div>`
      + `<div class='k'>finished</div><div>${fmtTs(job.finished_at)}</div>`
      + `<div class='k'>elapsed</div><div>${fmtDurSec(elapsed)}</div>`
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
        const s = String(job.sfml_url||'');
        const isUrl = (s.startsWith('http://') || s.startsWith('https://'));
        const key = isUrl ? 'sfml' : 'runtime';
        rows += `<div class='k'>${key}</div><div class='fadeLine'><div class='fadeText' title='${s||""}'>${s||'-'}</div>${s?`<button class="copyBtn" data-copy="${s}" onclick="copyFromAttr(this)" aria-label="Copy">${copyIconSvg()}</button>`:''}</div>`;
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
let __SF_JOBS_POLL_T = null;
function startJobsPoll(){
  try{
    if (__SF_JOBS_POLL_T) return;
    __SF_JOBS_POLL_T = setInterval(function(){
      try{
        // Fallback poll for iOS/Safari when EventSource is flaky.
        fetchJsonAuthed('/api/history?limit=60').then(function(j){
          if (j && j.ok && Array.isArray(j.jobs)) renderJobs(j.jobs);
        }).catch(function(_e){});
      }catch(_e){}
    }, 4000);
  }catch(e){}
}
function stopJobsPoll(){ try{ if(__SF_JOBS_POLL_T){ clearInterval(__SF_JOBS_POLL_T); __SF_JOBS_POLL_T=null; } }catch(e){} }

function startJobsStream(){
  try{ if ((window.__SF_JOBS_STREAM_PAUSED_UNTIL||0) > Date.now()) return; }catch(e){}
  try{ if (jobsES){ jobsES.close(); jobsES=null; } }catch(e){}
  try{
    jobsES = new EventSource('/api/jobs/stream');
    jobsES.onmessage = function(ev){
      try{
        stopJobsPoll();
        var j = JSON.parse(ev.data || '{}');
        if (j && j.ok && Array.isArray(j.jobs)) renderJobs(j.jobs);
      }catch(e){}
    };
    jobsES.onerror = function(_e){
      // Fall back to polling; EventSource will also attempt reconnect.
      try{ startJobsPoll(); }catch(e){}
    };
    // Start poll immediately; stop once SSE delivers.
    startJobsPoll();
  }catch(e){
    try{ startJobsPoll(); }catch(_e){}
  }
}

let metricsES = null;
let monitorEnabled = true;
let lastMetrics = null;
let metricsIntervalSec = 10; // 10s by default (dock closed)
function _metricsUrl(){
  try{
    var s = Number(metricsIntervalSec||10);
    if (!isFinite(s) || s<=0) s = 10;
    s = Math.max(1, Math.min(30, s));
    return '/api/metrics/stream?interval=' + String(s);
  }catch(e){
    return '/api/metrics/stream?interval=10';
  }
}
function setMetricsInterval(sec){
  try{
    var s = Number(sec||10);
    if (!isFinite(s) || s<=0) s = 10;
    s = Math.max(1, Math.min(30, s));
    if (Number(metricsIntervalSec||0) === Number(s||0)) return;
    metricsIntervalSec = s;
    if (monitorEnabled) startMetricsStream();
  }catch(e){}
}

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

  // When toggling debug back on, re-kick background streams/watchers.
  // (Some mobile browsers may drop EventSource connections while the UI is hidden.)
  try{
    if (on){
      try{ if (typeof __sfStartDeployWatch==='function') __sfStartDeployWatch(); }catch(e){}
      try{ if (typeof startJobsStream==='function') startJobsStream(); }catch(e){}
      try{ if (typeof startMetricsStream==='function' && (typeof monitorEnabled==='undefined' || monitorEnabled)) startMetricsStream(); }catch(e){}
    }
  }catch(_e){}
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

function _metricsUrl2(){
  // SPA monitor: interval controlled by open/close (10s dock, 1s sheet)
  try{
    var s = Number(metricsIntervalSec||10);
    if (!isFinite(s) || s<=0) s = 10;
    s = Math.max(1, Math.min(30, s));
    return '/api/metrics/stream?interval=' + String(s);
  }catch(e){
    return '/api/metrics/stream?interval=10';
  }
}
function startMetricsStream(){
  if (!monitorEnabled) return;
  stopMetricsStream();
  try{ if (typeof stopMetricsPoll==='function') try{ if (typeof stopMetricsPoll==='function') stopMetricsPoll(); }catch(e){} }catch(e){}
  // SSE stream (server pushes metrics continuously)
  metricsES = new EventSource(_metricsUrl2());
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

// voiceColorHex removed; color swatches are server-provided.

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
        "<label class='checkPill'><input type='checkbox' class='engCb' data-pid='"+escAttr(id)+"' data-engine='styletts2' "+(voiceEng.indexOf('styletts2')>=0?'checked':'')+" onchange='onEngineToggle(this)'/>styletts2</label>"+
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

function prodGetCastEngine(){
  var eng='';
  try{
    var r=document.querySelector("input[name='castEngine']:checked");
    if (r && r.value) eng = String(r.value||'').trim();
  }catch(_e){}
  return eng || 'tortoise';
}

function prodSetCastEngine(eng, persist){
  eng = String(eng||'').trim();
  if (eng!=='tortoise' && eng!=='styletts2') eng = 'tortoise';
  try{
    var rs=document.querySelectorAll("input[name='castEngine']");
    for (var i=0;i<rs.length;i++){
      var r=rs[i];
      r.checked = (String(r.value||'')===eng);
    }
  }catch(_e){}
  if (persist){
    try{ localStorage.setItem('sf_cast_engine', eng); }catch(_e){}
  }
}

function prodInitCastEngine(){
  try{
    // restore from localStorage on first render
    var eng='';
    try{ eng = String(localStorage.getItem('sf_cast_engine')||'').trim(); }catch(_e){}
    if (eng) prodSetCastEngine(eng, false);

    // persist on change
    var rs=document.querySelectorAll("input[name='castEngine']");
    for (var i=0;i<rs.length;i++){
      rs[i].onchange = function(){ try{ prodSetCastEngine(prodGetCastEngine(), true); }catch(_e){} };
    }
  }catch(_e){}
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

      // init engine choice persistence
      try{ prodInitCastEngine(); }catch(_e){}

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
    prodSetBusy(true, 'Loading…', 'Fetching saved casting and SFML');
    fetchJsonAuthed('/api/production/casting/'+encodeURIComponent(sid)).then(function(j){
      if (!j || !j.ok) { prodSetBusy(false); return; }
      window.__SF_PROD.story_id = sid;
      window.__SF_PROD.roster = j.roster || [];
      window.__SF_PROD.assignments = (j.assignments||[]).map(function(a){ return {character:String(a.character||''), voice_id:String(a.voice_id||''), reason:String(a.reason||''), _editing:false}; });
      window.__SF_PROD.saved = !!j.saved;
      try{
        // Prefer saved engine from server; otherwise fall back to localStorage
        if (j.engine) prodSetCastEngine(String(j.engine||''), true);
      }catch(_e){}
      if (out) out.textContent='';
      prodRenderAssignments();

      // Load persisted SFML (if any)
      try{
        fetchJsonAuthed('/api/library/story/'+encodeURIComponent(sid)).then(function(j2){
          try{
            var st = (j2 && j2.ok) ? (j2.story||{}) : {};
            var sfml = String(st.sfml_text||'');
            if (sfml){
              window.__SF_PROD.sfml = sfml;
              prodRenderSfml(sfml);
            }
          }catch(_e){}
        }).catch(function(_e){});
      }catch(_e){}

      prodSetBusy(false);

    }).catch(function(_e){ prodSetBusy(false); });
  }catch(e){}
}

window.__SF_PROD = window.__SF_PROD || { roster:[], assignments:[], story_id:'', saved:false, sfml:'' };

function prodSetBusy(on, title, sub){
  try{
    var box=document.getElementById('prodBusy');
    var t=document.getElementById('prodBusyTitle');
    var s=document.getElementById('prodBusySub');
    if (!box) return;
    if (on){
      box.classList.remove('hide');
      if (t) t.textContent = title || 'Working…';
      if (s) s.textContent = sub || 'Please wait';
    }else{
      box.classList.add('hide');
    }
  }catch(e){}
}

function prodSetSfmlBusy(on, title, sub){
  try{
    var box=document.getElementById('prodSfmlBusy');
    var t=document.getElementById('prodSfmlBusyTitle');
    var s=document.getElementById('prodSfmlBusySub');
    if (!box) return;
    if (on){
      box.classList.remove('hide');
      if (t) t.textContent = title || 'Working…';
      if (s) s.textContent = sub || 'Please wait';
    }else{
      box.classList.add('hide');
    }
  }catch(e){}
}


function prodRenderAssignments(){
  try{
    var box=document.getElementById('prodAssignments');
    var saveBtn=null;
    var step3=document.getElementById('prodStep3Btn');
    var prodBtn=document.getElementById('prodProduceBtn');
    if (!box) return;

    var st = window.__SF_PROD || {};
    var roster = Array.isArray(st.roster) ? st.roster : [];
    var assigns = Array.isArray(st.assignments) ? st.assignments : [];

    function getCastEngine(){
      var eng = '';
      try{
        var r1=document.querySelector("input[name='castEngine']:checked");
        if (r1 && r1.value) eng = String(r1.value||'').trim();
      }catch(_e){}
      return eng;
    }

    // helper: roster option list (filtered by selected engine)
    function optList(selected){
      var eng = getCastEngine();
      var rr = roster;
      try{
        if (eng){ rr = roster.filter(function(v){ return String(v.engine||'').trim()===eng; }); }
      }catch(_e){ rr = roster; }
      return rr.map(function(v){
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
      var voiceHex = '';
      try{
        var v = roster.find(function(x){ return String(x.id||'')===vid; });
        voiceName = v ? String(v.name||v.id||'') : vid;
        voiceHex = v ? String(v.color_hex||'').trim() : '';
      }catch(_e){}
      if (!voiceHex) voiceHex = '#64748b';

      var top = "<div class='row' style='justify-content:space-between;gap:10px'>"
        + "<div style='font-weight:950'>"+escapeHtml(ch||('Character '+(idx+1)))+"</div>"
        + "<div>" + (editing ? "<button class='secondary' type='button' onclick='prodCancelEdit("+idx+")'>Cancel</button>" : "<button class='secondary' type='button' onclick='prodEditAssign("+idx+")'>Edit</button>") + "</div>"
        + "</div>";

      var body = '';
      if (editing){
        body += "<div class='row' style='gap:10px;flex-wrap:nowrap;align-items:center;margin-top:10px'>"
          + "<div class='muted' style='flex:0 0 auto'>played by</div>"
          + "<span class='swatch' style='background:"+escAttr(voiceHex)+"'></span>"
          + "<select style='flex:1;min-width:0' onchange='prodSetVoice("+idx+", this.value)'>" + optList(vid) + "</select>"
          + "</div>";
      }else{
        body += "<div class='row' style='gap:10px;flex-wrap:nowrap;align-items:center;margin-top:10px'>"
          + "<div class='muted' style='flex:0 0 auto'>played by</div>"
          + "<span class='swatch' style='background:"+escAttr(voiceHex)+"'></span>"
          + "<div style='min-width:0'>"+escapeHtml(voiceName||'—')+"</div>"
          + "</div>";
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

    // Step 3 + Produce enabled when casting is saved.
    try{ if (step3) step3.disabled = (!st.saved); }catch(_e){}
    try{ if (prodBtn) prodBtn.disabled = (!st.saved); }catch(_e){}
  }catch(e){}
}

function prodEditAssign(i){
  try{ window.__SF_PROD.assignments[i]._editing=true; window.__SF_PROD.saved=false; prodRenderAssignments(); }catch(e){}
}
function prodCancelEdit(i){
  try{ window.__SF_PROD.assignments[i]._editing=false; prodRenderAssignments(); }catch(e){}
}
window.__SF_CAST_SAVE_T = null;

function prodCastAutosaveArm(){
  try{
    if (window.__SF_CAST_SAVE_T) clearTimeout(window.__SF_CAST_SAVE_T);
    window.__SF_CAST_SAVE_T = setTimeout(function(){
      try{ prodSaveCasting(true); }catch(_e){}
    }, 900);
  }catch(e){}
}

function prodSetVoice(i, voiceId){
  try{
    window.__SF_PROD.assignments[i].voice_id = String(voiceId||'');
    window.__SF_PROD.saved=false;
    // re-render so swatch updates immediately
    try{ prodRenderAssignments(); }catch(_e){}
    prodCastAutosaveArm();
  }catch(e){}
}

function prodSuggestCasting(){
  try{
    var sel=document.getElementById('prodStorySel');
    var out=document.getElementById('prodOut');
    var storyId = sel ? String(sel.value||'').trim() : '';
    if (!storyId){ if(out) out.innerHTML='<div class="err">Pick a story</div>'; return; }
    prodSetBusy(true, 'Suggesting casting…', 'Asking the LLM to match voices to characters');
    if (out) out.textContent='';

    var eng = 'tortoise';
    try{
      var r1=document.querySelector("input[name='castEngine']:checked");
      if (r1 && r1.value) eng = String(r1.value||'').trim() || 'tortoise';
    }catch(e){}
    fetchJsonAuthed('/api/production/suggest_casting', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({story_id: storyId, engine: eng})})
      .then(function(j){
        if (!j || !j.ok){ throw new Error((j&&j.error)||'suggest_failed'); }
        prodSetBusy(false);
        if (out) out.textContent='';
        window.__SF_PROD.story_id = storyId;
        window.__SF_PROD.roster = j.roster || [];
        window.__SF_PROD.assignments = ((j.suggestions||{}).assignments || []).map(function(a){
          return { character: String(a.character||''), voice_id: String(a.voice_id||''), reason: String(a.reason||''), _editing:false };
        });
        window.__SF_PROD.saved = false;
        prodRenderAssignments();
        // Autosave immediately after new suggestion
        try{ prodSaveCasting(true); }catch(_e){}
      })
      .catch(function(e){ prodSetBusy(false); if(out) out.innerHTML='<div class="err">'+escapeHtml(String(e&&e.message?e.message:e))+'</div>'; });
  }catch(e){}
}

function prodSaveCasting(silent){
  try{
    silent = !!silent;
    var out=document.getElementById('prodOut');
    var box=document.getElementById('prodSfmlBox');
    var st = window.__SF_PROD || {};
    if (!st.story_id) { if(out && !silent) out.innerHTML='<div class="err">Pick a story</div>'; return; }
    var assigns = Array.isArray(st.assignments) ? st.assignments : [];
    if (!assigns.length){ if(out && !silent) out.innerHTML='<div class="err">No assignments</div>'; return; }

    prodSetBusy(true, 'Saving casting…', 'Autosaving your casting choices');
    if (out) out.textContent='';
    var payload = { story_id: String(st.story_id), engine: prodGetCastEngine(), assignments: assigns.map(function(a){ return {character:a.character, voice_id:a.voice_id}; }) };

    fetchJsonAuthed('/api/production/casting_save', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)})
      .then(function(j){
        if (!j || !j.ok){ throw new Error((j&&j.error)||'save_failed'); }
        prodSetBusy(false);
        if (out && !silent) out.textContent='Saved.';
        window.__SF_PROD.saved = true;
        window.__SF_PROD.sfml = '';
        try{ if (box){ box.classList.add('hide'); box.innerHTML=''; } }catch(_e){}
        prodRenderAssignments();
      })
      .catch(function(e){ prodSetBusy(false); if(out && !silent) out.innerHTML='<div class="err">'+escapeHtml(String(e&&e.message?e.message:e))+'</div>'; });
  }catch(e){}
}

function prodGenerateSfml(){
  try{
    var out=document.getElementById('prodOut');
    var st = window.__SF_PROD || {};
    if (!st.saved){ if(out) out.innerHTML='<div class="err">Save casting first</div>'; return; }
    var sid = String(st.story_id||'').trim();
    if (!sid){ if(out) out.innerHTML='<div class="err">Pick a story</div>'; return; }

    prodSetSfmlBusy(true, 'Generating SFML…', 'Asking the LLM to produce a full script');
    if (out) out.textContent='';
    fetchJsonAuthed('/api/production/sfml_generate', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({story_id:sid})})
      .then(function(j){
        if (!j || !j.ok || !j.sfml){ throw new Error((j&&j.error)||'sfml_failed'); }
        prodSetSfmlBusy(false);
        window.__SF_PROD.sfml = String(j.sfml||'');
        if (out) out.textContent='';
        prodRenderSfml(window.__SF_PROD.sfml);
      })
      .catch(function(e){ prodSetSfmlBusy(false); if(out) out.innerHTML='<div class="err">'+escapeHtml(String(e&&e.message?e.message:e))+'</div>'; });
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

function prodProduceAudio(){
  try{
    var out=document.getElementById('prodOut');
    var st = window.__SF_PROD || {};
    if (!st.saved){ if(out) out.innerHTML='<div class="err">Save casting first</div>'; return; }
    var sid = String(st.story_id||'').trim();
    if (!sid){ if(out) out.innerHTML='<div class="err">Pick a story</div>'; return; }

    prodSetSfmlBusy(true, 'Producing audio…', 'Queuing a render job');
    if (out) out.textContent='';

    var eng = '';
    try{
      var r = document.querySelector('input[name="castEngine"]:checked');
      eng = r ? String(r.value||'').trim() : '';
    }catch(_e){ eng=''; }
    fetchJsonAuthed('/api/production/produce_audio', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({story_id:sid, engine: eng})})
      .then(function(j){
        if (!j || !j.ok || !j.job_id){ throw new Error((j&&j.error)||'produce_failed'); }
        prodSetSfmlBusy(false);
        // Jump to Jobs so progress is visible.
        try{ showTab('history'); }catch(_e){ try{ window.location.hash = '#tab-history'; }catch(__e){} }
      })
      .catch(function(e){ prodSetSfmlBusy(false); if(out) out.innerHTML='<div class="err">'+escapeHtml(String(e&&e.message?e.message:e))+'</div>'; });

  }catch(e){}
}

function prodSfmlSaveNow(sfmlText){
  try{
    var st = window.__SF_PROD || {};
    var sid = String(st.story_id||'').trim();
    if (!sid) return;

    fetchJsonAuthed('/api/production/sfml_save', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({story_id:sid, sfml_text:String(sfmlText||'')})})
      .then(function(j){
        if (!j || !j.ok){ throw new Error((j&&j.error)||'sfml_save_failed'); }
        try{ toastShowNow('SFML saved', 'ok', 900); }catch(_e){}
      })
      .catch(function(_e){ /* keep quiet; update bar will show if API is failing */ });
  }catch(e){}
}

function __sfmlFsIcon(expand){
  // expand=true => show expand icon; false => show compress icon
  if (expand){
    return "<svg viewBox='0 0 24 24' aria-hidden='true'>"+
      "<path stroke='currentColor' fill='none' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' d='M8 3H5a2 2 0 0 0-2 2v3M16 3h3a2 2 0 0 1 2 2v3M8 21H5a2 2 0 0 1-2-2v-3M16 21h3a2 2 0 0 0 2-2v-3'/>"+
    "</svg>";
  }
  return "<svg viewBox='0 0 24 24' aria-hidden='true'>"+
    "<path stroke='currentColor' fill='none' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' d='M9 9H5V5M15 9h4V5M9 15H5v4M15 15h4v4'/>"+
  "</svg>";
}

function __sfmlFsSetBtnState(on){
  try{
    var b = document.getElementById('sfmlFsBtn');
    if (!b) return;
    b.innerHTML = __sfmlFsIcon(!on);
    b.setAttribute('aria-label', on ? 'Exit full screen' : 'Full screen');
    b.setAttribute('title', on ? 'Exit full screen' : 'Full screen');
  }catch(e){}
}

function prodToggleSfmlFull(){
  try{
    var box=document.getElementById('prodSfmlBox');
    if(!box) return;
    var on = box.classList.contains('sfmlFull');
    var bd = document.getElementById('sfmlFullBackdrop');
    var tb = document.getElementById('sfmlFullTopbar');

    function cleanup(){
      // move fs button back into the editor box BEFORE removing the topbar
      try{
        var b = document.getElementById('sfmlFsBtn');
        if (b && box && b.parentNode !== box) box.appendChild(b);
      }catch(e){}

      try{ if(bd) bd.remove(); }catch(e){}
      try{ if(tb) tb.remove(); }catch(e){}
      try{ document.body.classList.remove('sfmlFullOn'); }catch(e){}
      try{ box.classList.remove('sfmlFull'); }catch(e){}
      try{ __sfmlFsSetBtnState(false); }catch(e){}
    }

    if(on){ cleanup(); return; }

    // enable
    try{ document.body.classList.add('sfmlFullOn'); }catch(e){}
    try{ box.classList.add('sfmlFull'); }catch(e){}
    try{ __sfmlFsSetBtnState(true); }catch(e){}

    // backdrop (tap to close)
    try{
      bd = document.createElement('div');
      bd.id='sfmlFullBackdrop';
      bd.className='sfmlFullBackdrop';
      bd.onclick=function(){ try{ prodToggleSfmlFull(); }catch(e){} };
      document.body.appendChild(bd);
    }catch(e){}

    // topbar (host the exit fullscreen icon so it's above everything)
    try{
      tb = document.createElement('div');
      tb.id='sfmlFullTopbar';
      tb.className='sfmlFullTopbar';
      tb.innerHTML = "<div class='t'>SFML</div><div class='sp'></div>";
      document.body.appendChild(tb);
      try{
        var b2 = document.getElementById('sfmlFsBtn');
        if (b2) tb.appendChild(b2);
      }catch(_e){}
    }catch(e){}

    try{ box.scrollTop = 0; }catch(e){}
  }catch(e){}
}

function prodRenderSfml(sfml){
  try{
    var box=document.getElementById('prodSfmlBox');
    if (!box) return;

    var raw = String(sfml||'');
    raw = raw.split("\\r\\n").join("\\n");

    box.classList.remove('hide');

    // Lightweight editor for now (no Ace). Next step: custom highlighting.
    if (!box.__sfmlInited){
      box.__sfmlInited = true;
      box.innerHTML = "<div id='sfmlEdHost'></div>";

      var host = document.getElementById('sfmlEdHost');
      window.__SF_SFML_ED = null;

      try{
        if (window.SFMLEditor && host){
          // Build voice_id -> color map for SFML highlighting
          var __vc = {};
          try{
            var vs = (window.__SF_VOICES || []);
            for (var i=0;i<vs.length;i++){
              var v = vs[i] || {};
              var id = String(v.id||'');
              var hx = String(v.color_hex||'');
              if (id && hx){ __vc[id] = hx; }
            }
          }catch(_e){}

          window.__SF_SFML_ED = window.SFMLEditor.create(host, {
            debounceMs: 2000,
            voiceColors: __vc,
            onSave: function(v){
              try{ window.__SF_PROD.sfml = String(v||''); }catch(_e){}
              try{ prodSfmlSaveNow(v); }catch(_e){}
            },
            onBlurSave: function(v){
              try{ window.__SF_PROD.sfml = String(v||''); }catch(_e){}
              try{ prodSfmlSaveNow(v); }catch(_e){}
            }
          });
        }else{
          host.innerHTML = "<textarea id='sfmlText' class='code' spellcheck='false' autocapitalize='none' autocomplete='off' autocorrect='off' style='width:100%;min-height:45vh;'></textarea>";
        }
      }catch(_e){
        try{ host.innerHTML = "<textarea id='sfmlText' class='code' spellcheck='false' autocapitalize='none' autocomplete='off' autocorrect='off' style='width:100%;min-height:45vh;'></textarea>"; }catch(__e){}
      }
    }

    try{
      if (window.__SF_SFML_ED && typeof window.__SF_SFML_ED.setValue === 'function'){
        window.__SF_SFML_ED.setValue(raw);
      }else{
        var ta2 = document.getElementById('sfmlText');
        if (ta2 && String(ta2.value||'') !== raw) ta2.value = raw;
      }
    }catch(_e){}

    // Fullscreen toggle icon (append AFTER editor init so it doesn't get wiped)
    try{
      var fsb = document.getElementById('sfmlFsBtn');
      if (!fsb){
        fsb = document.createElement('button');
        fsb.type = 'button';
        fsb.id = 'sfmlFsBtn';
        fsb.className = 'sfmlFsBtn';
        fsb.onclick = function(ev){ try{ if(ev&&ev.preventDefault) ev.preventDefault(); }catch(_e){}; try{ prodToggleSfmlFull(); }catch(_e){}; };
        box.appendChild(fsb);
      }
      __sfmlFsSetBtnState(box.classList.contains('sfmlFull'));
    }catch(_e){}

  }catch(e){}
}

function loadVoices(){
  var el=document.getElementById('voicesList');
  if (el) el.textContent='Loading…';
  return fetchJsonAuthed('/api/voices').then(function(j){
    if (!j.ok){ if(el) el.innerHTML = "<div class='muted'>Error loading voices</div>"; return; }
    var voices = j.voices || [];
    try{ window.__SF_VOICES = voices; }catch(_e){}
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

        // Engine chip (show which engine this voice uses)
        try{
          var eng = String(v.engine||'').trim();
          if (eng) chips += chip('engine ' + eng, '');
        }catch(_e){}

        traitsHtml = chips ? ("<div class='chips' style='margin-top:8px'>" + chips + "</div>") : '';
      }catch(e){ traitsHtml=''; }
      var en = (v.enabled!==false);
      var pill = en ? "<span class='pill good'>enabled</span>" : "<span class='pill bad'>disabled</span>";

      var playBtn = '';
      if (v.sample_url){
        playBtn = "<button class='secondary' data-vid='" + idEnc + "' data-sample='" + escAttr(v.sample_url||'') + "' onclick='playVoiceEl(this)'>Play</button>";
      }

      var sw = String(v.color_hex||'').trim() || '#64748b';
      var swHtml = "<span class='swatch' title='" + escAttr(nm) + "' style='background:" + escAttr(sw) + "'></span>";

      var card = "<div class='job'>"
        + "<div class='row' style='justify-content:space-between;'>"
        + "<div class='row' style='gap:10px;align-items:center;flex-wrap:nowrap;min-width:0'>" + swHtml + "<div class='title' style='min-width:0'>" + escapeHtml(nm) + "</div></div>"
        + "<div>" + pill + "</div>"
        + "</div>"
        + traitsHtml
        + "<div class='row' style='margin-top:10px'>"
        + playBtn
        + "<button class='secondary' data-vid='" + idEnc + "' onclick='goVoiceEdit(this)'>Edit</button>"
        + "</div>"
        /* inline audio element removed (use global floating audio dock) */
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
    __sfPlayAudio(sample, 'Voice sample');
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
  try{ metricsIntervalSec = 1; }catch(e){}
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
  try{ metricsIntervalSec = 10; }catch(e){}
  try{ startMetricsStream(); }catch(e){}
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

// deploy/update watch removed (will be rebuilt from scratch)

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
// startUpdateWatch removed

try{
  var __bootText2 = __sfEnsureBootBanner();
  if (__bootText2) __bootText2.textContent = 'Build: ' + (window.__SF_BUILD||'?') + ' • JS: ok';
  try{ __sfStartDeployWatch(); }catch(e){}
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
        .replace("__USER_MENU_JS__", USER_MENU_JS)
        .replace("__BUILD__", str(build))
        .replace("__VOICE_SERVERS__", voice_servers_html)
        .replace("__USER_MENU_HTML__", USER_MENU_HTML)
        .replace("__AUDIO_DOCK_JS__", AUDIO_DOCK_JS)
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
            # If the provider allowlist contains engines not reported by the gateway, include them.
            try:
                p2 = _get_tinybox_provider() or {}
                allow2 = p2.get('voice_engines') if isinstance(p2, dict) else None
                if isinstance(allow2, list) and allow2:
                    for e2 in allow2:
                        e2s = str(e2 or '').strip()
                        if e2s and e2s not in engs:
                            engs.append(e2s)
            except Exception:
                pass
            return {'ok': True, 'engines': engs or ['xtts', 'tortoise', 'styletts2']}
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
    chex = esc(v.get('color_hex') or '')
    eng = esc(v.get('engine') or '')
    vref = esc(v.get('voice_ref') or '')
    stxt = esc(v.get('sample_text') or '')
    surl = esc(v.get('sample_url') or '')
    enabled_checked = 'checked' if bool(v.get('enabled', True)) else ''
    vtraits_json = str(v.get('voice_traits_json') or '').strip()

    style_css = VOICES_BASE_CSS + VOICE_EDIT_EXTRA_CSS

    body_top = (
        DEBUG_BANNER_BOOT_JS
        + "\n" + USER_MENU_JS
        + "\n" + DEBUG_PREF_APPLY_JS
        + "\n" + AUDIO_DOCK_JS
    )

    nav_html = (
        "<div class='navBar'>"
        "  <div class='top'>"
        "    <div>"
        "      <div class='brandRow'><h1><a class='brandLink' href='/'>StoryForge</a></h1><div class='pageName'>Edit voice</div></div>"
        "      <div class='muted'><code>__VID__</code></div>"
        "    </div>"
        "    <div class='row headActions'>"
        "      <a href='/#tab-voices'><button class='secondary' type='button'>Back</button></a>"
        "      __USER_MENU_HTML__"
        "    </div>"
        "  </div>"
        "</div>"
    )

    content_html = """
  __DEBUG_BANNER_HTML__

  <div class='card'>
    <div style='font-weight:950;margin-bottom:6px;'>Basic fields</div>

    <div class='muted'>Display name</div>
    <div class='row' style='gap:10px;flex-wrap:nowrap'>
      <span id='editSwatch' class='swatch' title='Pick color' style='background:#64748b;cursor:pointer' onclick='openColorPick()'></span>
      <span id='colorPickWrap' class='colorPickWrap' style='display:none'>
        <input id='colorPick' type='color' class='colorPickHidden' value='__CHEX__' onchange='setEditColorHex(this.value)' onblur='setEditColorHex(this.value)' aria-label='Pick color' />
      </span>
      <input id='color_hex' type='hidden' value='__CHEX__' />
      <input id='display_name' value='__DN__' style='flex:1;min-width:0' />
      <button type='button' class='copyBtn' onclick='genEditVoiceName()' aria-label='Random voice name' title='Random voice name'>
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

    <div class='row' style='gap:10px;align-items:center;margin-top:12px'>
      <div class='muted'>Enabled</div>
      <label class='switch' style='margin:0'>
        <input id='enabled' type='checkbox' __ENABLED__ />
        <span class='slider'></span>
      </label>
    </div>

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
      <button type='button' class='secondary' onclick='analyzeVoice()'>Analyze voice</button>
    </div>
    <input id='voice_traits_json' type='hidden' value='__VTRAITS__' />
    <div id='traitsBox' class='term' style='margin-top:10px'>Loading…</div>
    <details class='rawBox' style='margin-top:10px'>
      <summary>Raw JSON</summary>
      <pre id='traits_raw' class='term' style='white-space:pre-wrap;max-height:240px;overflow:auto;-webkit-overflow-scrolling:touch'>__VTRAITS__</pre>
    </details>
  </div>

  __MONITOR__

  <div class='row' style='justify-content:space-between;margin-top:12px'>
    <button class='secondary' type='button' onclick='deleteVoice()' style='border-color:rgba(255,0,72,.35);color:#ff4d6d'>Delete</button>
    <button type='button' onclick='saveVoice()'>Save</button>
  </div>
"""

    body_bottom = """
__MONITOR_JS__
<script>
function copyText(s){
  try{
    if (navigator && navigator.clipboard && navigator.clipboard.writeText){
      navigator.clipboard.writeText(String(s||''));
      return;
    }
  }catch(e){}
  try{
    var ta=document.createElement('textarea');
    ta.value=String(s||'');
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
  }catch(e){}
}

function copySampleUrl(){
  try{ copyText(document.getElementById('sample_url').value||''); }catch(e){}
}
function copyVoiceRef(){
  try{ copyText(document.getElementById('voice_ref').textContent||''); }catch(e){}
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

function renderTraits(){
  try{
    var box=document.getElementById('traitsBox');
    var hid=document.getElementById('voice_traits_json');
    if (!box || !hid) return;
    var raw = String(hid.value||'').trim();
    var pre = document.getElementById('traits_raw');
    if (pre && raw) pre.textContent = raw;

    if (!raw || raw==='—'){
      box.innerHTML = '<div class="muted">No metadata yet. Tap <b>Analyze voice</b>.</div>';
      return;
    }

    var obj=null;
    try{ obj = JSON.parse(raw); }catch(e){
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
    var toneHtml = tone.length ? tone.map(function(t){ return chip(t,''); }).join('') : '<span class="muted">—</span>';

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

try{ document.addEventListener('DOMContentLoaded', function(){ try{ renderTraits(); }catch(_e){} }); }catch(e){}
try{ renderTraits(); }catch(e){}

function setEditColorHex(hex){
  try{ document.getElementById('color_hex').value = String(hex||''); }catch(e){}
  try{ document.getElementById('editSwatch').style.background = String(hex||''); }catch(e){}
}

function openColorPick(){
  try{
    var wrap = document.getElementById('colorPickWrap');
    var inp = document.getElementById('colorPick');
    if (wrap) wrap.style.display='inline-block';
    if (inp){
      try{ inp.focus(); }catch(e){}
      try{ inp.click(); }catch(e){}
    }
  }catch(e){}
}

function genEditVoiceName(){
  try{
    var names=['Moscow Winter','Silver River','Quiet Ember','Night Lantern','Cold Harbor','Iron Lullaby'];
    document.getElementById('display_name').value = names[Math.floor(Math.random()*names.length)];
  }catch(e){}
}

function playSample(){
  try{
    var url = document.getElementById('sample_url').value||'';
    if (!url) return;
    if (typeof window.__sfPlayAudio === 'function'){
      window.__sfPlayAudio(url, 'Sample: __VID_RAW__');
      return;
    }
    window.open(url, '_blank');
  }catch(e){}
}

function copyTraitsRaw(){
  try{ copyText((document.getElementById('traits_raw')||{}).textContent||''); }catch(e){}
}

async function analyzeVoice(){
  try{
    var btns=document.querySelectorAll('button');
    for (var i=0;i<btns.length;i++){ if ((btns[i].textContent||'').trim()==='Analyze voice'){ btns[i].disabled=true; } }
  }catch(e){}
  try{
    var r = await fetch('/api/voices/analyze', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({voice_id:'__VID_RAW__'})});
    var j = await r.json();
    if (j && j.ok){
      var txt = JSON.stringify(j.traits, null, 2);
      try{ document.getElementById('voice_traits_json').value = txt; }catch(_e){}
      try{ document.getElementById('traitsBox').textContent = txt; }catch(_e){}
      try{ document.getElementById('traits_raw').textContent = txt; }catch(_e){}
    }else{
      alert((j && j.error) ? j.error : 'Analyze failed');
    }
  }catch(e){
    alert('Analyze failed: ' + String(e));
  }
  try{
    var btns2=document.querySelectorAll('button');
    for (var k=0;k<btns2.length;k++){ if ((btns2[k].textContent||'').trim()==='Analyze voice'){ btns2[k].disabled=false; } }
  }catch(e){}
}

async function saveVoice(){
  try{
    var payload={
      voice_id:'__VID_RAW__',
      display_name: (document.getElementById('display_name').value||'').trim(),
      color_hex: (document.getElementById('color_hex').value||'').trim(),
      enabled: !!document.getElementById('enabled').checked
    };
    var r=await fetch('/api/voices/update', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
    var j=await r.json();
    if (!j || !j.ok){
      alert((j && j.error) ? j.error : 'Save failed');
      return;
    }
    location.href='/#tab-voices';
  }catch(e){
    alert('Save failed: ' + String(e));
  }
}

async function deleteVoice(){
  try{ if (!confirm('Delete this voice?')) return; }catch(e){}
  try{
    var r=await fetch('/api/voices/delete', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({voice_id:'__VID_RAW__'})});
    var j=await r.json();
    if (!j || !j.ok){
      alert((j && j.error) ? j.error : 'Delete failed');
      return;
    }
    location.href='/#tab-voices';
  }catch(e){
    alert('Delete failed: ' + String(e));
  }
}
</script>
"""

    html = render_page(
        title='StoryForge - Edit Voice',
        style_css=style_css,
        body_top_html=body_top,
        nav_html=nav_html,
        content_html=content_html,
        body_bottom_html=body_bottom,
    )

    html = (html
        .replace('__VID__', vid)
        .replace('__DN__', dn)
        .replace('__CHEX__', chex or '#64748b')
        .replace('__ENG__', eng)
        .replace('__VREF__', vref)
        .replace('__STXT__', stxt)
        .replace('__SURL__', surl)
        .replace('__ENABLED__', enabled_checked)
        .replace('__VID_RAW__', voice_id)
        .replace('__VTRAITS__', esc(vtraits_json) if vtraits_json else '—')
    )
    html = (html
        .replace('__DEBUG_BANNER_HTML__', DEBUG_BANNER_HTML)
        .replace('__USER_MENU_HTML__', USER_MENU_HTML)
        .replace('__MONITOR__', MONITOR_HTML)
        .replace('__MONITOR_JS__', MONITOR_JS)
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

    style_css = VOICES_BASE_CSS + VOICE_NEW_EXTRA_CSS
    body_top = (
        DEBUG_BANNER_BOOT_JS
        + "\n" + USER_MENU_JS
        + "\n" + DEBUG_PREF_APPLY_JS
        + "\n" + AUDIO_DOCK_JS
    )

    nav_html = (
        "<div class='navBar'>"
        "  <div class='top'>"
        "    <div>"
        "      <div class='brandRow'><h1><a class='brandLink' href='/'>StoryForge</a></h1><div class='pageName'>Generate voice</div></div>"
        "    </div>"
        "    <div class='row headActions'>"
        "      <a href='/#tab-voices'><button class='secondary' type='button'>Back</button></a>"
        "      __USER_MENU_HTML__"
        "    </div>"
        "  </div>"
        "</div>"
    )

    content_html = """
  __DEBUG_BANNER_HTML__

  <div class='card'>
    <div style='font-weight:950;margin-bottom:6px;'>Generate voice</div>

    <div class='k'>Voice name</div>
    <div class='row' style='gap:10px;flex-wrap:nowrap'>
      <span id='voiceSwatch' class='swatch' title='Pick color' style='background:#64748b;cursor:pointer' onclick='openVoiceColorPick()'></span>
      <span id='voiceColorPickWrap' class='colorPickWrap' style='display:none'>
        <input id='voiceColorPick' type='color' class='colorPickHidden' value='#64748b' onchange='setVoiceSwatchHex(this.value)' onblur='setVoiceSwatchHex(this.value)' aria-label='Pick color' />
      </span>
      <input id='voiceColorHex' type='hidden' value='' />
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
      <option value='styletts2'>styletts2</option>
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

  __MONITOR__

"""

    body_bottom = """
__MONITOR_JS__
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

function voiceColorHex(name){
  try{
    var s = String(name||'').toLowerCase();
    var words = s.replace(/[^a-z0-9]+/g,' ').trim().split(/\s+/).filter(Boolean);
    var map = {
      ruby:'#ef4444', amber:'#f59e0b', coral:'#fb7185', rose:'#f43f5e', peach:'#fdba74', lilac:'#c4b5fd', violet:'#a78bfa',
      sapphire:'#60a5fa', sky:'#38bdf8', aqua:'#22d3ee', mint:'#34d399', sage:'#86efac', jade:'#10b981', emerald:'#22c55e', teal:'#14b8a6', pearl:'#e5e7eb',
      onyx:'#0b0b10', slate:'#64748b', steel:'#94a3b8', cobalt:'#2563eb', indigo:'#4f46e5', navy:'#1e3a8a', forest:'#166534', moss:'#4d7c0f',
      copper:'#b45309', bronze:'#a16207', umber:'#92400e', ash:'#9ca3af', obsidian:'#111827', graphite:'#6b7280', stone:'#a3a3a3', sand:'#e7d3a7',
      ivory:'#f5f5dc', gold:'#facc15'
    };
    for (var i=words.length-1; i>=0; i--){
      var w = words[i];
      if (map[w]) return map[w];
      if (w.length>1 && w.charAt(w.length-1)==='s'){
        var w2 = w.slice(0,-1);
        if (map[w2]) return map[w2];
      }
    }
    var h=0;
    for (var k=0;k<s.length;k++){ h = ((h<<5)-h) + s.charCodeAt(k); h |= 0; }
    var hue = Math.abs(h) % 360;
    return 'hsl(' + hue + ', 70%, 55%)';
  }catch(e){
    return '#64748b';
  }
}

function setVoiceSwatchHex(hex){
  try{
    var hx=document.getElementById('voiceColorHex');
    var sw=document.getElementById('voiceSwatch');
    var pk=document.getElementById('voiceColorPick');
    var v = String(hex||'').trim();
    if (hx) hx.value = v;
    if (pk) pk.value = v || '#64748b';
    if (sw) sw.style.background = v || '#64748b';
  }catch(e){}
}
function openVoiceColorPick(){
  try{
    var pk=document.getElementById('voiceColorPick');
    if (!pk) return;
    var w=document.getElementById('voiceColorPickWrap'); if (w) w.style.display='inline-block';
    _colorReturnSetup('voiceColorPick', 'voiceColorPickWrap', function(v){ try{ setVoiceSwatchHex(v); }catch(_e){} });
    try{ pk.focus(); }catch(_e){}
    try{
      if (pk && typeof pk.showPicker === 'function') pk.showPicker();
      else pk.click();
    }catch(_e){ try{ pk.click(); }catch(__e){} }
  }catch(e){}
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
      try{ setVoiceSwatchHex(String(j.color_hex||'').trim()); }catch(e){}
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
    payload.color_hex = String(val('voiceColorHex')||'').trim();
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

"""

    html = render_page(
        title='StoryForge - Generate voice',
        style_css=style_css,
        body_top_html=body_top,
        nav_html=nav_html,
        content_html=content_html,
        body_bottom_html=body_bottom,
    )

    html = (html
        .replace('__DEBUG_BANNER_HTML__', DEBUG_BANNER_HTML)
        .replace('__USER_MENU_HTML__', USER_MENU_HTML)
        .replace('__MONITOR__', MONITOR_HTML)
        .replace('__MONITOR_JS__', MONITOR_JS)
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

    build = APP_BUILD

    # Use the same chrome as /base-template (INDEX_BASE_CSS), but keep the TODO list layout styles.
    style_css = INDEX_BASE_CSS + base_css("""\

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

    /* Override INDEX_BASE_CSS input{width:100%} so checkboxes don't become full-width on iOS */
    .todoMain input[type=checkbox]{width:auto;flex:0 0 auto;}
    .todoItem input{margin-top:3px;transform:scale(1.15);width:auto;}

    .todoTextWrap{min-width:0;}
    .todoText{line-height:1.25;}
    .todoMeta{color:var(--muted);font-size:12px;margin-top:4px;}
    .todoPlain{margin:8px 0;color:var(--muted);}

""")
    body_top = (
        str(DEBUG_BANNER_BOOT_JS)
        + str(USER_MENU_JS)
        + str(DEBUG_PREF_APPLY_JS)
        + str(AUDIO_DOCK_JS)
    )

    nav_html = (
        "<div class='navBar'>"
        "  <div class='top'>"
        "    <div>"
        "      <div class='brandRow'><h1><a class='brandLink' href='/'>StoryForge</a></h1><div class='pageName'>TODO</div></div>"
        "      <div class='muted'>Internal tracker (check/uncheck requires login).</div>"
        "    </div>"
        "    <div class='row headActions'>"
        "      <a href='/'><button class='secondary' type='button'>Back</button></a>"
        "      __USER_MENU_HTML__"
        "    </div>"
        "  </div>"
        "</div>"
    )

    content_html = """
  __DEBUG_BANNER_HTML__

  <div class='card'>
    <div class='row' style='justify-content:space-between;align-items:center;gap:10px'>
      <div class='row' style='gap:10px;align-items:center'>
        <div class='muted' style='font-weight:950'>Archived</div>
        <label class='switch' aria-label='Toggle archived'>
          <input id='archToggle' type='checkbox' __ARCH_CHECKED__ onchange='toggleArchived(this.checked)' />
          <span class='slider'></span>
        </label>
      </div>
      <div class='row' style='gap:10px;justify-content:flex-end;flex-wrap:wrap'>
        <button class='secondary' type='button' onclick='archiveDone()'>Archive done</button>
        <button class='secondary' type='button' onclick='clearHighlights()'>Clear highlights</button>
      </div>
    </div>
  </div>

  <div class='card'>
    __BODY_HTML__
  </div>

  __MONITOR__
"""

    body_bottom = """
__MONITOR_JS__
<script>
function jsonFetch(url, opts){
  opts = opts || {};
  opts.credentials = 'include';
  return fetch(url, opts).then(function(r){
    if (r.status===401){ window.location.href='/login'; return Promise.reject(new Error('unauthorized')); }
    return r.json().catch(function(){ return {ok:false,error:'bad_json'}; });
  });
}

function toggleArchived(on){
  try{
    var u=new URL(window.location.href);
    if (on) u.searchParams.set('arch','1'); else u.searchParams.delete('arch');
    window.location.href=u.toString();
  }catch(e){}
}

function onTodoToggle(cb){
  try{
    var id = cb && cb.getAttribute ? cb.getAttribute('data-id') : '';
    if (!id) return;
    var url = cb.checked ? ('/api/todos/'+id+'/done_auth') : ('/api/todos/'+id+'/open_auth');
    jsonFetch(url, {method:'POST'}).catch(function(_e){ window.location.reload(); });
  }catch(e){}
}

function deleteTodo(id){
  try{ if(!confirm('Delete TODO #' + id + '?')) return; }catch(e){}
  jsonFetch('/api/todos/'+String(id)+'/delete_auth', {method:'POST'})
    .then(function(j){ if(!j||!j.ok) throw new Error((j&&j.error)||'delete_failed'); window.location.reload(); })
    .catch(function(e){ alert('Delete failed: ' + String(e&&e.message?e.message:e)); });
}

function toggleHighlight(id){
  jsonFetch('/api/todos/'+String(id)+'/toggle_highlight_auth', {method:'POST'})
    .then(function(_j){ window.location.reload(); })
    .catch(function(_e){ window.location.reload(); });
}

function archiveDone(){
  jsonFetch('/api/todos/archive_done_auth', {method:'POST'})
    .then(function(_j){ window.location.reload(); })
    .catch(function(_e){ window.location.reload(); });
}

function clearHighlights(){
  jsonFetch('/api/todos/clear_highlights_auth', {method:'POST'})
    .then(function(_j){ window.location.reload(); })
    .catch(function(_e){ window.location.reload(); });
}
</script>
"""

    html = render_page(
        title='StoryForge - TODO',
        style_css=style_css,
        body_top_html=body_top,
        nav_html=nav_html,
        content_html=content_html,
        body_bottom_html=body_bottom,
    )

    html = (html
        .replace('__DEBUG_BANNER_HTML__', DEBUG_BANNER_HTML)
        .replace('__USER_MENU_HTML__', USER_MENU_HTML)
        .replace('__MONITOR__', MONITOR_HTML)
        .replace('__MONITOR_JS__', MONITOR_JS)
        .replace('__BUILD__', str(build))
        .replace('__ARCH_CHECKED__', arch_checked)
        .replace('__BODY_HTML__', body_html)
    )
    return HTMLResponse(html)

@app.get('/ui/test-tone.wav')
def ui_test_tone_wav():
    # Tiny WAV for UI testing (triggers the global audio dock)
    try:
        import io, math, struct, wave
        sr = 22050
        dur_s = 0.25
        freq = 880.0
        n = int(sr * dur_s)
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            for i in range(n):
                t = i / sr
                # simple sine with fade in/out to avoid clicks
                amp = 0.25
                fade = 0.02
                if t < fade:
                    amp *= (t / fade)
                if t > dur_s - fade:
                    amp *= max(0.0, (dur_s - t) / fade)
                v = amp * math.sin(2 * math.pi * freq * t)
                w.writeframes(struct.pack('<h', int(max(-1.0, min(1.0, v)) * 32767)))
        data = buf.getvalue()
        return Response(content=data, media_type='audio/wav', headers={'Cache-Control': 'no-store'})
    except Exception:
        return Response(content=b'', media_type='audio/wav', headers={'Cache-Control': 'no-store'})


@app.get('/base-template', response_class=HTMLResponse)
def base_template_page(response: Response):
    response.headers['Cache-Control'] = 'no-store'
    build = APP_BUILD

    style_css = INDEX_BASE_CSS
    body_top = (
        str(DEBUG_BANNER_BOOT_JS)
        + str(USER_MENU_JS)
        + str(DEBUG_PREF_APPLY_JS)
        + str(AUDIO_DOCK_JS)
    )

    nav_html = (
        "<div class='navBar'>"
        "  <div class='top'>"
        "    <div>"
        "      <div class='brandRow'><h1><a class='brandLink' href='/'>StoryForge</a></h1><div class='pageName'>Base template</div></div>"
        "      <div class='muted'>Reference page: header + debug + player + monitor + sample middle.</div>"
        "    </div>"
        "    <div class='row headActions'>"
        "      <a href='/'><button class='secondary' type='button'>Back</button></a>"
        "      __USER_MENU_HTML__"
        "    </div>"
        "  </div>"
        "</div>"
    )

    content_html = """
  __DEBUG_BANNER_HTML__

  <div class='card'>
    <div style='font-weight:950;margin-bottom:6px;'>Sample middle</div>
    <div class='muted'>Tap Play to trigger the shared floating audio player.</div>

    <div class='row' style='justify-content:space-between;align-items:center;margin-top:10px'>
      <div class='muted' style='font-weight:950'>Test tone</div>
      <button type='button' class='secondary' onclick='playTestTone()'>Play</button>
    </div>

    <div class='row' style='margin-top:10px'>
      <input id='audioUrl' placeholder='Or paste any audio URL…' />
      <button type='button' onclick='playUrl()'>Play URL</button>
    </div>
  </div>

  __MONITOR__
"""

    body_bottom = """
__MONITOR_JS__
<script>
function playTestTone(){
  try{
    if (typeof window.__sfPlayAudio === 'function'){
      window.__sfPlayAudio('/ui/test-tone.wav?v=' + String(window.__SF_BUILD||''), 'Test tone');
      return;
    }
    window.open('/ui/test-tone.wav', '_blank');
  }catch(e){}
}

function playUrl(){
  try{
    var u = String((document.getElementById('audioUrl')||{}).value||'').trim();
    if (!u) return;
    if (typeof window.__sfPlayAudio === 'function'){
      window.__sfPlayAudio(u, 'URL audio');
      return;
    }
    window.open(u, '_blank');
  }catch(e){}
}
</script>
"""

    html = render_page(
        title='StoryForge - Base template',
        style_css=style_css,
        body_top_html=body_top,
        nav_html=nav_html,
        content_html=content_html,
        body_bottom_html=body_bottom,
    )

    html = (html
        .replace('__DEBUG_BANNER_HTML__', DEBUG_BANNER_HTML)
        .replace('__USER_MENU_HTML__', USER_MENU_HTML)
        .replace('__MONITOR__', MONITOR_HTML)
        .replace('__MONITOR_JS__', MONITOR_JS)
        .replace('__BUILD__', str(build))
    )
    return HTMLResponse(html)


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
async def api_metrics_stream(request: Request):
    """SSE stream for metrics.

    IMPORTANT: this must be async to avoid exhausting worker threads.

    Query params:
      - interval: seconds between updates (clamped 1..30). Default: 2.
    """

    # Client-controlled interval (used to make the sheet feel "live" without spamming
    # updates when the dock is closed).
    interval_s = 2.0
    try:
        raw = str(request.query_params.get('interval') or '').strip()
        if raw:
            interval_s = float(raw)
    except Exception:
        interval_s = 2.0
    interval_s = max(1.0, min(30.0, float(interval_s or 2.0)))

    async def gen():
        import asyncio

        while True:
            try:
                # _get uses requests (blocking); run in a thread so we don't block the event loop.
                m = await asyncio.to_thread(_get, '/v1/metrics', 6.0)
                data = json.dumps(m, separators=(',', ':'))
                yield f"data: {data}\n\n"
            except Exception:
                yield f"data: {json.dumps({'ok': False, 'error': 'metrics_failed'})}\n\n"
            await asyncio.sleep(interval_s)

    headers = {
        'Cache-Control': 'no-store',
        'X-Accel-Buffering': 'no',
    }
    return StreamingResponse(gen(), media_type='text/event-stream', headers=headers)


@app.get('/api/jobs/stream')
async def api_jobs_stream():
    """SSE stream for jobs.

    IMPORTANT: async to avoid threadpool exhaustion.
    """

    async def gen():
        import asyncio

        while True:
            try:
                # DB access is blocking; run in a thread so we don't block the event loop.
                def _load_jobs():
                    conn = db_connect()
                    try:
                        db_init(conn)
                        return db_list_jobs(conn, limit=60)
                    finally:
                        conn.close()

                jobs = await asyncio.to_thread(_load_jobs)
                data = json.dumps({'ok': True, 'jobs': jobs}, separators=(',', ':'))
                yield f"data: {data}\n\n"
            except Exception:
                yield f"data: {json.dumps({'ok': False, 'error': 'jobs_failed'})}\n\n"
            await asyncio.sleep(1.5)

    headers = {
        'Cache-Control': 'no-store',
        'X-Accel-Buffering': 'no',
    }
    return StreamingResponse(gen(), media_type='text/event-stream', headers=headers)


def _require_job_token(request: Request) -> None:
    """Auth for external workers.

    Prefer x-sf-job-token (SF_JOB_TOKEN). For operator convenience we also
    accept x-sf-todo-token (TODO_API_TOKEN). As a last-resort bootstrap path,
    accept x-sf-deploy-token (SF_DEPLOY_TOKEN) so we can bring up workers even
    if TODO/SF_JOB tokens are out of sync.

    NOTE: SF_DEPLOY_TOKEN is more sensitive (CI deploy hook); keep usage minimal.
    """
    tok = (request.headers.get('x-sf-job-token') or '').strip()
    if tok and SF_JOB_TOKEN and tok == SF_JOB_TOKEN:
        return

    # Fallback: allow TODO API token
    todo_err = _todo_api_check(request)
    if todo_err is None:
        return

    # Last resort: deploy token
    dtok = (request.headers.get('x-sf-deploy-token') or '').strip()
    if dtok and SF_DEPLOY_TOKEN and dtok == SF_DEPLOY_TOKEN:
        return

    raise HTTPException(status_code=401, detail='unauthorized')


@app.post('/api/jobs/claim')
def api_jobs_claim(request: Request, payload: dict[str, Any] = Body(default={})):  # noqa: B008
    """Claim the oldest queued job for a kind.

    Used by external workers (Tinybox). This atomically transitions a job from
    queued -> running and sets started_at.

    Auth: x-sf-job-token
    Payload: {kind: "produce_audio"}
    """
    _require_job_token(request)
    try:
        kind = str((payload or {}).get('kind') or '').strip()
        if not kind:
            return {'ok': False, 'error': 'missing_kind'}

        conn = db_connect()
        try:
            db_init(conn)
            cur = conn.cursor()
            # Atomic claim (Postgres): select + lock one queued job
            cur.execute('BEGIN')
            cur.execute(
                "SELECT id,title,kind,meta_json,state,started_at,finished_at,total_segments,segments_done,mp3_url,sfml_url,created_at "
                "FROM jobs WHERE state='queued' AND kind=%s ORDER BY created_at ASC LIMIT 1 FOR UPDATE SKIP LOCKED",
                (kind,),
            )
            row = cur.fetchone()
            if not row:
                conn.commit()
                return {'ok': True, 'job': None}

            job_id = str(row[0])
            now = int(time.time())
            cur.execute("UPDATE jobs SET state=%s, started_at=%s WHERE id=%s", ('running', now, job_id))
            conn.commit()

            job = {
                'id': row[0],
                'title': row[1],
                'kind': row[2] or '',
                'meta_json': row[3] or '',
                'state': 'running',
                'started_at': now,
                'finished_at': int(row[6] or 0),
                'total_segments': int(row[7] or 0),
                'segments_done': int(row[8] or 0),
                'mp3_url': row[9] or '',
                'sfml_url': row[10] or '',
                'created_at': int(row[11] or 0),
            }
            return {'ok': True, 'job': job}
        finally:
            conn.close()
    except Exception as e:
        return {'ok': False, 'error': f'claim_failed: {type(e).__name__}: {str(e)[:200]}'}


@app.get('/api/production/sfml/{story_id}')
def api_production_sfml(request: Request, story_id: str):
    """Fetch persisted SFML for a story (worker use).

    Auth: x-sf-job-token
    """
    _require_job_token(request)
    try:
        sid = str(story_id or '').strip()
        if not sid:
            return {'ok': False, 'error': 'missing_story_id'}

        conn = db_connect()
        try:
            db_init(conn)
            cur = conn.cursor()
            cur.execute('SELECT id, title, sfml_text FROM sf_stories WHERE id=%s', (sid,))
            row = cur.fetchone()
        finally:
            conn.close()

        if not row:
            return {'ok': False, 'error': 'story_not_found'}
        title = str(row[1] or sid)
        sfml = str(row[2] or '')
        if not sfml.strip():
            return {'ok': False, 'error': 'missing_sfml'}
        return {'ok': True, 'story_id': sid, 'title': title, 'sfml_text': sfml}
    except Exception as e:
        return {'ok': False, 'error': f'sfml_failed: {type(e).__name__}: {str(e)[:200]}'}


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
        prev_state = ''
        kind = ''
        title = ''
        mp3_url = ''
        try:
            db_init(conn)
            cur = conn.cursor()

            # Ensure exists
            cur.execute(
                "INSERT INTO jobs (id,title,state,created_at) VALUES (%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING",
                (job_id, str(fields.get('title') or job_id), str(fields.get('state') or 'running'), int(time.time())),
            )

            # Read previous state for notifications
            try:
                cur.execute("SELECT state, kind, title, mp3_url FROM jobs WHERE id=%s", (job_id,))
                row = cur.fetchone()
                if row:
                    prev_state = str(row[0] or '')
                    kind = str(row[1] or '')
                    title = str(row[2] or '')
                    mp3_url = str(row[3] or '')
            except Exception:
                prev_state = ''

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

            # Determine if we should notify (state transition to completed/failed)
            try:
                new_state = str(fields.get('state') or '')
                if new_state in ('completed', 'failed') and prev_state != new_state:
                    # Use the patched fields when available
                    kind2 = str(fields.get('kind') or kind or '')
                    title2 = str(fields.get('title') or title or job_id)
                    mp32 = str(fields.get('mp3_url') or mp3_url or '')
                    _push_notify_job_state(kind2, new_state, job_id, title2, mp32)
            except Exception:
                pass

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


@app.post('/api/jobs/abort')
def api_jobs_abort(payload: dict[str, Any] = Body(default={})):  # noqa: B008
    """Abort a running/queued job.

    - Marks the job state as aborted in the DB.
    - Best-effort: calls Tinybox (/v1/jobs/abort) to kill any active subprocesses tied to this job.

    Auth: passphrase session middleware.
    Payload: {id: <job_id>}
    """
    try:
        job_id = str((payload or {}).get('id') or (payload or {}).get('job_id') or '').strip()
        if not job_id:
            return {'ok': False, 'error': 'missing_id'}

        now = int(time.time())

        # Update DB state first (so UI reflects abort even if Tinybox kill fails).
        conn = db_connect()
        try:
            db_init(conn)
            cur = conn.cursor()
            cur.execute(
                "UPDATE jobs SET state=%s, finished_at=%s WHERE id=%s",
                ('aborted', now, job_id),
            )
            conn.commit()
        finally:
            try:
                conn.close()
            except Exception:
                pass

        # Best-effort: request Tinybox to kill job subprocesses.
        try:
            requests.post(
                GATEWAY_BASE + '/v1/jobs/abort',
                json={'job_id': job_id},
                headers=_h(),
                timeout=8,
            )
        except Exception:
            pass

        return {'ok': True, 'job_id': job_id}
    except Exception as e:
        return {'ok': False, 'error': f'abort_failed: {type(e).__name__}: {e}'}




def _push_notify_job_state(kind: str, state: str, job_id: str, title: str, mp3_url: str = '') -> None:
    """Best-effort Web Push notifications on job terminal states."""
    try:
        kind = str(kind or '').strip()
        state = str(state or '').strip()
        if state not in ('completed', 'failed'):
            return
        if not VAPID_PUBLIC_KEY or not VAPID_PRIVATE_KEY:
            return

        conn = db_connect()
        try:
            db_init(conn)
            cur = conn.cursor()
            cur.execute(
                "SELECT endpoint,p256dh,auth,enabled,job_kinds_json FROM sf_push_subscriptions WHERE enabled=TRUE"
            )
            rows = cur.fetchall() or []
        finally:
            try:
                conn.close()
            except Exception:
                pass

        payload = {
            'kind': kind,
            'state': state,
            'job_id': job_id,
            'title': title,
            'url': '/#tab-history',
            'mp3_url': mp3_url or '',
        }
        try:
            body = json.dumps(payload, separators=(',', ':'))
        except Exception:
            body = '{"kind":"' + kind + '","state":"' + state + '"}'

        from pywebpush import webpush  # type: ignore

        for r in rows:
            try:
                endpoint = str(r[0] or '')
                p256dh = str(r[1] or '')
                auth = str(r[2] or '')
                enabled = bool(r[3])
                kinds_raw = str(r[4] or '[]')
                if not enabled or not endpoint or not p256dh or not auth:
                    continue
                try:
                    kinds = json.loads(kinds_raw) if kinds_raw else []
                except Exception:
                    kinds = []
                if isinstance(kinds, list) and kind and (kind not in [str(x) for x in kinds]):
                    continue

                webpush(
                    subscription_info={
                        'endpoint': endpoint,
                        'keys': {'p256dh': p256dh, 'auth': auth},
                    },
                    data=body,
                    vapid_private_key=_vapid_private_key_material(),
                    vapid_claims={'sub': VAPID_SUBJECT},
                    timeout=6,
                )
            except Exception:
                # TODO: garbage-collect invalid subscriptions on 410/404
                continue
    except Exception:
        return


@app.get('/api/notifications/vapid_public')
def api_notifications_vapid_public(request: Request):
    # Session auth is enforced by passphrase middleware; do not call an undefined helper.
    if not VAPID_PUBLIC_KEY or not VAPID_PRIVATE_KEY:
        return {'ok': False, 'error': 'push_not_configured'}
    return {'ok': True, 'public_key': VAPID_PUBLIC_KEY}


@app.get('/api/notifications/settings')
def api_notifications_settings(request: Request):
    device_id = str(request.query_params.get('device_id') or '').strip()
    if not device_id:
        return {'ok': False, 'error': 'missing_device_id'}
    conn = db_connect()
    try:
        db_init(conn)
        cur = conn.cursor()
        cur.execute(
            "SELECT enabled, job_kinds_json FROM sf_push_subscriptions WHERE device_id=%s ORDER BY updated_at DESC LIMIT 1",
            (device_id,),
        )
        row = cur.fetchone()
        if not row:
            return {'ok': True, 'enabled': False, 'job_kinds': ['produce_audio']}
        enabled = bool(row[0])
        raw = str(row[1] or '[]')
        try:
            kinds = json.loads(raw) if raw else []
        except Exception:
            kinds = []
        if not isinstance(kinds, list):
            kinds = []
        return {'ok': True, 'enabled': enabled, 'job_kinds': kinds}
    finally:
        try:
            conn.close()
        except Exception:
            pass


@app.post('/api/notifications/settings')
def api_notifications_settings_set(request: Request, payload: dict[str, Any] = Body(default={})):  # noqa: B008
    device_id = str((payload or {}).get('device_id') or '').strip()
    if not device_id:
        return {'ok': False, 'error': 'missing_device_id'}
    kinds = (payload or {}).get('job_kinds')
    if not isinstance(kinds, list):
        kinds = []
    kinds2 = [str(x) for x in kinds if str(x).strip()]
    now = int(time.time())
    conn = db_connect()
    try:
        db_init(conn)
        cur = conn.cursor()
        cur.execute(
            "UPDATE sf_push_subscriptions SET job_kinds_json=%s, updated_at=%s WHERE device_id=%s",
            (json.dumps(kinds2, separators=(',', ':')), now, device_id),
        )
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return {'ok': True}


@app.post('/api/notifications/subscribe')
def api_notifications_subscribe(request: Request, payload: dict[str, Any] = Body(default={})):  # noqa: B008
    device_id = str((payload or {}).get('device_id') or '').strip()
    sub = (payload or {}).get('subscription')
    ua = str((payload or {}).get('ua') or '').strip()
    kinds = (payload or {}).get('job_kinds')
    if not isinstance(kinds, list):
        kinds = ['produce_audio']
    kinds2 = [str(x) for x in kinds if str(x).strip()]

    if not device_id or not isinstance(sub, dict):
        return {'ok': False, 'error': 'missing_device_or_subscription'}
    endpoint = str(sub.get('endpoint') or '').strip()
    keys = sub.get('keys') if isinstance(sub.get('keys'), dict) else {}
    p256dh = str((keys or {}).get('p256dh') or '').strip()
    auth = str((keys or {}).get('auth') or '').strip()
    if not endpoint or not p256dh or not auth:
        return {'ok': False, 'error': 'bad_subscription'}

    now = int(time.time())
    conn = db_connect()
    try:
        db_init(conn)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO sf_push_subscriptions (device_id,endpoint,p256dh,auth,ua,enabled,job_kinds_json,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,TRUE,%s,%s,%s) "
            "ON CONFLICT (endpoint) DO UPDATE SET device_id=EXCLUDED.device_id,p256dh=EXCLUDED.p256dh,auth=EXCLUDED.auth,ua=EXCLUDED.ua,enabled=TRUE,job_kinds_json=EXCLUDED.job_kinds_json,updated_at=EXCLUDED.updated_at",
            (device_id, endpoint, p256dh, auth, ua, json.dumps(kinds2, separators=(',', ':')), now, now),
        )
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return {'ok': True}


@app.post('/api/notifications/unsubscribe')
def api_notifications_unsubscribe(request: Request, payload: dict[str, Any] = Body(default={})):  # noqa: B008
    endpoint = str((payload or {}).get('endpoint') or '').strip()
    device_id = str((payload or {}).get('device_id') or '').strip()
    now = int(time.time())
    conn = db_connect()
    try:
        db_init(conn)
        cur = conn.cursor()
        if endpoint:
            cur.execute("UPDATE sf_push_subscriptions SET enabled=FALSE, updated_at=%s WHERE endpoint=%s", (now, endpoint))
        elif device_id:
            cur.execute("UPDATE sf_push_subscriptions SET enabled=FALSE, updated_at=%s WHERE device_id=%s", (now, device_id))
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return {'ok': True}


@app.post('/api/notifications/test')
def api_notifications_test(request: Request, payload: dict[str, Any] = Body(default={})):  # noqa: B008
    device_id = str((payload or {}).get('device_id') or '').strip()
    if not device_id:
        return {'ok': False, 'error': 'missing_device_id'}
    if not VAPID_PUBLIC_KEY or not VAPID_PRIVATE_KEY:
        return {'ok': False, 'error': 'push_not_configured'}

    conn = db_connect()
    try:
        db_init(conn)
        cur = conn.cursor()
        cur.execute(
            "SELECT endpoint,p256dh,auth FROM sf_push_subscriptions WHERE enabled=TRUE AND device_id=%s ORDER BY updated_at DESC LIMIT 1",
            (device_id,),
        )
        row = cur.fetchone()
    finally:
        try:
            conn.close()
        except Exception:
            pass

    if not row:
        return {'ok': False, 'error': 'no_subscription_for_device'}

    endpoint, p256dh, auth = str(row[0] or ''), str(row[1] or ''), str(row[2] or '')
    if not endpoint or not p256dh or not auth:
        return {'ok': False, 'error': 'bad_subscription'}

    try:
        body = json.dumps({'kind': 'test', 'state': 'completed', 'job_id': 'test', 'title': 'Test notification', 'url': '/#tab-history'}, separators=(',', ':'))
        from pywebpush import webpush  # type: ignore

        webpush(
            subscription_info={'endpoint': endpoint, 'keys': {'p256dh': p256dh, 'auth': auth}},
            data=body,
            vapid_private_key=_vapid_private_key_material(),
            vapid_claims={'sub': VAPID_SUBJECT},
            timeout=6,
        )
        return {'ok': True}
    except Exception as e:
        return {'ok': False, 'error': f'test_send_failed: {type(e).__name__}: {str(e)[:200]}'}


@app.get('/manifest.webmanifest')
def manifest_webmanifest():
    body = {
        'name': 'StoryForge',
        'short_name': 'StoryForge',
        'start_url': '/?pwa=1',
        'display': 'standalone',
        'background_color': '#0b1020',
        'theme_color': '#0b1020',
        'icons': [],
    }
    return Response(content=json.dumps(body), media_type='application/manifest+json', headers={'Cache-Control': 'no-store'})


@app.get('/sw.js')
def service_worker_js():
    # Minimal SW: handle push and notification click
    js = r"""
self.addEventListener('push', function(event){
  try{
    var data = {};
    try{ data = event.data ? event.data.json() : {}; }catch(e){ data = {}; }
    var kind = String(data.kind||'job');
    var state = String(data.state||'completed');
    var title = (state==='failed') ? 'Job failed' : 'Job completed';
    if (kind==='produce_audio') title = (state==='failed') ? 'Produce audio failed' : 'Produce audio completed';
    var body = String(data.title||data.job_id||'');
    var url = String(data.url||'/');
    event.waitUntil(
      self.registration.showNotification(title, {
        body: body,
        data: {url: url, raw: data},
        tag: kind + ':' + state,
        renotify: false,
      })
    );
  }catch(e){}
});

self.addEventListener('notificationclick', function(event){
  try{ event.notification.close(); }catch(e){}
  var url = '/';
  try{ url = (event.notification && event.notification.data && event.notification.data.url) ? event.notification.data.url : '/'; }catch(e){}
  event.waitUntil(
    clients.matchAll({type:'window', includeUncontrolled:true}).then(function(clis){
      for (var i=0;i<clis.length;i++){
        var c=clis[i];
        try{ if (c && c.focus){ c.focus(); c.navigate(url); return; } }catch(e){}
      }
      try{ return clients.openWindow(url); }catch(e){}
    })
  );
});
"""
    return Response(content=js, media_type='application/javascript', headers={'Cache-Control': 'no-store'})


@app.get('/api/deploy/status')
def api_deploy_status():
    """Public deploy status used by the debug-only deploy bar."""
    try:
        conn = db_connect()
        try:
            db_init(conn)
            cur = conn.cursor()
            cur.execute("SELECT value_json, updated_at FROM sf_settings WHERE key='deploy_state'")
            row = cur.fetchone()
        finally:
            conn.close()

        if not row:
            return {'ok': True, 'state': 'idle', 'message': '', 'updated_at': 0}

        vraw = str(row[0] or '').strip()
        try:
            v = json.loads(vraw) if vraw else {}
        except Exception:
            v = {}

        return {
            'ok': True,
            'state': str(v.get('state') or 'idle'),
            'message': str(v.get('message') or ''),
            'updated_at': int(row[1] or 0),
        }
    except Exception:
        # Best-effort: never break the UI
        return {'ok': True, 'state': 'unknown', 'message': '', 'updated_at': 0}


@app.get('/api/runtime_fingerprint')
def api_runtime_fingerprint():
    """Public, non-sensitive runtime fingerprint.

    This verifies what code is actually running in App Platform (vs what the
    deploy workflow *thinks* it deployed).
    """
    try:
        import hashlib
        import subprocess

        boot_js_hash = hashlib.sha256((DEBUG_BANNER_BOOT_JS or '').encode('utf-8', 'replace')).hexdigest()[:12]
        dbg_html_hash = hashlib.sha256((DEBUG_BANNER_HTML or '').encode('utf-8', 'replace')).hexdigest()[:12]

        git_sha = None
        try:
            git_sha = subprocess.check_output(
                ['git', 'rev-parse', '--short', 'HEAD'],
                stderr=subprocess.DEVNULL,
                timeout=0.25,
            ).decode().strip() or None
        except Exception:
            git_sha = None

        return {
            'ok': True,
            'sf_build': int(APP_BUILD or 0),
            'boot_js_hash': boot_js_hash,
            'debug_html_hash': dbg_html_hash,
            'git_sha': git_sha,
        }
    except Exception as e:
        return {'ok': False, 'error': 'runtime_fingerprint_failed', 'detail': str(e)[:200]}


@app.get('/api/deploy/stream')
async def api_deploy_stream():
    """SSE stream for deploy state.

    NOTE: App Platform/Cloudflare may buffer SSE. We keep this endpoint for
    completeness, but the debug UI now prefers WebSockets.
    """

    async def gen():
        import asyncio

        # Best-effort keepalive frames.
        yield ": boot " + (" " * 2048) + "\n\n"

        last_upd = None
        last_state = None
        tick = 0

        while True:
            try:
                def _load():
                    conn = db_connect()
                    try:
                        db_init(conn)
                        cur = conn.cursor()
                        cur.execute("SELECT value_json, updated_at FROM sf_settings WHERE key='deploy_state'")
                        row = cur.fetchone()
                        if not row:
                            return {'ok': True, 'state': 'idle', 'message': '', 'updated_at': 0}
                        vraw = str(row[0] or '').strip()
                        try:
                            v = json.loads(vraw) if vraw else {}
                        except Exception:
                            v = {}
                        return {
                            'ok': True,
                            'state': str(v.get('state') or 'idle'),
                            'message': str(v.get('message') or ''),
                            'updated_at': int(row[1] or 0),
                        }
                    finally:
                        try:
                            conn.close()
                        except Exception:
                            pass

                j = await asyncio.to_thread(_load)
                upd = int((j or {}).get('updated_at') or 0)
                st = str((j or {}).get('state') or '')

                if last_upd is None or upd != last_upd or st != last_state:
                    yield f"data: {json.dumps(j, separators=(',', ':'))}\n\n"
                    last_upd = upd
                    last_state = st
                else:
                    if (tick % 6) == 0:
                        yield ": keepalive\n\n"
            except Exception:
                yield f"data: {json.dumps({'ok': True, 'state': 'unknown', 'message': '', 'updated_at': 0}, separators=(',', ':'))}\n\n"

            tick += 1
            await asyncio.sleep(2.5)

    headers = {
        'Cache-Control': 'no-store, no-cache, must-revalidate',
        'Pragma': 'no-cache',
        'Expires': '0',
        'X-Accel-Buffering': 'no',
        'Connection': 'keep-alive',
    }
    return StreamingResponse(gen(), media_type='text/event-stream', headers=headers)


@app.websocket('/ws/deploy')
async def ws_deploy(ws: WebSocket):
    """WebSocket stream for deploy state.

    Debug UI should only connect when sf_debug_ui is enabled client-side.
    Server side is public but low-impact.
    """
    await ws.accept()

    import asyncio

    last_upd = None
    last_state = None
    tick = 0

    try:
        while True:
            def _load():
                conn = db_connect()
                try:
                    db_init(conn)
                    cur = conn.cursor()
                    cur.execute("SELECT value_json, updated_at FROM sf_settings WHERE key='deploy_state'")
                    row = cur.fetchone()
                    if not row:
                        return {'ok': True, 'state': 'idle', 'message': '', 'updated_at': 0}
                    vraw = str(row[0] or '').strip()
                    try:
                        v = json.loads(vraw) if vraw else {}
                    except Exception:
                        v = {}
                    return {
                        'ok': True,
                        'state': str(v.get('state') or 'idle'),
                        'message': str(v.get('message') or ''),
                        'updated_at': int(row[1] or 0),
                    }
                finally:
                    try:
                        conn.close()
                    except Exception:
                        pass

            j = await asyncio.to_thread(_load)
            upd = int((j or {}).get('updated_at') or 0)
            st = str((j or {}).get('state') or '')

            if last_upd is None or upd != last_upd or st != last_state:
                await ws.send_text(json.dumps(j, separators=(',', ':')))
                last_upd = upd
                last_state = st
            else:
                # keepalive
                if (tick % 6) == 0:
                    await ws.send_text('{"type":"keepalive"}')

            tick += 1
            await asyncio.sleep(2.0)
    except WebSocketDisconnect:
        return
    except Exception:
        try:
            await ws.close()
        except Exception:
            pass
        return


def _require_deploy_token(request: Request) -> None:
    # Reusing SF_DEPLOY_TOKEN env var; kept even though we removed the older pipeline code.
    if not SF_DEPLOY_TOKEN:
        raise HTTPException(status_code=500, detail='SF_DEPLOY_TOKEN not configured')
    tok = (request.headers.get('x-sf-deploy-token') or '').strip()
    if not tok or tok != SF_DEPLOY_TOKEN:
        raise HTTPException(status_code=401, detail='unauthorized')


@app.get('/api/deploy/token_fingerprint')
def api_deploy_token_fingerprint():
    """Debug-only helper: returns a short fingerprint of SF_DEPLOY_TOKEN without revealing it."""
    try:
        import hashlib

        v = (SF_DEPLOY_TOKEN or '').encode('utf-8')
        h = hashlib.sha256(v).hexdigest()
        return {'ok': True, 'sha256_8': h[:8], 'configured': bool(SF_DEPLOY_TOKEN)}
    except Exception:
        return {'ok': True, 'sha256_8': '', 'configured': bool(SF_DEPLOY_TOKEN)}


@app.post('/api/deploy/backfill_job_error_text')
def api_deploy_backfill_job_error_text(request: Request):
    """One-time backfill: move legacy error strings from jobs.sfml_url -> jobs.error_text.

    Safe to re-run; it only updates rows where:
    - error_text is empty
    - sfml_url looks like an error string (starts with 'error:')

    Auth: requires x-sf-deploy-token.
    """
    _require_deploy_token(request)
    try:
        conn = db_connect()
        try:
            db_init(conn)
            cur = conn.cursor()
            cur.execute(
                """
UPDATE jobs
SET error_text = sfml_url,
    sfml_url = ''
WHERE COALESCE(error_text, '') = ''
  AND COALESCE(sfml_url, '') LIKE 'error:%'
"""
            )
            n = int(cur.rowcount or 0)
            conn.commit()
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return {'ok': True, 'updated': n}
    except Exception as e:
        return {'ok': False, 'error': f'backfill_failed:{type(e).__name__}:{str(e)[:200]}'}


@app.get('/api/debug/latency')
def api_debug_latency(request: Request):
    """Token-gated latency probe to debug slow UI loads.

    Auth: x-sf-deploy-token (SF_DEPLOY_TOKEN)
    """
    _require_deploy_token(request)
    out: dict[str, Any] = {'ok': True}
    t0 = time.time()

    # DB connect + simple query
    try:
        t_db0 = time.time()
        conn = db_connect()
        try:
            db_init(conn)
            cur = conn.cursor()
            cur.execute('SELECT 1')
            cur.fetchone()
        finally:
            conn.close()
        out['db_ms'] = int((time.time() - t_db0) * 1000)
    except Exception as e:
        out['db_ms'] = None
        out['db_err'] = f'{type(e).__name__}: {str(e)[:160]}'

    # Gateway metrics (Tinybox) probe
    try:
        t_g0 = time.time()
        _get('/v1/metrics', timeout_s=12.0)
        out['gateway_metrics_ms'] = int((time.time() - t_g0) * 1000)
    except Exception as e:
        out['gateway_metrics_ms'] = None
        out['gateway_err'] = f'{type(e).__name__}: {str(e)[:160]}'

    out['total_ms'] = int((time.time() - t0) * 1000)
    return out


def _deploy_commit_from_payload(payload: dict[str, Any]) -> str:
    try:
        c = str((payload or {}).get('commit') or '').strip().lower()
        if c and len(c) >= 7:
            return c[:7]
    except Exception:
        pass
    # best-effort parse from message: "... (Commit abcdef0)"
    try:
        import re

        msg = str((payload or {}).get('message') or '')
        m = re.search(r"\bcommit\s+([0-9a-f]{7,40})\b", msg, flags=re.I)
        if not m:
            m = re.search(r"\(\s*Commit\s+([0-9a-f]{7,40})\s*\)", msg, flags=re.I)
        if m:
            return str(m.group(1) or '').strip().lower()[:7]
    except Exception:
        pass
    return ''


@app.post('/api/deploy/start')
def api_deploy_start(request: Request, payload: dict[str, Any] = Body(default={})):  # noqa: B008
    """Mark deploy as started. Call from your deploy hook/pipeline."""
    _require_deploy_token(request)
    now = int(time.time())
    msg = str((payload or {}).get('message') or 'Deploying…')
    commit = _deploy_commit_from_payload(payload)
    v = {'state': 'deploying', 'message': msg, 'commit': commit}

    conn = db_connect()
    try:
        db_init(conn)
        cur = conn.cursor()
        cur.execute(
            """
INSERT INTO sf_settings (key,value_json,updated_at)
VALUES ('deploy_state', %s, %s)
ON CONFLICT (key)
DO UPDATE SET value_json=EXCLUDED.value_json, updated_at=EXCLUDED.updated_at
""",
            (json.dumps(v, separators=(',', ':')), now),
        )
        conn.commit()
    finally:
        conn.close()

    return {'ok': True}


@app.post('/api/deploy/end')
def api_deploy_end(request: Request, payload: dict[str, Any] = Body(default={})):  # noqa: B008
    """Mark deploy as finished. Call from your deploy hook/pipeline."""
    _require_deploy_token(request)
    now = int(time.time())
    msg = str((payload or {}).get('message') or 'Deployed')
    commit = _deploy_commit_from_payload(payload)

    conn = db_connect()
    try:
        db_init(conn)
        cur = conn.cursor()

        # Guard: don't allow an older pipeline to clear a newer deploy.
        cur.execute("SELECT value_json FROM sf_settings WHERE key='deploy_state' LIMIT 1")
        row = cur.fetchone()
        if row and row[0]:
            try:
                cur_state = row[0] if isinstance(row[0], dict) else json.loads(row[0])
            except Exception:
                cur_state = {}
            try:
                cur_deploying = str((cur_state or {}).get('state') or '') == 'deploying'
                cur_commit = str((cur_state or {}).get('commit') or '').strip().lower()[:7]
                if cur_deploying and cur_commit and commit and (cur_commit != commit):
                    return {'ok': True, 'ignored': True, 'reason': 'commit_mismatch'}
            except Exception:
                pass

        v = {'state': 'idle', 'message': msg, 'commit': commit}
        cur.execute(
            """
INSERT INTO sf_settings (key,value_json,updated_at)
VALUES ('deploy_state', %s, %s)
ON CONFLICT (key)
DO UPDATE SET value_json=EXCLUDED.value_json, updated_at=EXCLUDED.updated_at
""",
            (json.dumps(v, separators=(',', ':')), now),
        )
        conn.commit()
    finally:
        conn.close()

    return {'ok': True}


# (Older /api/build + auto-reload logic intentionally not reintroduced.)

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
        color_hex = str(payload.get('color_hex') or '').strip()
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
            upsert_voice_db(conn, voice_id, engine, voice_ref, display_name, color_hex, enabled, sample_text, sample_url)
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
                            'error_text': (f"error: {type(e).__name__}: {str(e)[:200]}" + ("\n" + det[:1400] if det else '')),
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
                        'error_text': (f"error: {type(e).__name__}: {str(e)[:200]}" + ("\n" + det[:1400] if det else '')),
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

        engine = str((payload or {}).get('engine') or '').strip().lower() or 'tortoise'
        if engine not in ('tortoise', 'styletts2', 'xtts'):
            return {'ok': False, 'error': 'bad_engine'}

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

        # Build compact voice roster summary (filter by engine)
        vrows = []
        for v in voices:
            try:
                if engine and str(v.get('engine') or '').strip().lower() != engine:
                    continue
            except Exception:
                pass
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
                'Only choose voices from the provided roster (already filtered by engine).',
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
                        'color_hex': str(v.get('color_hex') or ''),
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
        eng = ''
        try:
            eng = str((casting or {}).get('engine') or '').strip().lower()
        except Exception:
            eng = ''
        if eng not in ('tortoise', 'styletts2'):
            eng = ''
        return {'ok': True, 'saved': True, 'assignments': assigns, 'engine': eng, 'roster': vrows}
    except Exception as e:
        return {'ok': False, 'error': f'casting_get_failed: {type(e).__name__}: {str(e)[:200]}'}


@app.post('/api/production/sfml_generate')
def api_production_sfml_generate(payload: dict[str, Any] = Body(default={})):  # noqa: B008
    """Generate SFML (StoryForge Markup Language) from story + saved casting.

    SFML v0 directives/lines:
      - voice [Name] = <voice_id>        (casting block at top)
      - scene id=<id> title="..."      (scene header)
      - [Name] <text>                   (speaker line)

    The output is plain text and is intended to be exportable/self-contained.
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

        # Build a strict casting map (character -> voice_id) preserving human-facing names.
        cmap: dict[str, str] = {}
        for a in assigns:
            try:
                ch = str((a or {}).get('character') or '').strip()
                vid = str((a or {}).get('voice_id') or '').strip()
                if ch and vid:
                    cmap[ch] = vid
            except Exception:
                pass

        # Ensure narrator exists in map
        if 'Narrator' in cmap and 'NARRATOR' not in cmap:
            cmap['NARRATOR'] = cmap['Narrator']
        if 'NARRATOR' not in cmap:
            for k, v in list(cmap.items()):
                if str(k).strip().lower() == 'narrator':
                    cmap['NARRATOR'] = v
                    break

        # Scene policy: avoid over-splitting, but don't force everything into one tiny scene.
        story_chars = len(story_md or '')
        story_words = len((story_md or '').split())
        # For very short stories, 1 scene. For normal short stories, allow up to 2. Otherwise up to 3.
        if story_chars < 500 and story_words < 90:
            max_scenes = 1
        elif story_chars < 1600 and story_words < 320:
            max_scenes = 2
        else:
            max_scenes = 3

        prompt = {
            'format': 'SFML',
            'version': 0,
            'story': {'id': story_id, 'title': title, 'story_md': story_md},
            'casting_map': cmap,
            'scene_policy': {'max_scenes': int(max_scenes), 'default_scenes': (1 if max_scenes == 1 else 2)},
            'rules': [
                'Output MUST be plain SFML text only. No markdown, no fences.',
                'FORMAT: Use SFML v1 (succinct blocks + indentation). Do NOT use chevrons like <<CAST>> or <<SCENE>>.',
                'CASTING: At the top, emit a casting block exactly like:\ncast:\n  Name: voice_id',
                'CASTING: One mapping per character. Names must match the speaker tags used later.',
                'CASTING: Always include Narrator.',
                'DIRECTIVES (optional): You may include directives at top-level: @tortoise_preset, @tortoise_candidates, @seed, @tortoise_chunk_chars, @tortoise_chunk_pause_ms',
                'PAUSES (optional): In scene bodies, you may include: PAUSE: 0.25 (indented by two spaces). Use pauses to slow rushed narration.',
                'SCENES: Emit 1..max_scenes scene blocks. Each scene header is: scene <id> "<title>":',
                'SCENES: If max_scenes=1, output exactly ONE scene block (scene-1) but still cover the whole story.',
                'SCENES: Otherwise, output between 1 and max_scenes scenes; do not create scenes for minor mood shifts.',
                'BODY: Inside a scene block, content is indented by two spaces.',
                'BODY: You can emit either single speaker lines: [Name] text',
                'BODY: Or speaker blocks (preferred for consecutive lines by same speaker): Name: then 4-space indented bullets "- ..."',
                'BODY: Speaker blocks MUST be treated as one segment; use them to avoid splitting delivery.',
                'BODY: Every [Name] and every Name: in a speaker block must exist in cast: mappings.',
                'Do not invent voice ids; only use voice ids from casting_map values.',
                'For Tortoise delivery, keep punctuation; do not strip commas/periods.',
                'Keep each bullet line to a single line; split long paragraphs into multiple bullets within the speaker block.',
                'COVERAGE: Include the full story content (do not stop early; do not summarize).',
                'COVERAGE: Keep emitting speaker lines until the story reaches a clear ending.',
                'Do not output JSON.',
            ],
            'example': (
                '# SFML v1\n'
                '@tortoise_preset: standard\n'
                '@tortoise_candidates: 2\n'
                '@tortoise_chunk_chars: 450\n'
                '@tortoise_chunk_pause_ms: 120\n'
                '\n'
                'cast:\n'
                '  Narrator: indigo-dawn\n'
                '  Maris: lunar-violet\n'
                '\n'
                'scene scene-1 "Intro":\n'
                '  Narrator:\n'
                '    - The lighthouse stood silent on the cliff.\n'
                '    - The sea breathed below, slow and steady.\n'
                '  PAUSE: 0.25\n'
                '  Maris:\n'
                '    - I can hear the sea breathing below.\n'
            ),
        }

        req = {
            'model': 'google/gemma-2-9b-it',
            'messages': [
                {'role': 'user', 'content': 'Return ONLY SFML plain text.\n\n' + json.dumps(prompt, separators=(',', ':'))},
            ],
            'temperature': 0.3,
            'max_tokens': 2200,
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

        # Normalize common format mistakes so exported SFML is consistent.
        # For v1 we mainly normalize indentation (2 spaces) and avoid tabs.
        try:
            lines = []
            for ln in (txt or '').splitlines():
                # replace tabs with two spaces
                ln = (ln or '').replace('\t', '  ')
                lines.append(ln.rstrip())
            txt = '\n'.join(lines).strip()
        except Exception:
            pass

        # Cap size
        if len(txt) > 20000:
            txt = txt[:20000]

        # Persist SFML into the story record (overwrite on regenerate)
        try:
            now = int(time.time())
            conn2 = db_connect()
            try:
                db_init(conn2)
                cur2 = conn2.cursor()
                cur2.execute(
                    'UPDATE sf_stories SET sfml_text=%s, updated_at=%s WHERE id=%s',
                    (txt, now, story_id),
                )
                conn2.commit()
            finally:
                conn2.close()
        except Exception:
            # best-effort; do not fail generation
            pass

        return {'ok': True, 'sfml': txt}
    except Exception as e:
        return {'ok': False, 'error': f'sfml_generate_failed: {type(e).__name__}: {str(e)[:200]}'}


@app.post('/api/production/sfml_save')
def api_production_sfml_save(payload: dict[str, Any] = Body(default={})):  # noqa: B008
    """Persist edited SFML text for a story."""
    try:
        story_id = str((payload or {}).get('story_id') or '').strip()
        sfml_text = str((payload or {}).get('sfml_text') or '')
        if not story_id:
            return {'ok': False, 'error': 'missing_story_id'}

        # Best-effort: store as-is. Parsing/validation can come later.
        now = int(time.time())
        conn = db_connect()
        try:
            db_init(conn)
            cur = conn.cursor()
            cur.execute('UPDATE sf_stories SET sfml_text=%s, updated_at=%s WHERE id=%s', (sfml_text, now, story_id))
            conn.commit()
        finally:
            conn.close()

        return {'ok': True}
    except Exception as e:
        return {'ok': False, 'error': f'sfml_save_failed: {type(e).__name__}: {str(e)[:200]}'}


@app.post('/api/production/produce_audio')
def api_production_produce_audio(payload: dict[str, Any] = Body(default={})):  # noqa: B008
    """Queue a job to produce final story audio from persisted SFML + casting.

    Worker execution is implemented next (Tinybox). For now we create a job row
    so the UI flow (Produce -> Jobs) is in place.
    """
    try:
        story_id = str((payload or {}).get('story_id') or '').strip()
        if not story_id:
            return {'ok': False, 'error': 'missing_story_id'}

        conn = db_connect()
        try:
            db_init(conn)
            cur = conn.cursor()
            cur.execute('SELECT title, sfml_text FROM sf_stories WHERE id=%s', (story_id,))
            row = cur.fetchone()
        finally:
            conn.close()

        if not row:
            return {'ok': False, 'error': 'story_not_found'}

        title = str(row[0] or story_id)
        sfml = str(row[1] or '')
        if not sfml.strip():
            return {'ok': False, 'error': 'missing_sfml'}

        # Production primitive: snapshot exactly what we send to the job.
        engine = str((payload or {}).get('engine') or '').strip()

        # Snapshot casting at production runtime (source of truth: sf_castings).
        casting = {}
        try:
            conn2 = db_connect()
            try:
                db_init(conn2)
                cur2 = conn2.cursor()
                cur2.execute('SELECT casting FROM sf_castings WHERE story_id=%s', (story_id,))
                crow = cur2.fetchone()
            finally:
                conn2.close()
            if crow and crow[0] is not None:
                v = crow[0]
                if isinstance(v, str):
                    casting = json.loads(v) if v.strip() else {}
                else:
                    casting = v if isinstance(v, dict) else {}
        except Exception:
            casting = {}

        # Snapshot effective runtime params (keep global settings as source of truth; store what was used).
        params = {}
        try:
            p = _get_tinybox_provider() or {}
            gpus = []
            try:
                gpus = _get_allowed_voice_gpus()
            except Exception:
                gpus = []
            threads = None
            try:
                threads = int((p or {}).get('voice_threads') or 0) or None
            except Exception:
                threads = None
            # tortoise-specific knobs that affect determinism
            tortoise_split_min_text = None
            try:
                v = (p or {}).get('tortoise_split_min_text')
                tortoise_split_min_text = int(v) if v is not None else None
            except Exception:
                tortoise_split_min_text = None
            params = {
                'engine': engine,
                'gpus': gpus,
                'threads': threads,
                'tortoise_split_min_text': tortoise_split_min_text,
                'gateway_base': str(GATEWAY_BASE or ''),
                'provider': 'tinybox',
            }
        except Exception:
            params = {'engine': engine}

        import hashlib

        sfml_bytes = sfml.encode('utf-8', 'replace')
        sfml_sha = hashlib.sha256(sfml_bytes).hexdigest()

        # Content-addressed SFML storage (Spaces): sfml/<sha256>.sfml
        sfml_url = ''
        try:
            from .spaces_upload import upload_bytes_dedup

            _k, sfml_url, _existed = upload_bytes_dedup(
                sfml_bytes,
                obj_key=f"sfml/{sfml_sha}.sfml",
                content_type='text/plain; charset=utf-8',
            )
        except Exception:
            sfml_url = ''

        prod_id = f"prod_{int(time.time())}_{story_id.replace('/', '_').replace(' ', '_')[:48]}_{sfml_sha[:8]}"
        now = int(time.time())
        try:
            conn = db_connect()
            try:
                db_init(conn)
                cur = conn.cursor()

                # Keep a small preview in DB for UI (full text lives in Spaces).
                sfml_preview = (sfml or '').strip().replace('\r\n', '\n').replace('\r', '\n')
                if len(sfml_preview) > 800:
                    sfml_preview = sfml_preview[:800]

                cur.execute(
                    """
INSERT INTO sf_productions (id, story_id, label, engine, sfml_sha256, sfml_url, sfml_bytes, sfml_preview, casting, params, created_at, updated_at)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s)
ON CONFLICT (id) DO NOTHING
""",
                    (
                        prod_id,
                        story_id,
                        '',
                        engine,
                        sfml_sha,
                        sfml_url,
                        int(len(sfml_bytes)),
                        sfml_preview,
                        json.dumps(casting, separators=(',', ':')),
                        json.dumps(params, separators=(',', ':')),
                        now,
                        now,
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception:
            pass

        job_id = 'produce_' + str(int(time.time())) + '_' + story_id.replace('/', '_').replace(' ', '_')[:48]
        meta = {
            'story_id': story_id,
            'story_title': title,
            'engine': engine,
            'production_id': prod_id,
            'sfml_sha256': sfml_sha,
            'sfml_url': sfml_url,
        }
        _job_patch(
            job_id,
            {
                'title': f'Produce audio ({title})',
                'kind': 'produce_audio',
                'meta_json': json.dumps(meta, separators=(',', ':')),
                'state': 'queued',
                'started_at': 0,
                'finished_at': 0,
                'total_segments': 0,
                'segments_done': 0,
                'sfml_url': sfml_url,
            },
        )

        return {'ok': True, 'job_id': job_id, 'production_id': prod_id, 'sfml_url': sfml_url}
    except Exception as e:
        return {'ok': False, 'error': f'produce_failed: {type(e).__name__}: {str(e)[:200]}'}


@app.get('/api/library/story_audio/list/{story_id}')
def api_story_audio_list(story_id: str):
    """List saved audio versions for a story."""
    try:
        story_id = str(story_id or '').strip()
        if not story_id:
            return {'ok': False, 'error': 'missing_story_id'}
        conn = db_connect()
        try:
            db_init(conn)
            cur = conn.cursor()
            cur.execute(
                """
SELECT a.id, a.job_id, a.production_id, a.label, a.mp3_url, a.meta_json, a.created_at,
       p.sfml_url, p.engine, p.sfml_preview,
       j.sfml_url, j.meta_json
FROM sf_story_audio a
LEFT JOIN sf_productions p ON p.id = a.production_id
LEFT JOIN jobs j ON j.id = a.job_id
WHERE a.story_id=%s
ORDER BY a.created_at DESC
LIMIT 50
""",
                (story_id,),
            )
            rows = cur.fetchall()
        finally:
            conn.close()
        out = []
        for r in rows:
            # r: id, job_id, production_id, label, mp3_url, meta_json, created_at,
            #    p_sfml_url, p_engine, p_sfml_preview,
            #    j_sfml_url, j_meta_json
            prod_sfml_url = str(r[7] or '')
            prod_engine = str(r[8] or '')
            prod_preview = str(r[9] or '')

            job_sfml_url = str(r[10] or '')
            # Legacy: sfml_url was sometimes abused as a log/error/details field.
            if not (job_sfml_url.startswith('http://') or job_sfml_url.startswith('https://')):
                job_sfml_url = ''

            job_engine = ''
            try:
                jm = str(r[11] or '').strip()
                if jm:
                    jmj = json.loads(jm)
                    if isinstance(jmj, dict) and jmj.get('engine'):
                        job_engine = str(jmj.get('engine') or '').strip()
            except Exception:
                job_engine = ''

            out.append({
                'id': int(r[0]),
                'job_id': str(r[1] or ''),
                'production_id': str(r[2] or ''),
                'label': str(r[3] or ''),
                'mp3_url': str(r[4] or ''),
                'meta_json': str(r[5] or ''),
                'created_at': int(r[6] or 0),
                # Prefer production metadata, fallback to job metadata for legacy rows
                'sfml_url': prod_sfml_url or job_sfml_url,
                'engine': prod_engine or job_engine,
                'sfml_preview': prod_preview,
            })
        return {'ok': True, 'items': out}
    except Exception as e:
        return {'ok': False, 'error': f'list_failed: {type(e).__name__}: {str(e)[:200]}'}


@app.post('/api/library/story_audio/save')
def api_story_audio_save(payload: dict[str, Any] = Body(default={})):  # noqa: B008
    """Save a completed produce_audio job into the story library as a versioned audio item."""
    try:
        story_id = str((payload or {}).get('story_id') or '').strip()
        job_id = str((payload or {}).get('job_id') or '').strip()
        mp3_url = str((payload or {}).get('mp3_url') or '').strip()
        meta_json = str((payload or {}).get('meta_json') or '').strip()
        if not story_id or not job_id or not mp3_url:
            return {'ok': False, 'error': 'missing_required_fields'}

        # Build label: <story title> — <YYYY-MM-DD HH:mm> (America/New_York)
        from datetime import datetime
        try:
            from zoneinfo import ZoneInfo

            tz = ZoneInfo('America/New_York')
        except Exception:
            tz = None
        now_dt = datetime.now(tz) if tz else datetime.now()
        ts_label = now_dt.strftime('%Y-%m-%d %H:%M')

        conn = db_connect()
        try:
            db_init(conn)
            cur = conn.cursor()
            cur.execute('SELECT title FROM sf_stories WHERE id=%s', (story_id,))
            row = cur.fetchone()
            title = str((row[0] if row else '') or story_id)
            label = f"{title} — {ts_label}"

            # Best-effort: link saved audio to a durable production recipe.
            production_id = ''
            try:
                cur.execute('SELECT meta_json FROM jobs WHERE id=%s', (job_id,))
                jrow = cur.fetchone()
                jm = str((jrow[0] if jrow else '') or '').strip()
                if jm:
                    jmj = json.loads(jm)
                    if isinstance(jmj, dict) and jmj.get('production_id'):
                        production_id = str(jmj.get('production_id') or '').strip()
            except Exception:
                production_id = ''

            now = int(time.time())
            cur.execute(
                'INSERT INTO sf_story_audio (story_id, job_id, production_id, label, mp3_url, meta_json, created_at, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                (story_id, job_id, production_id, label, mp3_url, meta_json, now, now),
            )
            conn.commit()
        finally:
            conn.close()

        return {'ok': True}
    except Exception as e:
        return {'ok': False, 'error': f'save_failed: {type(e).__name__}: {str(e)[:200]}'}


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

        eng = str((payload or {}).get('engine') or '').strip().lower()
        if eng not in ('tortoise', 'styletts2'):
            eng = ''

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
                (story_id, json.dumps({'engine': eng, 'assignments': norm}, separators=(',', ':')), now, now),
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
            color_hex = str(payload.get('color_hex') if 'color_hex' in payload else existing.get('color_hex') or '')
            enabled = bool(payload.get('enabled') if 'enabled' in payload else existing.get('enabled', True))
            sample_text = str(payload.get('sample_text') if 'sample_text' in payload else existing.get('sample_text') or '')
            sample_url = str(payload.get('sample_url') if 'sample_url' in payload else existing.get('sample_url') or '')
            upsert_voice_db(conn, voice_id, engine, voice_ref, display_name, color_hex, enabled, sample_text, sample_url)
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
            "You are generating a voice name and a matching color swatch. "
            "Return ONLY strict JSON with keys: name, color_hex. "
            "Rules: "
            "- name: 1-3 words, letters/spaces only (no punctuation). "
            "- color_hex: a hex color in the form #RRGGBB. "
            "- The name should include a real color word that matches the hex (e.g. 'Amber', 'Violet', 'Slate', 'Teal', 'Ruby', 'Gold', 'Ivory', 'Navy'). "
            "Example output: {\"name\":\"Midnight Teal\",\"color_hex\":\"#0ea5a6\"}"
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
        out = ''
        try:
            ch0 = (((j or {}).get('choices') or [])[0] or {})
            msg = ch0.get('message') or {}
            out = str(msg.get('content') or ch0.get('text') or '')
        except Exception:
            out = ''
        out = out.strip()

        import re

        # Parse JSON (best-effort) and sanitize.
        name = ''
        color_hex = ''
        try:
            obj = json.loads(out)
            if isinstance(obj, dict):
                name = str(obj.get('name') or '').strip()
                color_hex = str(obj.get('color_hex') or '').strip()
        except Exception:
            # Fallback: try to extract fields
            name = ''
            color_hex = ''

        # sanitize name to letters/spaces only
        name = ' '.join(name.strip().split())
        name = re.sub(r"[^A-Za-z ]+", "", name).strip()
        name = re.sub(r"\s+", " ", name).strip()
        if not name:
            raise RuntimeError('empty_name')
        words = name.split(' ')
        if len(words) > 3:
            name = ' '.join(words[:3]).strip()
        if len(name) > 32:
            name = name[:32].rsplit(' ', 1)[0].strip() or name[:32]

        # sanitize/validate color
        m = re.match(r"^#[0-9a-fA-F]{6}$", color_hex or '')
        if not m:
            color_hex = '#64748b'

        return {'ok': True, 'name': name, 'color_hex': color_hex}
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
                    'voice_engines': [str(x).strip() for x in (p.get('voice_engines') or []) if str(x).strip() in ('xtts', 'tortoise', 'styletts2')],
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
                        json={'engine': engine, 'voice': voice_fixed, 'text': chunk, 'upload': True, 'gpu': gpu, 'threads': threads, 'job_id': job_id},
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
                # If the job was aborted, don't overwrite it as failed.
                try:
                    conn2 = db_connect()
                    st2 = ''
                    try:
                        db_init(conn2)
                        cur2 = conn2.cursor()
                        cur2.execute('SELECT state FROM jobs WHERE id=%s', (job_id,))
                        row2 = cur2.fetchone()
                        st2 = str(row2[0] or '') if row2 else ''
                    finally:
                        try:
                            conn2.close()
                        except Exception:
                            pass
                    if st2 == 'aborted':
                        return
                except Exception:
                    pass

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
                        'error_text': (f"error: {type(e).__name__}: {str(e)[:200]}" + ("\n" + det[:1400] if det else '')),
                    },
                )

        import threading

        threading.Thread(target=worker, daemon=True).start()
        return {'ok': True, 'job_id': job_id}
    except Exception as e:
        return {'ok': False, 'error': f'tts_job_failed: {type(e).__name__}: {e}'}