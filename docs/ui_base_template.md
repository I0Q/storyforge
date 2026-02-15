# StoryForge UI: Base Page Template (Shared Chrome)

Goal: stop duplicating **header/user menu**, **debug banner**, **floating audio player**, and **system monitor** wiring across standalone pages.

## Shared UI modules

These live in `apps/app-platform/app/`:

- `ui_header_shared.py`
  - `USER_MENU_HTML`
  - `USER_MENU_JS`
- `ui_debug_shared.py`
  - `DEBUG_BANNER_HTML`
  - `DEBUG_BANNER_BOOT_JS`
  - `DEBUG_PREF_APPLY_JS`
- `ui_audio_shared.py`
  - `AUDIO_DOCK_JS`
- `ui_page_shared.py`
  - `render_page(...)` — minimal HTML skeleton renderer

## The base skeleton

Use `render_page()` for any *standalone* (non-SPA) page.

Pattern:

1. **body_top_html** must include shared scripts:
   - `DEBUG_BANNER_BOOT_JS` (early JS error capture)
   - `USER_MENU_JS` (menu behavior)
   - `DEBUG_PREF_APPLY_JS` (consistent debug hide/show)
   - `AUDIO_DOCK_JS` (global floating audio player)

2. `nav_html` is responsible only for the top header row + `USER_MENU_HTML`.

3. `content_html` starts with `DEBUG_BANNER_HTML` (so you see Build/JS state) then page-specific content.

4. If the page includes the system monitor, include:
   - `MONITOR_HTML` somewhere in `content_html`
   - `MONITOR_JS` in `body_bottom_html` (or in a shared injected bundle)

## Example (voices edit/new)

The following pages have been migrated to use the base skeleton:

- `/voices/{voice_id}/edit`
- `/voices/new`

This ensures consistent:
- header + user menu
- debug banner behavior
- floating audio dock availability
- monitor availability

## Why the debug banner can stick on “booting…”

Some pages inject `DEBUG_BANNER_BOOT_JS` early (in `<body>`), but the banner HTML (`#bootText`) appears later.

`ui_debug_shared.py` now re-checks after a short delay and after `DOMContentLoaded` so it reliably flips to `JS: ok`.

## Next steps

Migrate other standalone pages (settings subpages, library viewer variants, etc.) to use `render_page()` and shared modules.

Long-term: consider adding a slightly higher-level helper that generates the common `nav_html` to reduce per-page string building.
