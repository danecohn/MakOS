/* Sprite: tiny dependency-free zlib (inflate + fixed-Huffman LZ77 deflate), crc32, adler32. Original code. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(function (n) { return require('./' + n + '.js'); });
  else { root.AS = root.AS || {}; root.AS.zlib = factory(function (n) { return root.AS[n]; }); }
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  var CRC = new Uint32Array(256);
  for (var n = 0; n < 256; n++) { var c = n; for (var k = 0; k < 8; k++) c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1); CRC[n] = c >>> 0; }
  function crc32(buf, crc) {
    var c = ((crc === undefined ? 0 : crc) ^ 0xFFFFFFFF) >>> 0;
    for (var i = 0; i < buf.length; i++) c = CRC[(c ^ buf[i]) & 255] ^ (c >>> 8);
    return (c ^ 0xFFFFFFFF) >>> 0;
  }
  function adler32(buf) {
    var a = 1, b = 0;
    for (var i = 0; i < buf.length; i++) { a = (a + buf[i]) % 65521; b = (b + a) % 65521; }
    return ((b << 16) | a) >>> 0;
  }

  // ---------------------------------------------------------------- inflate
  var LBASE = [3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258];
  var LEXT = [0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0];
  var DBASE = [1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577];
  var DEXT = [0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13];
  var CLORDER = [16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15];

  function makeHuff(lengths, n) {
    var count = new Uint16Array(16), symbol = new Uint16Array(n), offs = new Uint16Array(16), i;
    for (i = 0; i < n; i++) count[lengths[i]]++;
    count[0] = 0;
    for (i = 1; i < 16; i++) offs[i] = offs[i - 1] + count[i - 1];
    // offs[1] must start at 0 for symbols of length 1
    offs[1] = 0; for (i = 2; i < 16; i++) offs[i] = offs[i - 1] + count[i - 1];
    for (i = 0; i < n; i++) if (lengths[i]) symbol[offs[lengths[i]]++] = i;
    return { count: count, symbol: symbol };
  }
  var fixedL = null, fixedD = null;
  function fixedTables() {
    if (fixedL) return;
    var l = new Uint8Array(288), i;
    for (i = 0; i < 144; i++) l[i] = 8; for (; i < 256; i++) l[i] = 9; for (; i < 280; i++) l[i] = 7; for (; i < 288; i++) l[i] = 8;
    fixedL = makeHuff(l, 288);
    var d = new Uint8Array(30).fill(5); fixedD = makeHuff(d, 30);
  }

  function inflateRaw(src, pos, sizeHint) {
    var out = new Uint8Array(Math.max(sizeHint || 0, 1024)), op = 0, bitbuf = 0, bitcnt = 0;
    function need(n) { if (op + n > out.length) { var o = new Uint8Array(Math.max(out.length * 2, op + n)); o.set(out); out = o; } }
    function bits(n) {
      while (bitcnt < n) { if (pos >= src.length) throw new Error('inflate: unexpected end'); bitbuf |= src[pos++] << bitcnt; bitcnt += 8; }
      var v = bitbuf & ((1 << n) - 1); bitbuf >>>= n; bitcnt -= n; return v;
    }
    function decode(h) {
      var code = 0, first = 0, index = 0;
      for (var len = 1; len < 16; len++) {
        code |= bits(1);
        var cnt = h.count[len];
        if (code - cnt < first) return h.symbol[index + (code - first)];
        index += cnt; first += cnt; first <<= 1; code <<= 1;
      }
      throw new Error('inflate: bad code');
    }
    var last;
    do {
      last = bits(1);
      var type = bits(2);
      if (type === 0) {
        bitbuf = 0; bitcnt = 0;
        var len = src[pos] | (src[pos + 1] << 8); pos += 4;
        need(len); out.set(src.subarray(pos, pos + len), op); op += len; pos += len;
      } else if (type === 1 || type === 2) {
        var hl, hd;
        if (type === 1) { fixedTables(); hl = fixedL; hd = fixedD; }
        else {
          var nlen = bits(5) + 257, ndist = bits(5) + 1, ncode = bits(4) + 4, lengths = new Uint8Array(320), i;
          for (i = 0; i < ncode; i++) lengths[CLORDER[i]] = bits(3);
          var ch = makeHuff(lengths.subarray(0, 19), 19);
          lengths = new Uint8Array(320); i = 0;
          while (i < nlen + ndist) {
            var sym = decode(ch);
            if (sym < 16) lengths[i++] = sym;
            else {
              var prev = 0, rep;
              if (sym === 16) { prev = lengths[i - 1]; rep = 3 + bits(2); }
              else if (sym === 17) rep = 3 + bits(3); else rep = 11 + bits(7);
              while (rep--) lengths[i++] = prev;
            }
          }
          hl = makeHuff(lengths.subarray(0, nlen), nlen);
          hd = makeHuff(lengths.subarray(nlen, nlen + ndist), ndist);
        }
        for (;;) {
          var s = decode(hl);
          if (s < 256) { need(1); out[op++] = s; }
          else if (s === 256) break;
          else {
            s -= 257; if (s >= 29) throw new Error('inflate: bad length');
            var ln = LBASE[s] + bits(LEXT[s]);
            var ds = decode(hd); var dist = DBASE[ds] + bits(DEXT[ds]);
            if (dist > op) throw new Error('inflate: bad distance');
            need(ln);
            for (var j = 0; j < ln; j++) { out[op] = out[op - dist]; op++; }
          }
        }
      } else throw new Error('inflate: bad block type');
    } while (!last);
    return out.subarray(0, op);
  }
  function inflate(src, sizeHint) { // zlib-wrapped
    if (src.length < 2 || (src[0] & 15) !== 8) throw new Error('inflate: not a zlib stream');
    return inflateRaw(src, 2, sizeHint);
  }

  // ---------------------------------------------------------------- deflate
  var LCODE = new Uint16Array(259), LEXTRA = new Uint8Array(259), DCODEOF = null;
  (function () {
    for (var c = 0; c < 29; c++) { var hi = c === 28 ? 258 : LBASE[c] + (1 << LEXT[c]) - 1; for (var l = LBASE[c]; l <= hi && l <= 258; l++) { LCODE[l] = c; } }
    LCODE[258] = 28;
  })();
  function dcode(d) { var c = 29; while (DBASE[c] > d) c--; return c; }
  function rev(v, n) { var r = 0; for (var i = 0; i < n; i++) { r = (r << 1) | (v & 1); v >>>= 1; } return r; }

  function deflateRaw(data) {
    var out = new Uint8Array(Math.max(64, (data.length >> 1) + 64)), op = 0, bb = 0, bc = 0;
    function put(v, n) { // LSB-first
      bb |= v << bc; bc += n;
      while (bc >= 8) { if (op >= out.length) { var o = new Uint8Array(out.length * 2); o.set(out); out = o; } out[op++] = bb & 255; bb >>>= 8; bc -= 8; }
    }
    function lit(s) { // fixed huffman, MSB-first code
      if (s < 144) put(rev(0x30 + s, 8), 8); else if (s < 256) put(rev(0x190 + s - 144, 9), 9);
      else if (s < 280) put(rev(s - 256, 7), 7); else put(rev(0xC0 + s - 280, 8), 8);
    }
    put(1, 1); put(1, 2);
    var n = data.length, head = new Int32Array(1 << 15).fill(-1), prev = new Int32Array(n || 1), i = 0;
    function hash(p) { return ((data[p] << 10) ^ (data[p + 1] << 5) ^ data[p + 2]) & 32767; }
    while (i < n) {
      var bestLen = 0, bestDist = 0;
      if (i + 2 < n) {
        var h = hash(i), cand = head[h], chain = 48;
        while (cand >= 0 && i - cand <= 32768 && chain--) {
          var l = 0, max = Math.min(258, n - i);
          while (l < max && data[cand + l] === data[i + l]) l++;
          if (l > bestLen) { bestLen = l; bestDist = i - cand; if (l === max) break; }
          cand = prev[cand];
        }
      }
      if (bestLen >= 3) {
        var lc = LCODE[bestLen]; lit(257 + lc); if (LEXT[lc]) put(bestLen - LBASE[lc], LEXT[lc]);
        var dc = dcode(bestDist); put(rev(dc, 5), 5); if (DEXT[dc]) put(bestDist - DBASE[dc], DEXT[dc]);
        for (var k = 0; k < bestLen; k++) { if (i + 2 < n) { var hh = hash(i); prev[i] = head[hh]; head[hh] = i; } i++; }
      } else {
        lit(data[i]);
        if (i + 2 < n) { var h2 = hash(i); prev[i] = head[h2]; head[h2] = i; }
        i++;
      }
    }
    lit(256);
    if (bc > 0) put(0, 8 - bc);
    return out.subarray(0, op);
  }
  function deflate(data) { // zlib-wrapped
    var raw = deflateRaw(data), out = new Uint8Array(raw.length + 6), a = adler32(data);
    out[0] = 0x78; out[1] = 0x9C; out.set(raw, 2);
    out[raw.length + 2] = a >>> 24; out[raw.length + 3] = (a >>> 16) & 255; out[raw.length + 4] = (a >>> 8) & 255; out[raw.length + 5] = a & 255;
    return out;
  }
  return { crc32: crc32, adler32: adler32, inflate: inflate, inflateRaw: inflateRaw, deflate: deflate, deflateRaw: deflateRaw };
});
