/* SFML Editor (standalone, no deps)
 * - contenteditable editor with inline highlighting
 * - line-number gutter
 * - autosave (debounced) + blur save
 * - ES5-compatible (avoid optional chaining, etc.)
 */

(function(){
  'use strict';

  function escHtml(s){
    s = String(s == null ? '' : s);
    return s
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function normalizeNewlines(s){
    s = String(s == null ? '' : s);
    return s.replace(/\r\n/g, '\n');
  }

  function getCaretOffset(root){
    try{
      var sel = window.getSelection ? window.getSelection() : null;
      if (!sel || sel.rangeCount === 0) return 0;
      var r = sel.getRangeAt(0);
      var pre = r.cloneRange();
      pre.selectNodeContents(root);
      pre.setEnd(r.endContainer, r.endOffset);
      return pre.toString().length;
    }catch(e){
      return 0;
    }
  }

  function getTextFromEditor(ed){
    // Prefer a stored model; DOM is just a view.
    var t = '';
    try{ t = ed && ed.innerText ? String(ed.innerText) : ''; }catch(e){ t = ''; }
    t = normalizeNewlines(t);
    return t;
  }

  function findLineEl(node){
    try{
      while (node){
        if (node.nodeType === 1 && node.getAttribute && node.getAttribute('data-sfml-line') != null) return node;
        node = node.parentNode;
      }
    }catch(e){}
    return null;
  }

  function getSelOffsets(ed, lines){
    // Map DOM selection -> model offsets (accounting for structural newlines between line DIVs)
    try{
      var sel = window.getSelection ? window.getSelection() : null;
      if (!sel || sel.rangeCount === 0) return {start:0,end:0};
      var r = sel.getRangeAt(0);

      function offsetFor(container, off){
        var lineEl = findLineEl(container);
        if (!lineEl) return 0;
        var li = parseInt(lineEl.getAttribute('data-sfml-line') || '0', 10) || 0;

        // prefix: lengths of prior lines + '\n'
        var pre = 0;
        for (var i=0;i<li;i++) pre += (lines[i] ? lines[i].length : 0) + 1;

        // within this line: count chars from line start to selection point
        var rr = document.createRange();
        rr.selectNodeContents(lineEl);
        rr.setEnd(container, off);
        var within = rr.toString().length;

        // clamp within to model line length (DOM can include artifacts)
        var maxw = (lines[li] ? lines[li].length : 0);
        if (within < 0) within = 0;
        if (within > maxw) within = maxw;
        return pre + within;
      }

      var start = offsetFor(r.startContainer, r.startOffset);
      var end = offsetFor(r.endContainer, r.endOffset);
      return {start:start,end:end};
    }catch(e){
      return {start:0,end:0};
    }
  }

  function setCaretByOffset(ed, lines, offset){
    // Map model offset -> DOM caret (accounting for structural newlines)
    try{
      offset = offset|0;
      if (offset < 0) offset = 0;
      var total = 0;
      for (var k=0;k<lines.length;k++) total += (lines[k] ? lines[k].length : 0) + (k < lines.length-1 ? 1 : 0);
      if (offset > total) offset = total;

      // find line
      var li = 0;
      var acc = 0;
      for (li=0; li<lines.length; li++){
        var lnlen = (lines[li] ? lines[li].length : 0);
        var nextAcc = acc + lnlen;
        if (offset <= nextAcc) break;
        acc = nextAcc + 1; // skip '\n'
      }
      if (li >= lines.length) li = lines.length-1;
      if (li < 0) li = 0;
      var within = offset - acc;
      if (within < 0) within = 0;
      var maxw2 = (lines[li] ? lines[li].length : 0);
      if (within > maxw2) within = maxw2;

      var lineEl = ed.querySelector("[data-sfml-line='"+li+"']");
      if (!lineEl) return;

      var sel = window.getSelection ? window.getSelection() : null;
      if (!sel) return;

      var walker = document.createTreeWalker(lineEl, NodeFilter.SHOW_TEXT, null);
      var cur = 0;
      var node;
      while ((node = walker.nextNode())){
        var nlen = node.nodeValue ? node.nodeValue.length : 0;
        if (cur + nlen >= within){
          var rr = document.createRange();
          rr.setStart(node, Math.max(0, within - cur));
          rr.collapse(true);
          sel.removeAllRanges();
          sel.addRange(rr);
          return;
        }
        cur += nlen;
      }

      // fallback: end of line
      var rr2 = document.createRange();
      rr2.selectNodeContents(lineEl);
      rr2.collapse(false);
      sel.removeAllRanges();
      sel.addRange(rr2);
    }catch(e){}
  }

  function isBlockHeaderLine(trimmed){
    // e.g., cast: / meta: / settings:
    if (!trimmed) return false;
    if (trimmed.charAt(trimmed.length-1) !== ':') return false;
    var nm = trimmed.slice(0, -1);
    if (!nm) return false;
    return /^[A-Za-z][A-Za-z0-9_-]*$/.test(nm);
  }

  function hiliteLine(line){
    var s = String(line == null ? '' : line);

    // preserve leading 2-space indents
    var lead = '';
    while (s.indexOf('  ') === 0){
      lead += '  ';
      s = s.slice(2);
    }

    var t = s;
    var leadEsc = escHtml(lead);

    // comment
    if (t.replace(/^\s+/, '').indexOf('#') === 0){
      return leadEsc + '<span class="sfmlTokComment">' + escHtml(t) + '</span>';
    }

    // block header
    var tr = t.replace(/^\s+|\s+$/g, '');
    if (isBlockHeaderLine(tr)){
      return leadEsc + '<span class="sfmlTokKw">' + escHtml(tr) + '</span>';
    }

    // cast mapping: Name: voice_id (indented)
    if (lead && t.indexOf(':') > 0){
      var i = t.indexOf(':');
      var nm = t.slice(0, i).replace(/^\s+|\s+$/g, '');
      var rest = t.slice(i+1).replace(/^\s+|\s+$/g, '');
      if (nm && rest){
        return leadEsc +
          '<span class="sfmlTokId">' + escHtml(nm) + '</span>' +
          '<span class="sfmlTokKw">:</span> ' +
          '<span class="sfmlTokVoice">' + escHtml(rest) + '</span>';
      }
    }

    // scene header: scene id "Title":
    var low = tr.toLowerCase();
    if (low.indexOf('scene ') === 0){
      var parts = tr.split(' ');
      var kw = parts.shift();
      var id = parts.shift() || '';
      var tail = parts.join(' ');
      var out = '<span class="sfmlTokKw">' + escHtml(kw) + '</span>';
      if (id) out += ' <span class="sfmlTokId">' + escHtml(id) + '</span>';
      if (tail) out += ' <span class="sfmlTokStr">' + escHtml(tail) + '</span>';
      return leadEsc + out;
    }

    // speaker line: [Name] text
    if (tr.indexOf('[') === 0){
      var rb = tr.indexOf(']');
      if (rb > 0){
        var nm2 = tr.slice(1, rb).replace(/^\s+|\s+$/g, '');
        var rest2 = tr.slice(rb+1);
        return leadEsc +
          '<span class="sfmlTokKw">[</span>' +
          '<span class="sfmlTokId">' + escHtml(nm2) + '</span>' +
          '<span class="sfmlTokKw">]</span>' +
          escHtml(rest2);
      }
    }

    // quoted strings (fallback)
    // keep simple for safety
    if (t.indexOf('"') >= 0){
      // not a full parser; just tint whole line if it contains quotes
      return leadEsc + '<span class="sfmlTokBase">' + escHtml(t) + '</span>';
    }

    return leadEsc + '<span class="sfmlTokBase">' + escHtml(t) + '</span>';
  }

  function render(ed, text){
    text = normalizeNewlines(text);
    var lines = text.split('\n');

    // highlighted html
    var h = [];
    for (var j=0;j<lines.length;j++){
      var ln = lines[j];
      // ensure empty lines remain "editable" (some browsers collapse empty blocks)
      var body = ln.length ? hiliteLine(ln) : '<span class="sfmlTokBase"><br></span>';
      h.push('<div class="sfmlLine" data-sfml-line="'+j+'">' + body + '</div>');
    }
    ed.innerHTML = h.join('');
    return lines;
  }

  function Editor(hostEl, opts){
    opts = opts || {};
    this.hostEl = hostEl;
    this.opts = opts;
    this._t = null;
    this._lastSaved = null;
    this._value = '';

    var root = document.createElement('div');
    root.className = 'sfmlEditorRoot';

    var ed = document.createElement('div');
    ed.className = 'sfmlEditorPane';
    ed.setAttribute('contenteditable', 'true');
    ed.setAttribute('spellcheck', 'false');
    ed.setAttribute('autocapitalize', 'none');
    ed.setAttribute('autocomplete', 'off');
    ed.setAttribute('autocorrect', 'off');

    root.appendChild(ed);

    hostEl.innerHTML = '';
    hostEl.appendChild(root);

    this.root = root;
    this.ed = ed;

    var self = this;

    function rerenderFromValue(caret){
      var txt = String(self._value || '');
      self._lines = render(ed, txt);
      setCaretByOffset(ed, self._lines, caret == null ? 0 : caret);
      return txt;
    }

    function applyEdit(insertText, delStart, delEnd){
      var v = String(self._value || '');
      delStart = Math.max(0, Math.min(v.length, delStart|0));
      delEnd = Math.max(0, Math.min(v.length, delEnd|0));
      if (delEnd < delStart){ var tmp = delStart; delStart = delEnd; delEnd = tmp; }
      insertText = String(insertText == null ? '' : insertText);
      self._value = v.slice(0, delStart) + insertText + v.slice(delEnd);
      return delStart + insertText.length;
    }

    function queueSave(){
      if (self._t) { try{ clearTimeout(self._t); }catch(_e){} }
      self._t = setTimeout(function(){
        try{
          var v = self.getValue();
          if (String(v) !== String(self._lastSaved || '')){
            self._lastSaved = v;
            if (typeof opts.onSave === 'function') opts.onSave(v);
          }
        }catch(_e){}
      }, (opts.debounceMs != null) ? opts.debounceMs : 2000);
    }

    // Model-driven editing: intercept beforeinput so the browser doesn't mutate our highlighted DOM.
    ed.addEventListener('beforeinput', function(ev){
      try{
        ev = ev || window.event;
        if (!ev) return;
        if (ev.isComposing) return; // let IME handle composition

        var it = String(ev.inputType || '');
        if (!it) return;

        // We handle the common editing operations.
        if (
          it === 'insertText' ||
          it === 'insertLineBreak' ||
          it === 'deleteContentBackward' ||
          it === 'deleteContentForward' ||
          it === 'insertFromPaste'
        ){
          ev.preventDefault();

          var sel = getSelOffsets(ed, self._lines || String(self._value||'').split('\n'));
          var start = sel.start;
          var end = sel.end;
          var caret = start;

          if (it === 'insertLineBreak'){
            caret = applyEdit('\n', start, end);
          }else if (it === 'insertText'){
            caret = applyEdit(String(ev.data || ''), start, end);
          }else if (it === 'insertFromPaste'){
            var txt = '';
            try{ txt = ev.clipboardData ? String(ev.clipboardData.getData('text/plain') || '') : ''; }catch(_e){ txt=''; }
            caret = applyEdit(txt, start, end);
          }else if (it === 'deleteContentBackward'){
            if (start !== end){
              caret = applyEdit('', start, end);
            }else if (start > 0){
              caret = applyEdit('', start-1, start);
            }
          }else if (it === 'deleteContentForward'){
            var v = String(self._value || '');
            if (start !== end){
              caret = applyEdit('', start, end);
            }else if (start < v.length){
              caret = applyEdit('', start, start+1);
            }
          }

          rerenderFromValue(caret);
          queueSave();
        }
      }catch(_e){}
    });

    // On focus loss, flush save.
    ed.addEventListener('blur', function(){
      try{
        var v2 = self.getValue();
        if (String(v2) !== String(self._lastSaved || '')){
          self._lastSaved = v2;
          if (typeof opts.onSave === 'function') opts.onSave(v2);
        }
        if (typeof opts.onBlurSave === 'function') opts.onBlurSave(v2);
      }catch(_e){}
    });
  }

  Editor.prototype.setValue = function(text){
    text = normalizeNewlines(text);
    this._value = text;
    this._lines = render(this.ed, text);
    // put caret at end on initial set
    try{ setCaretByOffset(this.ed, this._lines || [text], text.length); }catch(_e){}
  };

  Editor.prototype.getValue = function(){
    return String(this._value || '');
  };

  Editor.prototype.destroy = function(){
    try{ if (this._t) clearTimeout(this._t); }catch(_e){}
    try{ this.hostEl.innerHTML = ''; }catch(_e){}
  };

  window.SFMLEditor = {
    create: function(hostEl, opts){ return new Editor(hostEl, opts); }
  };

})();
