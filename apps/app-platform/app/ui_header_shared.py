"""Shared Header UI snippets for StoryForge.

Scope (incremental):
- Centralize the user-menu (avatar button + dropdown) HTML.
- Centralize the user-menu toggle JS (toggle + outside click).

This is the common piece used by:
- main SPA (/)
- library pages (/library/...)
- other standalone pages that include the header

Keep HTML/CSS semantically identical; keep JS compatible with older iOS Safari.
"""

from __future__ import annotations


USER_MENU_HTML = """
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
"""


USER_MENU_JS = """
<script>
function __sfMenuClamp(v, lo, hi){
  try{
    v = Number(v);
    lo = Number(lo);
    hi = Number(hi);
    if (!isFinite(v)) return lo;
    if (v < lo) return lo;
    if (v > hi) return hi;
    return v;
  }catch(e){
    return lo;
  }
}

function __sfPositionUserMenu(){
  // iOS Safari can clip/tear absolutely-positioned dropdowns inside stacked/filtered containers.
  // Use viewport-fixed positioning based on the button's bounding rect.
  try{
    var btn = document.querySelector('.menuWrap .userBtn');
    var m = document.getElementById('topMenu');
    if (!btn || !m) return;

    // If we're in the mobile bottom-sheet mode, let CSS handle fixed/bottom layout.
    try{
      if (window.innerWidth && window.innerWidth <= 520){
        m.style.left = '';
        m.style.right = '';
        m.style.top = '';
        m.style.bottom = '';
        m.style.position = '';
        return;
      }
    }catch(_e){}

    var r = btn.getBoundingClientRect();
    m.style.position = 'fixed';
    m.style.zIndex = '99999';

    // Show first so we can measure height.
    try{ m.classList.add('show'); }catch(_e){}

    var pad = 10;
    var w = 266;
    try{ w = Math.max(200, Math.min(340, m.offsetWidth || 266)); }catch(_e){}
    var h = 140;
    try{ h = Math.max(90, Math.min(320, m.offsetHeight || 140)); }catch(_e){}

    var left = (r.right - w);
    left = __sfMenuClamp(left, pad, (window.innerWidth || 0) - w - pad);
    var top = (r.bottom + 8);
    top = __sfMenuClamp(top, pad, (window.innerHeight || 0) - h - pad);

    m.style.left = String(left) + 'px';
    m.style.top = String(top) + 'px';
    m.style.right = 'auto';
    m.style.bottom = 'auto';
  }catch(e){}
}

function toggleUserMenu(){
  try{
    var m=document.getElementById('topMenu');
    if(!m) return;
    var on = m.classList.contains('show');
    if (on){
      m.classList.remove('show');
      return;
    }
    // Position (and also turns it on)
    __sfPositionUserMenu();
  }catch(e){}
}

document.addEventListener('click', function(ev){
  try{
    var m=document.getElementById('topMenu');
    if(!m) return;
    var w=ev.target && ev.target.closest ? ev.target.closest('.menuWrap') : null;
    if(!w) m.classList.remove('show');
  }catch(e){}
});

// Reposition on scroll/resize while open.
try{
  window.addEventListener('resize', function(){
    try{ var m=document.getElementById('topMenu'); if (m && m.classList.contains('show')) __sfPositionUserMenu(); }catch(_e){}
  });
  window.addEventListener('scroll', function(){
    try{ var m=document.getElementById('topMenu'); if (m && m.classList.contains('show')) __sfPositionUserMenu(); }catch(_e){}
  }, {passive:true});
}catch(e){}
</script>
"""
