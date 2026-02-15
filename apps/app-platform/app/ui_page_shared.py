import html as pyhtml

# Minimal shared page renderer for "standalone" pages (non-SPA) so we stop
# duplicating header/menu/debug/player/monitor wiring across pages.
#
# Design goals:
# - Keep it dead-simple (string templates + replace)
# - Avoid modern JS syntax (iOS Safari)
# - Let each page supply its own CSS bundle (index/voices/library) while reusing
#   shared UI modules (debug, audio dock, user menu, monitor).


def esc(x) -> str:
    return pyhtml.escape(str(x or ""))


def render_page(
    *,
    title: str,
    style_css: str,
    head_extra_html: str = "",
    body_top_html: str = "",
    nav_html: str = "",
    content_html: str = "",
    body_bottom_html: str = "",
) -> str:
    # Note: we place body_top_html immediately after <body> to ensure shared
    # scripts (debug pref apply, user-menu JS, audio dock) can run regardless of
    # where the debug banner HTML appears in the page.
    return (
        """<!doctype html>
<html>
<head>
  <meta charset='utf-8'/>
  <meta name='viewport' content='width=device-width, initial-scale=1'/>
  <title>__TITLE__</title>
  <style>__STYLE__</style>
  __HEAD_EXTRA__
</head>
<body>
  __BODY_TOP__
  __NAV__
  __CONTENT__
  __BODY_BOTTOM__
</body>
</html>"""
        .replace("__TITLE__", esc(title))
        .replace("__STYLE__", style_css or "")
        .replace("__HEAD_EXTRA__", head_extra_html or "")
        .replace("__BODY_TOP__", body_top_html or "")
        .replace("__NAV__", nav_html or "")
        .replace("__CONTENT__", content_html or "")
        .replace("__BODY_BOTTOM__", body_bottom_html or "")
    )
