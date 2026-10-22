/* Sprite: animated GIF89a encoder (own LZW + median-cut quantiser). Original code. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(function (n) { return require('./' + n + '.js'); });
  else { root.AS = root.AS || {}; root.AS.gif = factory(function (n) { return root.AS[n]; }); }
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  function lzw(indices, minCode) {
    var clear = 1 << minCode, eoi = clear + 1, out = [], cur = 0, nbits = 0;
    var size = minCode + 1, next = eoi + 1, dict = new Map();
    function emit(code) {
      cur |= code << nbits; nbits += size;
      while (nbits >= 8) { out.push(cur & 255); cur >>>= 8; nbits -= 8; }
    }
    emit(clear);
    if (!indices.length) { emit(eoi); if (nbits > 0) out.push(cur & 255); return out; }
    var prefix = indices[0];
    for (var i = 1; i < indices.length; i++) {
      var k = indices[i], key = prefix * 256 + k, hit = dict.get(key);
      if (hit !== undefined) { prefix = hit; continue; }
      emit(prefix);
      if (next < 4096) {
        dict.set(key, next++);
        if (next > (1 << size) && size < 12) size++;
      } else { emit(clear); dict.clear(); size = minCode + 1; next = eoi + 1; }
      prefix = k;
    }
    emit(prefix); emit(eoi);
    if (nbits > 0) out.push(cur & 255);
    return out;
  }

  /** median cut: colours is [{c:0xRRGGBB, n:count}]; returns array of up to `max` [r,g,b] */
  function medianCut(colors, max) {
    var boxes = [colors.slice()];
    function range(box) {
      var mn = [255, 255, 255], mx = [0, 0, 0];
      box.forEach(function (e) { for (var ch = 0; ch < 3; ch++) { var v = (e.c >> (16 - 8 * ch)) & 255; if (v < mn[ch]) mn[ch] = v; if (v > mx[ch]) mx[ch] = v; } });
      var best = 0, bs = -1; for (var ch = 0; ch < 3; ch++) if (mx[ch] - mn[ch] > bs) { bs = mx[ch] - mn[ch]; best = ch; }
      return { ch: best, span: bs };
    }
    while (boxes.length < max) {
      var bi = -1, bsp = 0, bch = 0;
      boxes.forEach(function (b, i) { if (b.length > 1) { var r = range(b); if (r.span > bsp || bi < 0) { bsp = r.span; bi = i; bch = r.ch; } } });
      if (bi < 0) break;
      var b = boxes[bi], sh = 16 - 8 * bch;
      b.sort(function (p, q) { return ((p.c >> sh) & 255) - ((q.c >> sh) & 255); });
      var tot = 0; b.forEach(function (e) { tot += e.n; });
      var acc = 0, cut = 1; for (var i = 0; i < b.length - 1; i++) { acc += b[i].n; cut = i + 1; if (acc * 2 >= tot) break; }
      boxes.splice(bi, 1, b.slice(0, cut), b.slice(cut));
    }
    return boxes.map(function (b) {
      var r = 0, g = 0, bl = 0, n = 0;
      b.forEach(function (e) { r += ((e.c >> 16) & 255) * e.n; g += ((e.c >> 8) & 255) * e.n; bl += (e.c & 255) * e.n; n += e.n; });
      return [Math.round(r / n), Math.round(g / n), Math.round(bl / n)];
    });
  }

  function histogram(rgbaList) {
    var m = new Map(), transparent = false;
    rgbaList.forEach(function (rgba) {
      for (var i = 0; i < rgba.length; i += 4) {
        if (rgba[i + 3] < 128) { transparent = true; continue; }
        var c = (rgba[i] << 16) | (rgba[i + 1] << 8) | rgba[i + 2];
        m.set(c, (m.get(c) || 0) + 1);
      }
    });
    return { map: m, transparent: transparent };
  }
  function buildPalette(hist, reserve) {
    var cap = 256 - reserve, entries = [];
    hist.map.forEach(function (n, c) { entries.push({ c: c, n: n }); });
    var pal;
    if (entries.length <= cap) pal = entries.map(function (e) { return [(e.c >> 16) & 255, (e.c >> 8) & 255, e.c & 255]; });
    else pal = medianCut(entries, cap);
    return pal;
  }
  function mapper(pal, offset) {
    var cache = new Map(), exact = new Map();
    pal.forEach(function (c, i) { var k = (c[0] << 16) | (c[1] << 8) | c[2]; if (!exact.has(k)) exact.set(k, i + offset); });
    return function (r, g, b) {
      var k = (r << 16) | (g << 8) | b, e = exact.get(k); if (e !== undefined) return e;
      var h = cache.get(k); if (h !== undefined) return h;
      var best = 0, bd = Infinity;
      for (var i = 0; i < pal.length; i++) { var dr = pal[i][0] - r, dg = pal[i][1] - g, db = pal[i][2] - b, d = dr * dr * 3 + dg * dg * 4 + db * db * 2; if (d < bd) { bd = d; best = i; } }
      cache.set(k, best + offset); return best + offset;
    };
  }

  /**
   * encode({width,height,frames:[{rgba,delay}], loop}) -> Uint8Array
   * delay in ms (rounded to 1/100 s, min 2cs for browser compatibility). loop: 0 = forever, n = n times, -1 = no loop block.
   */
  function encode(o) {
    var w = o.width, h = o.height, frames = o.frames, loop = o.loop === undefined ? 0 : o.loop;
    if (!(w > 0 && h > 0 && w < 65536 && h < 65536) || !frames.length) throw new Error('gif: bad input');
    var hist = histogram(frames.map(function (f) { return f.rgba; }));
    var reserve = hist.transparent ? 1 : 0;
    var shared = hist.map.size <= 256 - reserve;
    var out = [], push = function (a) { for (var i = 0; i < a.length; i++) out.push(a[i]); };
    var gpal = null, gmap = null;
    if (shared) { gpal = buildPalette(hist, reserve); gmap = mapper(gpal, reserve); }
    function palBytes(pal, off) {
      var bits = 1; while ((1 << bits) < pal.length + off) bits++;
      var bytes = new Array((1 << bits) * 3).fill(0);
      pal.forEach(function (c, i) { bytes[(i + off) * 3] = c[0]; bytes[(i + off) * 3 + 1] = c[1]; bytes[(i + off) * 3 + 2] = c[2]; });
      return { bytes: bytes, bits: bits };
    }
    push([71, 73, 70, 56, 57, 97, w & 255, w >> 8, h & 255, h >> 8]);
    var gp = gpal ? palBytes(gpal, reserve) : { bytes: [0, 0, 0, 255, 255, 255], bits: 1 };
    push([0x80 | ((gp.bits - 1) << 4) | (gp.bits - 1), 0, 0]); push(gp.bytes);
    if (loop >= 0) push([0x21, 0xFF, 11, 78, 69, 84, 83, 67, 65, 80, 69, 50, 46, 48, 3, 1, loop & 255, (loop >> 8) & 255, 0]);
    frames.forEach(function (f) {
      var pal = gpal, map = gmap, lp = null;
      if (!shared) {
        var fh = histogram([f.rgba]); pal = buildPalette(fh, reserve); map = mapper(pal, reserve); lp = palBytes(pal, reserve);
      }
      var cs = Math.max(2, Math.round((f.delay === undefined ? 100 : f.delay) / 10));
      var idx = new Uint8Array(w * h), rg = f.rgba;
      for (var i = 0, p = 0; i < rg.length; i += 4, p++) idx[p] = rg[i + 3] < 128 ? 0 : map(rg[i], rg[i + 1], rg[i + 2]);
      push([0x21, 0xF9, 4, (reserve ? (2 << 2) | 1 : (1 << 2)), cs & 255, cs >> 8, 0, 0]);
      push([0x2C, 0, 0, 0, 0, w & 255, w >> 8, h & 255, h >> 8]);
      var bits = shared ? gp.bits : lp.bits;
      if (lp) { push([0x80 | (bits - 1)]); push(lp.bytes); } else push([0]);
      var minCode = Math.max(2, bits);
      out.push(minCode);
      var data = lzw(idx, minCode);
      for (var s = 0; s < data.length; s += 255) { var n = Math.min(255, data.length - s); out.push(n); for (var j = 0; j < n; j++) out.push(data[s + j]); }
      out.push(0);
    });
    out.push(0x3B);
    return Uint8Array.from(out);
  }
  return { encode: encode, lzw: lzw };
});
