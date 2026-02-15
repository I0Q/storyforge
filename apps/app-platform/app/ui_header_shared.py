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
          <div class='uActions'>
            <a href='/base-template'><button class='secondary' type='button'>Base template</button></a>
            <a href='/logout'><button class='secondary' type='button'>Log out</button></a>
          </div>
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
  // Also: window.innerHeight can be the *layout viewport*, while the visible viewport is visualViewport.
  // We position relative to the visible viewport and clamp inside it.
  try{
    var btn = document.querySelector('.menuWrap .userBtn');
    var m = document.getElementById('topMenu');
    if (!btn || !m) return;

    var r = btn.getBoundingClientRect();

    var vv = null;
    try{ vv = window.visualViewport || null; }catch(_e){}
    // NOTE: getBoundingClientRect() is already relative to the *visual* viewport.
    // Do NOT add visualViewport.offsetTop/offsetLeft here (double counts on iOS).
    var vw = (window.innerWidth||0), vh = (window.innerHeight||0);
    try{
      if (vv){
        vw = Number(vv.width||vw) || vw;
        vh = Number(vv.height||vh) || vh;
      }
    }catch(_e){}

    m.style.position = 'fixed';
    m.style.zIndex = '99999';

    // Show first so we can measure height.
    try{ m.classList.add('show'); }catch(_e){}

    var pad = 10;
    var w = 266;
    try{ w = Math.max(200, Math.min(340, m.offsetWidth || 266)); }catch(_e){}
    var h = 140;
    try{ h = Math.max(90, Math.min(320, m.offsetHeight || 140)); }catch(_e){}

    // Mobile: always open from the top-right under the header (stable iOS Safari positioning).
    try{
      if ((vw || 0) <= 520){
        m.style.left = 'auto';
        m.style.right = '14px';
        // Use env(safe-area-inset-top) so it doesn't go under the notch.
        m.style.top = 'calc(14px + env(safe-area-inset-top))';
        m.style.bottom = 'auto';
        m.style.maxWidth = 'calc(100vw - 28px)';
        m.style.overflowY = 'auto';
        m.style.webkitOverflowScrolling = 'touch';
        return;
      }
    }catch(_e){}

    var left = (r.right - w);
    left = __sfMenuClamp(left, pad, (vw || 0) - w - pad);
    var top = (r.bottom + 8);
    top = __sfMenuClamp(top, pad, (vh || 0) - h - pad);

    m.style.left = String(left) + 'px';
    m.style.top = String(top) + 'px';
    m.style.right = 'auto';
    m.style.bottom = 'auto';

    // Guard against iOS clipping by constraining menu height.
    try{
      var maxH = (vh) - (top) - pad;
      if (isFinite(maxH) && maxH > 80){
        m.style.maxHeight = String(Math.floor(maxH)) + 'px';
        m.style.overflowY = 'auto';
        m.style.webkitOverflowScrolling = 'touch';
      }
    }catch(_e){}
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
