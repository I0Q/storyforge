from __future__ import annotations

import hashlib
import hmac
import os
import time

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

PASSPHRASE_SHA256 = (os.environ.get("PASSPHRASE_SHA256") or "").strip().lower()
SESSION_TTL_SEC = 24 * 60 * 60


def _enabled() -> bool:
    return bool(PASSPHRASE_SHA256) and len(PASSPHRASE_SHA256) == 64


def _sign_session(ts: int) -> str:
    # Stateless cookie: <ts>.<hmac>
    key = PASSPHRASE_SHA256.encode("utf-8")
    msg = str(ts).encode("utf-8")
    sig = hmac.new(key, msg, hashlib.sha256).hexdigest()
    return f"{ts}.{sig}"


def _is_session_authed(request: Request) -> bool:
    v = request.cookies.get("sf_sid")
    if not v:
        return False
    try:
        ts_s, sig = v.split(".", 1)
        ts = int(ts_s)
    except Exception:
        return False

    now = int(time.time())
    if ts > now + 60:
        return False
    if (now - ts) > SESSION_TTL_SEC:
        return False

    expected_sig = _sign_session(ts).split(".", 1)[1]
    return hmac.compare_digest(sig, expected_sig)


def _login_html(err: str = "") -> str:
    err_html = ""
    if err:
        esc = err.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        err_html = f"<div class='err'>{esc}</div>"

    return (
        "<!doctype html>"
        "<html><head>"
        "<meta charset='utf-8'/>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'/>"
        "<title>StoryForge - Login</title>"
        "<style>"
        "body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#0b1020;color:#e7edff;padding:18px;max-width:520px;margin:0 auto;}"
        ".card{border:1px solid #24305e;border-radius:16px;padding:14px;background:#0f1733;margin-top:18px;}"
        "label{display:block;color:#a8b3d8;font-size:12px;margin:0 0 6px;}"
        "input{width:100%;padding:12px;border:1px solid #24305e;border-radius:12px;background:#0b1020;color:#e7edff;font-size:16px;}"
        "button{margin-top:12px;width:100%;padding:12px;border-radius:12px;border:1px solid #24305e;background:#163a74;color:#fff;font-weight:950;}"
        ".err{margin-top:10px;color:#ff4d4d;font-weight:800;}"
        ".muted{color:#a8b3d8;font-size:12px;margin-top:10px;}"
        "</style>"
        "</head><body>"
        "<h2 style='margin:0'>StoryForge</h2>"
        "<div class='muted'>Enter passphrase to continue.</div>"
        "<div class='card'>"
        "<form method='post' action='/login'>"
        "<label for='pass'>Passphrase</label>"
        "<input id='pass' name='passphrase' type='password' autocomplete='current-password' autofocus required />"
        "<button type='submit'>Unlock</button>"
        f"{err_html}"
        "</form></div></body></html>"
    )


def register_passphrase_auth(app: FastAPI) -> None:
    @app.middleware("http")
    async def _gate(request: Request, call_next):
        # Fail-open until configured so we don't lock ourselves out.
        if not _enabled():
            return await call_next(request)

        if request.url.path in ("/login", "/logout", "/ping"):
            return await call_next(request)

        if _is_session_authed(request):
            return await call_next(request)

        accept = (request.headers.get("accept") or "").lower()
        wants_html = ("text/html" in accept) or (accept == "")
        if wants_html:
            return RedirectResponse(url="/login", status_code=302)
        return Response(content="unauthorized", status_code=401)

    @app.get("/login")
    def login_get(request: Request):
        if _enabled() and _is_session_authed(request):
            resp = RedirectResponse(url="/", status_code=302)
            resp.headers["Cache-Control"] = "no-store"
            return resp
        resp = HTMLResponse(_login_html(err=str(request.query_params.get("err") or "")))
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.post("/login")
    def login_post(passphrase: str = Form(default="")):
        if not _enabled():
            resp = RedirectResponse(url="/login", status_code=302)
            resp.headers["Cache-Control"] = "no-store"
            return resp

        digest = hashlib.sha256((passphrase or "").encode("utf-8")).hexdigest().lower()
        if not hmac.compare_digest(digest, PASSPHRASE_SHA256):
            time.sleep(0.35)
            resp = RedirectResponse(url="/login?err=Wrong%20passphrase", status_code=302)
            resp.headers["Cache-Control"] = "no-store"
            return resp

        ts = int(time.time())
        sid = _sign_session(ts)
        resp = RedirectResponse(url="/", status_code=302)
        resp.headers["Cache-Control"] = "no-store"
        resp.set_cookie(
            key="sf_sid",
            value=sid,
            max_age=SESSION_TTL_SEC,
            httponly=True,
            secure=True,
            samesite="lax",
            path="/",
        )
        return resp

    @app.get("/logout")
    def logout():
        resp = RedirectResponse(url="/login", status_code=302)
        resp.headers["Cache-Control"] = "no-store"
        resp.delete_cookie("sf_sid", path="/")
        return resp
