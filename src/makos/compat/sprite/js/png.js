/* Sprite: PNG / APNG encoder and PNG decoder (pure JS, no canvas needed). Original code. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(function (n) { return require('./' + n + '.js'); });
  else { root.AS = root.AS || {}; root.AS.png = factory(function (n) { return root.AS[n]; }); }
})(typeof window !== 'undefined' ? window : globalThis, function (dep) {
  'use strict';
  var Z = dep('zlib');
  var SIG = [137, 80, 78, 71, 13, 10, 26, 10];

  function u32(v) { return [(v >>> 24) & 255, (v >>> 16) & 255, (v >>> 8) & 255, v & 255]; }
  function chunk(type, data) {
    var out = new Uint8Array(12 + data.length), t = [type.charCodeAt(0), type.charCodeAt(1), type.charCodeAt(2), type.charCodeAt(3)];
    out.set(u32(data.length), 0); out.set(t, 4); out.set(data, 8);
    out.set(u32(Z.crc32(out.subarray(4, 8 + data.length))), 8 + data.length);
    return out;
  }
  function concat(parts) {
    var n = 0, i; for (i = 0; i < parts.length; i++) n += parts[i].length;
    var out = new Uint8Array(n), p = 0; for (i = 0; i < parts.length; i++) { out.set(parts[i], p); p += parts[i].length; }
    return out;
  }
  function scan(w, h, rgba) { // filter 0 + Sub/Up heuristic per row (sum of abs)
    var stride = w * 4, out = new Uint8Array((stride + 1) * h);
    for (var y = 0; y < h; y++) {
      var row = rgba.subarray(y * stride, (y + 1) * stride), o = y * (stride + 1);
      var best = 0, bestSum = Infinity, cand;
      for (var f = 0; f < 3; f++) {
        var sum = 0;
        for (var x = 0; x < stride; x++) {
          var v = row[x];
          if (f === 1) v = (v - (x >= 4 ? row[x - 4] : 0)) & 255;
          else if (f === 2) v = (v - (y > 0 ? rgba[(y - 1) * stride + x] : 0)) & 255;
          sum += v < 128 ? v : 256 - v;
        }
        if (sum < bestSum) { bestSum = sum; best = f; }
      }
      out[o] = best;
      for (var x2 = 0; x2 < stride; x2++) {
        var v2 = row[x2];
        if (best === 1) v2 = (v2 - (x2 >= 4 ? row[x2 - 4] : 0)) & 255;
        else if (best === 2) v2 = (v2 - (y > 0 ? rgba[(y - 1) * stride + x2] : 0)) & 255;
        out[o + 1 + x2] = v2;
      }
    }
    return out;
  }
  function ihdr(w, h) { return chunk('IHDR', new Uint8Array(u32(w).concat(u32(h), [8, 6, 0, 0, 0]))); }

  /** encode(width,height,rgba) -> Uint8Array PNG */
  function encode(width, height, rgba) {
    if (!(width > 0 && height > 0) || rgba.length !== width * height * 4) throw new Error('png: bad dimensions');
    return concat([new Uint8Array(SIG), ihdr(width, height), chunk('IDAT', Z.deflate(scan(width, height, rgba))), chunk('IEND', new Uint8Array(0))]);
  }
  /** encodeAPNG(width,height,[{rgba,delay(ms)}],loops) full-frame APNG */
  function encodeAPNG(width, height, frames, loops) {
    var parts = [new Uint8Array(SIG), ihdr(width, height), chunk('acTL', new Uint8Array(u32(frames.length).concat(u32(loops | 0))))];
    var seq = 0;
    frames.forEach(function (f, i) {
      var d = Math.max(1, Math.round(f.delay || 100));
      var fc = new Uint8Array(u32(seq++).concat(u32(width), u32(height), u32(0), u32(0), [(d >> 8) & 255, d & 255, 3, 232], [1, 0]));
      parts.push(chunk('fcTL', fc));
      var z = Z.deflate(scan(width, height, f.rgba));
      if (i === 0) parts.push(chunk('IDAT', z));
      else parts.push(chunk('fdAT', concat([new Uint8Array(u32(seq++)), z])));
    });
    parts.push(chunk('IEND', new Uint8Array(0)));
    return concat(parts);
  }

  /** decode(bytes) -> {width,height,rgba,palette?} (non-interlaced only) */
  function decode(b) {
    for (var i = 0; i < 8; i++) if (b[i] !== SIG[i]) throw new Error('png: bad signature');
    var p = 8, w = 0, h = 0, depth = 0, ctype = 0, inter = 0, plte = null, trns = null, idat = [];
    while (p + 8 <= b.length) {
      var len = ((b[p] << 24) | (b[p + 1] << 16) | (b[p + 2] << 8) | b[p + 3]) >>> 0;
      var type = String.fromCharCode(b[p + 4], b[p + 5], b[p + 6], b[p + 7]);
      var d = b.subarray(p + 8, p + 8 + len);
      if (type === 'IHDR') { w = ((d[0] << 24) | (d[1] << 16) | (d[2] << 8) | d[3]) >>> 0; h = ((d[4] << 24) | (d[5] << 16) | (d[6] << 8) | d[7]) >>> 0; depth = d[8]; ctype = d[9]; inter = d[12]; }
      else if (type === 'PLTE') plte = d; else if (type === 'tRNS') trns = d; else if (type === 'IDAT') idat.push(d);
      else if (type === 'IEND') break;
      p += 12 + len;
    }
    if (!w || !h) throw new Error('png: missing IHDR');
    if (inter) throw new Error('png: interlaced images are not supported');
    var chans = { 0: 1, 2: 3, 3: 1, 4: 2, 6: 4 }[ctype];
    if (!chans) throw new Error('png: bad colour type');
    var bpp = Math.max(1, (chans * depth) >> 3), stride = (w * chans * depth + 7) >> 3;
    var raw = Z.inflate(concat(idat), (stride + 1) * h), px = new Uint8Array(stride * h);
    for (var y = 0; y < h; y++) {
      var ft = raw[y * (stride + 1)], so = y * (stride + 1) + 1, o = y * stride;
      for (var x = 0; x < stride; x++) {
        var a = x >= bpp ? px[o + x - bpp] : 0, up = y > 0 ? px[o - stride + x] : 0, ul = (x >= bpp && y > 0) ? px[o - stride + x - bpp] : 0, v = raw[so + x];
        if (ft === 1) v += a; else if (ft === 2) v += up; else if (ft === 3) v += (a + up) >> 1;
        else if (ft === 4) { var pp = a + up - ul, pa = Math.abs(pp - a), pb = Math.abs(pp - up), pc = Math.abs(pp - ul); v += (pa <= pb && pa <= pc) ? a : (pb <= pc ? up : ul); }
        else if (ft !== 0) throw new Error('png: bad filter');
        px[o + x] = v & 255;
      }
    }
    function sample(y, i) { // i-th sample in row y
      var o = y * stride;
      if (depth === 8) return px[o + i];
      if (depth === 16) return px[o + i * 2]; // keep the high byte
      var per = 8 / depth, byte = px[o + Math.floor(i / per)], shift = 8 - depth * (1 + (i % per));
      return (byte >> shift) & ((1 << depth) - 1);
    }
    var maxv = depth >= 8 ? 255 : (1 << depth) - 1, rgba = new Uint8Array(w * h * 4), pal = null;
    if (ctype === 3) { pal = []; for (var q = 0; plte && q * 3 < plte.length; q++) pal.push([plte[q * 3], plte[q * 3 + 1], plte[q * 3 + 2], trns && q < trns.length ? trns[q] : 255]); }
    for (var yy = 0; yy < h; yy++) for (var xx = 0; xx < w; xx++) {
      var r, g, bl, al = 255, k = (yy * w + xx) * 4;
      if (ctype === 0) { r = g = bl = sample(yy, xx) * 255 / maxv | 0; }
      else if (ctype === 2) { r = sample(yy, xx * 3); g = sample(yy, xx * 3 + 1); bl = sample(yy, xx * 3 + 2); }
      else if (ctype === 3) { var e = pal[sample(yy, xx)] || [0, 0, 0, 255]; r = e[0]; g = e[1]; bl = e[2]; al = e[3]; }
      else if (ctype === 4) { r = g = bl = sample(yy, xx * 2); al = sample(yy, xx * 2 + 1); }
      else { r = sample(yy, xx * 4); g = sample(yy, xx * 4 + 1); bl = sample(yy, xx * 4 + 2); al = sample(yy, xx * 4 + 3); }
      rgba[k] = r; rgba[k + 1] = g; rgba[k + 2] = bl; rgba[k + 3] = al;
    }
    return { width: w, height: h, rgba: rgba, palette: pal };
  }
  function toBase64(bytes) {
    if (typeof Buffer !== 'undefined') return Buffer.from(bytes.buffer, bytes.byteOffset, bytes.length).toString('base64');
    var s = '', CH = 0x8000;
    for (var i = 0; i < bytes.length; i += CH) s += String.fromCharCode.apply(null, bytes.subarray(i, i + CH));
    return btoa(s);
  }
  function fromBase64(str) {
    if (typeof Buffer !== 'undefined') { var bf = Buffer.from(str, 'base64'); return new Uint8Array(bf.buffer, bf.byteOffset, bf.length); }
    var bin = atob(str), out = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }
  return { encode: encode, encodeAPNG: encodeAPNG, decode: decode, toBase64: toBase64, fromBase64: fromBase64, concat: concat };
});
