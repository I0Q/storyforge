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
    "library_story_edit": "/library/story/maris-listening-lighthouse",
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

        # Ensure cookie actually landed in the browser context.
        cookies = ctx.cookies()
        assert any(c.get('name') == 'sf_sid' for c in cookies), f"sf_sid cookie missing; cookies={cookies}"

        page = ctx.new_page()

        def snap(name: str):
            page.screenshot(path=str(artifacts / f"{name}_{width}x{height}.png"), full_page=True)

        def goto(path: str):
            url = f"{BASE_URL}{path}?ts={int(time.time())}"
            last = None
            for _ in range(3):
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                    page.wait_for_timeout(250)
                    # If we got bounced to login, fail with a useful artifact.
                    if "/login" in (page.url or ""):
                        snap("redirected_to_login")
                        raise AssertionError(f"redirected_to_login url={page.url}")
                    return
                except Exception as e:
                    last = e
                    # Playwright can throw net::ERR_ABORTED transiently on some SPAs.
                    page.wait_for_timeout(500)
            raise last  # type: ignore[misc]

        # ---- /todo ----
        goto(CRITICAL_URLS['todo'])
        page.wait_for_timeout(250)
        assert page.locator("text=Archive done").first.is_visible()
        snap("todo")

        # Interaction: toggle first *todo item* checkbox twice (idempotent).
        # (Avoid the Archived toggle switch checkbox which is hidden on some layouts.)
        cbs = page.locator("input[type=checkbox][data-id]")
        if cbs.count() > 0:
            cbs.nth(0).scroll_into_view_if_needed()
            cbs.nth(0).click()
            page.wait_for_timeout(250)
            cbs.nth(0).click()
            page.wait_for_timeout(250)

        # ---- /voices/luna/edit ----
        goto(CRITICAL_URLS['voices_edit_luna'])
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
        goto(CRITICAL_URLS['voices_new'])
        page.wait_for_timeout(250)
        # Page heading text can vary; check for distinctive training section.
        assert page.locator("text=Training").first.is_visible()
        snap("voices_new")

        # ---- /library/new ----
        goto(CRITICAL_URLS['library_new'])
        page.wait_for_timeout(250)
        assert page.locator("text=New story").first.is_visible() or page.locator("text=Library").first.is_visible()
        snap("library_new")

        # ---- /library/story/... (edit) ----
        goto(CRITICAL_URLS['library_story_edit'])
        page.wait_for_timeout(250)
        assert page.locator("text=Autosave:").first.is_visible()
        snap("library_story_edit")

        # Interaction: type in title and wait for saved.
        title = page.locator("input[name='title']").first
        title.click()
        title.fill("Maris, the Lighthouse")
        title.type(" (autosave)")
        try:
            page.wait_for_function(
                """() => {
                    const el = document.getElementById('autosaveStatus');
                    if (!el) return false;
                    return (el.textContent||'').toLowerCase().includes('saved');
                }""",
                timeout=30_000,
            )
        except Exception:
            snap("library_story_edit_autosave_timeout")
            raise

        # ---- /library/story/.../view ----
        goto(CRITICAL_URLS['library_story_view'])
        page.wait_for_timeout(250)
        sc = page.get_by_text("Show code").first
        try:
            sc.wait_for(state="visible", timeout=15_000)
        except Exception:
            snap("library_story_view_missing_show_code")
            raise

        snap("library_story_view")

        ctx.close()
        browser.close()
