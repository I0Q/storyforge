from __future__ import annotations

import html as pyhtml
from typing import Optional


def esc(s: object) -> str:
    return pyhtml.escape(str(s if s is not None else ""))


def base_css() -> str:
    # Keep this conservative for iOS Safari compatibility.
    return """
    html,body{overscroll-behavior-y:none;}
    *{box-sizing:border-box;}
    :root{--bg:#0b1020;--card:#0f1733;--text:#e7edff;--muted:#a8b3d8;--line:#24305e;--accent:#4aa3ff;--bad:#ff4d4d;}
    body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--text);padding:18px;max-width:920px;margin:0 auto;overflow-x:hidden;}
    a{color:var(--accent);text-decoration:none}
    h1{font-size:20px;margin:0;}
    .muted{color:var(--muted);font-size:12px;}
    .card{border:1px solid var(--line);border-radius:16px;padding:12px;margin:12px 0;background:var(--card);}
    .row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;}
    button{padding:10px 12px;border-radius:12px;border:1px solid var(--line);background:#163a74;color:#fff;font-weight:950;cursor:pointer;}
    button.secondary{background:transparent;color:var(--text);}
    input,textarea,select{width:100%;padding:10px;border:1px solid var(--line);border-radius:12px;background:#0b1020;color:var(--text);font-size:16px;}
    textarea{resize:none;}
    audio{width:100%;margin-top:10px;}
    .hide{display:none}
    .err{color:var(--bad);font-weight:950;margin-top:10px;}

    .navBar{position:sticky;top:0;z-index:1200;background:rgba(11,16,32,0.96);backdrop-filter:blur(8px);border-bottom:1px solid rgba(36,48,94,.55);padding:14px 0 10px 0;margin-bottom:10px;}
    .top{display:flex;justify-content:space-between;align-items:flex-end;gap:12px;flex-wrap:wrap;}
    .brandRow{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;}
    .pageName{color:var(--muted);font-weight:900;font-size:12px;}
    """


def user_menu_html() -> str:
    return """
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

<script>
function toggleMenu(){
  try{ var m=document.getElementById('topMenu'); if(!m) return; m.classList.toggle('show'); }catch(e){}
}
try{ document.addEventListener('click', function(ev){
  try{ var m=document.getElementById('topMenu'); if(!m) return;
    var b=ev.target && ev.target.closest ? ev.target.closest('.menuWrap') : null;
    if(!b && m.classList.contains('show')) m.classList.remove('show');
  }catch(e){}
}); }catch(e){}
</script>
"""


def nav_html(page_name: str, subtitle: Optional[str] = None, back_href: Optional[str] = None, include_user_menu: bool = False) -> str:
    sub = f"<div class='muted'>{esc(subtitle)}</div>" if subtitle else ""
    back = (
        f"<a href='{esc(back_href)}'><button class='secondary' type='button'>Back</button></a>"
        if back_href
        else ""
    )
    menu = user_menu_html() if include_user_menu else ''
    return f"""
  <div class='navBar'>
    <div class='top'>
      <div>
        <div class='brandRow'><h1>StoryForge</h1><div class='pageName'>{esc(page_name)}</div></div>
        {sub}
      </div>
      <div class='row' style='justify-content:flex-end;'>
        {back}
        {menu}
      </div>
    </div>
  </div>
"""


def page(title: str, page_name: str, body_html: str, subtitle: Optional[str] = None, back_href: Optional[str] = None) -> str:
    return f"""<!doctype html>
<html>
<head>
  <meta charset='utf-8'/>
  <meta name='viewport' content='width=device-width, initial-scale=1'/>
  <title>{esc(title)}</title>
  <style>
{base_css()}
  </style>
</head>
<body>
{nav_html(page_name=page_name, subtitle=subtitle, back_href=back_href)}
{body_html}
</body>
</html>"""
