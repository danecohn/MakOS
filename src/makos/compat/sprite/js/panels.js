/* Sprite: side panels and timeline (toolbox, palette, tool options, preview, layers/frames, AI chat). Original code. */
(function (root, factory) {
  root.AS = root.AS || {}; root.AS.panels = factory(function (n) { return root.AS[n]; });
})(window, function (dep) {
  'use strict';
  var U = dep('ui'), C = dep('color'), X = dep('exporter'), E = dep('editor'), D = dep('draw'), h = U.h;

  // ================================================================ toolbox
  function Toolbox(app) {
    var S = app.S, el = h('div', { class: 'toolbox', role: 'toolbar', 'aria-label': 'Tools' }), btns = {};
    E.TOOLS.forEach(function (t) {
      var b = h('button', { class: 'tool', 'aria-label': E.TOOL_LABELS[t], 'aria-pressed': 'false', onclick: function () { app.editor.setTool(t); } }, U.icon(t));
      btns[t] = b; el.appendChild(b);
    });
    var fg = h('button', { class: 'swatch big fg', 'aria-label': 'Foreground colour', title: 'Foreground colour (click to edit)', onclick: function () { app.pickColor('fg'); } });
    var bg = h('button', { class: 'swatch big bg', 'aria-label': 'Background colour', title: 'Background colour / right-click colour (click to edit)', onclick: function () { app.pickColor('bg'); } });
    var swap = h('button', { class: 'tool tiny', title: 'Swap colours (X)', 'aria-label': 'Swap colours', onclick: function () { app.act('swapColors'); } }, '⇄');
    var cols = h('div', { class: 'colors' }, bg, fg, swap);
    el.appendChild(cols);
    function refresh() {
      E.TOOLS.forEach(function (t) {
        var sc = app.keymap.map['tool.' + t];
        btns[t].title = E.TOOL_LABELS[t] + (sc ? ' (' + U.prettyKey(sc) + ')' : '');
        btns[t].setAttribute('aria-pressed', String(app.editor.tool === t)); btns[t].classList.toggle('on', app.editor.tool === t);
      });
      fg.style.background = swatchCSS(S.fg); bg.style.background = swatchCSS(S.bg);
    }
    S.onChange(function (k) { if (k === 'color' || k === 'doc') refresh(); });
    app.onTool(refresh); refresh();
    el.refresh = refresh;
    return el;
  }
  function swatchCSS(c) {
    if (!(c >>> 24)) return 'repeating-conic-gradient(#4a4f6a 0% 25%, #20243a 0% 50%) 50% / 8px 8px';
    var u = C.unpack(c); return u[3] === 255 ? C.hex(c) : 'linear-gradient(' + 'rgba(' + u[0] + ',' + u[1] + ',' + u[2] + ',' + (u[3] / 255).toFixed(2) + '),' + 'rgba(' + u[0] + ',' + u[1] + ',' + u[2] + ',' + (u[3] / 255).toFixed(2) + ')), repeating-conic-gradient(#4a4f6a 0% 25%, #20243a 0% 50%) 50% / 8px 8px';
  }

  // ================================================================ palette
  function PalettePanel(app) {
    var S = app.S, el = h('section', { class: 'panel palette', 'aria-label': 'Palette' }), grid = h('div', { class: 'swatches', role: 'listbox', 'aria-label': 'Palette colours' });
    var preset = h('select', { 'aria-label': 'Palette preset', onchange: function () { if (preset.value) app.act('palettePreset', preset.value); preset.value = ''; } },
      h('option', { value: '' }, 'Presets...'), C.PALETTES.map(function (p) { return h('option', { value: p.id }, p.name + ' (' + p.colors.length + ')'); }));
    var hexIn = h('input', { class: 'hex', type: 'text', maxlength: 9, 'aria-label': 'Foreground colour hex', spellcheck: 'false', onchange: function () {
      var c = C.parse(hexIn.value); if (c === null) { hexIn.value = C.hex(S.fg); return; } S.setFg(c); } });
    var head = h('div', { class: 'phead' }, h('span', { class: 'ptitle' }, 'Palette'), preset);
    var tools = h('div', { class: 'prow' },
      mini('plus', 'Add foreground colour to palette', function () { app.act('paletteAdd'); }),
      mini('minus', 'Remove selected colour', function () { app.act('paletteRemove'); }),
      mini('copy', 'Edit selected colour...', function () { app.act('paletteEdit'); }),
      mini('up', 'Import palette (GPL, hex, PNG)', function () { app.act('paletteImport'); }),
      mini('down', 'Export palette (GPL)', function () { app.act('paletteExport'); }), hexIn);
    function mini(icon, title, fn) { return h('button', { class: 'tool tiny', title: title, 'aria-label': title, onclick: fn }, U.icon(icon, 0.75)); }
    el.append(head, grid, tools);
    function refresh() {
      var doc = S.doc; grid.textContent = '';
      doc.palette.forEach(function (c, i) {
        var b = h('button', { class: 'swatch', role: 'option', 'aria-label': 'Colour ' + i + ' ' + C.hex(c), title: i + '  ' + C.hex(c), 'aria-selected': String(c === S.fg),
          onclick: function () { app.palSel = i; S.setFg(c); }, oncontextmenu: function (e) { e.preventDefault(); S.bg = c; S.emit('color'); }, ondblclick: function () { app.palSel = i; app.act('paletteEdit'); } });
        b.style.background = swatchCSS(c);
        if (c === S.fg) b.classList.add('fg'); if (c === S.bg) b.classList.add('bg'); grid.appendChild(b);
      });
      if (document.activeElement !== hexIn) hexIn.value = C.hex(S.fg);
    }
    S.onChange(function (k) { if (['color', 'doc', 'edit', 'undo', 'redo'].indexOf(k) >= 0) refresh(); }); refresh();
    return el;
  }

  // ================================================================ tool options
  function OptionsPanel(app) {
    var el = h('section', { class: 'panel options', 'aria-label': 'Tool options' });
    function row(label, ctl) { return h('label', { class: 'orow' }, h('span', null, label), ctl); }
    function num(key, min, max, step) { var i = h('input', { type: 'range', min: min, max: max, step: step || 1, value: app.editor.opts[key] }), v = h('output', null, String(app.editor.opts[key])); i.oninput = function () { app.editor.opts[key] = parseFloat(i.value); v.textContent = i.value; app.editor.invalidate(); }; return h('span', { class: 'rng' }, i, v); }
    function chk(key, label) { var i = h('input', { type: 'checkbox' }); i.checked = !!app.editor.opts[key]; i.onchange = function () { app.editor.opts[key] = i.checked; }; return h('label', { class: 'orow check' }, i, h('span', null, label)); }
    function sel(key, options) { var s = h('select', { onchange: function () { var v = s.value; app.editor.opts[key] = isNaN(+v) ? v : +v; app.editor.invalidate(); } }, options.map(function (o) { return h('option', { value: o[0], selected: String(o[0]) === String(app.editor.opts[key]) }, o[1]); })); return s; }
    function refresh() {
      var t = app.editor.tool; el.textContent = '';
      el.appendChild(h('div', { class: 'phead' }, h('span', { class: 'ptitle' }, E.TOOL_LABELS[t])));
      var brush = ['pencil', 'eraser', 'shade', 'dither', 'line', 'rect', 'ellipse', 'polygon'].indexOf(t) >= 0;
      if (brush) { el.append(row('Size', num('size', 1, 16)), row('Brush', sel('shape', [['square', 'Square'], ['circle', 'Round']]))); }
      if (t === 'pencil' || t === 'eraser') el.appendChild(chk('pixelPerfect', 'Pixel-perfect'));
      if (t === 'rect' || t === 'ellipse' || t === 'polygon') el.appendChild(chk('fill', 'Filled'));
      if (t === 'bucket') el.append(row('Tolerance', num('tolerance', 0, 255)), chk('contiguous', 'Contiguous'));
      if (t === 'wand') el.append(row('Tolerance', num('wandTol', 0, 255)), chk('wandContig', 'Contiguous'));
      if (t === 'shade') el.appendChild(row('Mode', sel('shadeMode', [['lighten', 'Lighten (right: darken)'], ['darken', 'Darken (right: lighten)']])));
      if (t === 'dither') el.append(row('Pattern', sel('dither', [['bayer', 'Bayer'], ['checker', 'Checkerboard'], ['lines', 'Lines'], ['dots', 'Dots']])), row('Density', num('density', 0.05, 1, 0.05)));
      if (t === 'gradient') el.append(row('Matrix', sel('bayer', [[2, 'Bayer 2x2'], [4, 'Bayer 4x4'], [8, 'Bayer 8x8']])), h('p', { class: 'hint' }, 'Drag: background colour fades to foreground.'));
      if (t === 'select' || t === 'lasso' || t === 'wand') el.appendChild(h('p', { class: 'hint' }, 'Shift: add. Alt: subtract. Click empty: deselect.'));
      if (t === 'polygon') el.appendChild(h('p', { class: 'hint' }, 'Click points. Double-click or Enter to finish, Esc to cancel.'));
      if (t === 'move') el.appendChild(h('p', { class: 'hint' }, 'Drag selection or the whole layer. Arrows nudge.'));
      if (t === 'hand') el.appendChild(h('p', { class: 'hint' }, 'Drag to pan. Space also pans with any tool.'));
      if (t === 'eyedropper') el.appendChild(h('p', { class: 'hint' }, 'Click: foreground. Right-click: background. Alt+click works with any tool.'));
    }
    app.onTool(refresh); refresh();
    return el;
  }

  // ================================================================ preview
  function PreviewPanel(app) {
    var S = app.S, el = h('section', { class: 'panel preview', 'aria-label': 'Preview' }), cv = h('canvas', { width: 224, height: 104 }), g = cv.getContext('2d'), mode = 'anim';
    var modeSel = h('select', { 'aria-label': 'Preview mode', onchange: function () { mode = modeSel.value; draw(); } }, h('option', { value: 'anim' }, 'Animation'), h('option', { value: 'tile' }, 'Tiled 4x4'), h('option', { value: 'x2' }, 'Actual size'));
    el.append(h('div', { class: 'phead' }, h('span', { class: 'ptitle' }, 'Preview'), modeSel), cv);
    var cache = { key: '', c: null };
    function draw() {
      var doc = S.doc; g.imageSmoothingEnabled = false; g.clearRect(0, 0, cv.width, cv.height);
      g.fillStyle = '#10131f'; g.fillRect(0, 0, cv.width, cv.height);
      var key = doc.rev + ':' + S.fi + ':' + app.editor.strokeRev;
      if (cache.key !== key) { cache = { key: key, c: app.editor.compositeCanvas(S.fi) }; }
      var c = cache.c;
      if (mode === 'tile') {
        var s = Math.max(1, Math.floor(Math.min(cv.width / (doc.w * 4), cv.height / (doc.h * 4)))), ox = Math.round((cv.width - doc.w * s * 4) / 2), oy = Math.round((cv.height - doc.h * s * 4) / 2);
        for (var j = 0; j < 4; j++) for (var i = 0; i < 4; i++) g.drawImage(c, ox + i * doc.w * s, oy + j * doc.h * s, doc.w * s, doc.h * s);
      } else {
        var sc = mode === 'x2' ? 1 : Math.max(1, Math.floor(Math.min((cv.width - 8) / doc.w, (cv.height - 8) / doc.h)));
        var w = doc.w * sc, hh = doc.h * sc, x = Math.round((cv.width - w) / 2), y = Math.round((cv.height - hh) / 2);
        g.fillStyle = '#1a1e30'; g.fillRect(x, y, w, hh); g.drawImage(c, x, y, w, hh);
      }
    }
    S.onChange(function () { draw(); }); draw(); el.draw = draw;
    return el;
  }

  // ================================================================ timeline (layers x frames)
  function Timeline(app) {
    var S = app.S, el = h('section', { class: 'timeline', 'aria-label': 'Timeline' });
    var controls = h('div', { class: 'tl-controls' }), table = h('div', { class: 'tl-scroll' });
    el.append(controls, table);
    var playBtn = h('button', { class: 'tool tiny', 'aria-label': 'Play / pause', title: 'Play / pause (Enter)', onclick: function () { app.act('play'); } }, U.icon('play', 0.75));
    var tagSel = h('select', { 'aria-label': 'Playback range', title: 'Playback range', onchange: function () { app.playTag = tagSel.value; } });
    var loopSel = h('select', { 'aria-label': 'Loop', onchange: function () { app.loopMode = loopSel.value; } }, h('option', { value: 'loop' }, 'Loop'), h('option', { value: 'once' }, 'Once'));
    var durIn = h('input', { type: 'number', min: 10, max: 60000, step: 10, 'aria-label': 'Frame duration (ms)', title: 'Frame duration in ms', onchange: function () { var v = parseInt(durIn.value, 10); if (v >= 10) S.doc.setDuration(S.fi, v); } });
    function btn(icon, title, act) { return h('button', { class: 'tool tiny', title: title, 'aria-label': title, onclick: function () { app.act(act); } }, U.icon(icon, 0.75)); }
    controls.append(btn('prev', 'First frame (Home)', 'frameFirst'), playBtn, btn('next', 'Last frame (End)', 'frameLast'), tagSel, loopSel,
      h('span', { class: 'sep' }), h('label', { class: 'inl' }, 'ms', durIn), h('span', { class: 'sep' }),
      btn('plus', 'New frame', 'frameNew'), btn('copy', 'Duplicate frame', 'frameDup'), btn('trash', 'Delete frame', 'frameDelete'), h('span', { class: 'sep' }),
      btn('onion', 'Onion skin', 'toggleOnion'), h('span', { class: 'sep' }), h('span', { class: 'lbl' }, 'Layer'),
      btn('plus', 'New layer', 'layerNew'), btn('copy', 'Duplicate layer', 'layerDup'), btn('up', 'Move layer up', 'layerUp'), btn('down', 'Move layer down', 'layerDown'), btn('trash', 'Delete layer', 'layerDelete'));
    app.playBtn = playBtn;
    var range = null; // [a,b] frame range for tag creation
    function refresh() {
      var doc = S.doc, nf = doc.frames.length; table.textContent = '';
      var cols = '150px repeat(' + nf + ', 30px)';
      var grid = h('div', { class: 'tl-grid', style: { gridTemplateColumns: cols }, role: 'grid' });
      // tag lane
      grid.appendChild(h('div', { class: 'tl-cell corner lbl' }, 'Tags'));
      var lane = h('div', { class: 'tl-lane', style: { gridColumn: '2 / span ' + nf, gridTemplateColumns: 'repeat(' + nf + ', 30px)' } });
      doc.tags.forEach(function (t) {
        lane.appendChild(h('button', { class: 'tag', style: { gridColumn: (t.from + 1) + ' / ' + (t.to + 2), background: t.color }, title: t.name + ' (' + t.dir + ')', onclick: function () { range = [t.from, t.to]; S.setFrame(t.from); refresh(); }, ondblclick: function () { app.editTag(t); } }, t.name));
      });
      grid.appendChild(lane);
      // header
      grid.appendChild(h('div', { class: 'tl-cell corner' }, ''));
      doc.frames.forEach(function (f, i) {
        var inR = range && i >= Math.min(range[0], range[1]) && i <= Math.max(range[0], range[1]);
        grid.appendChild(h('button', { class: 'tl-cell fhead' + (i === S.fi ? ' cur' : '') + (inR ? ' range' : ''), title: 'Frame ' + (i + 1) + ' - ' + f.duration + ' ms', 'aria-label': 'Frame ' + (i + 1),
          onclick: function (e) { if (e.shiftKey && range) range[1] = i; else range = [i, i]; S.setFrame(i); refresh(); }, ondblclick: function () { app.act('frameProps'); } }, String(i + 1)));
      });
      for (var li = doc.layers.length - 1; li >= 0; li--) (function (li) {
        var l = doc.layers[li];
        grid.appendChild(h('div', { class: 'tl-cell lrow' + (li === S.li ? ' cur' : ''), role: 'rowheader' },
          h('button', { class: 'tool tiny' + (l.visible ? '' : ' off'), 'aria-label': 'Toggle visibility of ' + l.name, 'aria-pressed': String(l.visible), title: 'Visible', onclick: function () { doc.setLayer(l.id, { visible: !l.visible }); } }, U.icon('eye', 0.7)),
          h('button', { class: 'tool tiny' + (l.locked ? '' : ' off'), 'aria-label': 'Toggle lock of ' + l.name, 'aria-pressed': String(l.locked), title: 'Locked', onclick: function () { doc.setLayer(l.id, { locked: !l.locked }); } }, U.icon('lock', 0.7)),
          h('button', { class: 'lname', onclick: function () { S.setLayer(li); }, ondblclick: function () { app.editLayer(l); }, title: l.name + (l.opacity < 255 ? ' (' + Math.round(l.opacity / 2.55) + '%)' : '') + (l.blend !== 'normal' ? ' ' + l.blend : '') }, l.name)));
        doc.frames.forEach(function (f, fi) {
          var cel = doc.cel(l.id, f.id), has = false; if (cel) for (var k = 0; k < cel.length; k++) if (cel[k]) { has = true; break; }
          grid.appendChild(h('button', { class: 'tl-cell cel' + (has ? ' has' : '') + (li === S.li && fi === S.fi ? ' cur' : ''), role: 'gridcell', 'aria-label': l.name + ' frame ' + (fi + 1) + (has ? '' : ' empty'),
            onclick: function () { range = [fi, fi]; S.li = li; S.setFrame(fi); S.emit('layer'); } }));
        });
      })(li);
      table.appendChild(grid);
      durIn.value = doc.frames[S.fi].duration;
      var keep = tagSel.value; tagSel.textContent = '';
      tagSel.appendChild(h('option', { value: '' }, 'All frames')); doc.tags.forEach(function (t) { tagSel.appendChild(h('option', { value: t.name }, t.name)); });
      tagSel.value = doc.tags.some(function (t) { return t.name === keep; }) ? keep : ''; app.playTag = tagSel.value;
      el.range = range; app.frameRange = function () { return range ? [Math.min(range[0], range[1]), Math.max(range[0], range[1])] : [S.fi, S.fi]; };
    }
    S.onChange(function (k) { if (k !== 'selection' && k !== 'color' && k !== 'busy') refresh(); });
    refresh();
    el.refresh = refresh;
    return el;
  }

  // ================================================================ AI chat
  function AIPanel(app) {
    var S = app.S, el = h('section', { class: 'panel ai', 'aria-label': 'AI assistant' });
    var status = h('span', { class: 'status' }, '');
    var log = h('div', { class: 'chat-log', role: 'log', 'aria-live': 'polite' });
    var input = h('textarea', { class: 'chat-in', rows: 3, placeholder: 'Describe what to draw or change...  (Enter to send)', 'aria-label': 'Message to the AI sprite artist', spellcheck: 'true' });
    var send = h('button', { class: 'btn primary', onclick: function () { submit(); } }, 'Send');
    var stop = h('button', { class: 'btn danger', hidden: true, onclick: function () { app.ai.stop(); } }, 'Stop');
    var fresh = h('button', { class: 'tool tiny', title: 'New chat', 'aria-label': 'New chat', onclick: function () { app.ai.reset(); log.textContent = ''; hello(); } }, U.icon('plus', 0.75));
    var keys = h('button', { class: 'btn small', hidden: true, onclick: function () { checkStatus(true); } }, 'Check key again');
    el.append(h('div', { class: 'phead' }, h('span', { class: 'ptitle' }, U.icon('ai', 0.75), ' Amerika AI'), status, fresh), log, keys, input, h('div', { class: 'chat-btns' }, stop, send));
    var EXAMPLES = ['32x32 knight with a red plume, idle + walk animation, SNES style', 'Make the sword longer', 'Recolour it to a fire palette', 'Add a 4-frame walk cycle', 'Make a 16x16 forest tileset'];
    function hello() {
      var m = h('div', { class: 'msg sys' }, h('p', null, 'Tell me what to draw. I build it with tools you can undo in one step, and I look at the canvas as I go.'),
        h('div', { class: 'chips' }, EXAMPLES.map(function (t) { return h('button', { class: 'chip', onclick: function () { input.value = t; input.focus(); } }, t); })));
      log.appendChild(m);
    }
    function msg(cls, text) { var m = h('div', { class: 'msg ' + cls }, text); log.appendChild(m); log.scrollTop = log.scrollHeight; return m; }
    var toolLine = null;
    app.onAIEvent = function (ev) {
      if (ev.type === 'tool') { toolLine = h('div', { class: 'msg tool' }, h('code', null, ev.name), h('span', { class: 'st' }, ' ...')); log.appendChild(toolLine); log.scrollTop = log.scrollHeight; }
      else if (ev.type === 'tool_result' && toolLine) {
        toolLine.querySelector('.st').textContent = ev.ok ? ' ✓' : ' ✗ ' + (ev.error || ''); toolLine.classList.add(ev.ok ? 'ok' : 'bad');
        if (ev.image) toolLine.appendChild(h('img', { class: 'thumb', alt: 'canvas view', src: 'data:' + ev.image.mime + ';base64,' + ev.image.base64 }));
        log.scrollTop = log.scrollHeight;
      } else if (ev.type === 'text') msg('bot', ev.text);
    };
    app.chatUser = function (text, from) { msg('user', (from ? '[' + from + '] ' : '') + text); };
    app.chatBot = function (text) { msg('bot', text); };
    app.chatError = function (text) { msg('err', text); };
    function submit() {
      var t = input.value.trim(); if (!t || S.busy) return; input.value = '';
      app.runPrompt(t, 'user').catch(function () {});
    }
    input.addEventListener('keydown', function (e) { e.stopPropagation(); if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); submit(); } });
    S.onChange(function (k) { if (k === 'busy') { send.disabled = S.busy; stop.hidden = !S.busy; el.classList.toggle('working', !!S.busy); status.textContent = S.busy ? 'working...' : app.keyState; } });
    function checkStatus(force) {
      var shell = window.amerikaStudio; if (!shell || !shell.request) { app.keyState = 'no shell'; status.textContent = app.keyState; return Promise.resolve(); }
      return shell.request('/v1/status').then(function (r) {
        var ok = r && r.json && r.json.key && r.json.key.sprite;
        app.keyReady = !!ok; app.keyState = ok ? 'key ready' : 'no key'; status.textContent = app.keyState; keys.hidden = !!ok; el.classList.toggle('nokey', !ok);
        if (!ok && force) app.chatError('No Anthropic key is set for Sprite yet. Use the "Keys..." button in the window toolbar (or Studio), then press "Check key again".');
        if (ok && force) U.toast('Key found. The assistant is ready.');
      }, function (e) { app.keyReady = false; app.keyState = 'bridge offline'; status.textContent = app.keyState; keys.hidden = false; if (force) app.chatError('The Studio bridge is not reachable (' + ((e && e.message) || 'offline') + '). Start Studio first.'); });
    }
    app.checkAIStatus = checkStatus;
    hello(); app.keyState = ''; checkStatus(false);
    return el;
  }

  return { Toolbox: Toolbox, PalettePanel: PalettePanel, OptionsPanel: OptionsPanel, PreviewPanel: PreviewPanel, Timeline: Timeline, AIPanel: AIPanel, swatchCSS: swatchCSS };
});
