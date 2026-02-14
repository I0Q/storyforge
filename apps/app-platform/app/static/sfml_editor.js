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

  function setCaretByOffset(root, offset){
    try{
      var sel = window.getSelection ? window.getSelection() : null;
      if (!sel) return;
      var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
      var cur = 0;
      var node;
      while ((node = walker.nextNode())){
        var nlen = node.nodeValue ? node.nodeValue.length : 0;
        if (cur + nlen >= offset){
          var r = document.createRange();
          r.setStart(node, Math.max(0, offset - cur));
          r.collapse(true);
          sel.removeAllRanges();
          sel.addRange(r);
          return;
        }
        cur += nlen;
      }
    }catch(e){}
  }

  function getTextFromEditor(ed){
    // innerText keeps line breaks
    var t = '';
    try{ t = ed && ed.innerText ? String(ed.innerText) : ''; }catch(e){ t = ''; }
    t = normalizeNewlines(t);
    return t;
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
      h.push('<div class="sfmlLine">' + body + '</div>');
    }
    ed.innerHTML = h.join('');
  }

  function Editor(hostEl, opts){
    opts = opts || {};
    this.hostEl = hostEl;
    this.opts = opts;
    this._t = null;
    this._lastSaved = null;

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

    function rerenderFromDom(){
      var caret = getCaretOffset(ed);
      var txt = getTextFromEditor(ed);
      render(ed, txt);
      setCaretByOffset(ed, caret);
      return txt;
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

    ed.addEventListener('input', function(){
      rerenderFromDom();
      queueSave();
    });

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

    ed.addEventListener('keydown', function(ev){
      try{
        ev = ev || window.event;
        if (!ev) return;

        if (ev.key === 'Tab'){
          ev.preventDefault();
          // insert two spaces
          if (document.execCommand) document.execCommand('insertText', false, '  ');
          return;
        }

        if (ev.key === 'Enter'){
          // iOS Safari can be flaky inserting new block nodes in a highlighted contenteditable.
          // Force a literal newline, then our input handler will re-render into line DIVs.
          ev.preventDefault();
          if (document.execCommand) {
            // insertText is more reliable than insertHTML
            document.execCommand('insertText', false, '\n');
          }
          return;
        }
      }catch(_e){}
    });
  }

  Editor.prototype.setValue = function(text){
    text = normalizeNewlines(text);
    render(this.ed, text);
  };

  Editor.prototype.getValue = function(){
    return getTextFromEditor(this.ed);
  };

  Editor.prototype.destroy = function(){
    try{ if (this._t) clearTimeout(this._t); }catch(_e){}
    try{ this.hostEl.innerHTML = ''; }catch(_e){}
  };

  window.SFMLEditor = {
    create: function(hostEl, opts){ return new Editor(hostEl, opts); }
  };

})();
