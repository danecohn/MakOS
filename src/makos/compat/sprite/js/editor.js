/* Sprite: canvas editor view (zoom/pan/grid/onion/tiling/selection overlays) and the drawing tools. Original code. */
(function (root, factory) {
  root.AS = root.AS || {}; root.AS.editor = factory(function (n) { return root.AS[n]; });
})(window, function (dep) {
  'use strict';
  var D = dep('draw'), C = dep('color'), Tools = dep('tools'), U = dep('ui'), h = U.h;

  var ZOOMS = [0.25, 0.5, 1, 2, 3, 4, 5, 6, 8, 10, 12, 16, 20, 24, 32, 48, 64];
  var TOOLS = ['pencil', 'eraser', 'bucket', 'line', 'rect', 'ellipse', 'polygon', 'select', 'lasso', 'wand', 'move', 'eyedropper', 'shade', 'dither', 'gradient', 'hand'];
  var TOOL_LABELS = { pencil: 'Pencil', eraser: 'Eraser', bucket: 'Paint bucket', line: 'Line', rect: 'Rectangle', ellipse: 'Ellipse', polygon: 'Polygon', select: 'Rectangular select', lasso: 'Lasso select', wand: 'Magic wand', move: 'Move', eyedropper: 'Eyedropper', shade: 'Shading brush', dither: 'Dither brush', gradient: 'Gradient dither', hand: 'Hand (pan)' };
  function mod(a, n) { return ((a % n) + n) % n; }

  function Editor(S, host) {
    var self = this;
    this.S = S; this.host = host; this.zoom = 8; this.ox = 20; this.oy = 20; this.tool = 'pencil';
    this.opts = { size: 1, shape: 'square', pixelPerfect: true, fill: false, tolerance: 0, contiguous: true, shadeMode: 'lighten', dither: 'bayer', density: 0.5, bayer: 4, wandTol: 0, wandContig: true };
    this.showPixelGrid = true; this.showGrid = false; this.gridW = 16; this.gridH = 16; this.tile = 'off'; this.sym = { x: false, y: false };
    this.onion = { on: false, prev: 1, next: 1, opacity: 0.35 }; this.playing = false;
    this.hover = null; this.spaceDown = false; this.drag = null; this.stroke = null; this.poly = null; this.antsOffset = 0; this.antsPath = null; this.antsFor = null;
    this.clip = null; this.wheelPans = false; this.dirty = true; this.cache = { key: '', canvas: null }; this.onionCache = {};
    this.el = h('div', { class: 'viewport', tabindex: '0', 'aria-label': 'Sprite canvas' });
    this.canvas = h('canvas', { class: 'view' }); this.el.appendChild(this.canvas); this.ctx = this.canvas.getContext('2d');
    this.off = document.createElement('canvas'); this.offctx = this.off.getContext('2d');
    this.checker = null;
    new ResizeObserver(function () { self.resize(); }).observe(this.el);
    this.bind();
    S.onChange(function (kind) {
      if (kind === 'frame' || kind === 'layer' || kind === 'doc' || kind === 'undo' || kind === 'redo') self.cancelPoly();
      if (kind === 'doc') { self.fitSoon = true; }
      self.dirty = true; self.invalidate();
    });
    setInterval(function () { if (self.S.sel && !document.hidden) { self.antsOffset = (self.antsOffset + 1) % 8; self.invalidate(); } }, 140);
  }
  var P = Editor.prototype;

  P.resize = function () {
    var r = this.el.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
    this.cw = Math.max(1, Math.floor(r.width)); this.ch = Math.max(1, Math.floor(r.height)); this.dpr = dpr;
    this.canvas.width = Math.floor(this.cw * dpr); this.canvas.height = Math.floor(this.ch * dpr);
    this.canvas.style.width = this.cw + 'px'; this.canvas.style.height = this.ch + 'px';
    if (this.fitSoon) { this.fit(); this.fitSoon = false; }
    this.invalidate();
  };
  P.invalidate = function () { var self = this; if (this._raf) return; this._raf = requestAnimationFrame(function () { self._raf = 0; self.render(); }); };

  // ---------------------------------------------------------------- view
  P.fit = function () {
    var doc = this.S.doc, pad = 40, best = ZOOMS[0];
    ZOOMS.forEach(function (z) { if (doc.w * z <= this.cw - pad && doc.h * z <= this.ch - pad) best = z; }, this);
    this.zoom = best; this.center(); this.invalidate();
  };
  P.center = function () { var doc = this.S.doc; this.ox = Math.round((this.cw - doc.w * this.zoom) / 2); this.oy = Math.round((this.ch - doc.h * this.zoom) / 2); };
  P.setZoom = function (z, ax, ay) {
    z = Math.max(ZOOMS[0], Math.min(ZOOMS[ZOOMS.length - 1], z));
    if (ax === undefined) { ax = this.cw / 2; ay = this.ch / 2; }
    var px = (ax - this.ox) / this.zoom, py = (ay - this.oy) / this.zoom;
    this.zoom = z; this.ox = Math.round(ax - px * z); this.oy = Math.round(ay - py * z);
    this.invalidate(); if (this.host.onView) this.host.onView();
  };
  P.zoomStep = function (dir, ax, ay) {
    var i = 0; for (var k = 0; k < ZOOMS.length; k++) if (ZOOMS[k] <= this.zoom + 1e-6) i = k;
    if (dir > 0 && ZOOMS[i] < this.zoom - 1e-6) i--; // between steps
    this.setZoom(ZOOMS[Math.max(0, Math.min(ZOOMS.length - 1, i + (dir > 0 ? 1 : -1)))], ax, ay);
  };
  P.toPixel = function (cx, cy) { return { x: Math.floor((cx - this.ox) / this.zoom), y: Math.floor((cy - this.oy) / this.zoom) }; };
  P.setTool = function (t) { this.finishPoly(); this.tool = t; this.invalidate(); if (this.host.onTool) this.host.onTool(t); };

  // ---------------------------------------------------------------- rendering
  P.compositeCanvas = function (fi, key) {
    var doc = this.S.doc, c = document.createElement('canvas'); c.width = doc.w; c.height = doc.h;
    var g = c.getContext('2d'), rgba = doc.composite(fi);
    g.putImageData(new ImageData(new Uint8ClampedArray(rgba.buffer.slice(0)), doc.w, doc.h), 0, 0); return c;
  };
  P.checkerPattern = function () {
    if (this.checker) return this.checker;
    var c = document.createElement('canvas'); c.width = c.height = 16; var g = c.getContext('2d');
    g.fillStyle = '#2a2f45'; g.fillRect(0, 0, 16, 16); g.fillStyle = '#20243a'; g.fillRect(0, 0, 8, 8); g.fillRect(8, 8, 8, 8);
    this.checker = this.ctx.createPattern(c, 'repeat'); return this.checker;
  };
  P.render = function () {
    var S = this.S, doc = S.doc, g = this.ctx, z = this.zoom, w = doc.w, h = doc.h, dpr = this.dpr;
    if (!this.cw) return;
    g.setTransform(dpr, 0, 0, dpr, 0, 0); g.imageSmoothingEnabled = false;
    g.fillStyle = '#0a0c14'; g.fillRect(0, 0, this.cw, this.ch);
    var key = doc.rev + ':' + S.fi + ':' + this.strokeRev;
    if (this.dirty || this.cache.key !== key) {
      this.cache = { key: key, canvas: this.compositeCanvas(S.fi) }; this.dirty = false; this.onionCache = {};
    }
    var ox = this.ox, oy = this.oy, tx = this.tile.indexOf('x') >= 0, ty = this.tile.indexOf('y') >= 0;
    var fx = this.tile === 'off' ? [0] : [-1, 0, 1], fy = [0];
    var xs = tx ? [-1, 0, 1] : [0], ys = ty ? [-1, 0, 1] : [0];
    var self = this;
    ys.forEach(function (j) { xs.forEach(function (i) {
      var x = ox + i * w * z, y = oy + j * h * z;
      g.globalAlpha = (i === 0 && j === 0) ? 1 : 0.55;
      g.save(); g.translate(x, y); g.fillStyle = self.checkerPattern(); g.fillRect(0, 0, w * z, h * z); g.restore();
      if (i === 0 && j === 0 && self.onion.on) self.drawOnion(g, x, y);
      g.drawImage(self.cache.canvas, x, y, w * z, h * z);
    }); });
    g.globalAlpha = 1;
    // grids
    if (this.showPixelGrid && z >= 6) {
      g.strokeStyle = 'rgba(255,255,255,0.09)'; g.lineWidth = 1; g.beginPath();
      for (var gx = 0; gx <= w; gx++) { g.moveTo(Math.round(ox + gx * z) + 0.5, oy); g.lineTo(Math.round(ox + gx * z) + 0.5, oy + h * z); }
      for (var gy = 0; gy <= h; gy++) { g.moveTo(ox, Math.round(oy + gy * z) + 0.5); g.lineTo(ox + w * z, Math.round(oy + gy * z) + 0.5); }
      g.stroke();
    }
    if (this.showGrid && this.gridW > 0 && this.gridH > 0) {
      g.strokeStyle = 'rgba(24,208,255,0.55)'; g.beginPath();
      for (var cx = 0; cx <= w; cx += this.gridW) { g.moveTo(Math.round(ox + cx * z) + 0.5, oy); g.lineTo(Math.round(ox + cx * z) + 0.5, oy + h * z); }
      for (var cy = 0; cy <= h; cy += this.gridH) { g.moveTo(ox, Math.round(oy + cy * z) + 0.5); g.lineTo(ox + w * z, Math.round(oy + cy * z) + 0.5); }
      g.stroke();
    }
    g.strokeStyle = 'rgba(160,170,220,0.7)'; g.lineWidth = 1; g.strokeRect(ox - 0.5, oy - 0.5, w * z + 1, h * z + 1);
    // symmetry guides
    if (this.sym.x || this.sym.y) {
      g.strokeStyle = 'rgba(255,46,99,0.9)'; g.setLineDash([4, 4]); g.beginPath();
      if (this.sym.x) { g.moveTo(ox + w * z / 2, oy - 6); g.lineTo(ox + w * z / 2, oy + h * z + 6); }
      if (this.sym.y) { g.moveTo(ox - 6, oy + h * z / 2); g.lineTo(ox + w * z + 6, oy + h * z / 2); }
      g.stroke(); g.setLineDash([]);
    }
    // selection
    if (S.sel) this.drawAnts(g);
    // polygon in progress
    if (this.poly && this.poly.pts.length) {
      g.strokeStyle = '#ffe14d'; g.lineWidth = 1; g.beginPath();
      this.poly.pts.forEach(function (p, i) { var px = ox + (p[0] + 0.5) * z, py = oy + (p[1] + 0.5) * z; if (i) g.lineTo(px, py); else g.moveTo(px, py); });
      if (this.hover) g.lineTo(ox + (this.hover.x + 0.5) * z, oy + (this.hover.y + 0.5) * z);
      g.stroke();
    }
    // brush footprint
    if (this.hover && !this.spaceDown && !this.drag && !this.stroke && ['pencil', 'eraser', 'shade', 'dither'].indexOf(this.tool) >= 0 && z >= 3) {
      g.strokeStyle = 'rgba(255,255,255,0.85)'; g.lineWidth = 1;
      D.brushOffsets(this.opts.size, this.opts.shape).forEach(function (o) { g.strokeRect(ox + (self.hover.x + o[0]) * z + 0.5, oy + (self.hover.y + o[1]) * z + 0.5, z - 1, z - 1); });
    } else if (this.hover && z >= 3 && ['bucket', 'line', 'rect', 'ellipse', 'polygon', 'wand', 'gradient'].indexOf(this.tool) >= 0 && !this.drag && !this.stroke) {
      g.strokeStyle = 'rgba(255,255,255,0.85)'; g.strokeRect(ox + this.hover.x * z + 0.5, oy + this.hover.y * z + 0.5, z - 1, z - 1);
    }
    if (this.dragRect) { var r = this.dragRect; g.strokeStyle = '#18d0ff'; g.setLineDash([3, 3]); g.strokeRect(ox + r.x * z + 0.5, oy + r.y * z + 0.5, r.w * z, r.h * z); g.setLineDash([]); }
  };
  P.drawOnion = function (g, x, y) {
    var S = this.S, doc = S.doc, o = this.onion, z = this.zoom, self = this;
    function layer(fi, rgb, a) {
      if (fi < 0 || fi >= doc.frames.length || fi === S.fi) return;
      var key = fi + rgb, c = self.onionCache[key];
      if (!c) {
        c = self.compositeCanvas(fi); var cg = c.getContext('2d'); cg.globalCompositeOperation = 'source-atop'; cg.fillStyle = rgb; cg.fillRect(0, 0, c.width, c.height); self.onionCache[key] = c;
      }
      g.globalAlpha = a; g.drawImage(c, x, y, doc.w * z, doc.h * z); g.globalAlpha = 1;
    }
    for (var k = 1; k <= o.prev; k++) layer(S.fi - k, 'rgba(255,46,99,0.55)', o.opacity * (1 - (k - 1) / (o.prev + 0.5)));
    for (k = 1; k <= o.next; k++) layer(S.fi + k, 'rgba(24,208,255,0.55)', o.opacity * (1 - (k - 1) / (o.next + 0.5)));
  };
  P.selectionPath = function () {
    var S = this.S, m = S.sel, w = S.doc.w, h = S.doc.h;
    if (this.antsFor === m && this.antsPath) return this.antsPath;
    var p = new Path2D(), x, y;
    for (y = 0; y < h; y++) for (x = 0; x < w; x++) {
      if (!m[y * w + x]) continue;
      if (y === 0 || !m[(y - 1) * w + x]) { p.moveTo(x, y); p.lineTo(x + 1, y); }
      if (y === h - 1 || !m[(y + 1) * w + x]) { p.moveTo(x, y + 1); p.lineTo(x + 1, y + 1); }
      if (x === 0 || !m[y * w + x - 1]) { p.moveTo(x, y); p.lineTo(x, y + 1); }
      if (x === w - 1 || !m[y * w + x + 1]) { p.moveTo(x + 1, y); p.lineTo(x + 1, y + 1); }
    }
    this.antsFor = m; this.antsPath = p; return p;
  };
  P.drawAnts = function (g) {
    var z = this.zoom, path = this.selectionPath();
    g.save(); g.translate(this.ox, this.oy); g.scale(z, z); g.lineWidth = 1.5 / z;
    g.strokeStyle = '#000'; g.setLineDash([]); g.stroke(path);
    g.strokeStyle = '#fff'; g.setLineDash([3 / z, 3 / z]); g.lineDashOffset = -this.antsOffset / z; g.stroke(path);
    g.restore();
  };
  P.strokeRev = 0;

  // ---------------------------------------------------------------- painting helpers
  P.fgBg = function (button) { var doc = this.S.doc; return button === 2 ? doc.rgbaToValue(this.S.bg) : this.S.fgValue(); };
  /** put(x,y) that applies brush footprint, symmetry, tiling wrap and selection clipping onto buf */
  P.makePut = function (buf, valueFor, size, shape) {
    var doc = this.S.doc, w = doc.w, h = doc.h, sel = this.S.sel, off = D.brushOffsets(size || 1, shape || 'square'), tx = this.tile.indexOf('x') >= 0, ty = this.tile.indexOf('y') >= 0, sx = this.sym.x, sy = this.sym.y;
    function px(x, y) {
      if (tx) x = mod(x, w); if (ty) y = mod(y, h);
      if (x < 0 || y < 0 || x >= w || y >= h) return;
      if (sel && !sel[y * w + x]) return;
      var v = typeof valueFor === 'function' ? valueFor(x, y, buf[y * w + x]) : valueFor;
      if (v !== undefined) buf[y * w + x] = v;
    }
    return function (x, y) {
      for (var i = 0; i < off.length; i++) {
        var X = x + off[i][0], Y = y + off[i][1];
        px(X, Y); if (sx) px(w - 1 - X, Y); if (sy) px(X, h - 1 - Y); if (sx && sy) px(w - 1 - X, h - 1 - Y);
      }
    };
  };
  P.activeCel = function () {
    var S = this.S, doc = S.doc, l = S.layer();
    if (l.locked) { U.toast('Layer "' + l.name + '" is locked', 'error'); return null; }
    if (!l.visible) { U.toast('Layer "' + l.name + '" is hidden', 'error'); return null; }
    return doc.cw(l.id, S.frame().id);
  };
  P.touchView = function () { this.strokeRev++; this.dirty = true; this.invalidate(); };

  // ---------------------------------------------------------------- input
  P.bind = function () {
    var self = this, el = this.canvas;
    el.addEventListener('contextmenu', function (e) { e.preventDefault(); });
    el.addEventListener('pointerdown', function (e) { self.el.focus({ preventScroll: true }); self.onDown(e); });
    el.addEventListener('pointermove', function (e) { self.onMove(e); });
    el.addEventListener('pointerup', function (e) { self.onUp(e); });
    el.addEventListener('pointercancel', function (e) { self.onUp(e, true); });
    el.addEventListener('pointerleave', function () { if (!self.drag && !self.stroke) { self.hover = null; if (self.host.onHover) self.host.onHover(null); self.invalidate(); } });
    el.addEventListener('dblclick', function (e) { if (self.tool === 'polygon' && self.poly) self.finishPoly(); });
    el.addEventListener('wheel', function (e) {
      e.preventDefault(); var r = el.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
      if (e.ctrlKey || (!self.wheelPans && !e.shiftKey)) self.zoomStep(e.deltaY < 0 ? 1 : -1, x, y);
      else { self.ox -= e.shiftKey && !e.deltaX ? e.deltaY : e.deltaX; self.oy -= e.shiftKey ? 0 : e.deltaY; self.invalidate(); }
    }, { passive: false });
  };
  P.pos = function (e) { var r = this.canvas.getBoundingClientRect(); return { cx: e.clientX - r.left, cy: e.clientY - r.top }; };
  P.onDown = function (e) {
    if (this.S.busy) { U.toast('The assistant is working. Press Stop to take over.'); return; }
    var q = this.pos(e), p = this.toPixel(q.cx, q.cy); this.canvas.setPointerCapture(e.pointerId);
    var pan = e.button === 1 || this.spaceDown || this.tool === 'hand';
    if (pan) { this.drag = { type: 'pan', sx: q.cx, sy: q.cy, ox: this.ox, oy: this.oy }; return; }
    if (e.button !== 0 && e.button !== 2) return;
    if (e.altKey && e.button === 0 && this.tool !== 'select') { this.pick(p, 0); return; }
    this.button = e.button;
    var t = this.toolImpl[this.tool]; if (t && t.down) t.down.call(this, e, p, e.button);
  };
  P.onMove = function (e) {
    var q = this.pos(e), p = this.toPixel(q.cx, q.cy);
    this.hover = p; if (this.host.onHover) this.host.onHover(p);
    if (this.drag && this.drag.type === 'pan') { this.ox = this.drag.ox + (q.cx - this.drag.sx); this.oy = this.drag.oy + (q.cy - this.drag.sy); this.invalidate(); return; }
    var t = this.toolImpl[this.tool];
    if ((this.stroke || this.drag) && t && t.move) t.move.call(this, e, p, this.button);
    this.invalidate();
  };
  P.onUp = function (e, cancel) {
    if (this.drag && this.drag.type === 'pan') { this.drag = null; return; }
    var q = this.pos(e), p = this.toPixel(q.cx, q.cy), t = this.toolImpl[this.tool];
    if ((this.stroke || this.drag) && t && t.up) t.up.call(this, e, p, this.button, cancel);
    this.invalidate();
  };
  P.pick = function (p, button) {
    var doc = this.S.doc; if (p.x < 0 || p.y < 0 || p.x >= doc.w || p.y >= doc.h) return;
    var rgba = new Uint32Array(doc.composite(this.S.fi).buffer), c = rgba[p.y * doc.w + p.x] >>> 0;
    if (button === 2) this.S.bg = (c >>> 24) ? c : 0; else this.S.setFg((c >>> 24) ? c : 0);
    this.S.emit('color');
  };
  P.beginStroke = function (label) {
    var cel = null;
    this.S.doc.begin(label);
    try { cel = this.activeCel(); } catch (e) { this.S.doc.end(false); throw e; }
    if (!cel) { this.S.doc.end(false); return null; }
    this.stroke = { label: label, snap: cel.slice(), cel: cel, pts: [], start: null };
    return this.stroke;
  };
  P.endStroke = function (ok) {
    var st = this.stroke; if (!st) return;
    this.stroke = null; this.dragRect = null;
    this.S.doc.end(ok !== false); this.touchView();
  };

  // ---------------------------------------------------------------- tools
  var T = {}; P.toolImpl = T;
  function freehand(valueMaker) {
    return {
      down: function (e, p, b) {
        var st = this.beginStroke(this.tool); if (!st) return;
        st.pts = [[p.x, p.y]]; st.value = valueMaker.call(this, b, st); st.button = b; this.paintFreehand(); this.touchView();
      },
      move: function (e, p) {
        var st = this.stroke; if (!st) return; var last = st.pts[st.pts.length - 1];
        if (last[0] === p.x && last[1] === p.y) return;
        D.line(last[0], last[1], p.x, p.y, function (x, y) { var l = st.pts[st.pts.length - 1]; if (l[0] !== x || l[1] !== y) st.pts.push([x, y]); });
        this.paintFreehand(); this.touchView();
      },
      up: function (e, p, b, cancel) { this.endStroke(!cancel); }
    };
  }
  P.paintFreehand = function () {
    var st = this.stroke, o = this.opts, tool = this.tool; st.cel.set(st.snap);
    var pts = (o.pixelPerfect && o.size === 1 && (tool === 'pencil' || tool === 'eraser') && !this.sym.x && !this.sym.y) ? D.pixelPerfect(st.pts) : st.pts;
    var put;
    if (tool === 'dither') {
      var fg = this.S.fgValue(), bgv = this.S.doc.rgbaToValue(this.S.bg), alt = st.button === 2, a = alt ? bgv : fg, bb = alt ? fg : bgv, self = this;
      put = this.makePut(st.cel, function (x, y, cur) { return D.ditherOn(o.dither, x, y, o.density) ? a : (bb || undefined); }, o.size, o.shape);
    } else if (tool === 'shade') {
      var dir = (st.button === 2 || this.altShade) ? (o.shadeMode === 'lighten' ? -1 : 1) : (o.shadeMode === 'lighten' ? 1 : -1);
      var shifter = this.shifter(dir), seen = new Set(), snap = st.snap, w = this.S.doc.w;
      put = this.makePut(st.cel, function (x, y, cur) { var k = y * w + x; if (!snap[k]) return undefined; return shifter(snap[k]); }, o.size, o.shape);
    } else put = this.makePut(st.cel, st.value, o.size, o.shape);
    pts.forEach(function (q) { put(q[0], q[1]); });
  };
  P.shifter = function (dir) {
    var doc = this.S.doc, cache = new Map();
    return function (v) {
      if (cache.has(v)) return cache.get(v);
      var c = doc.valueToRGBA(v), n = C.shiftTone(doc.palette, c, dir), r = n === c ? v : doc.rgbaToValue(n); cache.set(v, r); return r;
    };
  };
  T.pencil = freehand(function (b) { return this.fgBg(b); });
  T.eraser = freehand(function () { return 0; });
  T.shade = freehand(function () { return 0; });
  T.dither = freehand(function () { return 0; });

  T.bucket = {
    down: function (e, p, b) {
      var S = this.S, doc = S.doc; if (p.x < 0 || p.y < 0 || p.x >= doc.w || p.y >= doc.h) return;
      var st = this.beginStroke('Fill'); if (!st) return;
      var m = D.floodMask(st.cel, doc.w, doc.h, p.x, p.y, this.opts.tolerance, this.opts.contiguous, function (v) { return doc.valueToRGBA(v); });
      D.applyMask(st.cel, m, this.fgBg(b), S.sel); this.endStroke(true);
    }
  };
  function shapeTool(draw) {
    return {
      down: function (e, p, b) { var st = this.beginStroke(this.tool); if (!st) return; st.start = [p.x, p.y]; st.value = this.fgBg(b); this.paintShape(p, e); this.touchView(); },
      move: function (e, p) { if (!this.stroke) return; this.paintShape(p, e); this.touchView(); },
      up: function (e, p, b, cancel) { if (this.stroke) { if (!cancel) this.paintShape(p, e); this.endStroke(!cancel); } }
    };
  }
  P.paintShape = function (p, e) {
    var st = this.stroke, o = this.opts, a = st.start, x1 = p.x, y1 = p.y; st.cel.set(st.snap);
    var put = this.makePut(st.cel, st.value, o.size, o.shape), dx = x1 - a[0], dy = y1 - a[1];
    if (e && e.shiftKey) {
      if (this.tool === 'line') { var ang = Math.round(Math.atan2(dy, dx) / (Math.PI / 4)) * (Math.PI / 4), len = Math.max(Math.abs(dx), Math.abs(dy)) * (Math.abs(Math.cos(ang)) > 0.1 && Math.abs(Math.sin(ang)) > 0.1 ? 1 : 1); x1 = a[0] + Math.round(Math.cos(ang) * len); y1 = a[1] + Math.round(Math.sin(ang) * len); }
      else { var m = Math.max(Math.abs(dx), Math.abs(dy)); x1 = a[0] + (dx < 0 ? -m : m); y1 = a[1] + (dy < 0 ? -m : m); }
    }
    if (this.tool === 'line') D.line(a[0], a[1], x1, y1, put);
    else if (this.tool === 'rect') D.rect(a[0], a[1], x1, y1, o.fill ? this.makePut(st.cel, st.value, 1, 'square') : put, o.fill);
    else if (this.tool === 'ellipse') D.ellipse(a[0], a[1], x1, y1, o.fill ? this.makePut(st.cel, st.value, 1, 'square') : put, o.fill);
  };
  T.line = shapeTool(); T.rect = shapeTool(); T.ellipse = shapeTool();

  T.polygon = {
    down: function (e, p, b) {
      if (!this.poly) {
        var st = this.beginStroke('Polygon'); if (!st) return;
        this.poly = { pts: [], value: this.fgBg(b) }; this.polyStroke = st; this.stroke = null; // keep tx open across clicks
      }
      var first = this.poly.pts[0];
      if (first && this.poly.pts.length > 2 && first[0] === p.x && first[1] === p.y) { this.finishPoly(); return; }
      this.poly.pts.push([p.x, p.y]); this.paintPoly(); this.touchView();
    }
  };
  P.paintPoly = function () {
    var st = this.polyStroke, poly = this.poly; if (!st || !poly) return; st.cel.set(st.snap);
    var o = this.opts, put = this.makePut(st.cel, poly.value, o.size, o.shape), pts = poly.pts;
    if (pts.length === 1) put(pts[0][0], pts[0][1]);
    else if (o.fill && pts.length > 2) D.polygonFill(pts, this.makePut(st.cel, poly.value, 1, 'square'));
    else D.polyline(pts, put, pts.length > 2);
  };
  P.finishPoly = function () {
    if (!this.poly) return; var n = this.poly.pts.length; this.paintPoly();
    this.S.doc.end(n >= 2); this.poly = null; this.polyStroke = null; this.touchView();
  };
  P.cancelPoly = function () { if (!this.poly) return; this.S.doc.end(false); this.poly = null; this.polyStroke = null; this.touchView(); };

  T.eyedropper = { down: function (e, p, b) { this.pick(p, b); this.drag = { type: 'pick', b: b }; }, move: function (e, p) { if (this.drag && this.drag.type === 'pick') this.pick(p, this.drag.b); }, up: function () { this.drag = null; } };

  function selMode(e) { return e.shiftKey ? 'add' : e.altKey ? 'sub' : 'replace'; }
  T.select = {
    down: function (e, p) { this.drag = { type: 'select', a: p, mode: selMode(e), base: this.S.sel, moved: false }; },
    move: function (e, p) {
      var d = this.drag; if (!d || d.type !== 'select') return; d.moved = true;
      var doc = this.S.doc, x0 = Math.max(0, Math.min(d.a.x, p.x)), y0 = Math.max(0, Math.min(d.a.y, p.y)), x1 = Math.min(doc.w - 1, Math.max(d.a.x, p.x)), y1 = Math.min(doc.h - 1, Math.max(d.a.y, p.y));
      this.dragRect = { x: Math.min(d.a.x, p.x), y: Math.min(d.a.y, p.y), w: Math.abs(p.x - d.a.x) + 1, h: Math.abs(p.y - d.a.y) + 1 };
      var m = D.rectMask(doc.w, doc.h, x0, y0, x1, y1);
      this.S.sel = d.mode === 'replace' ? m : D.maskCombine(d.base || D.newMask(doc.w, doc.h), m, d.mode === 'add' ? 'add' : 'sub'); this.S.emit('selection');
    },
    up: function (e, p) { var d = this.drag; this.drag = null; this.dragRect = null; if (d && !d.moved && d.mode === 'replace') { this.S.sel = null; } this.fixSel(); this.S.emit('selection'); }
  };
  P.fixSel = function () { var S = this.S; if (S.sel && !D.maskBounds(S.sel, S.doc.w, S.doc.h)) S.sel = null; };
  T.lasso = {
    down: function (e, p) { this.drag = { type: 'lasso', pts: [[p.x, p.y]], mode: selMode(e), base: this.S.sel }; },
    move: function (e, p) {
      var d = this.drag; if (!d || d.type !== 'lasso') return; var l = d.pts[d.pts.length - 1];
      D.line(l[0], l[1], p.x, p.y, function (x, y) { var q = d.pts[d.pts.length - 1]; if (q[0] !== x || q[1] !== y) d.pts.push([x, y]); });
      var doc = this.S.doc, m = D.polyMask(doc.w, doc.h, d.pts);
      this.S.sel = d.mode === 'replace' ? m : D.maskCombine(d.base || D.newMask(doc.w, doc.h), m, d.mode === 'add' ? 'add' : 'sub'); this.S.emit('selection');
    },
    up: function () { this.drag = null; this.fixSel(); this.S.emit('selection'); }
  };
  T.wand = {
    down: function (e, p) {
      var S = this.S, doc = S.doc; if (p.x < 0 || p.y < 0 || p.x >= doc.w || p.y >= doc.h) return;
      var cel = S.celBuf() || new Uint32Array(doc.w * doc.h);
      var m = D.floodMask(cel, doc.w, doc.h, p.x, p.y, this.opts.wandTol, this.opts.wandContig, function (v) { return doc.valueToRGBA(v); }), mode = selMode(e);
      S.sel = mode === 'replace' ? m : D.maskCombine(S.sel || D.newMask(doc.w, doc.h), m, mode === 'add' ? 'add' : 'sub'); this.fixSel(); S.emit('selection');
    }
  };

  T.move = {
    down: function (e, p) {
      var st = this.beginStroke('Move'); if (!st) return; var S = this.S, doc = S.doc, sel = S.sel, snap = st.snap;
      var lifted = new Uint32Array(snap.length);
      if (sel) for (var i = 0; i < snap.length; i++) { if (sel[i]) lifted[i] = snap[i]; } else lifted.set(snap);
      st.lifted = lifted; st.origSel = sel; st.a = p; st.dx = 0; st.dy = 0; this.drag = { type: 'move' };
    },
    move: function (e, p) { var st = this.stroke; if (!st) return; st.dx = p.x - st.a.x; st.dy = p.y - st.a.y; this.paintMove(); this.touchView(); },
    up: function (e, p, b, cancel) { if (!this.stroke) return; this.paintMove(); this.drag = null; this.endStroke(!cancel); this.S.emit('selection'); }
  };
  P.paintMove = function () {
    var st = this.stroke, doc = this.S.doc, w = doc.w, h = doc.h, cel = st.cel, snap = st.snap, sel = st.origSel, dx = st.dx, dy = st.dy;
    cel.set(snap);
    if (sel) { for (var i = 0; i < cel.length; i++) if (sel[i]) cel[i] = 0; } else cel.fill(0);
    var L = st.lifted;
    for (var y = 0; y < h; y++) for (var x = 0; x < w; x++) {
      var v = L[y * w + x]; if (!v) continue;
      var nx = x + dx, ny = y + dy; if (nx >= 0 && ny >= 0 && nx < w && ny < h) cel[ny * w + nx] = v;
    }
    if (sel) this.S.sel = D.shift(sel, w, h, dx, dy, false);
  };

  T.gradient = {
    down: function (e, p, b) {
      var st = this.beginStroke('Gradient dither'); if (!st) return; st.start = [p.x, p.y]; st.button = b; this.paintGradient(p); this.touchView();
    },
    move: function (e, p) { if (!this.stroke) return; this.paintGradient(p); this.touchView(); },
    up: function (e, p, b, cancel) { if (this.stroke) { if (!cancel) this.paintGradient(p); this.endStroke(!cancel); } }
  };
  P.paintGradient = function (p) {
    var st = this.stroke, S = this.S, doc = S.doc, a = st.start, w = doc.w, sel = S.sel; st.cel.set(st.snap);
    var from = doc.rgbaToValue(S.bg), to = S.fgValue(), box = sel ? D.maskBounds(sel, w, doc.h) : { x: 0, y: 0, w: w, h: doc.h };
    if (!box) return;
    D.ditherGradient(a[0], a[1], p.x, p.y, from, to, this.opts.bayer, function (x, y, v) { if (x < 0 || y < 0 || x >= w || y >= doc.h) return; if (sel && !sel[y * w + x]) return; st.cel.set([v], y * w + x); }, box);
  };

  // ---------------------------------------------------------------- keyboard (editor-local); returns true if handled
  P.onKeyDown = function (e) {
    if (e.key === ' ' && !e.repeat) { this.spaceDown = true; this.canvas.style.cursor = 'grab'; }
    if (this.poly) {
      if (e.key === 'Enter') { this.finishPoly(); return true; }
      if (e.key === 'Escape') { this.cancelPoly(); return true; }
    }
    if (this.stroke && e.key === 'Escape') { this.endStroke(false); this.drag = null; return true; }
    if (this.tool === 'move' && e.key.indexOf('Arrow') === 0 && !this.stroke) {
      var dx = e.key === 'ArrowLeft' ? -1 : e.key === 'ArrowRight' ? 1 : 0, dy = e.key === 'ArrowUp' ? -1 : e.key === 'ArrowDown' ? 1 : 0, n = e.shiftKey ? 8 : 1;
      this.nudge(dx * n, dy * n); return true;
    }
    return false;
  };
  P.onKeyUp = function (e) { if (e.key === ' ') { this.spaceDown = false; this.canvas.style.cursor = ''; } };
  P.nudge = function (dx, dy) {
    var S = this.S, doc = S.doc, l = S.layer(); if (l.locked) return;
    doc.edit('Move', function () {
      var cel = doc.cw(l.id, S.frame().id), w = doc.w, h = doc.h, sel = S.sel, snap = cel.slice(), moved = new Uint32Array(snap.length);
      if (sel) { for (var i = 0; i < snap.length; i++) if (sel[i]) { moved[i] = snap[i]; cel[i] = 0; } } else { moved.set(snap); cel.fill(0); }
      for (var y = 0; y < h; y++) for (var x = 0; x < w; x++) { var v = moved[y * w + x]; if (!v) continue; var nx = x + dx, ny = y + dy; if (nx >= 0 && ny >= 0 && nx < w && ny < h) cel[ny * w + nx] = v; }
      if (sel) S.sel = D.shift(sel, w, h, dx, dy, false);
    });
  };

  // ---------------------------------------------------------------- whole-cel operations used by menus
  /** apply fn(buf,w,h)->Uint32Array to the selection bounds (masked) or whole cel, on current layer/frame or all frames */
  P.transformCel = function (label, fn, allFrames) {
    var S = this.S, doc = S.doc, l = S.layer(); if (l.locked) { U.toast('Layer is locked', 'error'); return; }
    doc.edit(label, function () {
      var frames = allFrames ? doc.frames : [S.frame()];
      frames.forEach(function (f) {
        if (!doc.cel(l.id, f.id)) return; var cel = doc.cw(l.id, f.id), w = doc.w, h = doc.h, sel = S.sel;
        if (!sel) { cel.set(fn(cel, w, h)); return; }
        var b = D.maskBounds(sel, w, h); if (!b) return;
        var sub = new Uint32Array(b.w * b.h), x, y;
        for (y = 0; y < b.h; y++) for (x = 0; x < b.w; x++) { var k = (b.y + y) * w + b.x + x; if (sel[k]) { sub[y * b.w + x] = cel[k]; cel[k] = 0; } }
        var out = fn(sub, b.w, b.h);
        for (y = 0; y < b.h; y++) for (x = 0; x < b.w; x++) { var v = out[y * b.w + x]; if (v) cel[(b.y + y) * w + b.x + x] = v; }
      });
    });
  };
  P.clearSelection = function () {
    var S = this.S, doc = S.doc, l = S.layer(); if (l.locked) return;
    doc.edit('Clear', function () { var cel = doc.cw(l.id, S.frame().id), sel = S.sel; for (var i = 0; i < cel.length; i++) if (!sel || sel[i]) cel[i] = 0; });
  };
  P.copy = function (cut) {
    var S = this.S, doc = S.doc, cel = S.celBuf(); if (!cel) return false;
    var sel = S.sel, b = sel ? D.maskBounds(sel, doc.w, doc.h) : { x: 0, y: 0, w: doc.w, h: doc.h }; if (!b) return false;
    var data = new Uint32Array(b.w * b.h);
    for (var y = 0; y < b.h; y++) for (var x = 0; x < b.w; x++) { var k = (b.y + y) * doc.w + b.x + x; if (!sel || sel[k]) data[y * b.w + x] = doc.valueToRGBA(cel[k]); }
    this.clip = { w: b.w, h: b.h, data: data, x: b.x, y: b.y }; if (cut) this.clearSelection(); return true;
  };
  P.paste = function () {
    var S = this.S, doc = S.doc, c = this.clip; if (!c) { U.toast('Clipboard is empty'); return; }
    var l = S.layer(); if (l.locked) return;
    var px = this.hover ? this.hover.x : c.x, py = this.hover ? this.hover.y : c.y; px = Math.max(-c.w + 1, Math.min(doc.w - 1, px)); py = Math.max(-c.h + 1, Math.min(doc.h - 1, py));
    doc.edit('Paste', function () {
      var cel = doc.cw(l.id, S.frame().id), sel = D.newMask(doc.w, doc.h), cache = new Map();
      for (var y = 0; y < c.h; y++) for (var x = 0; x < c.w; x++) {
        var rgba = c.data[y * c.w + x]; if (!(rgba >>> 24)) continue;
        var tx = px + x, ty = py + y; if (tx < 0 || ty < 0 || tx >= doc.w || ty >= doc.h) continue;
        var v = cache.get(rgba); if (v === undefined) { v = doc.rgbaToValue(rgba); cache.set(rgba, v); }
        cel[ty * doc.w + tx] = v; sel[ty * doc.w + tx] = 1;
      }
      S.sel = sel;
    });
    this.setTool('move'); S.emit('selection');
  };

  return { Editor: Editor, TOOLS: TOOLS, TOOL_LABELS: TOOL_LABELS, ZOOMS: ZOOMS };
});
