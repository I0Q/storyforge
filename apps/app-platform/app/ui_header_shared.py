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
function toggleUserMenu(){
  try{
    var m=document.getElementById('topMenu');
    if(!m) return;
    if(m.classList.contains('show')) m.classList.remove('show');
    else m.classList.add('show');
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
</script>
"""
