/* Sprite: the structured, validated tool set used by the AI panel and by the sprite.* control endpoint.
   Every tool call is applied through doc.edit() (atomic: a failing call changes nothing). Original code. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(function (n) { return require('./' + n + '.js'); });
  else { root.AS = root.AS || {}; root.AS.tools = factory(function (n) { return root.AS[n]; }); }
})(typeof window !== 'undefined' ? window : globalThis, function (dep) {
  'use strict';
  var M = dep('model'), C = dep('color'), D = dep('draw'), PNG = dep('png'), GIF = dep('gif'), X = dep('export');

  var CHARS = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ';
  function ToolError(msg, code) { var e = new Error(msg); e.code = code || -32602; e.toolError = true; return e; }

  // ------------------------------------------------------------------ argument helpers
  function int(v, name, min, max, dflt) {
    if (v === undefined || v === null) { if (dflt !== undefined) return dflt; throw ToolError(name + ' is required'); }
    if (typeof v !== 'number' || !isFinite(v)) throw ToolError(name + ' must be a number');
    v = Math.round(v);
    if (v < min || v > max) throw ToolError(name + ' must be between ' + min + ' and ' + max + ' (got ' + v + ')');
    return v;
  }
  function num(v, name, min, max, dflt) { if (v === undefined || v === null) return dflt; if (typeof v !== 'number' || !isFinite(v) || v < min || v > max) throw ToolError(name + ' must be a number in ' + min + '..' + max); return v; }
  function oneOf(v, name, list, dflt) { if (v === undefined || v === null) return dflt; if (list.indexOf(v) < 0) throw ToolError(name + ' must be one of ' + list.join(', ')); return v; }
  function bool(v, dflt) { return v === undefined || v === null ? dflt : !!v; }
  function layerIndex(S, ref) {
    var doc = S.doc;
    if (ref === undefined || ref === null) return S.li;
    if (typeof ref === 'number') { if (ref < 0 || ref >= doc.layers.length) throw ToolError('layer index ' + ref + ' out of range 0..' + (doc.layers.length - 1)); return ref | 0; }
    for (var i = 0; i < doc.layers.length; i++) if (doc.layers[i].name === ref) return i;
    throw ToolError('no layer named "' + ref + '"');
  }
  function frameIndex(S, v) { if (v === undefined || v === null) return S.fi; return int(v, 'frame', 0, S.doc.frames.length - 1); }
  function targets(S, input, wantLayers) {
    // returns [{li, fi}] honouring layer/frame ('all' allowed)
    var doc = S.doc, ls = [], fs = [], i;
    if (input.layer === 'all') for (i = 0; i < doc.layers.length; i++) ls.push(i); else ls.push(layerIndex(S, input.layer));
    if (input.frame === 'all') for (i = 0; i < doc.frames.length; i++) fs.push(i); else if (Array.isArray(input.frame)) fs = input.frame.map(function (f) { return int(f, 'frame', 0, doc.frames.length - 1); }); else fs.push(frameIndex(S, input.frame));
    var out = []; ls.forEach(function (l) { fs.forEach(function (f) { out.push({ li: l, fi: f }); }); });
    return out;
  }
  /** colour argument -> pixel value. int = palette index; "#hex"; null/"transparent"/-1 = transparent. */
  function colorValue(S, c, name) {
    var doc = S.doc;
    if (c === null || c === 'transparent' || c === -1 || c === undefined) { if (c === undefined) throw ToolError((name || 'color') + ' is required'); return 0; }
    if (typeof c === 'number') {
      if (c < 0 || c >= doc.palette.length) throw ToolError((name || 'color') + ' ' + c + ' is not a palette index (palette has ' + doc.palette.length + ' colours, indices 0..' + (doc.palette.length - 1) + ')');
      return doc.rgbaToValue(doc.palette[c]) || 0;
    }
    if (typeof c === 'string') {
      var p = C.parse(c); if (p === null) throw ToolError((name || 'color') + ' "' + c + '" is not a hex colour like #aabbcc');
      return doc.rgbaToValue(p);
    }
    throw ToolError((name || 'color') + ' must be a palette index, a #hex string or null');
  }
  function writable(S, li, fi) {
    var doc = S.doc, l = doc.layers[li];
    if (l.locked) throw ToolError('layer "' + l.name + '" is locked');
    return doc.cw(l.id, doc.frames[fi].id);
  }
  function makePut(S, buf, v, stats) {
    var w = S.doc.w, h = S.doc.h;
    return function (x, y) { if (x < 0 || y < 0 || x >= w || y >= h) { stats.clipped++; return; } buf[y * w + x] = v; stats.n++; };
  }
  function region(S, r) {
    var w = S.doc.w, h = S.doc.h;
    if (!r) return { x: 0, y: 0, w: w, h: h };
    var x = int(r.x, 'region.x', -w, w * 2, 0), y = int(r.y, 'region.y', -h, h * 2, 0), rw = int(r.w, 'region.w', 1, w, w), rh = int(r.h, 'region.h', 1, h, h);
    var x0 = Math.max(0, x), y0 = Math.max(0, y), x1 = Math.min(w, x + rw), y1 = Math.min(h, y + rh);
    if (x1 <= x0 || y1 <= y0) throw ToolError('region is outside the canvas');
    return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
  }
  function getRegion(buf, w, r) { var o = new Uint32Array(r.w * r.h); for (var y = 0; y < r.h; y++) for (var x = 0; x < r.w; x++) o[y * r.w + x] = buf[(r.y + y) * w + r.x + x]; return o; }
  function putRegion(buf, w, r, sub, clear) { for (var y = 0; y < r.h; y++) for (var x = 0; x < r.w; x++) buf[(r.y + y) * w + r.x + x] = sub[y * r.w + x]; }

  // ------------------------------------------------------------------ introspection
  function legendFor(S) { return CHARS.slice(0, Math.min(CHARS.length, S.doc.palette.length)); }
  function ascii(S, fi) {
    var doc = S.doc, rgba = doc.composite(fi), u = new Uint32Array(rgba.buffer), map = new Map(), rows = [];
    doc.palette.forEach(function (c, i) { if (!map.has(c) && i < CHARS.length) map.set(c, CHARS[i]); });
    for (var y = 0; y < doc.h; y++) {
      var r = '';
      for (var x = 0; x < doc.w; x++) {
        var c = u[y * doc.w + x]; if (!(c >>> 24)) { r += '.'; continue; }
        var ch = map.get(c); if (ch === undefined) { var n = C.nearest(doc.palette.slice(0, CHARS.length), c); ch = n >= 0 ? CHARS[n] : '?'; if (n >= 0 && doc.palette[n] !== c) ch = ch; }
        r += ch;
      }
      rows.push(r);
    }
    return rows.join('\n');
  }
  function info(S) {
    var doc = S.doc;
    var res = {
      name: doc.name, path: doc.path || null, width: doc.w, height: doc.h, mode: doc.mode,
      palette: doc.palette.map(function (c, i) { return { index: i, char: i < CHARS.length ? CHARS[i] : null, color: C.hex(c) }; }),
      layers: doc.layers.map(function (l, i) { return { index: i, name: l.name, visible: l.visible, opacity: l.opacity, blend: l.blend, locked: l.locked, current: i === S.li }; }),
      frame_count: doc.frames.length, current_frame: S.fi, current_layer: S.li,
      frames: doc.frames.map(function (f, i) { return { index: i, duration_ms: f.duration }; }),
      tags: doc.tags.map(function (t) { return { name: t.name, from: t.from, to: t.to, direction: t.dir }; }),
      foreground: C.hex(S.fg), selection: S.sel ? D.maskBounds(S.sel, doc.w, doc.h) : null,
      can_undo: doc.canUndo(), legend_note: 'In draw_pixels rows, characters 0-9a-zA-Z map to palette indices 0..61; "." transparent.'
    };
    if (doc.w * doc.h <= 48 * 48) res.ascii_current_frame = ascii(S, S.fi);
    return res;
  }
  function asciiMaybe(S, res) { if (S.doc.w * S.doc.h <= 40 * 40) res.ascii_current_frame = ascii(S, S.fi); return res; }

  // ------------------------------------------------------------------ view_canvas
  var DIGITS = { '0': '111101101101111', '1': '010110010010111', '2': '111001111100111', '3': '111001111001111', '4': '101101111001001', '5': '111100111001111', '6': '111100111101111', '7': '111001001001001', '8': '111101111101111', '9': '111101111001111' };
  function drawText(img, W, H, str, x, y, col) {
    for (var k = 0; k < str.length; k++) {
      var g = DIGITS[str[k]]; if (!g) continue;
      for (var i = 0; i < 15; i++) if (g[i] === '1') { var px = x + k * 4 + (i % 3), py = y + Math.floor(i / 3); if (px >= 0 && py >= 0 && px < W && py < H) img[py * W + px] = col; }
    }
  }
  /** returns {width,height,rgba} image of one frame upscaled; options: scale, grid (px), rulers, checker, frame */
  function renderView(S, o) {
    o = o || {}; var doc = S.doc, fi = o.frame === undefined ? S.fi : o.frame;
    var maxSide = Math.max(doc.w, doc.h), scale = o.scale ? Math.max(1, Math.min(32, o.scale | 0)) : Math.max(1, Math.min(16, Math.floor(512 / maxSide)));
    var rulers = o.rulers !== false, ml = rulers ? 18 : 0, mt = rulers ? 8 : 0, W = ml + doc.w * scale, H = mt + doc.h * scale;
    var img = new Uint32Array(W * H), src = new Uint32Array(doc.composite(fi).buffer), BG = C.pack(24, 26, 38), A = C.pack(70, 74, 92), B = C.pack(52, 56, 74);
    img.fill(rulers ? C.pack(14, 15, 22) : BG);
    var cell = Math.max(2, Math.min(scale, 8));
    for (var y = 0; y < doc.h * scale; y++) for (var x = 0; x < doc.w * scale; x++) {
      var px = src[Math.floor(y / scale) * doc.w + Math.floor(x / scale)], c;
      if (px >>> 24 === 255) c = px;
      else { var chk = ((Math.floor(x / cell) + Math.floor(y / cell)) & 1) ? A : B; if (!(px >>> 24)) c = o.checker === false ? BG : chk; else { var a = (px >>> 24) / 255, q = C.unpack(chk), p = C.unpack(px); c = C.pack(Math.round(p[0] * a + q[0] * (1 - a)), Math.round(p[1] * a + q[1] * (1 - a)), Math.round(p[2] * a + q[2] * (1 - a))); } }
      img[(mt + y) * W + ml + x] = c;
    }
    var grid = o.grid === undefined ? (scale >= 6 ? 8 : 0) : o.grid | 0;
    if (grid > 0) {
      var GL = C.pack(255, 255, 255, 255);
      for (var gx = grid; gx < doc.w; gx += grid) for (var yy = 0; yy < doc.h * scale; yy += 2) img[(mt + yy) * W + ml + gx * scale] = GL;
      for (var gy = grid; gy < doc.h; gy += grid) for (var xx = 0; xx < doc.w * scale; xx += 2) img[(mt + gy * scale) * W + ml + xx] = GL;
    }
    if (rulers) {
      var step = 8; while (step * scale < 22) step *= 2;
      var TXT = C.pack(150, 160, 200);
      for (var tx = 0; tx < doc.w; tx += step) drawText(img, W, H, String(tx), ml + tx * scale + 1, 1, TXT);
      for (var ty = 0; ty < doc.h; ty += step) drawText(img, W, H, String(ty), 1, mt + ty * scale + 1, TXT);
    }
    return { width: W, height: H, rgba: new Uint8Array(img.buffer), scale: scale };
  }
  function viewResult(S, o) {
    var doc = S.doc;
    if (o.all_frames && doc.frames.length > 1) { // contact sheet
      var n = doc.frames.length, scale = o.scale ? o.scale | 0 : Math.max(1, Math.min(8, Math.floor(640 / (doc.w * Math.min(n, 8)))));
      var cols = Math.min(n, 8), rows = Math.ceil(n / cols), cw = doc.w * scale + 4, ch = doc.h * scale + 10, W = cols * cw, H = rows * ch, out = new Uint32Array(W * H);
      out.fill(C.pack(14, 15, 22));
      for (var f = 0; f < n; f++) {
        var v = renderView(S, { frame: f, scale: scale, rulers: false, grid: 0 }), vv = new Uint32Array(v.rgba.buffer), ox = (f % cols) * cw + 2, oy = Math.floor(f / cols) * ch + 8;
        for (var y = 0; y < v.height; y++) for (var x = 0; x < v.width; x++) out[(oy + y) * W + ox + x] = vv[y * v.width + x];
        drawText(out, W, H, String(f), ox, oy - 7, C.pack(255, 225, 77));
      }
      return { width: W, height: H, rgba: new Uint8Array(out.buffer), scale: scale };
    }
    return renderView(S, o);
  }

  // ------------------------------------------------------------------ colour tone helpers
  function toneShifter(S, dir) { // dir +1 lighter / -1 darker: returns fn(value)->value
    var doc = S.doc, cache = new Map();
    return function (v) {
      var hit = cache.get(v); if (hit !== undefined) return hit;
      var c = doc.valueToRGBA(v), res = v;
      if (doc.palette.length) { var n = C.shiftTone(doc.palette, c, dir); res = n === c ? v : doc.rgbaToValue(n); }
      else if (doc.mode === 'rgba') res = C.shiftTone([], c, dir) === c ? v : v;
      cache.set(v, res); return res;
    };
  }
  function rampShifter(S, ramps, dir) {
    var map = new Map();
    ramps.forEach(function (r) { var vals = r.map(function (i) { return colorValue(S, i, 'ramp entry'); }); for (var i = 0; i < vals.length; i++) { var j = i + dir; if (j >= 0 && j < vals.length) map.set(vals[i], vals[j]); } });
    return function (v) { var r = map.get(v); return r === undefined ? v : r; };
  }

  // ------------------------------------------------------------------ tool implementations
  var T = {}; // name -> {def, run(S,input,io)}
  function def(name, description, props, required, run, extra) {
    T[name] = { def: { name: name, description: description, input_schema: { type: 'object', properties: props, required: required || [] } }, run: run, readonly: !!(extra && extra.readonly) };
  }
  var COLOR = { description: 'Palette index (integer) or "#rrggbb" hex string; null = transparent.', anyOf: [{ type: 'integer' }, { type: 'string' }, { type: 'null' }] };
  var LAYER = { description: 'Layer name, layer index, or "all" (default: current layer).', anyOf: [{ type: 'string' }, { type: 'integer' }] };
  var FRAME = { description: 'Frame index, or "all" (default: current frame).', anyOf: [{ type: 'integer' }, { type: 'string' }] };
  var REGION = { type: 'object', description: 'Limit the operation to this rectangle.', properties: { x: { type: 'integer' }, y: { type: 'integer' }, w: { type: 'integer' }, h: { type: 'integer' } } };

  def('canvas_info', 'Describe the open sprite: size, colour mode, palette (index, legend char, hex), layers, frames, tags and an ASCII picture of the current frame (small sprites). Call this first and whenever unsure of the state.', {}, [],
    function (S) { return info(S); }, { readonly: true });

  def('set_canvas', 'Set the canvas size and colour mode. By default keeps existing pixels (anchored at the centre); with clear=true starts a blank sprite (one layer, one frame). Use mode "indexed" to restrict every pixel to the palette (recommended for pixel art) or "rgba" for free colours.', {
    width: { type: 'integer', minimum: 1, maximum: 512 }, height: { type: 'integer', minimum: 1, maximum: 512 },
    mode: { type: 'string', enum: ['indexed', 'rgba'] }, clear: { type: 'boolean', description: 'Discard all layers, frames and pixels first.' },
    anchor: { type: 'string', enum: ['center', 'top-left', 'top', 'top-right', 'left', 'right', 'bottom-left', 'bottom', 'bottom-right'] }
  }, [], function (S, i) {
    var doc = S.doc, w = int(i.width, 'width', 1, 512, doc.w), h = int(i.height, 'height', 1, 512, doc.h), mode = oneOf(i.mode, 'mode', ['indexed', 'rgba'], doc.mode);
    if (i.clear) {
      var pal = doc.palette; var nd = new M.Doc({ w: w, h: h, mode: mode, palette: pal, name: doc.name });
      doc.edit('Clear', function () { doc.cels.forEach(function (b, k) { doc._touch(k); }); doc.cels.clear(); doc.layers = nd.layers.map(function (l) { l.id = doc.nextId++; return l; }); doc.frames = nd.frames.map(function (f) { f.id = doc.nextId++; return f; }); doc.tags = []; doc.w = w; doc.h = h; doc.mode = 'rgba'; });
      if (mode === 'indexed') doc.convertMode('indexed');
      S.fi = 0; S.li = 0; S.sel = null;
    } else {
      if (w !== doc.w || h !== doc.h) {
        var a = { center: [0.5, 0.5], 'top-left': [0, 0], top: [0.5, 0], 'top-right': [1, 0], left: [0, 0.5], right: [1, 0.5], 'bottom-left': [0, 1], bottom: [0.5, 1], 'bottom-right': [1, 1] }[oneOf(i.anchor, 'anchor', ['center', 'top-left', 'top', 'top-right', 'left', 'right', 'bottom-left', 'bottom', 'bottom-right'], 'center')];
        doc.resize(w, h, a[0], a[1]);
      }
      if (mode !== doc.mode) doc.convertMode(mode);
    }
    return asciiMaybe(S, { ok: true, width: doc.w, height: doc.h, mode: doc.mode });
  });
  T.resize = { def: { name: 'resize', description: 'Resize the canvas keeping the drawing (same as set_canvas without clear). anchor says where existing pixels stay.', input_schema: T.set_canvas.def.input_schema }, run: T.set_canvas.run };

  def('set_palette', 'Replace or extend the palette. Give hex colours and/or a preset (pico8, sweetie16, endesga32, db16, gameboy, c64, gray8, fire, amerika). In indexed mode pixel indices are kept (so the artwork recolours); with remap=true in rgba mode existing pixels are recoloured by luminance order. Keep palettes small (8-32 colours), ordered dark to light inside each colour ramp.', {
    colors: { type: 'array', items: { type: 'string' }, maxItems: 256, description: 'Hex colours "#rrggbb".' },
    preset: { type: 'string' }, mode: { type: 'string', enum: ['replace', 'append'] }, remap: { type: 'boolean', description: 'rgba mode only: recolour existing pixels to the new palette by luminance rank.' }
  }, [], function (S, i) {
    var doc = S.doc, cols = [];
    if (i.preset) { var p = C.builtin(String(i.preset).toLowerCase()); if (!p) throw ToolError('unknown preset "' + i.preset + '"; known: ' + C.PALETTES.map(function (q) { return q.id; }).join(', ')); cols = cols.concat(p.colors); }
    (i.colors || []).forEach(function (h) { var c = C.parse(h); if (c === null) throw ToolError('bad colour "' + h + '"'); cols.push(c); });
    if (!cols.length) throw ToolError('give colors and/or preset');
    var out = oneOf(i.mode, 'mode', ['replace', 'append'], 'replace') === 'append' ? doc.palette.concat(cols) : cols;
    var seen = new Set(); out = out.filter(function (c) { if (seen.has(c)) return false; seen.add(c); return true; });
    if (out.length > 256) throw ToolError('palette would exceed 256 colours');
    var remap = null;
    if (i.remap && doc.mode === 'rgba') remap = C.remapByLuma(doc.palette, out);
    doc.setPalette(out, remap);
    if (S.fg === 0 || !out.length) S.fg = out[0] || 0;
    return { ok: true, count: doc.palette.length, palette: doc.palette.map(function (c, k) { return (k < CHARS.length ? CHARS[k] : '?') + ' ' + C.hex(c); }) };
  });

  function parseRLE(row, legend, name) {
    var out = [], toks = row.split(/[\s,]+/).filter(Boolean);
    toks.forEach(function (t) {
      var m = /^(\d+)x(.)$/.exec(t); if (m) { for (var k = 0; k < +m[1]; k++) out.push(m[2]); }
      else if (t.length === 1) out.push(t);
      else throw ToolError(name + ': bad run-length token "' + t + '" (use "<count>x<char>", e.g. "4x. 3xa")');
    });
    return out;
  }
  def('draw_pixels', 'Draw pixels onto a layer/frame. Four input styles (combine freely): rows (array of strings; each char is a palette index via legend, default 0-9a-zA-Z = indices 0-61; "." transparent, " " or "?" leave unchanged), rle (rows as run-length tokens like "4x. 3xa 2xb"), rects (filled rectangles), pixels ([x,y,color] triples). rows/rle start at (x,y). "." erases when the rows cover the whole canvas (or blank="erase"), otherwise it leaves existing pixels alone (blank="keep"). Pixels outside the canvas are clipped and counted.', {
    x: { type: 'integer', description: 'Left of rows/rle (default 0).' }, y: { type: 'integer', description: 'Top of rows/rle (default 0).' },
    rows: { type: 'array', items: { type: 'string' } }, rle: { type: 'array', items: { type: 'string' } },
    legend: { type: 'object', description: 'Optional char -> colour map overriding the default (value: palette index, "#hex", or null for transparent).' },
    rects: { type: 'array', items: { type: 'object', properties: { x: { type: 'integer' }, y: { type: 'integer' }, w: { type: 'integer' }, h: { type: 'integer' }, color: COLOR }, required: ['x', 'y', 'w', 'h', 'color'] } },
    pixels: { type: 'array', items: { type: 'array' }, description: '[[x, y, color], ...]' },
    blank: { type: 'string', enum: ['erase', 'keep'] }, layer: LAYER, frame: FRAME
  }, [], function (S, i) {
    var doc = S.doc, tgs = targets(S, { layer: i.layer, frame: i.frame }), stats = { n: 0, clipped: 0 }, x0 = int(i.x, 'x', -4096, 4096, 0), y0 = int(i.y, 'y', -4096, 4096, 0);
    if (!i.rows && !i.rle && !i.rects && !i.pixels) throw ToolError('nothing to draw: give rows, rle, rects or pixels');
    var legend = {}; var lg = i.legend || {}; Object.keys(lg).forEach(function (k) { if (k.length !== 1) throw ToolError('legend keys must be single characters'); legend[k] = colorValue(S, lg[k], 'legend ' + k); });
    function charValue(ch) {
      if (Object.prototype.hasOwnProperty.call(legend, ch)) return legend[ch];
      if (ch === '.') return 0;
      var k = CHARS.indexOf(ch); if (k < 0) throw ToolError('unknown legend character "' + ch + '"');
      if (k >= doc.palette.length) throw ToolError('character "' + ch + '" means palette index ' + k + ' but the palette only has ' + doc.palette.length + ' colours');
      return doc.rgbaToValue(doc.palette[k]);
    }
    var grid = []; (i.rows || []).forEach(function (r) { if (typeof r !== 'string') throw ToolError('rows must be strings'); grid.push(r.split('')); });
    (i.rle || []).forEach(function (r) { if (typeof r !== 'string') throw ToolError('rle rows must be strings'); grid.push(parseRLE(r, legend, 'rle')); });
    var maxw = grid.reduce(function (m, r) { return Math.max(m, r.length); }, 0);
    var covers = x0 <= 0 && y0 <= 0 && maxw + x0 >= doc.w && grid.length + y0 >= doc.h;
    var blank = oneOf(i.blank, 'blank', ['erase', 'keep'], covers ? 'erase' : 'keep');
    if (grid.length * maxw > 262144) throw ToolError('too many pixels in one call (max 262144)');
    tgs.forEach(function (t) {
      var buf = writable(S, t.li, t.fi), w = doc.w, h = doc.h;
      grid.forEach(function (row, ry) {
        row.forEach(function (ch, rx) {
          if (ch === ' ' || ch === '?') return;
          if (ch === '.' && blank === 'keep' && !Object.prototype.hasOwnProperty.call(legend, '.')) return;
          var x = x0 + rx, y = y0 + ry;
          if (x < 0 || y < 0 || x >= w || y >= h) { stats.clipped++; return; }
          buf[y * w + x] = charValue(ch); stats.n++;
        });
      });
      (i.rects || []).forEach(function (r) {
        var v = colorValue(S, r.color, 'rect color'), put = makePut(S, buf, v, stats);
        D.rect(int(r.x, 'rect.x', -4096, 4096), int(r.y, 'rect.y', -4096, 4096), int(r.x, 'rect.x', -4096, 4096) + int(r.w, 'rect.w', 1, 4096) - 1, int(r.y, 'rect.y', -4096, 4096) + int(r.h, 'rect.h', 1, 4096) - 1, function (x, y) { put(x, y); }, true);
      });
      (i.pixels || []).forEach(function (p) {
        if (!Array.isArray(p) || p.length < 3) throw ToolError('pixels entries must be [x, y, color]');
        makePut(S, buf, colorValue(S, p[2], 'pixel color'), stats)(int(p[0], 'pixel x', -4096, 4096), int(p[1], 'pixel y', -4096, 4096));
      });
    });
    return asciiMaybe(S, { ok: true, pixels_written: stats.n / Math.max(1, tgs.length) | 0, clipped: stats.clipped });
  });

  def('draw_shape', 'Draw a line, rectangle, ellipse (inscribed in the box), polygon or polyline with a palette colour. Coordinates are inclusive pixel coordinates. fill=true fills rectangles/ellipses/polygons. thickness>1 uses a square brush (line only).', {
    shape: { type: 'string', enum: ['line', 'rect', 'ellipse', 'polygon', 'polyline'] }, x0: { type: 'integer' }, y0: { type: 'integer' }, x1: { type: 'integer' }, y1: { type: 'integer' },
    points: { type: 'array', items: { type: 'array', items: { type: 'integer' } }, description: 'For polygon/polyline: [[x,y],...]' },
    color: COLOR, fill: { type: 'boolean' }, thickness: { type: 'integer', minimum: 1, maximum: 16 }, layer: LAYER, frame: FRAME
  }, ['shape', 'color'], function (S, i) {
    var shape = oneOf(i.shape, 'shape', ['line', 'rect', 'ellipse', 'polygon', 'polyline']), v = colorValue(S, i.color), th = int(i.thickness, 'thickness', 1, 16, 1);
    var stats = { n: 0, clipped: 0 };
    targets(S, { layer: i.layer, frame: i.frame }).forEach(function (t) {
      var buf = writable(S, t.li, t.fi), put = makePut(S, buf, v, stats), brush = D.brushOffsets(th, 'square');
      var bput = th > 1 ? function (x, y) { brush.forEach(function (o) { put(x + o[0], y + o[1]); }); } : put;
      if (shape === 'polygon' || shape === 'polyline') {
        var pts = i.points; if (!Array.isArray(pts) || pts.length < 2) throw ToolError('points needs at least 2 [x,y] pairs');
        pts = pts.map(function (p) { return [int(p[0], 'point x', -4096, 4096), int(p[1], 'point y', -4096, 4096)]; });
        if (shape === 'polygon' && i.fill) D.polygonFill(pts, put); else D.polyline(pts, bput, shape === 'polygon');
      } else {
        var a = int(i.x0, 'x0', -4096, 4096), b = int(i.y0, 'y0', -4096, 4096), c = int(i.x1, 'x1', -4096, 4096), d = int(i.y1, 'y1', -4096, 4096);
        if (shape === 'line') D.line(a, b, c, d, bput);
        else if (shape === 'rect') D.rect(a, b, c, d, th > 1 && !i.fill ? bput : put, !!i.fill);
        else D.ellipse(a, b, c, d, put, !!i.fill);
      }
    });
    return asciiMaybe(S, { ok: true });
  });

  def('fill_region', 'Flood fill (paint bucket) from a point. tolerance 0-255 widens what counts as the same colour; contiguous=false recolours every matching pixel on the layer.', {
    x: { type: 'integer' }, y: { type: 'integer' }, color: COLOR, tolerance: { type: 'integer', minimum: 0, maximum: 255 }, contiguous: { type: 'boolean' }, layer: LAYER, frame: FRAME
  }, ['x', 'y', 'color'], function (S, i) {
    var doc = S.doc, x = int(i.x, 'x', 0, doc.w - 1), y = int(i.y, 'y', 0, doc.h - 1), v = colorValue(S, i.color), n = 0;
    targets(S, { layer: i.layer, frame: i.frame }).forEach(function (t) {
      var buf = writable(S, t.li, t.fi), m = D.floodMask(buf, doc.w, doc.h, x, y, int(i.tolerance, 'tolerance', 0, 255, 0), bool(i.contiguous, true), function (p) { return doc.valueToRGBA(p); });
      n += D.applyMask(buf, m, v, null);
    });
    return asciiMaybe(S, { ok: true, pixels_changed: n });
  });

  def('new_layer', 'Add a transparent layer above the current one (or at index) and make it current. Use separate layers for outline, shading, props, so edits stay independent.', {
    name: { type: 'string' }, index: { type: 'integer' }, opacity: { type: 'integer', minimum: 0, maximum: 255 }, blend: { type: 'string', enum: M.BLEND_MODES }
  }, [], function (S, i) {
    var doc = S.doc, l = doc.addLayer(i.name, i.index === undefined ? S.li + 1 : int(i.index, 'index', 0, doc.layers.length));
    if (i.opacity !== undefined || i.blend) doc.setLayer(l.id, { opacity: i.opacity, blend: i.blend });
    S.li = doc.layerIndex(l.id);
    return { ok: true, layer_index: S.li, name: l.name };
  });
  def('new_frame', 'Insert a frame (blank, or a copy of copy_from) at index (default: end) and make it current.', {
    index: { type: 'integer' }, copy_from: { type: 'integer' }, duration_ms: { type: 'integer', minimum: 10, maximum: 60000 }
  }, [], function (S, i) {
    var doc = S.doc, cf = i.copy_from === undefined ? undefined : int(i.copy_from, 'copy_from', 0, doc.frames.length - 1);
    var at = i.index === undefined ? doc.frames.length : int(i.index, 'index', 0, doc.frames.length), f = doc.addFrame(at, cf);
    if (i.duration_ms) doc.setDuration(doc.frameIndex(f.id), i.duration_ms);
    S.fi = doc.frameIndex(f.id);
    return asciiMaybe(S, { ok: true, frame_index: S.fi, frame_count: doc.frames.length });
  });
  def('delete_frame', 'Delete a frame (and its pixels on every layer). The sprite always keeps at least one frame.', { index: { type: 'integer' } }, ['index'], function (S, i) { S.doc.removeFrame(int(i.index, 'index', 0, S.doc.frames.length - 1)); return { ok: true, frame_count: S.doc.frames.length }; });
  def('delete_layer', 'Delete a layer by name or index, with all its frames. The sprite always keeps at least one layer.', { layer: LAYER }, ['layer'], function (S, i) { var li = layerIndex(S, i.layer); S.doc.removeLayer(S.doc.layers[li].id); return { ok: true, layer_count: S.doc.layers.length }; });
  def('select', 'Make a frame and/or layer current for later tools.', { frame: { type: 'integer' }, layer: LAYER }, [], function (S, i) {
    if (i.frame !== undefined) S.fi = frameIndex(S, i.frame); if (i.layer !== undefined) S.li = layerIndex(S, i.layer);
    return { ok: true, current_frame: S.fi, current_layer: S.li };
  });
  def('layer_properties', 'Rename a layer or change visibility, opacity (0-255), blend mode or lock.', {
    layer: LAYER, name: { type: 'string' }, visible: { type: 'boolean' }, opacity: { type: 'integer', minimum: 0, maximum: 255 }, blend: { type: 'string', enum: M.BLEND_MODES }, locked: { type: 'boolean' }
  }, [], function (S, i) { var li = layerIndex(S, i.layer); S.doc.setLayer(S.doc.layers[li].id, i); return { ok: true }; });
  def('set_frame_duration', 'Set how long frames are shown, in milliseconds.', { frame: FRAME, duration_ms: { type: 'integer', minimum: 10, maximum: 60000 } }, ['duration_ms'], function (S, i) {
    var ms = int(i.duration_ms, 'duration_ms', 10, 60000); targets(S, { layer: 0, frame: i.frame }).forEach(function (t) { S.doc.setDuration(t.fi, ms); }); return { ok: true };
  });
  def('set_tag', 'Create/replace an animation tag (a named frame range such as "idle" or "walk"). Tags become animation names in sprite sheet / Godot exports.', {
    name: { type: 'string' }, from: { type: 'integer' }, to: { type: 'integer' }, direction: { type: 'string', enum: ['forward', 'reverse', 'pingpong', 'pingpong_reverse'] }, repeat: { type: 'integer', description: '0 = loop forever' }
  }, ['name', 'from', 'to'], function (S, i) {
    var n = S.doc.frames.length; S.doc.setTag({ name: i.name, from: int(i.from, 'from', 0, n - 1), to: int(i.to, 'to', 0, n - 1), dir: i.direction, repeat: i.repeat }); return { ok: true, tags: S.doc.tags.map(function (t) { return t.name + ' ' + t.from + '-' + t.to; }) };
  });

  function transformCel(S, t, fn, rgn) { // fn(sub, w, h) -> Uint32Array same size
    var doc = S.doc, buf = writable(S, t.li, t.fi), r = region(S, rgn);
    if (!rgn) { var o = fn(buf, doc.w, doc.h); buf.set(o); return; }
    var sub = getRegion(buf, doc.w, r), o2 = fn(sub, r.w, r.h); putRegion(buf, doc.w, r, o2);
  }
  def('copy_frame_with_transform', 'Duplicate a frame and transform the copy: shift (dx,dy), flip, rotate, optionally only inside a region/layers. Ideal for animation: copy then nudge to build bobbing/idle cycles; for walk cycles copy then redraw legs with draw_pixels. The new frame is inserted after the source (or at insert_at) and becomes current.', {
    source: { type: 'integer', description: 'Frame to copy (default current).' }, insert_at: { type: 'integer' },
    dx: { type: 'integer' }, dy: { type: 'integer' }, wrap: { type: 'boolean' }, flip: { type: 'string', enum: ['horizontal', 'vertical', 'none'] }, rotate_degrees: { type: 'number' },
    region: REGION, layer: LAYER, duration_ms: { type: 'integer', minimum: 10, maximum: 60000 }
  }, [], function (S, i) {
    var doc = S.doc, src = i.source === undefined ? S.fi : int(i.source, 'source', 0, doc.frames.length - 1), at = i.insert_at === undefined ? src + 1 : int(i.insert_at, 'insert_at', 0, doc.frames.length);
    var f = doc.addFrame(at, src), nfi = doc.frameIndex(f.id);
    if (i.duration_ms) doc.setDuration(nfi, i.duration_ms);
    var ls = i.layer === undefined || i.layer === 'all' ? doc.layers.map(function (l, k) { return k; }) : [layerIndex(S, i.layer)];
    var dx = int(i.dx, 'dx', -512, 512, 0), dy = int(i.dy, 'dy', -512, 512, 0), flip = i.flip || 'none', rot = num(i.rotate_degrees, 'rotate_degrees', -360, 360, 0);
    ls.forEach(function (li) {
      if (doc.layers[li].locked) return;
      var t = { li: li, fi: nfi }; if (!doc.celAt(li, nfi)) return;
      transformCel(S, t, function (b, w, h) {
        var o = b;
        if (flip === 'horizontal') o = D.flipH(o, w, h); else if (flip === 'vertical') o = D.flipV(o, w, h);
        if (rot) o = D.rotateSmart(o, w, h, rot);
        if (dx || dy) o = D.shift(o, w, h, dx, dy, !!i.wrap);
        return o;
      }, i.region);
    });
    S.fi = nfi;
    return asciiMaybe(S, { ok: true, frame_index: nfi, frame_count: doc.frames.length });
  });
  def('shift', 'Move pixels by (dx,dy) on a layer/frame (optionally inside a region, optionally wrapping around the edges).', { dx: { type: 'integer' }, dy: { type: 'integer' }, wrap: { type: 'boolean' }, region: REGION, layer: LAYER, frame: FRAME }, [], function (S, i) {
    var dx = int(i.dx, 'dx', -512, 512, 0), dy = int(i.dy, 'dy', -512, 512, 0);
    targets(S, i).forEach(function (t) { transformCel(S, t, function (b, w, h) { return D.shift(b, w, h, dx, dy, !!i.wrap); }, i.region); });
    return asciiMaybe(S, { ok: true });
  });
  def('rotate', 'Rotate pixels about the centre of the canvas/region. smart=true (default) uses a rotsprite-like algorithm that keeps pixel art crisp; multiples of 90 degrees are exact.', { degrees: { type: 'number' }, smart: { type: 'boolean' }, region: REGION, layer: LAYER, frame: FRAME }, ['degrees'], function (S, i) {
    var deg = num(i.degrees, 'degrees', -360, 360, 0), smart = bool(i.smart, true);
    targets(S, i).forEach(function (t) {
      transformCel(S, t, function (b, w, h) {
        if (deg % 90 === 0 && w === h) return D.rotate90(b, w, h, deg / 90).data;
        return smart ? D.rotateSmart(b, w, h, deg) : D.rotateNearest(b, w, h, deg);
      }, i.region);
    });
    return asciiMaybe(S, { ok: true });
  });
  def('mirror', 'Mirror the drawing. mode "flip" flips the image; "copy_left_to_right" / "copy_right_to_left" / "copy_top_to_bottom" / "copy_bottom_to_top" makes the picture symmetric (draw one half, then mirror it).', {
    mode: { type: 'string', enum: ['flip_horizontal', 'flip_vertical', 'copy_left_to_right', 'copy_right_to_left', 'copy_top_to_bottom', 'copy_bottom_to_top'] }, region: REGION, layer: LAYER, frame: FRAME
  }, ['mode'], function (S, i) {
    var mode = oneOf(i.mode, 'mode', ['flip_horizontal', 'flip_vertical', 'copy_left_to_right', 'copy_right_to_left', 'copy_top_to_bottom', 'copy_bottom_to_top']);
    targets(S, i).forEach(function (t) {
      transformCel(S, t, function (b, w, h) {
        if (mode === 'flip_horizontal') return D.flipH(b, w, h);
        if (mode === 'flip_vertical') return D.flipV(b, w, h);
        var o = b.slice(), x, y;
        if (mode.indexOf('left') >= 0 || mode.indexOf('right') >= 0) {
          for (y = 0; y < h; y++) for (x = 0; x < Math.floor(w / 2); x++) { if (mode === 'copy_left_to_right') o[y * w + w - 1 - x] = b[y * w + x]; else o[y * w + x] = b[y * w + w - 1 - x]; }
        } else for (y = 0; y < Math.floor(h / 2); y++) for (x = 0; x < w; x++) { if (mode === 'copy_top_to_bottom') o[(h - 1 - y) * w + x] = b[y * w + x]; else o[y * w + x] = b[(h - 1 - y) * w + x]; }
        return o;
      }, i.region);
    });
    return asciiMaybe(S, { ok: true });
  });

  def('recolor', 'Recolour. (a) pairs: replace colour A by B (palette index or hex, with tolerance). (b) palette/preset: switch to a new palette, mapping old colours to new ones by brightness order so shading is preserved ("make it a fire palette"). (c) hue_shift (degrees), saturation and lightness (-1..1) adjustments of the palette colours/pixels. scope: "sprite" (default, all layers and frames), "layer" or "frame" (current only).', {
    pairs: { type: 'array', items: { type: 'object', properties: { from: COLOR, to: COLOR, tolerance: { type: 'integer', minimum: 0, maximum: 255 } }, required: ['from', 'to'] } },
    colors: { type: 'array', items: { type: 'string' } }, preset: { type: 'string' },
    hue_shift: { type: 'number' }, saturation: { type: 'number', minimum: -1, maximum: 1 }, lightness: { type: 'number', minimum: -1, maximum: 1 },
    scope: { type: 'string', enum: ['sprite', 'layer', 'frame'] }
  }, [], function (S, i) {
    var doc = S.doc, scope = oneOf(i.scope, 'scope', ['sprite', 'layer', 'frame'], 'sprite'), changed = 0, keys = [];
    doc.layers.forEach(function (l, li) { doc.frames.forEach(function (f, fi) {
      if (scope === 'layer' && li !== S.li) return; if (scope === 'frame' && fi !== S.fi) return;
      if (l.locked || !doc.cel(l.id, f.id)) return; keys.push([l.id, f.id]);
    }); });
    if (i.pairs) i.pairs.forEach(function (p) {
      var from = colorValue(S, p.from, 'from'), to = colorValue(S, p.to, 'to'), tol = int(p.tolerance, 'tolerance', 0, 255, 0);
      keys.forEach(function (k) { changed += D.replaceColor(doc.cw(k[0], k[1]), from, to, tol, function (v) { return doc.valueToRGBA(v); }); });
    });
    var newPal = null;
    if (i.preset || (i.colors && i.colors.length)) {
      newPal = [];
      if (i.preset) { var pr = C.builtin(String(i.preset).toLowerCase()); if (!pr) throw ToolError('unknown preset "' + i.preset + '"'); newPal = newPal.concat(pr.colors); }
      (i.colors || []).forEach(function (h) { var c = C.parse(h); if (c === null) throw ToolError('bad colour "' + h + '"'); newPal.push(c); });
    }
    var adjust = i.hue_shift || i.saturation || i.lightness;
    function adj(c) { var hsl = C.toHSL(c); return C.fromHSL(hsl[0] + (i.hue_shift || 0), Math.max(0, Math.min(1, hsl[1] * (1 + (i.saturation || 0)))), Math.max(0, Math.min(1, hsl[2] + (i.lightness || 0) * 0.5)), C.unpack(c)[3]); }
    if (doc.mode === 'indexed') {
      if (newPal || adjust) {
        var cur = doc.palette; var target;
        if (newPal) { var m = C.remapByLuma(cur, newPal); target = cur.map(function (c, k) { return adjust ? adj(m[k]) : m[k]; }); } else target = cur.map(adj);
        if (scope === 'sprite') { doc.setPalette(target); changed += cur.length; }
        else {
          // scoped recolour in indexed mode: map the affected pixels to nearest colour of the target palette extended onto the palette
          var map = new Map(), pal2 = doc.palette.slice();
          cur.forEach(function (c, k) { var tc = target[k]; var ix = pal2.indexOf(tc); if (ix < 0) { if (pal2.length >= 256) throw ToolError('palette is full'); pal2.push(tc); ix = pal2.length - 1; } map.set(k + 1, ix + 1); });
          doc.setPalette(pal2);
          keys.forEach(function (k) { changed += D.mapValues(doc.cw(k[0], k[1]), map); });
        }
      }
    } else if (newPal || adjust) {
      var map2 = new Map(), tab = newPal ? C.remapByLuma(doc.palette, newPal) : null;
      keys.forEach(function (k) {
        var buf = doc.cw(k[0], k[1]);
        for (var p = 0; p < buf.length; p++) {
          var v = buf[p]; if (!v) continue;
          var r = map2.get(v);
          if (r === undefined) {
            var c = v; if (newPal) { var ix = doc.palette.indexOf(v); c = ix >= 0 ? tab[ix] : newPal[C.nearest(newPal, v)]; if (ix < 0) { var lo = C.luma(v); c = newPal.slice().sort(function (a, b) { return Math.abs(C.luma(a) - lo) - Math.abs(C.luma(b) - lo); })[0]; } }
            if (adjust) c = adj(c); r = c; map2.set(v, r);
          }
          if (r !== v) { buf[p] = r; changed++; }
        }
      });
      if (newPal && scope === 'sprite') doc.setPalette(newPal);
    }
    return asciiMaybe(S, { ok: true, pixels_or_colours_changed: changed });
  });

  def('outline', 'Add a 1-pixel outline around the artwork of a layer (outside by default; inside=true recolours the border pixels instead). Outline on a separate layer is cleanest: create the layer, copy art there via layer="all" is not supported, so normally outline the art layer and keep it as one layer. diagonal=true also connects corners (8-neighbour).', {
    color: COLOR, diagonal: { type: 'boolean' }, inside: { type: 'boolean' }, layer: LAYER, frame: FRAME
  }, ['color'], function (S, i) {
    var doc = S.doc, v = colorValue(S, i.color), n = 0;
    targets(S, i).forEach(function (t) { var buf = writable(S, t.li, t.fi), r = D.outline(buf, doc.w, doc.h, v, { diagonal: !!i.diagonal, inside: !!i.inside }); buf.set(r.data); n += r.changed; });
    return asciiMaybe(S, { ok: true, pixels_added: n });
  });
  def('drop_shadow', 'Add a hard drop shadow (offset copy of the silhouette drawn behind the art) to a layer.', { color: COLOR, dx: { type: 'integer' }, dy: { type: 'integer' }, layer: LAYER, frame: FRAME }, ['color'], function (S, i) {
    var doc = S.doc, v = colorValue(S, i.color), dx = int(i.dx, 'dx', -16, 16, 1), dy = int(i.dy, 'dy', -16, 16, 1), n = 0;
    targets(S, i).forEach(function (t) { var buf = writable(S, t.li, t.fi), r = D.dropShadow(buf, doc.w, doc.h, v, dx, dy); buf.set(r.data); n += r.changed; });
    return asciiMaybe(S, { ok: true, pixels_added: n });
  });
  def('shade_by_light_direction', 'Automatic first-pass shading: pixels on the lit edges (facing the light) get the next lighter palette colour and pixels on the opposite edges get the next darker one, depth pixels deep. Pass ramps (lists of palette indices dark->light) to control exactly which colours are used; otherwise the nearest lighter/darker palette colour is chosen. Follow up with manual draw_pixels for highlights and clean-up.', {
    direction: { type: 'string', enum: ['n', 'ne', 'e', 'se', 's', 'sw', 'w', 'nw'], description: 'Direction the light comes FROM, e.g. "nw" = top-left light.' },
    depth: { type: 'integer', minimum: 1, maximum: 4 }, ramps: { type: 'array', items: { type: 'array', items: { type: 'integer' } } }, layer: LAYER, frame: FRAME
  }, ['direction'], function (S, i) {
    var doc = S.doc, dir = oneOf(i.direction, 'direction', Object.keys(D.LIGHT_DIRS)), n = 0, up, down;
    if (i.ramps && i.ramps.length) { up = rampShifter(S, i.ramps, 1); down = rampShifter(S, i.ramps, -1); } else { up = toneShifter(S, 1); down = toneShifter(S, -1); }
    targets(S, i).forEach(function (t) { var buf = writable(S, t.li, t.fi), r = D.shadeByLight(buf, doc.w, doc.h, dir, up, down, { depth: int(i.depth, 'depth', 1, 4, 1), clip: S.sel }); buf.set(r.data); n += r.changed; });
    return asciiMaybe(S, { ok: true, pixels_shaded: n });
  });
  def('clear', 'Erase a layer/frame (or a region of it).', { region: REGION, layer: LAYER, frame: FRAME }, [], function (S, i) {
    targets(S, i).forEach(function (t) { var buf = writable(S, t.li, t.fi), r = region(S, i.region); for (var y = 0; y < r.h; y++) for (var x = 0; x < r.w; x++) buf[(r.y + y) * S.doc.w + r.x + x] = 0; });
    return asciiMaybe(S, { ok: true });
  });

  def('view_canvas', 'Return an image of the sprite so you can SEE it: the composited frame, upscaled with nearest-neighbour, with a dashed grid every 8 px and coordinate rulers (pixel numbers). Use after every few drawing steps to check proportions and colours. all_frames=true returns a contact sheet of the whole animation.', {
    frame: { type: 'integer' }, scale: { type: 'integer', minimum: 1, maximum: 32 }, grid: { type: 'integer', minimum: 0, maximum: 64, description: '0 disables the grid.' }, rulers: { type: 'boolean' }, all_frames: { type: 'boolean' }
  }, [], function (S, i) {
    var o = { frame: i.frame === undefined ? undefined : int(i.frame, 'frame', 0, S.doc.frames.length - 1), scale: i.scale, grid: i.grid, rulers: i.rulers, all_frames: i.all_frames };
    var im = viewResult(S, o);
    return { text: 'Frame ' + (o.frame === undefined ? S.fi : o.frame) + ' of ' + S.doc.frames.length + ', ' + S.doc.w + 'x' + S.doc.h + ' px, shown at ' + im.scale + 'x (grid lines every 8 px, rulers give pixel coordinates).', image: { mime: 'image/png', base64: PNG.toBase64(PNG.encode(im.width, im.height, im.rgba)) } };
  }, { readonly: true });

  def('undo', 'Undo the last editing step (use when a change went wrong).', { steps: { type: 'integer', minimum: 1, maximum: 20 } }, [], function (S, i) {
    var n = int(i.steps, 'steps', 1, 20, 1), done = 0; while (n-- > 0 && S.doc.canUndo()) { S.doc.undo(); done++; }
    return asciiMaybe(S, { ok: true, undone: done });
  });

  // ------------------------------------------------------------------ export
  function checkRel(p) {
    if (typeof p !== 'string' || !p) throw ToolError('path is required');
    if (p[0] === '/' || /^[A-Za-z]:/.test(p) || p.split(/[\\/]/).indexOf('..') >= 0 || p.indexOf('\0') >= 0) { var e = ToolError('path must be relative to the project folder and not contain ..', -32003); throw e; }
    return p.replace(/\\/g, '/');
  }
  function swapExt(p, ext) { var k = p.lastIndexOf('.'), s = p.lastIndexOf('/'); return (k > s ? p.slice(0, k) : p) + ext; }
  function baseName(p) { return p.slice(p.lastIndexOf('/') + 1); }
  /** build export artefacts without touching disk: returns [{path, data(Uint8Array|string), kind}] */
  function buildExport(S, o) {
    var doc = S.doc, fmt = oneOf(o.format, 'format', ['png', 'gif', 'apng', 'sheet', 'frames'], 'png'), path = checkRel(o.path !== undefined ? o.path : (X.safeName(doc.name) + '.' + (fmt === 'sheet' ? 'png' : fmt === 'frames' ? 'png' : fmt))), scale = int(o.scale, 'scale', 1, 32, 1), files = [];
    var frameSel = o.tag ? 'tag:' + o.tag : (o.frames || undefined);
    if (fmt === 'png') {
      var fi = o.frame === undefined ? S.fi : int(o.frame, 'frame', 0, doc.frames.length - 1), rgba = X.scaleRGBA(doc.composite(fi), doc.w, doc.h, scale);
      files.push({ path: path, kind: 'png', data: PNG.encode(doc.w * scale, doc.h * scale, new Uint8Array(rgba.buffer, rgba.byteOffset, rgba.length)) });
    } else if (fmt === 'gif' || fmt === 'apng') {
      var fr = X.animationFrames(doc, { scale: scale, frames: frameSel }), W = doc.w * scale, H = doc.h * scale;
      var loop = o.loop === undefined ? 0 : int(o.loop, 'loop', 0, 65535);
      files.push({ path: path, kind: fmt, data: fmt === 'gif' ? GIF.encode({ width: W, height: H, frames: fr.map(function (f) { return { rgba: f.rgba, delay: f.delay }; }), loop: loop }) : PNG.encodeAPNG(W, H, fr.map(function (f) { return { rgba: new Uint8Array(f.rgba.buffer, f.rgba.byteOffset, f.rgba.length), delay: f.delay }; }), loop) });
    } else if (fmt === 'frames') {
      X.animationFrames(doc, { scale: scale, frames: frameSel }).forEach(function (f) {
        files.push({ path: swapExt(path, '') + '_' + String(f.index).padStart(3, '0') + '.png', kind: 'png', data: PNG.encode(doc.w * scale, doc.h * scale, new Uint8Array(f.rgba.buffer, f.rgba.byteOffset, f.rgba.length)) });
      });
    } else {
      var sheet = X.buildSheet(doc, { scale: scale, frames: frameSel, trim: !!o.trim, layout: oneOf(o.layout, 'layout', ['horizontal', 'vertical', 'grid', 'packed'], 'horizontal'), columns: o.columns, padding: o.padding, spacing: o.spacing, innerPadding: o.inner_padding,
        name: o.name || baseName(swapExt(path, '')), image: baseName(path), godotPath: o.godot_path });
      files.push({ path: path, kind: 'png', data: PNG.encode(sheet.width, sheet.height, new Uint8Array(sheet.rgba.buffer, sheet.rgba.byteOffset, sheet.rgba.length)) });
      files.push({ path: swapExt(path, '.json'), kind: 'json', data: sheet.jsonText });
      files.push({ path: swapExt(path, '.tres'), kind: 'tres', data: sheet.tres });
      files.push({ path: swapExt(path, '.atlas.gd'), kind: 'gd', data: sheet.atlas });
    }
    return files;
  }
  def('export', 'Export into the project folder (~/Studio/Sprite): png (one frame), gif / apng (animation; tag="walk" for one tag), sheet (spritesheet PNG + Aseprite-compatible JSON + Godot SpriteFrames .tres + AtlasTexture .gd), frames (one PNG per frame). path is relative, never absolute and without "..". scale 1-32 is an integer upscale. Sheet options: layout, columns, trim, padding, spacing, inner_padding, godot_path (e.g. res://sprites/).', {
    format: { type: 'string', enum: ['png', 'gif', 'apng', 'sheet', 'frames'] }, path: { type: 'string' }, scale: { type: 'integer', minimum: 1, maximum: 32 }, frame: { type: 'integer' }, tag: { type: 'string' },
    layout: { type: 'string', enum: ['horizontal', 'vertical', 'grid', 'packed'] }, columns: { type: 'integer' }, trim: { type: 'boolean' }, padding: { type: 'integer' }, spacing: { type: 'integer' }, inner_padding: { type: 'integer' }, godot_path: { type: 'string' }, loop: { type: 'integer' }
  }, ['format', 'path'], function (S, i, io) {
    var files = buildExport(S, i);
    if (!io || !io.write) throw ToolError('file writing is not available here', -32004);
    return Promise.all(files.map(function (f) { return io.write(f.path, f.data); })).then(function (res) {
      return { ok: true, files: files.map(function (f, k) { return { path: (res[k] && res[k].path) || f.path, bytes: f.data.length }; }) };
    });
  });

  var order = Object.keys(T);
  function definitions() { return order.map(function (n) { return T[n].def; }); }
  /** run a tool by name; returns a Promise of result object. Tool errors reject with Error (message safe to show the model). */
  function run(S, name, input, io) {
    var t = T[name]; if (!t) { var e = new Error('unknown tool ' + name); e.code = -32601; return Promise.reject(e); }
    input = input || {};
    try {
      var res = t.readonly ? t.run(S, input, io) : S.doc.edit('AI: ' + name, function () { return t.run(S, input, io); });
      return Promise.resolve(res);
    } catch (e) { return Promise.reject(e); }
  }
  return { definitions: definitions, run: run, info: info, ascii: ascii, renderView: renderView, viewResult: viewResult, buildExport: buildExport, checkRel: checkRel, CHARS: CHARS, ToolError: ToolError, TOOLS: T };
});
