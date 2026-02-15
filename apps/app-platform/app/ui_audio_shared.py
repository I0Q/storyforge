"""Shared floating audio dock (global player) for StoryForge.

Goal: one canonical implementation reused across pages.

Keep JS compatible with older iOS Safari.
"""

from __future__ import annotations

AUDIO_DOCK_JS = """
<script>
// Global audio player (survives tab re-renders; iOS-friendly)
function __sfEnsureAudioDock(){
  try{
    var d=document.getElementById('sfAudioDock');
    if (d) return d;
    d=document.createElement('div');
    d.id='sfAudioDock';
    d.style.position='fixed';
    d.style.left='12px';
    d.style.right='12px';
    d.style.bottom='calc(64px + env(safe-area-inset-bottom, 0px))';
    d.style.zIndex='99998';
    d.style.padding='10px 12px';
    d.style.border='1px solid rgba(255,255,255,0.10)';
    d.style.borderRadius='14px';
    d.style.background='rgba(20,22,30,0.96)';
    d.style.backdropFilter='blur(6px)';
    d.style.webkitBackdropFilter='blur(6px)';
    d.style.boxShadow='0 12px 40px rgba(0,0,0,0.35)';
    d.style.display='none';

    var row=document.createElement('div');
    row.style.display='flex';
    row.style.alignItems='center';
    row.style.gap='10px';

    var t=document.createElement('div');
    t.id='sfAudioTitle';
    t.style.flex='1';
    t.style.minWidth='0';
    t.style.fontWeight='900';
    t.style.fontSize='13px';
    t.style.whiteSpace='nowrap';
    t.style.overflow='hidden';
    t.style.textOverflow='ellipsis';
    t.textContent='Audio';

    var x=document.createElement('button');
    x.type='button';
    x.textContent='×';
    x.style.width='34px';
    x.style.height='30px';
    x.style.borderRadius='10px';
    x.style.border='1px solid rgba(255,255,255,0.10)';
    x.style.background='transparent';
    x.style.color='var(--text)';
    x.style.fontWeight='900';
    x.onclick=function(){
      try{
        var a=document.getElementById('sfAudioEl');
        if (a) a.pause();
      }catch(_e){}
      try{ d.style.display='none'; }catch(_e){}
    };

    row.appendChild(t);
    row.appendChild(x);

    var a=document.createElement('audio');
    a.id='sfAudioEl';
    a.controls=true;
    a.preload='none';
    a.style.width='100%';
    a.style.marginTop='8px';

    d.appendChild(row);
    d.appendChild(a);
    document.body.appendChild(d);
    return d;
  }catch(e){ return null; }
}

function __sfPlayAudio(url, title){
  try{
    url = String(url||'').trim();
    if (!url) return;
    var d=__sfEnsureAudioDock();
    var a=document.getElementById('sfAudioEl');
    var t=document.getElementById('sfAudioTitle');
    if (t) t.textContent = String(title||'Audio');
    if (d) d.style.display='block';
    if (a){
      // Reset src to force iOS to treat this as a fresh user-initiated play
      try{ a.pause(); }catch(_e){}
      a.src = url;
      try{ a.currentTime = 0; }catch(_e){}
      try{
        var p=a.play();
        if (p && typeof p.catch==='function') p.catch(function(_e){});
      }catch(_e){}
    }
  }catch(e){}
}
</script>
"""
