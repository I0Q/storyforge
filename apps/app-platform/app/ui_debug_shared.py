"""Shared Debug UI (boot banner) for StoryForge.

Goal: one canonical HTML+JS snippet reused across pages.

- DEBUG_BANNER_HTML: the banner container ("Build: ... • JS: ...")
- DEBUG_BANNER_BOOT_JS: minimal boot script (runs even if later JS fails)
- DEBUG_PREF_APPLY_JS: tiny script to apply sf_debug_ui -> body.debugOff

IMPORTANT: Keep JS compatible with older iOS Safari (avoid modern syntax).
"""

from __future__ import annotations

DEBUG_BANNER_HTML = """
  <div id='boot' class='boot muted'>
    <span id='bootText'><strong>Build</strong>: __BUILD__ • JS: booting…</span>
    <button class='copyBtn' type='button' onclick='copyBoot()' aria-label='Copy build + error' style='margin-left:auto'>
      <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
        <path stroke="currentColor" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" d="M11 7H7a2 2 0 00-2 2v9a2 2 0 002 2h10a2 2 0 002-2v-9a2 2 0 00-2-2h-4M11 7V5a2 2 0 114 0v2M11 7h4"/>
      </svg>
    </button>
  </div>
  <script>
  // Flip to JS: ok even if the boot JS ran before this HTML existed.
  try{
    setTimeout(function(){
      try{
        var bt=document.getElementById('bootText');
        if (!bt) return;
        var t=String(bt.textContent||'');
        if (t.indexOf('JS: booting')!==-1){
          bt.textContent = t.replace('JS: booting…','JS: ok').replace('JS: booting...','JS: ok');
        }
      }catch(_e){}
    }, 0);
  }catch(_e){}
  </script>
"""

# NOTE: This is copied from apps/app-platform/app/main.py (DEBUG_BANNER_BOOT_JS).
# Keep changes here and update main.py to import from here over time.
DEBUG_BANNER_BOOT_JS = """
<script>
// minimal boot script (runs even if the main app script has a syntax error)
window.__SF_BUILD = '__BUILD__';
window.__SF_BOOT_TS = Date.now();
window.__SF_LAST_ERR = '';

// Cache-bust HTML on iOS/Safari/CF edge caching: only when Debug UI is enabled.
// IMPORTANT: avoid refresh loops. Only auto-add ?v=... once per tab/session, and only if v is missing.
try{
  var dbg = null;
  try{ dbg = localStorage.getItem('sf_debug_ui'); }catch(e){}
  var debugOn = (dbg===null || dbg==='' || dbg==='1');
  if (debugOn){
    var u = new URL(window.location.href);
    var v = u.searchParams.get('v');
    if (!v){
      var key = 'sf_reload_once';
      var did = false;
      try{ did = (sessionStorage.getItem(key) === '1'); }catch(e){}
      if (!did){
        try{ sessionStorage.setItem(key, '1'); }catch(e){}
        u.searchParams.set('v', String(window.__SF_BUILD||''));
        window.location.replace(u.toString());
      }
    }
  }
}catch(e){}

function __sfEnsureBootBanner(){
  // Ensure we always have a dedicated #bootText span + copy button.
  try{
    var boot = document.getElementById('boot');
    if (!boot) return null;
    var t = document.getElementById('bootText');
    if (t){
      // If server rendered bootText but not the deploy bar, inject it.
      try{
        var dep = document.getElementById('bootDeploy');
        if (!dep){
          t.insertAdjacentHTML('afterend',
            "<div id='bootDeploy' class='hide' style='flex:1 1 auto; min-width:200px; margin-left:12px'>"+
              "<div class='muted' style='font-weight:950'>StoryForge updating…</div>"+
              "<div class='updateTrack' style='margin-top:6px;position:relative'>"+
                "<div class='updateProg'></div>"+
                "<div id='bootDeployTimer' style='position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:950;font-size:12px;letter-spacing:0.2px;text-shadow:0 2px 10px rgba(0,0,0,0.6);pointer-events:none'>0:00</div>"+
              "</div>"+
            "</div>"
          );
        }
      }catch(_e){}
      return t;
    }

    boot.innerHTML = "<span id='bootText'><strong>Build</strong>: " + String(window.__SF_BUILD||'?') + " • JS: ok</span>" +
      "<div id='bootDeploy' class='hide' style='flex:1 1 auto; min-width:200px; margin-left:12px'>" +
        "<div class='muted' style='font-weight:950'>StoryForge updating…</div>" +
        "<div class='updateTrack' style='margin-top:6px;position:relative'>" +
          "<div class='updateProg'></div>" +
          "<div id='bootDeployTimer' style='position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:950;font-size:12px;letter-spacing:0.2px;text-shadow:0 2px 10px rgba(0,0,0,0.6);pointer-events:none'>0:00</div>" +
        "</div>" +
      "</div>" +
      "<button class='copyBtn' type='button' onclick='copyBoot()' aria-label='Copy build + error' style='margin-left:auto'>" +
      "<svg viewBox='0 0 24 24' width='18' height='18' aria-hidden='true'>" +
      "<path stroke='currentColor' fill='none' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' d='M11 7H7a2 2 0 00-2 2v9a2 2 0 002 2h10a2 2 0 002-2v-9a2 2 0 00-2-2h-4M11 7V5a2 2 0 114 0v2M11 7h4'/>" +
      "</svg>" +
      "</button>";

    return document.getElementById('bootText');
  }catch(e){
    return null;
  }
}

function __sfSetDebugInfo(msg){
  try{
    window.__SF_LAST_ERR = msg || '';
    var t = __sfEnsureBootBanner();
    if (t) t.textContent = 'Build: ' + window.__SF_BUILD + ' • JS: ' + (window.__SF_LAST_ERR || 'ok');
  }catch(e){}
}

// If the boot banner script fails to run (some Safari edge cases), don't leave it stuck on 'booting…'.
function __sfFixBooting(){
  try{
    var bt=document.getElementById('bootText');
    if (!bt) return;
    var t=String(bt.textContent||'');
    if (t.indexOf('JS: booting')!==-1){
      bt.textContent = t.replace('JS: booting…','JS: ok').replace('JS: booting...','JS: ok');
    }
  }catch(_e){}
}
try{ setTimeout(__sfFixBooting, 0); }catch(_e){}
try{ setTimeout(__sfFixBooting, 500); }catch(_e){}
try{ document.addEventListener('DOMContentLoaded', function(){ try{ __sfFixBooting(); }catch(_e){} }); }catch(_e){}
</script>
"""

DEBUG_PREF_APPLY_JS = """
<script>
// Apply debug preference early on non-main pages.
try{
  var v = null;
  try{ v = localStorage.getItem('sf_debug_ui'); }catch(e){}
  var on = (v===null || v==='' || v==='1');
  try{ document.body.classList.toggle('debugOff', !on); }catch(e){}
}catch(e){}
</script>
"""
