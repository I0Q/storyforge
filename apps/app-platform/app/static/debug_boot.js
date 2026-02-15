// debug_boot.js
// Shared debug-area boot helpers: deploy bar watcher + minimal error reporting.
// Keep this file ASCII-only for maximum Safari/iOS compatibility.

(function(){
  'use strict';

  function debugOn(){
    try{
      var v = null;
      try{ v = localStorage.getItem('sf_debug_ui'); }catch(e){}
      return (v===null || v==='' || v==='1');
    }catch(e){
      return false;
    }
  }

  function fmtDur(sec){
    sec = Math.max(0, (sec|0));
    var m = Math.floor(sec/60);
    var s = sec % 60;
    return String(m) + ':' + (s < 10 ? ('0'+String(s)) : String(s));
  }

  function ensureDeployEl(){
    try{
      var el = document.getElementById('bootDeploy');
      if (el) return el;
      var t = document.getElementById('bootText');
      if (!t) return null;
      t.insertAdjacentHTML('afterend',
        "<div id='bootDeploy' class='hide' style='flex:1 1 auto; min-width:200px; margin-left:12px'>"+
          "<div class='muted' style='font-weight:950'>StoryForge updating...</div>"+
          "<div class='updateTrack' style='margin-top:6px;position:relative'>"+
            "<div class='updateProg'></div>"+
            "<div id='bootDeployTimer' style='position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:950;font-size:12px;letter-spacing:0.2px;text-shadow:0 2px 10px rgba(0,0,0,0.6);pointer-events:none'>0:00</div>"+
          "</div>"+
        "</div>"
      );
      return document.getElementById('bootDeploy');
    }catch(e){
      return null;
    }
  }

  var DEPLOY_T0 = 0;
  var DEPLOY_TIMER = null;

  function setDeployBar(on, msg){
    try{
      var el = ensureDeployEl();
      if (!el) return;
      if (on){
        el.classList.remove('hide');
        if (msg){
          try{ el.querySelector('.muted').textContent = String(msg || 'StoryForge updating...'); }catch(e){}
        }
        if (!DEPLOY_T0) DEPLOY_T0 = Date.now();
        if (!DEPLOY_TIMER){
          DEPLOY_TIMER = setInterval(function(){
            try{
              var tt = document.getElementById('bootDeployTimer');
              if (!tt) return;
              tt.textContent = fmtDur(Math.floor((Date.now()-DEPLOY_T0)/1000));
            }catch(e){}
          }, 1000);
        }
      }else{
        el.classList.add('hide');
        DEPLOY_T0 = 0;
        try{ if (DEPLOY_TIMER) clearInterval(DEPLOY_TIMER); }catch(e){}
        DEPLOY_TIMER = null;
        try{ var tt2 = document.getElementById('bootDeployTimer'); if (tt2) tt2.textContent='0:00'; }catch(e){}
      }
    }catch(e){}
  }

  function startDeployWatch(){
    if (!debugOn()) return;

    var lastState = '';
    var lastUpdated = 0;
    var es = null;
    var rt = null;
    var backoff = 900;

    function stop(){
      try{ if(rt){ clearTimeout(rt); rt=null; } }catch(e){}
      try{ if(es){ es.close(); es=null; } }catch(e){}
    }

    function schedule(){
      try{ if(rt) return; }catch(e){}
      stop();
      var d = Math.max(400, Math.min(10000, Number(backoff||900)));
      backoff = Math.min(10000, Math.floor(d*1.7));
      try{ rt = setTimeout(function(){ rt=null; start(); }, d); }catch(e){}
    }

    function apply(j){
      try{
        if (!j || !j.ok) return;
        var st = String(j.state || 'idle');
        var msg = String(j.message || '');
        var upd = Number(j.updated_at || 0);

        if (st === 'deploying') setDeployBar(true, msg || 'StoryForge updating...');
        else setDeployBar(false, '');

        if (lastState === 'deploying' && st !== 'deploying'){
          if (upd && upd !== lastUpdated){
            setTimeout(function(){ try{ window.location.reload(); }catch(e){} }, 450);
          }
        }
        lastState = st;
        lastUpdated = upd || lastUpdated;
      }catch(e){}
    }

    function start(){
      stop();
      try{
        es = new EventSource('/api/deploy/stream');
        es.onopen = function(){ backoff = 900; };
        es.onmessage = function(ev){ try{ apply(JSON.parse(ev.data || '{}')); }catch(e){} };
        es.onerror = function(){ schedule(); };
      }catch(e){
        schedule();
      }
    }

    start();
  }

  // minimal error-to-bootText (best-effort)
  function setBootMsg(msg){
    try{
      window.__SF_LAST_ERR = String(msg || '');
      var t = document.getElementById('bootText');
      if (t) t.textContent = 'Build: ' + String(window.__SF_BUILD||'') + ' - JS: ' + (window.__SF_LAST_ERR || 'ok');
    }catch(e){}
  }

  window.addEventListener('error', function(ev){
    try{
      var m = 'error';
      try{ m = (ev && (ev.message || ev.type)) ? String(ev.message || ev.type) : 'error'; }catch(e){}
      setBootMsg(m);
    }catch(e){}
  });

  window.addEventListener('unhandledrejection', function(ev){
    try{
      var msg = 'promise error';
      try{ msg = String(ev && ev.reason ? (ev.reason.message || ev.reason) : msg); }catch(e){}
      setBootMsg(msg);
    }catch(e){}
  });

  try{ startDeployWatch(); }catch(e){}
})();
