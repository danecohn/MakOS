/* Sprite: application shell (actions, menus, dialogs, files, AI wiring, control endpoint). Original code. */
(function () {
  'use strict';
  var AS = window.AS, U = AS.ui, h = U.h, C = AS.color, M = AS.model, D = AS.draw, PNG = AS.png, X = AS.exporter, Tools = AS.tools, E = AS.editor, P = AS.panels;
  var shell = window.amerikaStudio;
  var VERSION = '1.0.0';

  var DEFAULT_KEYS = {
    'file.new': 'ctrl+n', 'file.open': 'ctrl+o', 'file.save': 'ctrl+s', 'file.saveAs': 'ctrl+shift+s', 'file.export': 'ctrl+e',
    undo: 'ctrl+z', redo: 'ctrl+y', copy: 'ctrl+c', cut: 'ctrl+x', paste: 'ctrl+v', delete: 'delete', selectAll: 'ctrl+a', deselect: 'ctrl+d', invertSel: 'ctrl+shift+i',
    'tool.pencil': 'b', 'tool.eraser': 'e', 'tool.bucket': 'g', 'tool.line': 'l', 'tool.rect': 'r', 'tool.ellipse': 'o', 'tool.polygon': 'p', 'tool.select': 'm', 'tool.lasso': 'q', 'tool.wand': 'w',
    'tool.move': 'v', 'tool.eyedropper': 'i', 'tool.shade': 'u', 'tool.dither': 'd', 'tool.gradient': 'h', 'tool.hand': '',
    swapColors: 'x', zoomIn: '=', zoomOut: '-', zoomFit: 'ctrl+0', zoom100: 'ctrl+1', toggleGrid: "ctrl+'", togglePixelGrid: 'ctrl+g', toggleOnion: 'alt+o', symX: 'shift+x', symY: 'shift+y', cycleTile: 'shift+t',
    framePrev: ',', frameNext: '.', frameFirst: 'home', frameLast: 'end', play: 'enter', frameNew: 'alt+n', frameDup: 'alt+d', layerNew: 'shift+n', toggleDocks: 'tab', focusAI: 'ctrl+k', 'help.keys': 'f1',
    flipH: 'shift+h', flipV: 'shift+v', brushBigger: ']', brushSmaller: '['
  };
  var ACTION_LABELS = {
    'file.new': 'New sprite', 'file.open': 'Open', 'file.save': 'Save', 'file.saveAs': 'Save as', 'file.export': 'Export', undo: 'Undo', redo: 'Redo', copy: 'Copy', cut: 'Cut', paste: 'Paste', delete: 'Clear selection', selectAll: 'Select all', deselect: 'Deselect', invertSel: 'Invert selection',
    swapColors: 'Swap colours', zoomIn: 'Zoom in', zoomOut: 'Zoom out', zoomFit: 'Zoom to fit', zoom100: 'Zoom 1:1... (x8)', toggleGrid: 'Toggle grid', togglePixelGrid: 'Toggle pixel grid', toggleOnion: 'Toggle onion skin', symX: 'Mirror X', symY: 'Mirror Y', cycleTile: 'Cycle tiling mode',
    framePrev: 'Previous frame', frameNext: 'Next frame', frameFirst: 'First frame', frameLast: 'Last frame', play: 'Play / pause', frameNew: 'New frame', frameDup: 'Duplicate frame', layerNew: 'New layer', toggleDocks: 'Show / hide side panels', focusAI: 'Focus AI prompt', 'help.keys': 'Keyboard shortcuts',
    flipH: 'Flip horizontally', flipV: 'Flip vertically', brushBigger: 'Bigger brush', brushSmaller: 'Smaller brush'
  };
  E.TOOLS.forEach(function (t) { ACTION_LABELS['tool.' + t] = 'Tool: ' + E.TOOL_LABELS[t]; });

  function App() {
    var self = this;
    this.S = new AS.session.Session(new M.Doc({ w: 32, h: 32, mode: 'rgba' }));
    this.keymap = new U.Keymap(DEFAULT_KEYS);
    this.toolListeners = []; this.palSel = 0; this.playTag = ''; this.loopMode = 'loop'; this.keyState = ''; this.keyReady = false;
    this.io = { write: function (path, data) { return self.writeProject(path, data); } };
    this.recent = [];
  }
  var A = App.prototype;
  A.onTool = function (fn) { this.toolListeners.push(fn); };

  // ------------------------------------------------------------------ files
  A.writeProject = function (path, data) {
    if (!shell || !shell.fs || !shell.fs.writeProject) return Promise.reject(Object.assign(new Error('no project folder is available'), { code: -32004 }));
    var bin = typeof data !== 'string';
    return shell.fs.writeProject(path, bin ? PNG.toBase64(data) : data, { encoding: bin ? 'base64' : 'utf8', overwrite: true }).catch(function (e) {
      var err = new Error('could not write ' + path + ': ' + ((e && (e.message || e.error)) || e)); err.code = /not_allowed|outside|confined/.test(JSON.stringify(e)) ? -32003 : -32000; throw err;
    });
  };
  A.setTitle = function () {
    var doc = this.S.doc; document.title = doc.name + ' - Sprite';
    if (shell && shell.window) { try { shell.window.setTitle(doc.name + (doc.dirty() ? ' *' : '')); shell.window.setDirty(doc.dirty()); } catch (e) {} }
    if (this.titleEl) this.titleEl.textContent = doc.name + (doc.dirty() ? ' *' : '');
  };
  A.confirmDiscard = async function () { if (!this.S.doc.dirty()) return true; return U.confirmBox('Unsaved changes', 'Discard the changes to "' + this.S.doc.name + '"?', 'Discard'); };
  A.useDoc = function (doc) {
    this.S.setDoc(doc); doc.markSaved(); this.editor.fitSoon = true; this.editor.resize(); this.setTitle(); this.palSel = 0;
  };
  function baseOf(name) { return String(name || 'sprite').replace(/\.(asprite\.json|aseprite|ase|png|json|gif)$/i, ''); }
  A.openFileObj = async function (f) {
    var name = f.name || '', low = name.toLowerCase();
    try {
      if (/\.(gpl|hex|pal)$/i.test(low)) { await this.importPaletteData(f.binary ? PNG.fromBase64(f.data) : f.data); return; }
      if (!(await this.confirmDiscard())) return;
      var doc;
      if (/\.(aseprite|ase)$/i.test(low)) {
        var r = AS.aseprite.read(PNG.fromBase64(f.data)); doc = r.doc; doc.name = baseOf(name);
        if (r.warnings.length) U.toast('Imported with notes: ' + r.warnings.slice(0, 3).join('; '));
        else U.toast('Imported ' + name + ' (read-only import; save as .asprite.json)');
      } else if (/\.png$/i.test(low)) {
        var img = PNG.decode(PNG.fromBase64(f.data)); doc = await this.importPngAsDoc(img, baseOf(name));
        if (!doc) return;
      } else if (/\.gif$/i.test(low)) { U.toast('GIF import is not supported. Import the PNG sheet instead.', 'error'); return; }
      else { doc = M.Doc.fromJSON(f.data); }
      if (!doc.name || doc.name === 'Sprite') doc.name = baseOf(name);
      doc.path = f.path || null; this.useDoc(doc); this.S.doc.path = f.path || null; this.setTitle();
    } catch (e) { U.toast('Could not open ' + name + ': ' + (e && e.message || e), 'error'); }
  };
  A.importPngAsDoc = async function (img, name) {
    var v = await U.dialog({ title: 'Import PNG', fields: [
      { type: 'note', text: img.width + ' x ' + img.height + ' px image. Slice it into animation frames?' },
      { id: 'fw', label: 'Frame width', type: 'number', value: img.width, min: 1, max: img.width }, { id: 'fh', label: 'Frame height', type: 'number', value: img.height, min: 1, max: img.height },
      { id: 'mode', label: 'Colour mode', type: 'select', value: 'rgba', options: [['rgba', 'RGBA'], ['indexed', 'Indexed (build palette from image)']] }
    ], ok: 'Import' });
    if (!v) return null;
    var fw = Math.max(1, Math.min(img.width, v.fw | 0)), fh = Math.max(1, Math.min(img.height, v.fh | 0)), cols = Math.floor(img.width / fw), rows = Math.floor(img.height / fh), frames = [];
    for (var r = 0; r < rows; r++) for (var c = 0; c < cols; c++) {
      var rgba = new Uint8Array(fw * fh * 4);
      for (var y = 0; y < fh; y++) rgba.set(img.rgba.subarray(((r * fh + y) * img.width + c * fw) * 4, ((r * fh + y) * img.width + c * fw + fw) * 4), y * fw * 4);
      frames.push({ rgba: rgba, delay: 100 });
    }
    if (frames.length > 256) throw new Error('too many frames (' + frames.length + ')');
    var pal = C.fromImage(img, 256); if (pal.length > 256 || !pal.length) pal = null;
    var doc = M.Doc.fromRGBA(fw, fh, frames, pal && pal.length ? pal.slice(0, 64) : null); doc.name = name;
    if (pal && pal.length) doc.palette = pal.slice(0, 256);
    if (v.mode === 'indexed') doc.convertMode('indexed', { fromImage: true });
    doc.undoStack.length = 0; return doc;
  };
  A.fileOpenDialog = async function () {
    if (!shell || !shell.fs) { U.toast('File access is not available here', 'error'); return; }
    var f = await shell.fs.open({ title: 'Open sprite', binary: true, filters: [{ name: 'Sprites', patterns: ['*.asprite.json', '*.json', '*.png', '*.aseprite', '*.ase', '*.gpl', '*.hex'] }] });
    if (f) {
      if (/\.json$/i.test(f.name) && f.binary) f.data = new TextDecoder().decode(PNG.fromBase64(f.data));
      await this.openFileObj(f);
    }
  };
  A.save = async function (as) {
    var doc = this.S.doc, text = JSON.stringify(doc.toJSON()), proj = shell && shell.info && shell.info.projectDir;
    try {
      if (!as && doc.path && proj && doc.path.indexOf(proj + '/') === 0) {
        await this.writeProject(doc.path.slice(proj.length + 1), text);
      } else {
        var r = await shell.fs.save({ title: 'Save sprite', suggestedName: baseOf(doc.name) + '.asprite.json', data: text, encoding: 'utf8', filters: [{ name: 'Sprite', patterns: ['*.asprite.json'] }] });
        if (!r) return; doc.path = r.path; doc.name = baseOf(r.name);
      }
      doc.markSaved(); this.setTitle(); U.toast('Saved ' + doc.name);
    } catch (e) { U.toast('Save failed: ' + (e && e.message || e), 'error'); }
  };

  // ------------------------------------------------------------------ export
  A.exportDialog = async function () {
    var doc = this.S.doc, tags = [['', 'All frames']].concat(doc.tags.map(function (t) { return [t.name, 'Tag: ' + t.name]; }));
    var v = await U.dialog({ title: 'Export', ok: 'Export to project folder', buttons: [{ id: 'saveas', label: 'Save as...' }], fields: [
      { id: 'format', label: 'Format', type: 'select', value: 'sheet', options: [['sheet', 'Sprite sheet (PNG + JSON + Godot .tres)'], ['png', 'PNG (current frame)'], ['gif', 'Animated GIF'], ['apng', 'Animated PNG (APNG)'], ['frames', 'One PNG per frame']] },
      { id: 'name', label: 'File name', type: 'text', value: X.safeName(doc.name) }, { id: 'scale', label: 'Scale', type: 'number', value: 1, min: 1, max: 32 },
      { id: 'tag', label: 'Frames', type: 'select', value: '', options: tags },
      { id: 'layout', label: 'Sheet layout', type: 'select', value: 'horizontal', options: [['horizontal', 'Horizontal strip'], ['vertical', 'Vertical strip'], ['grid', 'Grid'], ['packed', 'Packed']] },
      { id: 'columns', label: 'Grid columns', type: 'number', value: 0, min: 0, max: 64, hint: '0 = automatic' },
      { id: 'trim', label: 'Auto-trim transparent borders', type: 'check', value: false },
      { id: 'padding', label: 'Sheet padding', type: 'number', value: 0, min: 0, max: 64 }, { id: 'spacing', label: 'Frame spacing', type: 'number', value: 0, min: 0, max: 64 },
      { id: 'inner', label: 'Inner padding', type: 'number', value: 0, min: 0, max: 16 },
      { id: 'godot', label: 'Godot resource folder', type: 'text', value: 'res://sprites/', hint: 'Used in the .tres texture path' }
    ] });
    if (!v) return;
    var name = X.safeName(v.name), fmt = v.format, ext = fmt === 'sheet' || fmt === 'png' || fmt === 'frames' ? 'png' : fmt;
    var opts = { format: fmt, path: name + '.' + ext, scale: v.scale, tag: v.tag || undefined, layout: v.layout, columns: v.columns || undefined, trim: v.trim, padding: v.padding, spacing: v.spacing, inner_padding: v.inner, godot_path: v.godot, name: name };
    try {
      var files = Tools.buildExport(this.S, opts);
      if (v.__button === 'saveas') {
        for (var i = 0; i < files.length; i++) {
          var f = files[i], bin = typeof f.data !== 'string';
          var r = await shell.fs.save({ title: 'Save ' + f.path, suggestedName: f.path.split('/').pop(), data: bin ? PNG.toBase64(f.data) : f.data, encoding: bin ? 'base64' : 'utf8' });
          if (!r) break;
        }
        U.toast('Export finished');
      } else {
        for (var j = 0; j < files.length; j++) await this.writeProject(files[j].path, files[j].data);
        U.toast('Exported ' + files.length + ' file' + (files.length > 1 ? 's' : '') + ' to ' + (shell && shell.info ? shell.info.projectDir : 'the project folder'));
      }
    } catch (e) { U.toast('Export failed: ' + (e && e.message || e), 'error'); }
  };

  // ------------------------------------------------------------------ palette
  A.importPaletteData = async function (data) {
    var res = AS.color.importAny(data); if (!res.colors.length) { U.toast('No colours found in that file', 'error'); return; }
    var v = await U.dialog({ title: 'Import palette', fields: [{ type: 'note', text: res.colors.length + ' colours' + (res.name ? ' ("' + res.name + '")' : '') }, { id: 'mode', label: 'Apply as', type: 'select', value: 'replace', options: [['replace', 'Replace palette'], ['append', 'Append to palette']] }], ok: 'Import' });
    if (!v) return;
    var pal = v.mode === 'append' ? this.S.doc.palette.concat(res.colors) : res.colors, seen = new Set();
    pal = pal.filter(function (c) { if (seen.has(c)) return false; seen.add(c); return true; }).slice(0, 256);
    this.S.doc.setPalette(pal); U.toast('Palette: ' + pal.length + ' colours');
  };
  A.pickColor = function (which) {
    var self = this, S = this.S, inp = h('input', { type: 'color', style: { position: 'fixed', left: '-100px', opacity: 0 } });
    var c = which === 'fg' ? S.fg : S.bg; inp.value = (c >>> 24) ? C.hex(c).slice(0, 7) : '#000000';
    inp.addEventListener('input', function () { var n = C.parse(inp.value); if (which === 'fg') S.setFg(n); else { S.bg = n; S.emit('color'); } });
    inp.addEventListener('change', function () { inp.remove(); }); document.body.appendChild(inp); inp.click();
  };
  A.editPaletteColor = function () {
    var S = this.S, i = Math.min(this.palSel, S.doc.palette.length - 1); if (i < 0) return;
    var inp = h('input', { type: 'color', style: { position: 'fixed', left: '-100px', opacity: 0 } }); inp.value = C.hex(S.doc.palette[i]).slice(0, 7);
    var self = this, timer = null, alpha = C.unpack(S.doc.palette[i])[3];
    inp.addEventListener('change', function () { var n = C.parse(inp.value); var u = C.unpack(n); var was = S.doc.palette[i]; var newc = C.pack(u[0], u[1], u[2], alpha); S.doc.setPaletteColor(i, newc); if (was === S.fg) S.setFg(newc); inp.remove(); });
    document.body.appendChild(inp); inp.click();
  };

  // ------------------------------------------------------------------ AI
  A.setupAI = function () {
    var self = this;
    this.ai = AS.ai.createAssistant({ session: this.S, io: this.io, request: shell && shell.request ? function (p, b, o) { return shell.request(p, b, o); } : function () { return Promise.reject(new Error('no bridge')); },
      AIClient: shell && typeof shell.AIClient === 'function' ? shell.AIClient : null, onEvent: function (ev) { self.sawText = self.sawText || ev.type === 'text'; if (self.onAIEvent) self.onAIEvent(ev); } });
  };
  A.runPrompt = async function (text, from) {
    var self = this; this.chatUser(text, from === 'user' ? null : from); this.sawText = false;
    try {
      var res = await this.ai.send(text);
      if (res.text && !this.sawText) this.chatBot(res.text);
      if (res.stopped) this.chatError('Stopped.');
      this.lastRun = res; return res;
    } catch (e) {
      var msg = e && e.code === 'no_key' ? 'No Anthropic key is set up for Sprite. Use the Keys... button in the window toolbar, then press "Check key again".' : (e && e.message) || String(e);
      if (e && e.code === 'stopped') msg = 'Stopped.';
      this.chatError(msg); if (e && e.code === 'no_key') { this.keyReady = false; this.checkAIStatus(false); }
      throw e;
    }
  };
  A.promptForRpc = async function (message, timeoutS) {
    var self = this, timer, timedOut = false;
    var run = this.runPrompt(message, 'Amerika Agent');
    var to = new Promise(function (_, rej) { timer = setTimeout(function () { timedOut = true; self.ai.stop(); var e = new Error('timeout waiting for the assistant'); e.code = -32000; rej(e); }, Math.max(5, timeoutS || 600) * 1000); });
    try { var res = await Promise.race([run, to]); return { reply: res.text || '', tool_calls: res.toolCalls.map(function (c) { return c.name; }) }; }
    finally { clearTimeout(timer); }
  };

  // ------------------------------------------------------------------ actions
  A.act = function (name, arg) {
    var self = this, S = this.S, doc = S.doc, ed = this.editor;
    if (S.busy && ['undo', 'redo', 'file.new', 'file.open', 'delete', 'cut', 'paste'].indexOf(name) >= 0) { U.toast('The assistant is working. Press Stop first.'); return; }
    if (name.indexOf('tool.') === 0) { ed.setTool(name.slice(5)); return; }
    var fn = ACTIONS[name]; if (!fn) { U.toast('Unknown action ' + name, 'error'); return; }
    var r = fn.call(this, arg, S, doc, ed);
    if (r && r.catch) r.catch(function (e) { U.toast(String(e && e.message || e), 'error'); });
  };
  function scopeTarget(scope) { return scope === 'sprite' ? { layer: 'all', frame: 'all' } : scope === 'frames' ? { frame: 'all' } : scope === 'layer' ? { frame: 'all' } : {}; }
  var SCOPE_OPTS = [['cel', 'Current layer and frame'], ['frames', 'Current layer, all frames'], ['sprite', 'Whole sprite']];
  function guard(app, p) { return p.catch(function (e) { U.toast(String(e && e.message || e), 'error'); }); }
  function runTool(app, name, input) { return guard(app, Tools.run(app.S, name, input, app.io)); }
  var ACTIONS = {
    'file.new': async function () {
      if (!(await this.confirmDiscard())) return;
      var v = await U.dialog({ title: 'New sprite', fields: [
        { id: 'w', label: 'Width', type: 'number', value: 32, min: 1, max: 512 }, { id: 'h', label: 'Height', type: 'number', value: 32, min: 1, max: 512 },
        { id: 'mode', label: 'Colour mode', type: 'select', value: 'rgba', options: [['rgba', 'RGBA (free colours)'], ['indexed', 'Indexed (palette only)']] },
        { id: 'pal', label: 'Palette', type: 'select', value: 'pico8', options: C.PALETTES.map(function (p) { return [p.id, p.name + ' (' + p.colors.length + ')']; }) },
        { id: 'bg', label: 'Background', type: 'select', value: 'transparent', options: [['transparent', 'Transparent'], ['fill', 'Fill with first colour']] }
      ], ok: 'Create' });
      if (!v) return;
      var d = new M.Doc({ w: v.w, h: v.h, mode: v.mode, palette: C.builtin(v.pal).colors.slice() }); d.name = 'Untitled';
      if (v.bg === 'fill') d.edit('bg', function () { d.cw(d.layers[0].id, d.frames[0].id).fill(d.rgbaToValue(d.palette[0])); });
      d.undoStack.length = 0; this.useDoc(d);
    },
    'file.open': function () { return this.fileOpenDialog(); },
    'file.save': function () { return this.save(false); }, 'file.saveAs': function () { return this.save(true); }, 'file.export': function () { return this.exportDialog(); },
    undo: function (_, S, doc) { if (this.editor.stroke || this.editor.poly) return; doc.undo(); }, redo: function (_, S, doc) { if (this.editor.stroke || this.editor.poly) return; doc.redo(); },
    copy: function (_, S, d, ed) { ed.copy(false); }, cut: function (_, S, d, ed) { ed.copy(true); }, paste: function (_, S, d, ed) { ed.paste(); },
    delete: function (_, S, d, ed) { ed.clearSelection(); },
    selectAll: function (_, S, doc) { S.setSelection(new Uint8Array(doc.w * doc.h).fill(1)); }, deselect: function (_, S) { S.setSelection(null); },
    invertSel: function (_, S, doc) { S.setSelection(S.sel ? D.maskInvert(S.sel) : new Uint8Array(doc.w * doc.h).fill(1)); },
    swapColors: function (_, S) { var t = S.fg; S.fg = S.bg || 0; S.bg = t; S.emit('color'); },
    zoomIn: function (_, S, d, ed) { ed.zoomStep(1); }, zoomOut: function (_, S, d, ed) { ed.zoomStep(-1); }, zoomFit: function (_, S, d, ed) { ed.fit(); }, zoom100: function (_, S, d, ed) { ed.setZoom(1); ed.center(); ed.invalidate(); },
    zoomTo: function (z, S, d, ed) { ed.setZoom(z); ed.center(); ed.invalidate(); },
    toggleGrid: function (_, S, d, ed) { ed.showGrid = !ed.showGrid; ed.invalidate(); }, togglePixelGrid: function (_, S, d, ed) { ed.showPixelGrid = !ed.showPixelGrid; ed.invalidate(); },
    gridSize: async function (_, S, d, ed) { var v = await U.dialog({ title: 'Grid size', fields: [{ id: 'w', label: 'Cell width', type: 'number', value: ed.gridW, min: 1, max: 256 }, { id: 'h', label: 'Cell height', type: 'number', value: ed.gridH, min: 1, max: 256 }] }); if (v) { ed.gridW = v.w | 0; ed.gridH = v.h | 0; ed.showGrid = true; ed.invalidate(); } },
    toggleOnion: function (_, S, d, ed) { ed.onion.on = !ed.onion.on; ed.invalidate(); this.syncView(); },
    onionSettings: async function (_, S, d, ed) { var v = await U.dialog({ title: 'Onion skin', fields: [{ id: 'prev', label: 'Frames before (red)', type: 'number', value: ed.onion.prev, min: 0, max: 8 }, { id: 'next', label: 'Frames after (blue)', type: 'number', value: ed.onion.next, min: 0, max: 8 }, { id: 'op', label: 'Opacity %', type: 'number', value: Math.round(ed.onion.opacity * 100), min: 5, max: 100 }] }); if (v) { ed.onion.prev = v.prev | 0; ed.onion.next = v.next | 0; ed.onion.opacity = v.op / 100; ed.onion.on = true; ed.invalidate(); this.syncView(); } },
    symX: function (_, S, d, ed) { ed.sym.x = !ed.sym.x; ed.invalidate(); this.syncView(); }, symY: function (_, S, d, ed) { ed.sym.y = !ed.sym.y; ed.invalidate(); this.syncView(); },
    cycleTile: function (_, S, d, ed) { var order = ['off', 'x', 'y', 'xy']; ed.tile = order[(order.indexOf(ed.tile) + 1) % 4]; ed.invalidate(); this.syncView(); },
    setTile: function (m, S, d, ed) { ed.tile = m; ed.invalidate(); this.syncView(); },
    toggleWheel: function (_, S, d, ed) { ed.wheelPans = !ed.wheelPans; },
    toggleDocks: function () { document.body.classList.toggle('no-docks'); this.editor.resize(); },
    focusAI: function () { document.body.classList.remove('no-docks'); var t = document.querySelector('.chat-in'); if (t) t.focus(); },
    brushBigger: function (_, S, d, ed) { ed.opts.size = Math.min(16, ed.opts.size + 1); this.toolListeners.forEach(function (f) { f(ed.tool); }); }, brushSmaller: function (_, S, d, ed) { ed.opts.size = Math.max(1, ed.opts.size - 1); this.toolListeners.forEach(function (f) { f(ed.tool); }); },
    // frames / playback
    framePrev: function (_, S) { S.setFrame((S.fi - 1 + S.doc.frames.length) % S.doc.frames.length); }, frameNext: function (_, S) { S.setFrame((S.fi + 1) % S.doc.frames.length); },
    frameFirst: function (_, S) { S.setFrame(0); }, frameLast: function (_, S) { S.setFrame(S.doc.frames.length - 1); },
    frameNew: function (_, S, doc) { var f = doc.addFrame(S.fi + 1); S.setFrame(doc.frameIndex(f.id)); },
    frameDup: function (_, S, doc) { var f = doc.addFrame(S.fi + 1, S.fi); S.setFrame(doc.frameIndex(f.id)); },
    frameDelete: function (_, S, doc) { if (doc.frames.length < 2) { U.toast('A sprite needs at least one frame'); return; } doc.removeFrame(S.fi); },
    frameLeft: function (_, S, doc) { if (S.fi > 0) { doc.moveFrame(S.fi, S.fi - 1); S.setFrame(S.fi - 1); } }, frameRight: function (_, S, doc) { if (S.fi < doc.frames.length - 1) { doc.moveFrame(S.fi, S.fi + 1); S.setFrame(S.fi + 1); } },
    frameReverse: function (_, S, doc) { doc.edit('Reverse frames', function () { var r = doc.frames.slice().reverse(); doc.frames = r; }); },
    frameProps: async function (_, S, doc) { var v = await U.dialog({ title: 'Frame ' + (S.fi + 1), fields: [{ id: 'ms', label: 'Duration (ms)', type: 'number', value: doc.frames[S.fi].duration, min: 10, max: 60000 }, { id: 'all', label: 'Apply to all frames', type: 'check', value: false }] }); if (!v) return; if (v.all) doc.edit('Frame durations', function () { doc.frames.forEach(function (f) { f.duration = v.ms | 0; }); }); else doc.setDuration(S.fi, v.ms); },
    play: function () { this.togglePlay(); },
    tagNew: async function () { var r = this.frameRange ? this.frameRange() : [this.S.fi, this.S.fi]; return this.editTag({ name: 'tag' + (this.S.doc.tags.length + 1), from: r[0], to: r[1], dir: 'forward', repeat: 0, color: '#3cf0a8' }, true); },
    // layers
    layerNew: function (_, S, doc) { var l = doc.addLayer(null, S.li + 1); S.setLayer(doc.layerIndex(l.id)); },
    layerDup: function (_, S, doc) { var l = doc.duplicateLayer(S.layer().id); S.setLayer(doc.layerIndex(l.id)); },
    layerDelete: function (_, S, doc) { if (doc.layers.length < 2) { U.toast('A sprite needs at least one layer'); return; } doc.removeLayer(S.layer().id); },
    layerUp: function (_, S, doc) { if (S.li < doc.layers.length - 1) { doc.moveLayer(S.layer().id, S.li + 1); S.setLayer(S.li + 1); } }, layerDown: function (_, S, doc) { if (S.li > 0) { doc.moveLayer(S.layer().id, S.li - 1); S.setLayer(S.li - 1); } },
    layerMerge: function (_, S, doc) { if (S.li < 1) { U.toast('There is no layer below'); return; } doc.mergeLayerDown(S.layer().id); S.setLayer(S.li - 1); },
    layerProps: function (_, S) { return this.editLayer(S.layer()); },
    flatten: function (_, S, doc) { doc.edit('Flatten', function () { while (doc.layers.length > 1) doc.mergeLayerDown(doc.layers[doc.layers.length - 1].id); }); S.setLayer(0); },
    // pixels
    flipH: function (_, S, d, ed) { ed.transformCel('Flip horizontally', D.flipH, false); }, flipV: function (_, S, d, ed) { ed.transformCel('Flip vertically', D.flipV, false); },
    flipSpriteH: function (_, S, doc, ed) { return runTool(this, 'mirror', { mode: 'flip_horizontal', layer: 'all', frame: 'all' }); }, flipSpriteV: function () { return runTool(this, 'mirror', { mode: 'flip_vertical', layer: 'all', frame: 'all' }); },
    rotate90: function (_, S, d, ed) { ed.transformCel('Rotate 90', function (b, w, h) { if (w === h) return D.rotate90(b, w, h, 1).data; return D.rotateSmart(b, w, h, 90); }, false); },
    rotateDlg: async function () {
      var v = await U.dialog({ title: 'Rotate', fields: [{ id: 'deg', label: 'Angle (degrees, clockwise)', type: 'number', value: 15, min: -360, max: 360, step: 1 }, { id: 'smart', label: 'Smart rotation (RotSprite-like)', type: 'check', value: true }, { id: 'scope', label: 'Apply to', type: 'select', value: 'cel', options: SCOPE_OPTS }] });
      if (v) return runTool(this, 'rotate', Object.assign({ degrees: v.deg, smart: v.smart }, scopeTarget(v.scope)));
    },
    shiftDlg: async function () {
      var v = await U.dialog({ title: 'Shift pixels', fields: [{ id: 'dx', label: 'Horizontal', type: 'number', value: 1, min: -512, max: 512 }, { id: 'dy', label: 'Vertical', type: 'number', value: 0, min: -512, max: 512 }, { id: 'wrap', label: 'Wrap around', type: 'check', value: false }, { id: 'scope', label: 'Apply to', type: 'select', value: 'cel', options: SCOPE_OPTS }] });
      if (v) return runTool(this, 'shift', Object.assign({ dx: v.dx, dy: v.dy, wrap: v.wrap }, scopeTarget(v.scope)));
    },
    outlineDlg: async function (_, S) {
      var v = await U.dialog({ title: 'Outline', fields: [{ id: 'color', label: 'Colour', type: 'color', value: C.hex(S.bg >>> 24 ? S.bg : C.pack(10, 11, 18)).slice(0, 7) }, { id: 'diag', label: 'Include diagonals', type: 'check', value: false }, { id: 'inside', label: 'Inside the shape', type: 'check', value: false }, { id: 'scope', label: 'Apply to', type: 'select', value: 'cel', options: SCOPE_OPTS }] });
      if (v) return runTool(this, 'outline', Object.assign({ color: v.color, diagonal: v.diag, inside: v.inside }, scopeTarget(v.scope)));
    },
    shadowDlg: async function (_, S) {
      var v = await U.dialog({ title: 'Drop shadow', fields: [{ id: 'color', label: 'Colour', type: 'color', value: '#1a1c2c' }, { id: 'dx', label: 'Offset X', type: 'number', value: 1, min: -16, max: 16 }, { id: 'dy', label: 'Offset Y', type: 'number', value: 1, min: -16, max: 16 }, { id: 'scope', label: 'Apply to', type: 'select', value: 'cel', options: SCOPE_OPTS }] });
      if (v) return runTool(this, 'drop_shadow', Object.assign({ color: v.color, dx: v.dx, dy: v.dy }, scopeTarget(v.scope)));
    },
    lightDlg: async function () {
      var v = await U.dialog({ title: 'Shade by light direction', fields: [{ id: 'dir', label: 'Light comes from', type: 'select', value: 'nw', options: [['nw', 'Top-left'], ['n', 'Top'], ['ne', 'Top-right'], ['w', 'Left'], ['e', 'Right'], ['sw', 'Bottom-left'], ['s', 'Bottom'], ['se', 'Bottom-right']] }, { id: 'depth', label: 'Depth (px)', type: 'number', value: 1, min: 1, max: 4 }, { id: 'scope', label: 'Apply to', type: 'select', value: 'cel', options: SCOPE_OPTS }] });
      if (v) return runTool(this, 'shade_by_light_direction', Object.assign({ direction: v.dir, depth: v.depth }, scopeTarget(v.scope)));
    },
    replaceDlg: async function (_, S) {
      var v = await U.dialog({ title: 'Replace colour', fields: [{ id: 'from', label: 'Replace', type: 'color', value: C.hex(S.fg).slice(0, 7) }, { id: 'to', label: 'With', type: 'color', value: C.hex(S.bg >>> 24 ? S.bg : C.pack(255, 255, 255)).slice(0, 7) }, { id: 'tol', label: 'Tolerance', type: 'number', value: 0, min: 0, max: 255 }, { id: 'scope', label: 'Apply to', type: 'select', value: 'frame', options: [['frame', 'Current frame'], ['layer', 'Current layer'], ['sprite', 'Whole sprite']] }] });
      if (v) return runTool(this, 'recolor', { pairs: [{ from: v.from, to: v.to, tolerance: v.tol }], scope: v.scope });
    },
    hueDlg: async function () {
      var v = await U.dialog({ title: 'Adjust colours', fields: [{ id: 'hue', label: 'Hue shift (deg)', type: 'number', value: 0, min: -180, max: 180 }, { id: 'sat', label: 'Saturation (-100..100)', type: 'number', value: 0, min: -100, max: 100 }, { id: 'lig', label: 'Lightness (-100..100)', type: 'number', value: 0, min: -100, max: 100 }, { id: 'scope', label: 'Apply to', type: 'select', value: 'sprite', options: [['sprite', 'Whole sprite (and palette)'], ['frame', 'Current frame'], ['layer', 'Current layer']] }] });
      if (v) return runTool(this, 'recolor', { hue_shift: v.hue, saturation: v.sat / 100, lightness: v.lig / 100, scope: v.scope });
    },
    // sprite
    canvasSize: async function (_, S, doc) {
      var v = await U.dialog({ title: 'Canvas size', fields: [{ id: 'w', label: 'Width', type: 'number', value: doc.w, min: 1, max: 2048 }, { id: 'h', label: 'Height', type: 'number', value: doc.h, min: 1, max: 2048 }, { id: 'anchor', label: 'Anchor', type: 'select', value: 'center', options: [['top-left', 'Top-left'], ['top', 'Top'], ['top-right', 'Top-right'], ['left', 'Left'], ['center', 'Center'], ['right', 'Right'], ['bottom-left', 'Bottom-left'], ['bottom', 'Bottom'], ['bottom-right', 'Bottom-right']] }] });
      if (v) { this.S.sel = null; return runTool(this, 'resize', { width: v.w, height: v.h, anchor: v.anchor }).then(function () { }); }
    },
    scaleSprite: async function (_, S, doc) {
      var v = await U.dialog({ title: 'Scale sprite', fields: [{ id: 'w', label: 'New width', type: 'number', value: doc.w * 2, min: 1, max: 2048 }, { id: 'h', label: 'New height', type: 'number', value: doc.h * 2, min: 1, max: 2048 }, { id: 'algo', label: 'Algorithm', type: 'select', value: 'nearest', options: [['nearest', 'Nearest neighbour'], ['scale2x', 'Scale2x / EPX (x2 only)']] }] });
      if (!v) return;
      if (v.algo === 'scale2x') { doc.transformAll('Scale2x', function (b, w, h) { return D.scale2x(b, w, h); }, doc.w * 2, doc.h * 2); }
      else doc.transformAll('Scale', function (b, w, h) { return D.scaleNearest(b, w, h, v.w | 0, v.h | 0); }, v.w | 0, v.h | 0);
      this.editor.fit();
    },
    cropContent: function (_, S, doc) {
      var x0 = doc.w, y0 = doc.h, x1 = -1, y1 = -1;
      doc.cels.forEach(function (b) { for (var y = 0; y < doc.h; y++) for (var x = 0; x < doc.w; x++) if (b[y * doc.w + x]) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; } });
      if (x1 < 0) { U.toast('Nothing to crop'); return; }
      this.cropTo({ x: x0, y: y0, w: x1 - x0 + 1, h: y1 - y0 + 1 });
    },
    cropSelection: function (_, S, doc) { var b = S.sel && D.maskBounds(S.sel, doc.w, doc.h); if (!b) { U.toast('Make a selection first'); return; } this.cropTo(b); },
    colorMode: function (m, S, doc) { doc.convertMode(m); U.toast('Colour mode: ' + (m === 'indexed' ? 'indexed' : 'RGBA')); },
    // palette
    palettePreset: function (id, S, doc) { var p = C.builtin(id); if (p) { doc.setPalette(p.colors.slice()); U.toast(p.name + ' loaded'); } },
    paletteAdd: function (_, S, doc) { if (doc.palette.indexOf(S.fg) >= 0) { U.toast('Colour is already in the palette'); return; } if (doc.palette.length >= 256) { U.toast('Palette is full (256)', 'error'); return; } doc.setPalette(doc.palette.concat([S.fg])); this.palSel = doc.palette.length - 1; },
    paletteRemove: function (_, S, doc) { var i = Math.min(this.palSel, doc.palette.length - 1); if (i < 0) return; var o = doc.palette.map(function (c, k) { return k; }).filter(function (k) { return k !== i; }); doc.reorderPalette(o, 'Remove colour'); this.palSel = Math.max(0, i - 1); },
    paletteEdit: function () { this.editPaletteColor(); },
    paletteImport: async function () { var f = await shell.fs.open({ title: 'Import palette', binary: true, filters: [{ name: 'Palettes', patterns: ['*.gpl', '*.hex', '*.pal', '*.png', '*.txt'] }] }); if (f) await this.importPaletteData(PNG.fromBase64(f.data)); },
    paletteExport: async function (_, S, doc) { var r = await shell.fs.save({ title: 'Export palette', suggestedName: baseOf(doc.name) + '.gpl', data: C.toGPL(doc.name, doc.palette), encoding: 'utf8' }); if (r) U.toast('Palette saved'); },
    paletteSort: function (by, S, doc) { var order = doc.palette.map(function (c, i) { return i; }); order.sort(function (a, b) { return by === 'luma' ? C.luma(doc.palette[a]) - C.luma(doc.palette[b]) : (function () { var x = C.toHSL(doc.palette[a]), y = C.toHSL(doc.palette[b]); return (x[1] < 0.08 ? -1 : x[0]) - (y[1] < 0.08 ? -1 : y[0]) || x[2] - y[2]; })(); }); doc.reorderPalette(order, 'Sort palette'); },
    paletteRamp: async function (_, S, doc) {
      var v = await U.dialog({ title: 'Add colour ramp', fields: [{ id: 'a', label: 'From', type: 'color', value: C.hex(S.fg).slice(0, 7) }, { id: 'b', label: 'To', type: 'color', value: C.hex(S.bg >>> 24 ? S.bg : C.pack(255, 255, 255)).slice(0, 7) }, { id: 'n', label: 'Steps', type: 'number', value: 5, min: 2, max: 16 }] });
      if (!v) return; var ramp = C.ramp(C.parse(v.a), C.parse(v.b), v.n | 0).filter(function (c) { return doc.palette.indexOf(c) < 0; });
      doc.setPalette(doc.palette.concat(ramp).slice(0, 256)); U.toast(ramp.length + ' colours added');
    },
    paletteFromSprite: function (_, S, doc) { var seen = new Set(), out = []; doc.cels.forEach(function (b) { for (var i = 0; i < b.length && out.length < 256; i++) { var c = doc.valueToRGBA(b[i]); if ((c >>> 24) && !seen.has(c)) { seen.add(c); out.push(c); } } }); if (!out.length) return; doc.setPalette(C.sortPalette(out, 'luma')); },
    // help
    'help.keys': function () { return this.keysDialog(); },
    'help.about': function () {
      return U.dialog({ title: 'About Sprite', cancel: false, ok: 'Close', fields: [
        { type: 'note', text: 'Sprite ' + VERSION + ' - a pixel-art editor with an AI sprite builder, part of Studio (Developer Edition).' },
        { type: 'note', text: 'Original code by Amerika LLC. Sprite is not Aseprite and is not affiliated with Aseprite or Igara Studio. It can read (import only) the documented .aseprite file format so you can bring your files in; it never writes it.' },
        { type: 'note', text: 'Your project files are .asprite.json. Exports: PNG, GIF, APNG, sprite sheets with Aseprite-compatible JSON and Godot SpriteFrames (.tres).' }] });
    }
  };
  A.cropTo = function (b) {
    var doc = this.S.doc;
    doc.edit('Crop', function () {
      doc.cels.forEach(function (buf, k) {
        var out = new Uint32Array(b.w * b.h); for (var y = 0; y < b.h; y++) for (var x = 0; x < b.w; x++) out[y * b.w + x] = buf[(b.y + y) * doc.w + b.x + x];
        doc._touch(k); doc.cels.set(k, out);
      });
      doc.w = b.w; doc.h = b.h;
    });
    this.S.sel = null; this.editor.fit();
  };
  A.editTag = async function (t, isNew) {
    var doc = this.S.doc, n = doc.frames.length;
    var v = await U.dialog({ title: isNew ? 'New tag' : 'Tag "' + t.name + '"', buttons: isNew ? [] : [{ id: 'del', label: 'Delete' }], fields: [
      { id: 'name', label: 'Name (animation name)', type: 'text', value: t.name }, { id: 'from', label: 'From frame', type: 'number', value: t.from + 1, min: 1, max: n }, { id: 'to', label: 'To frame', type: 'number', value: t.to + 1, min: 1, max: n },
      { id: 'dir', label: 'Direction', type: 'select', value: t.dir, options: [['forward', 'Forward'], ['reverse', 'Reverse'], ['pingpong', 'Ping-pong'], ['pingpong_reverse', 'Ping-pong reverse']] },
      { id: 'repeat', label: 'Repeat (0 = forever)', type: 'number', value: t.repeat, min: 0, max: 255 }, { id: 'color', label: 'Colour', type: 'color', value: t.color || '#3cf0a8' }] });
    if (!v) return; if (v.__button === 'del') { doc.removeTag(t.id); return; }
    doc.setTag({ id: isNew ? undefined : t.id, name: v.name.trim() || 'tag', from: v.from - 1, to: v.to - 1, dir: v.dir, repeat: v.repeat, color: v.color });
  };
  A.editLayer = async function (l) {
    var doc = this.S.doc;
    var v = await U.dialog({ title: 'Layer properties', fields: [{ id: 'name', label: 'Name', type: 'text', value: l.name }, { id: 'op', label: 'Opacity (0-255)', type: 'number', value: l.opacity, min: 0, max: 255 },
      { id: 'blend', label: 'Blend mode', type: 'select', value: l.blend, options: M.BLEND_MODES.map(function (b) { return [b, b]; }) }, { id: 'vis', label: 'Visible', type: 'check', value: l.visible }, { id: 'lock', label: 'Locked', type: 'check', value: l.locked }] });
    if (v) doc.setLayer(l.id, { name: v.name, opacity: v.op, blend: v.blend, visible: v.vis, locked: v.lock });
  };

  // ------------------------------------------------------------------ playback
  A.togglePlay = function () {
    var self = this, S = this.S;
    if (this.playing) { this.stopPlay(); return; }
    var tag = this.playTag ? X.findTag(S.doc, this.playTag) : null, order = X.tagFrames(S.doc, tag);
    if (order.length < 2) { U.toast('Add more frames to play an animation'); return; }
    this.playing = true; var pos = Math.max(0, order.indexOf(S.fi)); this.editor.playing = true;
    this.playBtn.firstChild.replaceWith(U.icon('stop', 0.75));
    (function step() {
      if (!self.playing) return;
      S.setFrame(order[pos]); var d = S.doc.frames[order[pos]].duration;
      self.playTimer = setTimeout(function () {
        pos++; if (pos >= order.length) { if (self.loopMode === 'once') { self.stopPlay(); return; } pos = 0; }
        step();
      }, d);
    })();
  };
  A.stopPlay = function () {
    if (!this.playing) return; this.playing = false; this.editor.playing = false; clearTimeout(this.playTimer);
    if (this.playBtn) this.playBtn.firstChild.replaceWith(U.icon('play', 0.75));
  };

  // ------------------------------------------------------------------ shortcuts dialog
  A.keysDialog = function () {
    var self = this, km = this.keymap, rows = Object.keys(DEFAULT_KEYS);
    return new Promise(function (resolve) {
      var back = h('div', { class: 'dlg-back' }), table = h('div', { class: 'keytable' }), capturing = null;
      function render() {
        table.textContent = '';
        rows.forEach(function (a) {
          var b = h('button', { class: 'btn small key', onclick: function () { capturing = a; b.textContent = 'press a key...'; b.classList.add('rec'); } }, km.map[a] ? U.prettyKey(km.map[a]) : '(none)');
          table.appendChild(h('div', { class: 'krow' }, h('span', null, ACTION_LABELS[a] || a), b, h('button', { class: 'btn small', title: 'Reset to default', onclick: function () { km.set(a, DEFAULT_KEYS[a]); render(); } }, 'Reset')));
        });
      }
      function onKey(e) {
        if (!capturing) { if (e.key === 'Escape') { close(); } return; }
        e.preventDefault(); e.stopPropagation();
        if (e.key === 'Escape') { capturing = null; render(); return; }
        var combo = U.normKey(e); if (!combo) return;
        if (e.key === 'Backspace' || e.key === 'Delete' && false) combo = '';
        km.set(capturing, combo); capturing = null; render();
      }
      function close() { document.removeEventListener('keydown', onKey, true); back.remove(); self.refreshShortcuts(); resolve(); }
      render();
      back.appendChild(h('div', { class: 'dlg wide', role: 'dialog', 'aria-label': 'Keyboard shortcuts' }, h('div', { class: 'dlg-title' }, 'Keyboard shortcuts'), h('p', { class: 'dlg-note' }, 'Click a shortcut, then press the new key combination. Backspace clears it. Space always pans.'), table,
        h('div', { class: 'dlg-btns' }, h('button', { class: 'btn', onclick: function () { km.reset(); render(); } }, 'Reset all'), h('button', { class: 'btn primary', onclick: close }, 'Close'))));
      document.body.appendChild(back); document.addEventListener('keydown', onKey, true);
    });
  };
  A.refreshShortcuts = function () { if (this.toolbox) this.toolbox.refresh(); };

  // ------------------------------------------------------------------ menus
  A.menuSpec = function () {
    var self = this, S = this.S, doc = function () { return S.doc; }, ed = function () { return self.editor; };
    function it(label, action, extra) { return Object.assign({ label: label, action: action }, extra || {}); }
    return [
      { label: 'File', items: function () { return [it('New...', 'file.new'), it('Open...', 'file.open'), { label: 'Open recent', submenu: function () { return self.recentItems(); } }, '-', it('Save', 'file.save'), it('Save as...', 'file.saveAs'), '-', it('Export...', 'file.export'), '-', it('Close window', 'quit')]; } },
      { label: 'Edit', items: function () { return [it('Undo', 'undo', { disabled: function () { return !doc().canUndo(); } }), it('Redo', 'redo', { disabled: function () { return !doc().canRedo(); } }), '-', it('Cut', 'cut'), it('Copy', 'copy'), it('Paste', 'paste'), it('Clear', 'delete'), '-', it('Select all', 'selectAll'), it('Deselect', 'deselect'), it('Invert selection', 'invertSel'), '-',
        it('Flip horizontally', 'flipH'), it('Flip vertically', 'flipV'), it('Rotate 90°', 'rotate90'), it('Rotate...', 'rotateDlg'), it('Shift...', 'shiftDlg'), '-', it('Outline...', 'outlineDlg'), it('Drop shadow...', 'shadowDlg'), it('Shade by light direction...', 'lightDlg'), it('Replace colour...', 'replaceDlg'), it('Adjust hue/saturation...', 'hueDlg'), '-', it('Keyboard shortcuts...', 'help.keys')]; } },
      { label: 'Sprite', items: [it('Canvas size...', 'canvasSize'), it('Scale sprite...', 'scaleSprite'), it('Crop to content', 'cropContent'), it('Crop to selection', 'cropSelection'), '-', it('Flip sprite horizontally', 'flipSpriteH'), it('Flip sprite vertically', 'flipSpriteV'), '-',
        { label: 'Colour mode: RGBA', action: 'colorMode', arg: 'rgba', checked: function () { return doc().mode === 'rgba'; } }, { label: 'Colour mode: Indexed', action: 'colorMode', arg: 'indexed', checked: function () { return doc().mode === 'indexed'; } }] },
      { label: 'Layer', items: [it('New layer', 'layerNew'), it('Duplicate layer', 'layerDup'), it('Delete layer', 'layerDelete'), it('Merge down', 'layerMerge'), it('Flatten sprite', 'flatten'), '-', it('Move up', 'layerUp'), it('Move down', 'layerDown'), '-', it('Layer properties...', 'layerProps')] },
      { label: 'Frame', items: [it('New frame', 'frameNew'), it('Duplicate frame', 'frameDup'), it('Delete frame', 'frameDelete'), '-', it('Move left', 'frameLeft'), it('Move right', 'frameRight'), it('Reverse frames', 'frameReverse'), '-', it('Frame duration...', 'frameProps'), it('New tag from selection...', 'tagNew'), it('Play / pause', 'play')] },
      { label: 'Palette', items: function () { return [{ label: 'Presets', submenu: C.PALETTES.map(function (p) { return { label: p.name + ' (' + p.colors.length + ')', action: 'palettePreset', arg: p.id }; }) }, it('Import palette...', 'paletteImport'), it('Export palette (GPL)...', 'paletteExport'), '-', it('Add foreground colour', 'paletteAdd'), it('Remove selected colour', 'paletteRemove'), it('Add colour ramp...', 'paletteRamp'), '-',
        { label: 'Sort by brightness', action: 'paletteSort', arg: 'luma' }, { label: 'Sort by hue', action: 'paletteSort', arg: 'hue' }, it('Build palette from sprite', 'paletteFromSprite')]; } },
      { label: 'View', items: function () { var e = ed(); return [it('Zoom in', 'zoomIn'), it('Zoom out', 'zoomOut'), it('Fit to window', 'zoomFit'), { label: 'Zoom 1x', action: 'zoomTo', arg: 1 }, { label: 'Zoom 8x', action: 'zoomTo', arg: 8 }, '-',
        it('Pixel grid', 'togglePixelGrid', { checked: function () { return e.showPixelGrid; } }), it('Grid', 'toggleGrid', { checked: function () { return e.showGrid; } }), it('Grid size...', 'gridSize'), '-',
        it('Onion skin', 'toggleOnion', { checked: function () { return e.onion.on; } }), it('Onion skin settings...', 'onionSettings'), '-',
        it('Mirror X (vertical axis)', 'symX', { checked: function () { return e.sym.x; } }), it('Mirror Y (horizontal axis)', 'symY', { checked: function () { return e.sym.y; } }), '-',
        { label: 'Tiled mode: off', action: 'setTile', arg: 'off', checked: function () { return e.tile === 'off'; } }, { label: 'Tiled mode: horizontal', action: 'setTile', arg: 'x', checked: function () { return e.tile === 'x'; } }, { label: 'Tiled mode: vertical', action: 'setTile', arg: 'y', checked: function () { return e.tile === 'y'; } }, { label: 'Tiled mode: both', action: 'setTile', arg: 'xy', checked: function () { return e.tile === 'xy'; } }, '-',
        it('Mouse wheel pans (touchpad)', 'toggleWheel', { checked: function () { return e.wheelPans; } }), it('Show / hide side panels', 'toggleDocks')]; } },
      { label: 'Help', items: [it('Keyboard shortcuts...', 'help.keys'), it('About Sprite', 'help.about')] }
    ];
  };
  ACTIONS.quit = function () { if (shell && shell.window && shell.window.close) shell.window.close(); };
  A.recentItems = function () {
    var self = this;
    if (!this.recent.length) return [{ label: '(none)', disabled: function () { return true; } }];
    return this.recent.map(function (r) { return { label: r.name || r.path, action: 'openRecent', arg: r.path }; });
  };
  ACTIONS.openRecent = async function (path) { var f = await shell.fs.readFile(path, { binary: true }); if (f) { var name = path.split('/').pop(); await this.openFileObj({ path: path, name: name, binary: true, data: f.data !== undefined ? f.data : f }); } };
  A.syncView = function () {
    var e = this.editor; if (!this.viewBtns) return;
    this.viewBtns.onion.classList.toggle('on', e.onion.on); this.viewBtns.symx.classList.toggle('on', e.sym.x); this.viewBtns.symy.classList.toggle('on', e.sym.y);
    this.viewBtns.grid.classList.toggle('on', e.showGrid); this.viewBtns.tile.value = e.tile;
    this.zoomLabel.textContent = Math.round(e.zoom * 100) + '%';
  };

  // ------------------------------------------------------------------ boot
  A.build = function () {
    var self = this, S = this.S, root = document.getElementById('app');
    this.editor = new E.Editor(S, {
      onHover: function (p) { self.updateStatus(p); }, onTool: function (t) { self.toolListeners.forEach(function (f) { f(t); }); self.updateStatus(self.editor.hover); }, onView: function () { self.syncView(); }
    });
    this.setupAI();
    var menubar = U.buildMenubar(this.menuSpec(), function (a, arg) { self.act(a, arg); }, function (a) { var k = self.keymap.map[a]; return k ? U.prettyKey(k) : ''; });
    this.menubar = menubar;
    this.titleEl = h('span', { class: 'doc-title' }, S.doc.name);
    var logo = h('div', { class: 'brand' }, h('img', { src: 'icon.svg', alt: '', width: 22, height: 22 }), h('span', { class: 'bname' }, 'AMERIKA ', h('b', null, 'SPRITE')));
    var undoB = h('button', { class: 'tool tiny', title: 'Undo (Ctrl+Z)', 'aria-label': 'Undo', onclick: function () { self.act('undo'); } }, '↶'), redoB = h('button', { class: 'tool tiny', title: 'Redo (Ctrl+Y)', 'aria-label': 'Redo', onclick: function () { self.act('redo'); } }, '↷');
    var top = h('header', { class: 'top' }, logo, menubar, h('span', { class: 'grow' }), this.titleEl, undoB, redoB);
    // view strip
    var zoomLabel = h('span', { class: 'zoomlbl' }, '800%'); this.zoomLabel = zoomLabel;
    function vb(icon, title, act, extra) { return h('button', { class: 'tool tiny', title: title, 'aria-label': title, onclick: function () { self.act(act); } }, extra || U.icon(icon, 0.75)); }
    var tileSel = h('select', { 'aria-label': 'Tiled mode', title: 'Tiled drawing mode', onchange: function () { self.act('setTile', tileSel.value); } }, h('option', { value: 'off' }, 'Tile: off'), h('option', { value: 'x' }, 'Tile: X'), h('option', { value: 'y' }, 'Tile: Y'), h('option', { value: 'xy' }, 'Tile: XY'));
    this.viewBtns = { onion: vb('onion', 'Onion skin (Alt+O)', 'toggleOnion'), symx: vb('symx', 'Mirror X (Shift+X)', 'symX'), symy: vb('symy', 'Mirror Y (Shift+Y)', 'symY'), grid: vb('grid', 'Grid (Ctrl+\')', 'toggleGrid'), tile: tileSel };
    var viewbar = h('div', { class: 'viewbar' }, vb('minus', 'Zoom out (-)', 'zoomOut'), zoomLabel, vb('plus', 'Zoom in (+)', 'zoomIn'), vb('zoom', 'Fit to window (Ctrl+0)', 'zoomFit'), h('span', { class: 'sep' }),
      this.viewBtns.grid, this.viewBtns.symx, this.viewBtns.symy, this.viewBtns.onion, tileSel, h('span', { class: 'grow' }), h('span', { class: 'busy-note' }, ''));
    this.toolbox = P.Toolbox(this); this.preview = P.PreviewPanel(this); this.palette = P.PalettePanel(this); this.options = P.OptionsPanel(this); this.aip = P.AIPanel(this); this.timeline = P.Timeline(this);
    var center = h('div', { class: 'center' }, viewbar, this.editor.el);
    var dock = h('aside', { class: 'dock' }, this.preview, this.palette, this.options, this.aip);
    this.statusL = h('span', null, 'Ready'); this.statusC = h('span', { class: 'grow' }); this.statusR = h('span', null);
    var status = h('footer', { class: 'status' }, this.statusL, this.statusC, this.statusR);
    root.append(top, h('div', { class: 'main' }, this.toolbox, center, dock), this.timeline, status);
    S.onChange(function (k) {
      self.setTitle(); self.updateStatus(self.editor.hover); undoB.disabled = !S.doc.canUndo(); redoB.disabled = !S.doc.canRedo();
      if (k === 'busy') root.classList.toggle('busy', !!S.busy);
      self.syncView();
    });
    undoB.disabled = true; redoB.disabled = true;
    this.editor.resize(); this.editor.fit(); this.syncView(); this.setTitle(); this.updateStatus(null);
    window.addEventListener('keydown', function (e) { self.onKey(e); }, true);
    window.addEventListener('keyup', function (e) { self.editor.onKeyUp(e); });
    window.addEventListener('beforeunload', function () { self.stopPlay(); });
    this.editor.el.addEventListener('pointerdown', function () { self.stopPlay(); }, true);
  };
  A.updateStatus = function (p) {
    var S = this.S, doc = S.doc, e = this.editor;
    var txt = '';
    if (p && p.x >= 0 && p.y >= 0 && p.x < doc.w && p.y < doc.h) {
      var rgba = new Uint32Array(doc.composite(S.fi).buffer), c = rgba[p.y * doc.w + p.x] >>> 0;
      txt = p.x + ', ' + p.y + (c >>> 24 ? '   ' + C.hex(c) : '   transparent');
    }
    this.statusL.textContent = txt || E.TOOL_LABELS[e.tool];
    this.statusR.textContent = doc.w + 'x' + doc.h + '  ' + doc.mode.toUpperCase() + '  frame ' + (S.fi + 1) + '/' + doc.frames.length + '  layer ' + S.layer().name + '  ' + Math.round(e.zoom * 100) + '%';
    if (this.syncZoomLabel !== false && this.zoomLabel) this.zoomLabel.textContent = Math.round(e.zoom * 100) + '%';
  };
  A.onKey = function (e) {
    if (U.isModal()) return;
    var t = e.target, typing = t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable);
    if (this.editor.onKeyDown(e) && !typing) { e.preventDefault(); return; }
    if (typing) return;
    var combo = U.normKey(e); if (!combo) return;
    if (combo === 'shift+=' || combo === '+') combo = this.keymap.map.zoomIn;
    if (combo === 'ctrl+shift+z') { e.preventDefault(); this.act('redo'); return; }
    if (combo === 'escape') { if (this.S.sel) this.S.setSelection(null); this.menubar.closeAll(); return; }
    var a = this.keymap.actionFor(combo);
    if (a) { e.preventDefault(); this.act(a); }
  };

  // ------------------------------------------------------------------ shell hooks
  A.install = function () {
    var self = this;
    if (!shell) return;
    shell.onOpen = function (f) { return self.openFileObj(f); };
    var handler = AS.rpc.createRpc({ get session() { return self.S; }, io: this.io, prompt: function (m, t) { return self.promptForRpc(m, t); } });
    shell.onRpc = async function (method, params) {
      try { return await handler(method, params); }
      catch (e) { var err = e instanceof Error ? e : new Error(String(e)); if (typeof err.code !== 'number') err.code = -32000; throw err; }
    };
    if (shell.recent && shell.recent.list) shell.recent.list().then(function (l) { self.recent = (l || []).map(function (r) { return typeof r === 'string' ? { path: r, name: r.split('/').pop() } : r; }); }, function () {});
  };
  A.api = { handlers: null };

  document.addEventListener('DOMContentLoaded', function () {
    var app = new App(); window.amerikaSprite = app;
    try { app.build(); app.install(); } catch (e) { document.body.appendChild(h('pre', { class: 'fatal' }, 'Sprite failed to start: ' + (e && e.stack || e))); console.error(e); }
  });
})();
