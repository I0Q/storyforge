import os
import time
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright


BASE_URL = os.environ.get("SF_BASE_URL", "https://storyforge.i0q.com").rstrip("/")
TODO_TOKEN = (os.environ.get("SF_TODO_TOKEN") or "").strip()

# Keep this list small and high-signal.
CRITICAL_URLS = {
    "todo": "/todo",
    "voices_new": "/voices/new",
    "voices_edit_luna": "/voices/luna/edit",
    "library_new": "/library/new",
    "library_story_view": "/library/story/maris-listening-lighthouse/view",
}

VIEWPORTS = [
    (390, 844),   # iPhone-ish
    (1280, 800),  # desktop-ish
]


def _artifact_dir() -> Path:
    out = Path(os.environ.get("SF_UI_ARTIFACTS", "ui_artifacts"))
    stamp = time.strftime("%Y%m%d-%H%M%S")
    d = out / stamp
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.mark.parametrize("width,height", VIEWPORTS)
def test_ui_smoke(width: int, height: int):
    if not TODO_TOKEN:
        pytest.skip("Set SF_TODO_TOKEN to run UI smoke tests")

    artifacts = _artifact_dir()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": width, "height": height})

        # Bootstrap an authenticated session (mints sf_sid cookie).
        r = ctx.request.post(
            f"{BASE_URL}/api/session",
            headers={"x-sf-todo-token": TODO_TOKEN},
        )
        assert r.status in (200, 204), f"/api/session status={r.status} body={r.text()}"

        page = ctx.new_page()

        def snap(name: str):
            page.screenshot(path=str(artifacts / f"{name}_{width}x{height}.png"), full_page=True)

        # ---- /todo ----
        page.goto(f"{BASE_URL}{CRITICAL_URLS['todo']}?ts={int(time.time())}", wait_until="domcontentloaded")
        page.wait_for_timeout(250)
        assert page.locator("text=Archive done").first.is_visible()
        snap("todo")

        # Interaction: toggle first checkbox twice (idempotent)
        cbs = page.locator("input[type=checkbox]")
        if cbs.count() > 0:
            cbs.nth(0).click()
            page.wait_for_timeout(250)
            cbs.nth(0).click()
            page.wait_for_timeout(250)

        # ---- /voices/luna/edit ----
        page.goto(f"{BASE_URL}{CRITICAL_URLS['voices_edit_luna']}?ts={int(time.time())}", wait_until="domcontentloaded")
        page.wait_for_timeout(250)
        assert page.locator("text=Edit voice").first.is_visible()
        assert page.locator("text=Provider fields").first.is_visible()
        assert page.locator("text=Test sample").first.is_visible()
        snap("voices_edit")

        # Interaction: click Test sample and wait for audio src OR sample URL text.
        page.locator("role=button[name='Test sample']").click()
        # Give TTS a bit of time (network + provider). Keep bounded.
        try:
            page.wait_for_function(
                """() => {
                    const a = document.querySelector('audio');
                    if (a && a.src && a.src.length > 8) return true;
                    const out = document.getElementById('out');
                    return !!(out && out.textContent && out.textContent.toLowerCase().includes('sample'));
                }""",
                timeout=60_000,
            )
        except Exception:
            # Capture state for debugging but don't hard-fail on flaky provider.
            snap("voices_edit_after_test_sample")

        # Interaction: save (with existing values)
        page.locator("role=button[name='Save']").click()
        page.wait_for_timeout(500)

        # ---- /voices/new ----
        page.goto(f"{BASE_URL}{CRITICAL_URLS['voices_new']}?ts={int(time.time())}", wait_until="domcontentloaded")
        page.wait_for_timeout(250)
        assert page.locator("text=Generate voice").first.is_visible()
        snap("voices_new")

        # ---- /library/new ----
        page.goto(f"{BASE_URL}{CRITICAL_URLS['library_new']}?ts={int(time.time())}", wait_until="domcontentloaded")
        page.wait_for_timeout(250)
        assert page.locator("text=New story").first.is_visible() or page.locator("text=Library").first.is_visible()
        snap("library_new")

        # ---- /library/story/.../view ----
        page.goto(f"{BASE_URL}{CRITICAL_URLS['library_story_view']}?ts={int(time.time())}", wait_until="domcontentloaded")
        page.wait_for_timeout(250)
        assert page.locator("text=Show code").first.is_visible()
        snap("library_story_view")

        # Interaction: toggle Show code twice.
        page.locator("role=button[name='Show code']").click()
        page.wait_for_timeout(300)
        page.locator("role=button[name='Show code']").click()
        page.wait_for_timeout(300)

        ctx.close()
        browser.close()
