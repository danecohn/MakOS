/* Sprite: pixel drawing primitives, fills, masks, dithering and image transforms. Original code.
   Buffers are Uint32Array(w*h) of pixel values (see model.js). Shapes call put(x,y) per pixel (caller clips). */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(function (n) { return require('./' + n + '.js'); });
  else { root.AS = root.AS || {}; root.AS.draw = factory(function (n) { return root.AS[n]; }); }
})(typeof window !== 'undefined' ? window : globalThis, function (dep) {
  'use strict';
  var C = dep('color');

  // ---------------------------------------------------------------- shapes (callbacks)
  function line(x0, y0, x1, y1, put) {
    x0 |= 0; y0 |= 0; x1 |= 0; y1 |= 0;
    var dx = Math.abs(x1 - x0), dy = -Math.abs(y1 - y0), sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1, err = dx + dy;
    for (;;) {
      put(x0, y0);
      if (x0 === x1 && y0 === y1) break;
      var e2 = 2 * err;
      if (e2 >= dy) { err += dy; x0 += sx; }
      if (e2 <= dx) { err += dx; y0 += sy; }
    }
  }
  function linePoints(x0, y0, x1, y1) { var p = []; line(x0, y0, x1, y1, function (x, y) { p.push([x, y]); }); return p; }
  function rect(x0, y0, x1, y1, put, fill) {
    var a = Math.min(x0, x1), b = Math.max(x0, x1), c = Math.min(y0, y1), d = Math.max(y0, y1), x, y;
    if (fill) { for (y = c; y <= d; y++) for (x = a; x <= b; x++) put(x, y); return; }
    for (x = a; x <= b; x++) { put(x, c); if (d !== c) put(x, d); }
    for (y = c + 1; y < d; y++) { put(a, y); if (b !== a) put(b, y); }
  }
  /** ellipse inscribed in the bounding box (inclusive pixel coordinates) */
  function ellipse(x0, y0, x1, y1, put, fill) {
    var a = Math.abs(x1 - x0), b = Math.abs(y1 - y0), b1 = b & 1;
    var dx = 4 * (1 - a) * b * b, dy = 4 * (b1 + 1) * a * a, err = dx + dy + b1 * a * a, e2;
    if (x0 > x1) { x0 = x1; x1 += a; }
    if (y0 > y1) y0 = y1;
    y0 += (b + 1) >> 1; y1 = y0 - b1; a *= 8 * a; b1 = 8 * b * b;
    var rows = fill ? new Map() : null;
    function pl(x, y) { if (rows) { var r = rows.get(y); if (!r) rows.set(y, [x, x]); else { if (x < r[0]) r[0] = x; if (x > r[1]) r[1] = x; } } else put(x, y); }
    do {
      pl(x1, y0); pl(x0, y0); pl(x0, y1); pl(x1, y1);
      e2 = 2 * err;
      if (e2 <= dy) { y0++; y1--; err += dy += a; }
      if (e2 >= dx || 2 * err > dy) { x0++; x1--; err += dx += b1; }
    } while (x0 <= x1);
    while (y0 - y1 < b) { pl(x0 - 1, y0); pl(x1 + 1, y0++); pl(x0 - 1, y1); pl(x1 + 1, y1--); }
    if (rows) rows.forEach(function (r, y) { for (var x = r[0]; x <= r[1]; x++) put(x, y); });
  }
  function polyline(pts, put, closed) {
    for (var i = 0; i + 1 < pts.length; i++) line(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], put);
    if (closed && pts.length > 2) line(pts[pts.length - 1][0], pts[pts.length - 1][1], pts[0][0], pts[0][1], put);
    else if (pts.length === 1) put(pts[0][0], pts[0][1]);
  }
  function polygonFill(pts, put) { // even-odd rule sampled at pixel centres, edges included via outline
    if (pts.length < 3) { polyline(pts, put, false); return; }
    var minY = Infinity, maxY = -Infinity, i;
    pts.forEach(function (p) { minY = Math.min(minY, p[1]); maxY = Math.max(maxY, p[1]); });
    for (var y = minY; y <= maxY; y++) {
      var xs = [], cy = y + 0.5;
      for (i = 0; i < pts.length; i++) {
        var a = pts[i], b = pts[(i + 1) % pts.length];
        if ((a[1] + 0.5 <= cy && b[1] + 0.5 > cy) || (b[1] + 0.5 <= cy && a[1] + 0.5 > cy)) xs.push(a[0] + (cy - a[1] - 0.5) * (b[0] - a[0]) / (b[1] - a[1]));
      }
      xs.sort(function (p, q) { return p - q; });
      for (i = 0; i + 1 < xs.length; i += 2) for (var x = Math.round(xs[i]); x <= Math.round(xs[i + 1]); x++) put(x, y);
    }
    polyline(pts, put, true);
  }
  /** remove L-shaped corner pixels from a 1px stroke (pixel-perfect) */
  function pixelPerfect(pts) {
    if (pts.length < 3) return pts.slice();
    var out = [pts[0]];
    for (var i = 1; i < pts.length; i++) {
      var p = out[out.length - 1], c = pts[i], n = pts[i + 1];
      if (n && (p[0] === c[0] || p[1] === c[1]) && (n[0] === c[0] || n[1] === c[1]) && p[0] !== n[0] && p[1] !== n[1] && (Math.abs(p[0] - c[0]) + Math.abs(p[1] - c[1]) === 1) && (Math.abs(n[0] - c[0]) + Math.abs(n[1] - c[1]) === 1)) continue;
      out.push(c);
    }
    return out;
  }
  /** brush footprint offsets for a size (1..64) */
  function brushOffsets(size, shape) {
    size = Math.max(1, size | 0); var o = [], r = size / 2, c = (size - 1) / 2, x, y;
    for (y = 0; y < size; y++) for (x = 0; x < size; x++) {
      if (shape === 'circle' && size > 2) { var dx = x - c, dy = y - c; if (dx * dx + dy * dy > r * r - (size % 2 ? 0.25 : 0.5) + 0.2) continue; }
      o.push([x - Math.floor((size - 1) / 2), y - Math.floor((size - 1) / 2)]);
    }
    return o;
  }

  // ---------------------------------------------------------------- masks
  function newMask(w, h) { return new Uint8Array(w * h); }
  function rectMask(w, h, x0, y0, x1, y1) {
    var m = newMask(w, h), a = Math.max(0, Math.min(x0, x1)), b = Math.min(w - 1, Math.max(x0, x1)), c = Math.max(0, Math.min(y0, y1)), d = Math.min(h - 1, Math.max(y0, y1));
    for (var y = c; y <= d; y++) for (var x = a; x <= b; x++) m[y * w + x] = 1;
    return m;
  }
  function polyMask(w, h, pts) {
    var m = newMask(w, h);
    polygonFill(pts, function (x, y) { if (x >= 0 && y >= 0 && x < w && y < h) m[y * w + x] = 1; });
    return m;
  }
  function maskBounds(m, w, h) {
    var x0 = w, y0 = h, x1 = -1, y1 = -1;
    for (var y = 0; y < h; y++) for (var x = 0; x < w; x++) if (m[y * w + x]) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
    return x1 < 0 ? null : { x: x0, y: y0, w: x1 - x0 + 1, h: y1 - y0 + 1 };
  }
  function maskCombine(a, b, op) { // op: 'add' | 'sub' | 'and' | 'replace'
    if (!a || op === 'replace') return b;
    var o = new Uint8Array(a.length);
    for (var i = 0; i < a.length; i++) o[i] = op === 'add' ? (a[i] | b[i]) : op === 'sub' ? (a[i] & ~b[i] & 1) : (a[i] & b[i]);
    return o;
  }
  function maskInvert(m) { var o = new Uint8Array(m.length); for (var i = 0; i < m.length; i++) o[i] = m[i] ? 0 : 1; return o; }

  // ---------------------------------------------------------------- colour matching + flood fill
  /** matcher(v) true when pixel value v is within tolerance (0..255 per channel) of target value; toRGBA converts values */
  function makeMatcher(target, tol, toRGBA) {
    if (!tol) return function (v) { return v === target; };
    var t = toRGBA(target), cache = new Map();
    return function (v) {
      if (v === target) return true;
      var r = cache.get(v); if (r === undefined) { r = C.maxDiff(toRGBA(v), t) <= tol; cache.set(v, r); } return r;
    };
  }
  /** returns a Uint8Array mask of the matching region */
  function floodMask(buf, w, h, sx, sy, tol, contiguous, toRGBA) {
    var m = new Uint8Array(w * h);
    if (sx < 0 || sy < 0 || sx >= w || sy >= h) return m;
    var match = makeMatcher(buf[sy * w + sx], tol || 0, toRGBA || function (v) { return v; }), i;
    if (!contiguous) { for (i = 0; i < buf.length; i++) if (match(buf[i])) m[i] = 1; return m; }
    var stack = [[sx, sy]];
    while (stack.length) {
      var s = stack.pop(), x = s[0], y = s[1];
      if (m[y * w + x] || !match(buf[y * w + x])) continue;
      var l = x, r = x;
      while (l > 0 && !m[y * w + l - 1] && match(buf[y * w + l - 1])) l--;
      while (r < w - 1 && !m[y * w + r + 1] && match(buf[y * w + r + 1])) r++;
      for (var xx = l; xx <= r; xx++) m[y * w + xx] = 1;
      for (var dy = -1; dy <= 1; dy += 2) {
        var ny = y + dy; if (ny < 0 || ny >= h) continue;
        var inRun = false;
        for (xx = l; xx <= r; xx++) {
          var ok = !m[ny * w + xx] && match(buf[ny * w + xx]);
          if (ok && !inRun) stack.push([xx, ny]);
          inRun = ok;
        }
      }
    }
    return m;
  }
  function applyMask(buf, mask, value, clip) { // clip: optional selection mask
    var n = 0;
    for (var i = 0; i < buf.length; i++) if (mask[i] && (!clip || clip[i]) && buf[i] !== value) { buf[i] = value; n++; }
    return n;
  }

  // ---------------------------------------------------------------- dithering
  var BAYER2 = [[0, 2], [3, 1]];
  var BAYER4 = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]];
  var BAYER8 = (function () { var m = [[0]]; for (var k = 0; k < 3; k++) { var n = m.length, o = []; for (var y = 0; y < n * 2; y++) { o.push([]); for (var x = 0; x < n * 2; x++) { var q = m[y % n][x % n] * 4; o[y].push(q + [[0, 2], [3, 1]][Math.floor(y / n)][Math.floor(x / n)]); } } m = o; } return m; })();
  function bayer(kind) { return kind === 2 ? BAYER2 : kind === 8 ? BAYER8 : BAYER4; }
  /** threshold in 0..1 at pixel */
  function bayerAt(kind, x, y) { var m = bayer(kind), n = m.length; return (m[((y % n) + n) % n][((x % n) + n) % n] + 0.5) / (n * n); }
  /** pattern for dither brush: density 0..1 -> boolean at x,y */
  function ditherOn(pattern, x, y, density) {
    if (pattern === 'checker') return ((x + y) & 1) === 0;
    if (pattern === 'lines') return (y & 1) === 0;
    if (pattern === 'dots') return (x & 1) === 0 && (y & 1) === 0;
    return bayerAt(4, x, y) < (density === undefined ? 0.5 : density);
  }
  /** gradient dither between two values along a vector. put receives (x,y,value). */
  function ditherGradient(x0, y0, x1, y1, a, b, kind, put, box) {
    var dx = x1 - x0, dy = y1 - y0, len2 = dx * dx + dy * dy || 1;
    var bx0 = box ? box.x : Math.min(x0, x1), by0 = box ? box.y : Math.min(y0, y1), bx1 = box ? box.x + box.w - 1 : Math.max(x0, x1), by1 = box ? box.y + box.h - 1 : Math.max(y0, y1);
    for (var y = by0; y <= by1; y++) for (var x = bx0; x <= bx1; x++) {
      var t = ((x - x0) * dx + (y - y0) * dy) / len2; t = Math.max(0, Math.min(1, t));
      put(x, y, t > bayerAt(kind || 4, x, y) ? b : a);
    }
  }

  // ---------------------------------------------------------------- transforms (return new Uint32Array)
  function shift(buf, w, h, dx, dy, wrap) {
    var o = new Uint32Array(buf.length);
    for (var y = 0; y < h; y++) for (var x = 0; x < w; x++) {
      var nx = x + dx, ny = y + dy;
      if (wrap) { nx = ((nx % w) + w) % w; ny = ((ny % h) + h) % h; } else if (nx < 0 || ny < 0 || nx >= w || ny >= h) continue;
      o[ny * w + nx] = buf[y * w + x];
    }
    return o;
  }
  function flipH(buf, w, h) { var o = new Uint32Array(buf.length); for (var y = 0; y < h; y++) for (var x = 0; x < w; x++) o[y * w + w - 1 - x] = buf[y * w + x]; return o; }
  function flipV(buf, w, h) { var o = new Uint32Array(buf.length); for (var y = 0; y < h; y++) for (var x = 0; x < w; x++) o[(h - 1 - y) * w + x] = buf[y * w + x]; return o; }
  /** rotate by multiples of 90 degrees clockwise; returns {data,w,h} */
  function rotate90(buf, w, h, turns) {
    turns = ((turns % 4) + 4) % 4; if (!turns) return { data: buf.slice(), w: w, h: h };
    var nw = turns === 2 ? w : h, nh = turns === 2 ? h : w, o = new Uint32Array(buf.length);
    for (var y = 0; y < h; y++) for (var x = 0; x < w; x++) {
      var nx, ny;
      if (turns === 1) { nx = h - 1 - y; ny = x; } else if (turns === 2) { nx = w - 1 - x; ny = h - 1 - y; } else { nx = y; ny = w - 1 - x; }
      o[ny * nw + nx] = buf[y * w + x];
    }
    return { data: o, w: nw, h: nh };
  }
  function scaleNearest(buf, w, h, nw, nh) {
    var o = new Uint32Array(nw * nh);
    for (var y = 0; y < nh; y++) { var sy = Math.min(h - 1, Math.floor(y * h / nh)); for (var x = 0; x < nw; x++) o[y * nw + x] = buf[sy * w + Math.min(w - 1, Math.floor(x * w / nw))]; }
    return o;
  }
  /** Scale2x / EPX (Andrea Mazzoleni's public algorithm). Edge pixels use themselves as missing neighbours. */
  function scale2x(buf, w, h) {
    var nw = w * 2, o = new Uint32Array(nw * h * 2);
    for (var y = 0; y < h; y++) for (var x = 0; x < w; x++) {
      var p = buf[y * w + x], a = y > 0 ? buf[(y - 1) * w + x] : p, d = y < h - 1 ? buf[(y + 1) * w + x] : p, c = x > 0 ? buf[y * w + x - 1] : p, b = x < w - 1 ? buf[y * w + x + 1] : p;
      var p1 = p, p2 = p, p3 = p, p4 = p;
      if (c === a && c !== d && a !== b) p1 = a;
      if (a === b && a !== c && b !== d) p2 = b;
      if (d === c && d !== b && c !== a) p3 = c;
      if (b === d && b !== a && d !== c) p4 = d;
      var q = y * 2 * nw + x * 2; o[q] = p1; o[q + 1] = p2; o[q + nw] = p3; o[q + nw + 1] = p4;
    }
    return o;
  }
  function rotateNearest(buf, w, h, deg) {
    var o = new Uint32Array(buf.length), a = deg * Math.PI / 180, cs = Math.cos(a), sn = Math.sin(a), cx = (w - 1) / 2, cy = (h - 1) / 2;
    for (var y = 0; y < h; y++) for (var x = 0; x < w; x++) {
      var dx = x - cx, dy = y - cy, sx = Math.round(cx + dx * cs + dy * sn), sy = Math.round(cy - dx * sn + dy * cs);
      if (sx >= 0 && sy >= 0 && sx < w && sy < h) o[y * w + x] = buf[sy * w + sx];
    }
    return o;
  }
  /** rotsprite-like: scale2x x3 -> rotate nearest -> block-mode downsample */
  function rotateSmart(buf, w, h, deg) {
    var cur = buf, cw = w, ch = h;
    for (var i = 0; i < 3; i++) { cur = scale2x(cur, cw, ch); cw *= 2; ch *= 2; }
    var rot = rotateNearest(cur, cw, ch, deg), o = new Uint32Array(w * h), K = 8;
    for (var y = 0; y < h; y++) for (var x = 0; x < w; x++) {
      var counts = new Map(), empty = 0, best = 0, bn = 0;
      for (var yy = 0; yy < K; yy++) for (var xx = 0; xx < K; xx++) {
        var v = rot[(y * K + yy) * cw + x * K + xx];
        if (!v) { empty++; continue; }
        var n = (counts.get(v) || 0) + 1; counts.set(v, n); if (n > bn) { bn = n; best = v; }
      }
      o[y * w + x] = empty > K * K / 2 ? 0 : best;
    }
    return o;
  }

  // ---------------------------------------------------------------- helpers: outline, shadow, replace, shading
  var N4 = [[1, 0], [-1, 0], [0, 1], [0, -1]], N8 = N4.concat([[1, 1], [1, -1], [-1, 1], [-1, -1]]);
  function outline(buf, w, h, value, opts) {
    opts = opts || {}; var nb = opts.diagonal ? N8 : N4, o = buf.slice(), n = 0, inner = opts.inside;
    for (var y = 0; y < h; y++) for (var x = 0; x < w; x++) {
      var v = buf[y * w + x];
      if (inner ? !v : !!v) continue;
      for (var k = 0; k < nb.length; k++) {
        var nx = x + nb[k][0], ny = y + nb[k][1];
        var other = (nx < 0 || ny < 0 || nx >= w || ny >= h) ? 0 : buf[ny * w + nx];
        if (inner ? false : !!other) { o[y * w + x] = value; n++; break; }
      }
    }
    if (inner) {
      for (var y2 = 0; y2 < h; y2++) for (var x2 = 0; x2 < w; x2++) {
        if (!buf[y2 * w + x2]) continue;
        for (var k2 = 0; k2 < nb.length; k2++) {
          var ax = x2 + nb[k2][0], ay = y2 + nb[k2][1];
          if (ax < 0 || ay < 0 || ax >= w || ay >= h || !buf[ay * w + ax]) { o[y2 * w + x2] = value; n++; break; }
        }
      }
    }
    return { data: o, changed: n };
  }
  function dropShadow(buf, w, h, value, dx, dy) {
    var o = buf.slice(), n = 0;
    for (var y = 0; y < h; y++) for (var x = 0; x < w; x++) {
      if (!buf[y * w + x]) continue;
      var nx = x + dx, ny = y + dy;
      if (nx >= 0 && ny >= 0 && nx < w && ny < h && !buf[ny * w + nx] && !o[ny * w + nx]) { o[ny * w + nx] = value; n++; }
    }
    return { data: o, changed: n };
  }
  function replaceColor(buf, from, to, tol, toRGBA, clip) {
    var m = makeMatcher(from, tol || 0, toRGBA || function (v) { return v; }), n = 0;
    for (var i = 0; i < buf.length; i++) if ((from === 0 ? !buf[i] : (buf[i] && m(buf[i]))) && (!clip || clip[i])) { buf[i] = to; n++; }
    return n;
  }
  /** map every pixel through a Map(oldValue -> newValue) */
  function mapValues(buf, map, clip) { var n = 0; for (var i = 0; i < buf.length; i++) { if (clip && !clip[i]) continue; var r = map.get(buf[i]); if (r !== undefined && r !== buf[i]) { buf[i] = r; n++; } } return n; }

  var LIGHT_DIRS = { n: [0, -1], ne: [1, -1], e: [1, 0], se: [1, 1], s: [0, 1], sw: [-1, 1], w: [-1, 0], nw: [-1, -1] };
  /**
   * Shade a sprite by light direction: pixels with empty space on the light side get a lighter tone (rim), pixels with
   * empty space opposite to the light get a darker tone. lighter/darker are functions value -> value.
   * `depth` shades 1..3 pixels in from each edge (default 1).
   */
  function shadeByLight(buf, w, h, dir, lighter, darker, opts) {
    opts = opts || {}; var d = LIGHT_DIRS[dir]; if (!d) throw new Error('unknown light direction ' + dir);
    var depth = opts.depth || 1, o = buf.slice(), n = 0, clip = opts.clip;
    function empty(x, y) { return x < 0 || y < 0 || x >= w || y >= h || !buf[y * w + x]; }
    for (var y = 0; y < h; y++) for (var x = 0; x < w; x++) {
      var v = buf[y * w + x]; if (!v || (clip && !clip[y * w + x])) continue;
      var hi = false, lo = false;
      for (var k = 1; k <= depth; k++) {
        if (empty(x + d[0] * k, y + d[1] * k) || (d[0] && d[1] && (empty(x + d[0] * k, y) || empty(x, y + d[1] * k)) && opts.soft)) hi = true;
        if (empty(x - d[0] * k, y - d[1] * k) || (d[0] && d[1] && (empty(x - d[0] * k, y) || empty(x, y - d[1] * k)) && opts.soft)) lo = true;
      }
      if (hi && !lo && lighter) { var nv = lighter(v); if (nv !== v) { o[y * w + x] = nv; n++; } }
      else if (lo && !hi && darker) { var nd = darker(v); if (nd !== v) { o[y * w + x] = nd; n++; } }
    }
    return { data: o, changed: n };
  }
  return { line: line, linePoints: linePoints, rect: rect, ellipse: ellipse, polyline: polyline, polygonFill: polygonFill, pixelPerfect: pixelPerfect, brushOffsets: brushOffsets,
    newMask: newMask, rectMask: rectMask, polyMask: polyMask, maskBounds: maskBounds, maskCombine: maskCombine, maskInvert: maskInvert,
    makeMatcher: makeMatcher, floodMask: floodMask, applyMask: applyMask, bayerAt: bayerAt, ditherOn: ditherOn, ditherGradient: ditherGradient,
    shift: shift, flipH: flipH, flipV: flipV, rotate90: rotate90, scaleNearest: scaleNearest, scale2x: scale2x, rotateNearest: rotateNearest, rotateSmart: rotateSmart,
    outline: outline, dropShadow: dropShadow, replaceColor: replaceColor, mapValues: mapValues, shadeByLight: shadeByLight, LIGHT_DIRS: LIGHT_DIRS };
});
