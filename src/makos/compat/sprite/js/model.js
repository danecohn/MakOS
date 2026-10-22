/* Sprite: document model (layers, frames, tags, palette, cels), compositing, undo/redo command stack,
   native .asprite.json (de)serialisation. Original code.
   Cel pixel values: rgba mode = packed RGBA uint32 (0 = transparent); indexed mode = palette index + 1 (0 = transparent). */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(function (n) { return require('./' + n + '.js'); });
  else { root.AS = root.AS || {}; root.AS.model = factory(function (n) { return root.AS[n]; }); }
})(typeof window !== 'undefined' ? window : globalThis, function (dep) {
  'use strict';
  var C = dep('color'), Z = dep('zlib'), PNG = dep('png');

  var BLEND_MODES = ['normal', 'multiply', 'screen', 'overlay', 'darken', 'lighten', 'add', 'subtract', 'difference', 'exclusion', 'hardlight', 'softlight', 'colordodge', 'colorburn'];
  var MAX_SIDE = 2048;

  function blendCh(mode, b, s) { // b backdrop, s source, 0..255 -> 0..255
    var cb = b / 255, cs = s / 255, r;
    switch (mode) {
      case 'multiply': r = cb * cs; break;
      case 'screen': r = cb + cs - cb * cs; break;
      case 'overlay': r = cb <= 0.5 ? 2 * cs * cb : 1 - 2 * (1 - cs) * (1 - cb); break;
      case 'hardlight': r = cs <= 0.5 ? 2 * cs * cb : 1 - 2 * (1 - cs) * (1 - cb); break;
      case 'darken': r = Math.min(cb, cs); break;
      case 'lighten': r = Math.max(cb, cs); break;
      case 'add': r = Math.min(1, cb + cs); break;
      case 'subtract': r = Math.max(0, cb - cs); break;
      case 'difference': r = Math.abs(cb - cs); break;
      case 'exclusion': r = cb + cs - 2 * cb * cs; break;
      case 'colordodge': r = cb === 0 ? 0 : (cs >= 1 ? 1 : Math.min(1, cb / (1 - cs))); break;
      case 'colorburn': r = cb >= 1 ? 1 : (cs <= 0 ? 0 : 1 - Math.min(1, (1 - cb) / cs)); break;
      case 'softlight': { var d = cb <= 0.25 ? ((16 * cb - 12) * cb + 4) * cb : Math.sqrt(cb); r = cs <= 0.5 ? cb - (1 - 2 * cs) * cb * (1 - cb) : cb + (2 * cs - 1) * (d - cb); break; }
      default: r = cs;
    }
    return r * 255;
  }

  function clone(o) { return JSON.parse(JSON.stringify(o)); }
  function isEmpty32(a) { for (var i = 0; i < a.length; i++) if (a[i]) return false; return true; }
  function eq32(a, b) { if (a === b) return true; if (!a) return isEmpty32(b); if (!b) return isEmpty32(a); if (a.length !== b.length) return false; for (var i = 0; i < a.length; i++) if (a[i] !== b[i]) return false; return true; }

  function Doc(o) {
    o = o || {};
    this.w = clamp(o.w || 32, 1, MAX_SIDE); this.h = clamp(o.h || 32, 1, MAX_SIDE);
    this.mode = o.mode === 'indexed' ? 'indexed' : 'rgba';
    this.palette = (o.palette || C.builtin('pico8').colors).slice(0, 256);
    this.layers = []; this.frames = []; this.tags = []; this.cels = new Map();
    this.nextId = 1; this.name = o.name || 'Sprite'; this.path = null;
    this.undoStack = []; this.redoStack = []; this._tx = null; this._depth = 0;
    this.rev = 0; this.savedRev = 0; this.listeners = [];
    this.layers.push({ id: this.nextId++, name: 'Layer 1', visible: true, opacity: 255, blend: 'normal', locked: false });
    this.frames.push({ id: this.nextId++, duration: 100 });
  }
  function clamp(v, a, b) { v = Math.floor(+v); if (!isFinite(v)) v = a; return Math.max(a, Math.min(b, v)); }
  var P = Doc.prototype;

  P.key = function (l, f) { return l + ':' + f; };
  P.onChange = function (fn) { this.listeners.push(fn); };
  P.emit = function (kind) { this.rev++; for (var i = 0; i < this.listeners.length; i++) this.listeners[i](kind || 'edit'); };
  P.layerIndex = function (id) { for (var i = 0; i < this.layers.length; i++) if (this.layers[i].id === id) return i; return -1; };
  P.frameIndex = function (id) { for (var i = 0; i < this.frames.length; i++) if (this.frames[i].id === id) return i; return -1; };
  P.layerById = function (id) { return this.layers[this.layerIndex(id)]; };
  P.cel = function (layerId, frameId) { return this.cels.get(layerId + ':' + frameId); };
  P.celAt = function (li, fi) { return this.cels.get(this.layers[li].id + ':' + this.frames[fi].id); };
  P.dirty = function () { return this.rev !== this.savedRev; };
  P.markSaved = function () { this.savedRev = this.rev; };

  // ---- pixel value conversion
  P.valueToRGBA = function (v) { if (!v) return 0; if (this.mode === 'rgba') return v >>> 0; var c = this.palette[v - 1]; return c === undefined ? 0 : c; };
  P.rgbaToValue = function (c) {
    c = c >>> 0; if ((c >>> 24) === 0) return 0;
    if (this.mode === 'rgba') return c;
    if (!this.palette.length) return 0;
    var i = this.palette.indexOf(c); if (i < 0) i = C.nearest(this.palette, c);
    return i + 1;
  };
  P.lut = function () { // value -> rgba for indexed
    var l = new Uint32Array(this.palette.length + 1); for (var i = 0; i < this.palette.length; i++) l[i + 1] = this.palette[i]; return l;
  };

  // ---- transactions / history
  P.meta = function () {
    return JSON.stringify({ w: this.w, h: this.h, mode: this.mode, palette: this.palette, layers: this.layers, frames: this.frames, tags: this.tags, nextId: this.nextId });
  };
  P.applyMeta = function (s) {
    var m = JSON.parse(s);
    this.w = m.w; this.h = m.h; this.mode = m.mode; this.palette = m.palette; this.layers = m.layers; this.frames = m.frames; this.tags = m.tags; this.nextId = m.nextId;
  };
  P.begin = function (label) {
    if (this._depth === 0) this._tx = { label: label || 'Edit', before: this.meta(), cels: new Map() };
    this._depth++;
  };
  P.end = function (ok) {
    this._depth--;
    if (this._depth === 0) { var tx = this._tx; this._tx = null; if (ok !== false) this._commit(tx); else this._rollback(tx); }
  };
  P.inEdit = function () { return this._depth > 0; };
  P.edit = function (label, fn) {
    this.begin(label);
    var ok = false, res;
    try { res = fn(this); ok = true; }
    finally { this.end(ok); }
    return res;
  };
  P._rollback = function (tx) {
    var self = this;
    tx.cels.forEach(function (e, k) { if (e.before) self.cels.set(k, e.before); else self.cels.delete(k); });
    this.applyMeta(tx.before); this.emit('abort');
  };
  P._commit = function (tx) {
    var self = this, after = this.meta(), entries = [];
    tx.cels.forEach(function (e, k) {
      var cur = self.cels.get(k) || null;
      if (!eq32(e.before, cur)) entries.push({ key: k, before: e.before, after: cur ? cur.slice() : null });
    });
    if (after === tx.before && !entries.length) return false;
    this.undoStack.push({ label: tx.label, before: tx.before, after: after, cels: entries });
    if (this.undoStack.length > 400) this.undoStack.shift();
    this.redoStack.length = 0;
    this.emit('edit'); return true;
  };
  P._touch = function (key) {
    if (!this._tx) throw new Error('document edits must happen inside doc.edit()');
    if (!this._tx.cels.has(key)) { var c = this.cels.get(key); this._tx.cels.set(key, { before: c ? c.slice() : null }); }
  };
  /** writable cel buffer (created on demand). Valid until the edit ends. */
  P.cw = function (layerId, frameId) {
    var k = layerId + ':' + frameId; this._touch(k);
    var c = this.cels.get(k);
    if (!c) { c = new Uint32Array(this.w * this.h); this.cels.set(k, c); }
    return c;
  };
  P.setCel = function (layerId, frameId, buf) { var k = layerId + ':' + frameId; this._touch(k); if (buf) this.cels.set(k, buf); else this.cels.delete(k); };
  /** merge history entries pushed since `n` into one undo step (used to make a whole AI turn one step) */
  P.collapseSince = function (n, label) {
    if (this.undoStack.length - n < 2) { if (this.undoStack.length - n === 1 && label) this.undoStack[n].label = label; return; }
    var seg = this.undoStack.splice(n), first = seg[0], last = seg[seg.length - 1], cels = new Map();
    seg.forEach(function (h) { h.cels.forEach(function (e) { var o = cels.get(e.key); cels.set(e.key, { key: e.key, before: o ? o.before : e.before, after: e.after }); }); });
    this.undoStack.push({ label: label || first.label, before: first.before, after: last.after, cels: Array.from(cels.values()) });
  };
  P.canUndo = function () { return this.undoStack.length > 0; };
  P.canRedo = function () { return this.redoStack.length > 0; };
  P.undo = function () {
    var h = this.undoStack.pop(); if (!h) return null;
    var self = this;
    h.cels.forEach(function (e) { if (e.before) self.cels.set(e.key, e.before.slice()); else self.cels.delete(e.key); });
    this.applyMeta(h.before); this.redoStack.push(h); this.emit('undo'); return h.label;
  };
  P.redo = function () {
    var h = this.redoStack.pop(); if (!h) return null;
    var self = this;
    h.cels.forEach(function (e) { if (e.after) self.cels.set(e.key, e.after.slice()); else self.cels.delete(e.key); });
    this.applyMeta(h.after); this.undoStack.push(h); this.emit('redo'); return h.label;
  };

  // ---- structure
  P.addLayer = function (name, index) {
    var self = this;
    return this.edit('Add layer', function () {
      var l = { id: self.nextId++, name: name || 'Layer ' + (self.layers.length + 1), visible: true, opacity: 255, blend: 'normal', locked: false };
      self.layers.splice(index === undefined ? self.layers.length : Math.max(0, Math.min(self.layers.length, index)), 0, l); return l;
    });
  };
  P.removeLayer = function (id) {
    var self = this;
    if (this.layers.length < 2) throw new Error('a sprite needs at least one layer');
    this.edit('Delete layer', function () {
      self.frames.forEach(function (f) { if (self.cel(id, f.id)) self.setCel(id, f.id, null); });
      self.layers.splice(self.layerIndex(id), 1);
    });
  };
  P.moveLayer = function (id, to) {
    var self = this;
    this.edit('Move layer', function () { var i = self.layerIndex(id), l = self.layers.splice(i, 1)[0]; self.layers.splice(Math.max(0, Math.min(self.layers.length, to)), 0, l); });
  };
  P.duplicateLayer = function (id) {
    var self = this;
    return this.edit('Duplicate layer', function () {
      var i = self.layerIndex(id), src = self.layers[i], l = clone(src); l.id = self.nextId++; l.name = src.name + ' copy';
      self.layers.splice(i + 1, 0, l);
      self.frames.forEach(function (f) { var c = self.cel(id, f.id); if (c) self.setCel(l.id, f.id, c.slice()); });
      return l;
    });
  };
  P.mergeLayerDown = function (id) {
    var self = this;
    this.edit('Merge down', function () {
      var i = self.layerIndex(id); if (i < 1) throw new Error('no layer below');
      var top = self.layers[i], bot = self.layers[i - 1];
      self.frames.forEach(function (f, fi) {
        var flat = self.compositeLayers(fi, [bot, top], true);
        var out = new Uint32Array(self.w * self.h), v = new Uint32Array(flat.buffer, flat.byteOffset, self.w * self.h);
        for (var p = 0; p < out.length; p++) out[p] = self.rgbaToValue(v[p]);
        self.setCel(bot.id, f.id, out); self.setCel(top.id, f.id, null);
      });
      bot.blend = 'normal'; bot.opacity = 255; self.layers.splice(i, 1);
    });
  };
  P.setLayer = function (id, props) {
    var self = this;
    this.edit('Layer properties', function () {
      var l = self.layerById(id); if (!l) throw new Error('no such layer');
      ['name', 'visible', 'locked'].forEach(function (k) { if (props[k] !== undefined) l[k] = k === 'name' ? String(props[k]).slice(0, 64) : !!props[k]; });
      if (props.opacity !== undefined) l.opacity = clamp(props.opacity, 0, 255);
      if (props.blend !== undefined) { if (BLEND_MODES.indexOf(props.blend) < 0) throw new Error('unknown blend mode ' + props.blend); l.blend = props.blend; }
    });
  };
  P.addFrame = function (index, copyFrom, opts) {
    var self = this;
    return this.edit(copyFrom === undefined ? 'Add frame' : 'Duplicate frame', function () {
      if (self.frames.length >= 512) throw new Error('too many frames (512 max)');
      index = index === undefined ? self.frames.length : Math.max(0, Math.min(self.frames.length, index));
      var src = copyFrom === undefined ? null : self.frames[copyFrom];
      if (copyFrom !== undefined && !src) throw new Error('no such frame to copy');
      var f = { id: self.nextId++, duration: src ? src.duration : (self.frames[self.frames.length - 1] || { duration: 100 }).duration };
      self.frames.splice(index, 0, f);
      if (src) self.layers.forEach(function (l) { var c = self.cel(l.id, src.id); if (c) self.setCel(l.id, f.id, c.slice()); });
      self.tags.forEach(function (t) {
        if (t.from >= index) t.from++;
        if (t.to >= index && !(t.to === index - 1)) t.to++;
        else if (t.to === index - 1 && opts && opts.extendTag) t.to++;
      });
      return f;
    });
  };
  P.removeFrame = function (index) {
    var self = this;
    if (this.frames.length < 2) throw new Error('a sprite needs at least one frame');
    this.edit('Delete frame', function () {
      var f = self.frames[index]; if (!f) throw new Error('no such frame');
      self.layers.forEach(function (l) { if (self.cel(l.id, f.id)) self.setCel(l.id, f.id, null); });
      self.frames.splice(index, 1);
      self.tags = self.tags.filter(function (t) {
        if (t.from > index) t.from--; if (t.to >= index) t.to--;
        if (t.to < t.from) return false; if (t.from < 0) t.from = 0; return true;
      });
    });
  };
  P.moveFrame = function (from, to) {
    var self = this;
    this.edit('Move frame', function () { var f = self.frames.splice(from, 1)[0]; self.frames.splice(Math.max(0, Math.min(self.frames.length, to)), 0, f); });
  };
  P.setDuration = function (index, ms) {
    var self = this;
    this.edit('Frame duration', function () { if (!self.frames[index]) throw new Error('no such frame'); self.frames[index].duration = clamp(ms, 10, 60000); });
  };
  P.setTag = function (tag) { // add or replace by name
    var self = this;
    this.edit('Tag', function () {
      var t = { id: tag.id || self.nextId++, name: String(tag.name || 'tag').slice(0, 48), from: clamp(tag.from, 0, self.frames.length - 1), to: clamp(tag.to, 0, self.frames.length - 1), dir: ['forward', 'reverse', 'pingpong', 'pingpong_reverse'].indexOf(tag.dir) >= 0 ? tag.dir : 'forward', repeat: clamp(tag.repeat || 0, 0, 255), color: tag.color || '#3cf0a8' };
      if (t.to < t.from) t.to = t.from;
      var i = -1; self.tags.forEach(function (x, k) { if (x.id === t.id || (!tag.id && x.name === t.name)) i = k; });
      if (i >= 0) { t.id = self.tags[i].id; self.tags[i] = t; } else self.tags.push(t);
    });
  };
  P.removeTag = function (id) { var self = this; this.edit('Delete tag', function () { self.tags = self.tags.filter(function (t) { return t.id !== id && t.name !== id; }); }); };

  // ---- palette / mode / size
  P.setPalette = function (colors, remap) {
    var self = this;
    this.edit('Palette', function () {
      colors = colors.slice(0, 256).map(function (c) { return c >>> 0; });
      if (self.mode === 'indexed') {
        // keep indices; clip pixels whose index no longer exists
        var n = colors.length;
        self.cels.forEach(function (buf, k) { var w = self.cw.apply(self, k.split(':').map(Number)); for (var i = 0; i < w.length; i++) if (w[i] > n) w[i] = 0; });
      } else if (remap) { // rgba: recolour by old->new colour table
        var map = new Map(); remap.forEach(function (to, i) { map.set(self.palette[i], to); });
        self.cels.forEach(function (buf, k) { var w = self.cw.apply(self, k.split(':').map(Number)); for (var i = 0; i < w.length; i++) { var m = map.get(w[i]); if (m !== undefined && w[i]) w[i] = m; } });
      }
      self.palette = colors;
    });
  };
  /** order[newIndex] = oldIndex; entries not listed are dropped (their pixels become transparent in indexed mode) */
  P.reorderPalette = function (order, label) {
    var self = this;
    this.edit(label || 'Reorder palette', function () {
      var old = self.palette, pal = order.map(function (i) { return old[i]; });
      if (self.mode === 'indexed') {
        var map = new Uint32Array(old.length + 1); order.forEach(function (oi, ni) { map[oi + 1] = ni + 1; });
        self.cels.forEach(function (buf, k) { var w = self.cw.apply(self, k.split(':').map(Number)); for (var i = 0; i < w.length; i++) if (w[i]) w[i] = map[w[i]] || 0; });
      }
      self.palette = pal;
    });
  };
  P.setPaletteColor = function (i, color) {
    var self = this;
    this.edit('Edit colour', function () {
      var old = self.palette[i]; self.palette = self.palette.slice(); self.palette[i] = color >>> 0;
      if (self.mode === 'rgba' && old !== undefined) { // keep pixels linked to their palette swatch
        self.cels.forEach(function (buf, k) { var w = null; for (var p = 0; p < buf.length; p++) if (buf[p] === old) { w = w || self.cw.apply(self, k.split(':').map(Number)); w[p] = color >>> 0; } });
      }
    });
  };
  P.convertMode = function (mode, opts) {
    var self = this;
    if (mode === this.mode) return;
    this.edit('Convert to ' + mode, function () {
      if (mode === 'indexed') {
        if (!self.palette.length || (opts && opts.fromImage)) {
          var uniq = []; var seen = new Set();
          self.cels.forEach(function (buf) { for (var i = 0; i < buf.length; i++) { var v = buf[i]; if (v && !seen.has(v)) { seen.add(v); uniq.push(v); } } });
          if (uniq.length <= 255) self.palette = uniq; else self.palette = quantize(uniq, 255);
        }
        self.mode = 'rgba'; var pal = self.palette; var table = new Map();
        self.cels.forEach(function (buf, k) {
          var w = new Uint32Array(buf.length);
          for (var i = 0; i < buf.length; i++) {
            var v = buf[i]; if (!v) continue;
            var t = table.get(v); if (t === undefined) { var ix = pal.indexOf(v); t = (ix >= 0 ? ix : C.nearest(pal, v)) + 1; table.set(v, t); }
            w[i] = t;
          }
          var ids = k.split(':').map(Number); self._touch(k); self.cels.set(k, w);
        });
        self.mode = 'indexed';
      } else {
        var lut = self.lut();
        self.cels.forEach(function (buf, k) { var w = new Uint32Array(buf.length); for (var i = 0; i < buf.length; i++) w[i] = lut[buf[i]] || 0; self._touch(k); self.cels.set(k, w); });
        self.mode = 'rgba';
      }
    });
  };
  function quantize(colors, n) { // median cut on packed colours
    var ents = colors.map(function (c) { var u = C.unpack(c); return { c: (u[0] << 16) | (u[1] << 8) | u[2], n: 1, a: u[3] }; });
    var boxes = [ents];
    while (boxes.length < n) {
      var bi = -1, bs = 0, bch = 0;
      boxes.forEach(function (b, i) {
        if (b.length < 2) return;
        for (var ch = 0; ch < 3; ch++) { var mn = 255, mx = 0; b.forEach(function (e) { var v = (e.c >> (16 - 8 * ch)) & 255; if (v < mn) mn = v; if (v > mx) mx = v; }); if (mx - mn >= bs) { bs = mx - mn; bi = i; bch = ch; } }
      });
      if (bi < 0) break;
      var b = boxes[bi], sh = 16 - 8 * bch; b.sort(function (p, q) { return ((p.c >> sh) & 255) - ((q.c >> sh) & 255); });
      boxes.splice(bi, 1, b.slice(0, b.length >> 1), b.slice(b.length >> 1));
    }
    return boxes.map(function (b) { var r = 0, g = 0, bl = 0; b.forEach(function (e) { r += (e.c >> 16) & 255; g += (e.c >> 8) & 255; bl += e.c & 255; }); return C.pack(Math.round(r / b.length), Math.round(g / b.length), Math.round(bl / b.length), 255); });
  }
  P.resize = function (w, h, ax, ay) { // anchor 0..1 (0 = top/left)
    var self = this; w = clamp(w, 1, MAX_SIDE); h = clamp(h, 1, MAX_SIDE); ax = ax === undefined ? 0.5 : ax; ay = ay === undefined ? 0.5 : ay;
    this.edit('Canvas size', function () {
      var ox = Math.round((w - self.w) * ax), oy = Math.round((h - self.h) * ay), ow = self.w, oh = self.h;
      self.cels.forEach(function (buf, k) {
        var out = new Uint32Array(w * h);
        for (var y = 0; y < oh; y++) { var ty = y + oy; if (ty < 0 || ty >= h) continue; for (var x = 0; x < ow; x++) { var tx = x + ox; if (tx >= 0 && tx < w) out[ty * w + tx] = buf[y * ow + x]; } }
        self._touch(k); self.cels.set(k, out);
      });
      self.w = w; self.h = h;
    });
  };
  /** replace every cel via fn(buf,w,h)->{w,h,data} (used for scale/rotate of the whole sprite) */
  P.transformAll = function (label, fn, newW, newH) {
    var self = this;
    this.edit(label, function () {
      var nw = newW || self.w, nh = newH || self.h, res = new Map();
      self.cels.forEach(function (buf, k) { res.set(k, fn(buf, self.w, self.h)); });
      res.forEach(function (out, k) { self._touch(k); self.cels.set(k, out); });
      self.w = nw; self.h = nh;
    });
  };

  // ---- compositing
  P.compositeLayers = function (fi, layers, ignoreVisible) {
    var w = this.w, h = this.h, n = w * h, out = new Uint8ClampedArray(n * 4), self = this, lut = this.mode === 'indexed' ? this.lut() : null, frame = this.frames[fi];
    var o32 = new Uint32Array(out.buffer);
    for (var li = 0; li < layers.length; li++) {
      var L = layers[li]; if (!ignoreVisible && !L.visible) continue;
      var cel = this.cels.get(L.id + ':' + frame.id); if (!cel) continue;
      var op = L.opacity / 255, mode = L.blend || 'normal';
      for (var p = 0; p < n; p++) {
        var v = cel[p]; if (!v) continue;
        var s = lut ? lut[v] : v; var sa = (s >>> 24); if (!sa) continue;
        if (mode === 'normal' && op === 1 && sa === 255) { o32[p] = s; continue; }
        var q = p * 4, ba = out[q + 3] / 255, a = (sa / 255) * op, ao = a + ba * (1 - a);
        if (ao <= 0) continue;
        var sr = s & 255, sg = (s >>> 8) & 255, sb = (s >>> 16) & 255, br = out[q], bg = out[q + 1], bb = out[q + 2];
        if (mode !== 'normal' && ba > 0) {
          var mr = blendCh(mode, br, sr), mg = blendCh(mode, bg, sg), mb = blendCh(mode, bb, sb);
          sr = (1 - ba) * sr + ba * mr; sg = (1 - ba) * sg + ba * mg; sb = (1 - ba) * sb + ba * mb;
        }
        out[q] = (sr * a + br * ba * (1 - a)) / ao; out[q + 1] = (sg * a + bg * ba * (1 - a)) / ao; out[q + 2] = (sb * a + bb * ba * (1 - a)) / ao; out[q + 3] = ao * 255;
      }
    }
    return out;
  };
  P.composite = function (fi) { return this.compositeLayers(fi, this.layers, false); };
  /** one layer cel as RGBA (for thumbnails / layer export) */
  P.celRGBA = function (layerId, frameId) {
    var cel = this.cel(layerId, frameId), out = new Uint8ClampedArray(this.w * this.h * 4), o32 = new Uint32Array(out.buffer);
    if (!cel) return out;
    if (this.mode === 'rgba') o32.set(cel); else { var lut = this.lut(); for (var i = 0; i < cel.length; i++) o32[i] = lut[cel[i]] || 0; }
    return out;
  };

  // ---- native serialisation
  function celToB64(doc, buf) {
    var bytes;
    if (doc.mode === 'indexed') { var u = new Uint16Array(buf.length); for (var i = 0; i < buf.length; i++) u[i] = buf[i]; bytes = new Uint8Array(u.buffer); }
    else bytes = new Uint8Array(buf.buffer, buf.byteOffset, buf.byteLength);
    return PNG.toBase64(Z.deflate(bytes));
  }
  function celFromB64(doc, s) {
    var n = doc.w * doc.h, raw = Z.inflate(PNG.fromBase64(s), n * (doc.mode === 'indexed' ? 2 : 4)), copy = new Uint8Array(raw.length); copy.set(raw);
    if (doc.mode === 'indexed') { var u = new Uint16Array(copy.buffer, 0, n), out = new Uint32Array(n); for (var i = 0; i < n; i++) out[i] = u[i]; return out; }
    return new Uint32Array(copy.buffer, 0, n);
  }
  P.toJSON = function () {
    var self = this, cels = [];
    this.cels.forEach(function (buf, k) {
      var ids = k.split(':').map(Number), any = false; for (var i = 0; i < buf.length; i++) if (buf[i]) { any = true; break; }
      if (any) cels.push({ layer: self.layerIndex(ids[0]), frame: self.frameIndex(ids[1]), data: celToB64(self, buf) });
    });
    return {
      format: 'amerika-sprite', version: 1, name: this.name, width: this.w, height: this.h, mode: this.mode,
      palette: this.palette.map(function (c) { return C.hex(c, true); }),
      layers: this.layers.map(function (l) { return { name: l.name, visible: l.visible, opacity: l.opacity, blend: l.blend, locked: l.locked }; }),
      frames: this.frames.map(function (f) { return { duration: f.duration }; }),
      tags: this.tags.map(function (t) { return { name: t.name, from: t.from, to: t.to, direction: t.dir, repeat: t.repeat, color: t.color }; }),
      cels: cels
    };
  };
  Doc.fromJSON = function (j) {
    if (typeof j === 'string') j = JSON.parse(j);
    if (!j || j.format !== 'amerika-sprite') throw new Error('not a Sprite project');
    var d = new Doc({ w: j.width, h: j.height, mode: j.mode, palette: (j.palette || []).map(C.parse).filter(function (c) { return c !== null; }) });
    d.name = j.name || 'Sprite'; d.layers = []; d.frames = [];
    (j.layers || []).forEach(function (l) { d.layers.push({ id: d.nextId++, name: String(l.name || 'Layer'), visible: l.visible !== false, opacity: clamp(l.opacity === undefined ? 255 : l.opacity, 0, 255), blend: BLEND_MODES.indexOf(l.blend) >= 0 ? l.blend : 'normal', locked: !!l.locked }); });
    (j.frames || []).forEach(function (f) { d.frames.push({ id: d.nextId++, duration: clamp(f.duration || 100, 10, 60000) }); });
    if (!d.layers.length || !d.frames.length) throw new Error('project has no layers or frames');
    (j.tags || []).forEach(function (t) { d.tags.push({ id: d.nextId++, name: String(t.name), from: clamp(t.from, 0, d.frames.length - 1), to: clamp(t.to, 0, d.frames.length - 1), dir: t.direction || 'forward', repeat: t.repeat | 0, color: t.color || '#3cf0a8' }); });
    (j.cels || []).forEach(function (c) { var l = d.layers[c.layer], f = d.frames[c.frame]; if (l && f) d.cels.set(l.id + ':' + f.id, celFromB64(d, c.data)); });
    return d;
  };

  /** Build a Doc from RGBA images (e.g. PNG import): frames = [{rgba,delay}] */
  Doc.fromRGBA = function (w, h, frames, palette) {
    var d = new Doc({ w: w, h: h, mode: 'rgba', palette: palette || C.builtin('pico8').colors });
    d.frames = []; frames.forEach(function (f) { d.frames.push({ id: d.nextId++, duration: f.delay || 100 }); });
    var l = d.layers[0];
    frames.forEach(function (f, i) {
      var buf = new Uint32Array(w * h), src = new Uint32Array(f.rgba.buffer.slice(f.rgba.byteOffset, f.rgba.byteOffset + w * h * 4));
      for (var p = 0; p < buf.length; p++) buf[p] = (src[p] >>> 24) ? src[p] : 0;
      d.cels.set(l.id + ':' + d.frames[i].id, buf);
    });
    return d;
  };
  return { Doc: Doc, BLEND_MODES: BLEND_MODES, MAX_SIDE: MAX_SIDE, blendCh: blendCh, quantize: quantize, eq32: eq32 };
});
