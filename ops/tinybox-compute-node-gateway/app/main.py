from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import requests
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import Response

APP_NAME = "tinybox-compute-node-gateway"

# Gateway auth (App Platform -> gateway)
GATEWAY_TOKEN_FILE = Path(os.environ.get("GATEWAY_TOKEN_FILE", "/root/.config/storyforge-cloud/gateway_token"))

# Tinybox compute node (gateway -> tinybox over tailscale)
TINYBOX_BASE = os.environ.get("TINYBOX_BASE", "http://100.75.30.1:8790").rstrip("/")
TINYBOX_TOKEN_FILE = Path(os.environ.get("TINYBOX_TOKEN_FILE", "/root/.config/storyforge-cloud/tinybox_token"))

app = FastAPI(title=APP_NAME, version="0.2")


def _read(p: Path) -> str:
    try:
        return p.read_text().strip()
    except Exception:
        return ""


def _auth(authorization: str | None) -> None:
    tok = _read(GATEWAY_TOKEN_FILE)
    if not tok:
        raise HTTPException(status_code=500, detail="gateway_token_not_configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="unauthorized")
    got = authorization.removeprefix("Bearer ").strip()
    if got != tok:
        raise HTTPException(status_code=403, detail="forbidden")


def _tinybox_headers() -> dict[str, str]:
    tok = _read(TINYBOX_TOKEN_FILE)
    if not tok:
        raise HTTPException(status_code=500, detail="tinybox_token_not_configured")
    return {"Authorization": "Bearer " + tok}


def _filter_resp_headers(h: dict[str, str]) -> dict[str, str]:
    drop = {
        "content-encoding",
        "transfer-encoding",
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "upgrade",
    }
    out: dict[str, str] = {}
    for k, v in h.items():
        if k.lower() in drop:
            continue
        out[k] = v
    return out


@app.get("/ping")
def ping():
    return {"ok": True, "service": APP_NAME}


@app.api_route("/v1/{p:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_v1(p: str, request: Request, authorization: str | None = Header(default=None)):
    _auth(authorization)

    url = f"{TINYBOX_BASE}/v1/{p}"
    headers = _tinybox_headers()
    params = dict(request.query_params)

    method = request.method.upper()
    raw_body = await request.body()
    ctype = (request.headers.get("content-type") or "").lower()

    req_kwargs: dict[str, Any] = {"headers": headers, "params": params, "timeout": 90}

    if method in ("POST", "PUT", "PATCH"):
        if "application/json" in ctype:
            try:
                req_kwargs["json"] = requests.utils.json.loads(raw_body.decode("utf-8")) if raw_body else {}
            except Exception:
                req_kwargs["data"] = raw_body
        else:
            req_kwargs["data"] = raw_body

    r = requests.request(method, url, **req_kwargs)

    return Response(
        content=r.content,
        status_code=r.status_code,
        headers=_filter_resp_headers(dict(r.headers)),
        media_type=r.headers.get("content-type"),
    )
