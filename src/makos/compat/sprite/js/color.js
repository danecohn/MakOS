/* Sprite: colour helpers, built-in retro palettes and palette importers/exporters. Original code.
   Packed colour = little-endian RGBA in one uint32: r | g<<8 | b<<16 | a<<24 (always >>> 0). 0 = fully transparent. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(function (n) { return require('./' + n + '.js'); });
  else { root.AS = root.AS || {}; root.AS.color = factory(function (n) { return root.AS[n]; }); }
})(typeof window !== 'undefined' ? window : globalThis, function (dep) {
  'use strict';
  var PNG = dep('png');

  function pack(r, g, b, a) { return (((a === undefined ? 255 : a) << 24) | (b << 16) | (g << 8) | r) >>> 0; }
  function unpack(c) { return [c & 255, (c >>> 8) & 255, (c >>> 16) & 255, (c >>> 24) & 255]; }
  function hex(c, withAlpha) {
    var u = unpack(c), s = '#' + [u[0], u[1], u[2]].map(function (v) { return (v < 16 ? '0' : '') + v.toString(16); }).join('');
    if (withAlpha || u[3] !== 255) s += (u[3] < 16 ? '0' : '') + u[3].toString(16);
    return s;
  }
  /** parse "#rgb", "#rrggbb", "#rrggbbaa", "rrggbb", "rgb(r,g,b)" -> packed or null */
  function parse(s) {
    if (typeof s === 'number') return s >>> 0;
    if (typeof s !== 'string') return null;
    s = s.trim();
    var m = /^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)$/i.exec(s);
    if (m) return pack(Math.min(255, +m[1]), Math.min(255, +m[2]), Math.min(255, +m[3]), m[4] === undefined ? 255 : Math.round(Math.min(1, +m[4]) * 255));
    s = s.replace(/^#/, '');
    if (!/^[0-9a-f]+$/i.test(s)) return null;
    if (s.length === 3 || s.length === 4) s = s.split('').map(function (ch) { return ch + ch; }).join('');
    if (s.length === 6) s += 'ff';
    if (s.length !== 8) return null;
    return pack(parseInt(s.substr(0, 2), 16), parseInt(s.substr(2, 2), 16), parseInt(s.substr(4, 2), 16), parseInt(s.substr(6, 2), 16));
  }
  function luma(c) { var u = unpack(c); return 0.299 * u[0] + 0.587 * u[1] + 0.114 * u[2]; }
  function dist(a, b) { // weighted RGB distance, includes alpha
    var p = unpack(a), q = unpack(b), dr = p[0] - q[0], dg = p[1] - q[1], db = p[2] - q[2], da = p[3] - q[3];
    return Math.sqrt(dr * dr * 0.30 + dg * dg * 0.59 + db * db * 0.11 + da * da * 0.5);
  }
  function maxDiff(a, b) { var p = unpack(a), q = unpack(b); return Math.max(Math.abs(p[0] - q[0]), Math.abs(p[1] - q[1]), Math.abs(p[2] - q[2]), Math.abs(p[3] - q[3])); }
  function toHSL(c) {
    var u = unpack(c), r = u[0] / 255, g = u[1] / 255, b = u[2] / 255, mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2, h = 0, s = 0, d = mx - mn;
    if (d) { s = l > 0.5 ? d / (2 - mx - mn) : d / (mx + mn); h = mx === r ? (g - b) / d + (g < b ? 6 : 0) : mx === g ? (b - r) / d + 2 : (r - g) / d + 4; h *= 60; }
    return [h, s, l];
  }
  function fromHSL(h, s, l, a) {
    h = ((h % 360) + 360) % 360 / 360;
    function f(t) { t = (t + 1) % 1; if (t < 1 / 6) return p0 + (q0 - p0) * 6 * t; if (t < 1 / 2) return q0; if (t < 2 / 3) return p0 + (q0 - p0) * (2 / 3 - t) * 6; return p0; }
    var q0 = l < 0.5 ? l * (1 + s) : l + s - l * s, p0 = 2 * l - q0;
    var r = s === 0 ? l : f(h + 1 / 3), g = s === 0 ? l : f(h), b = s === 0 ? l : f(h - 1 / 3);
    return pack(Math.round(r * 255), Math.round(g * 255), Math.round(b * 255), a === undefined ? 255 : a);
  }
  function nearest(palette, c, skipTransparent) {
    var best = -1, bd = Infinity;
    for (var i = 0; i < palette.length; i++) { var d = dist(palette[i], c); if (d < bd) { bd = d; best = i; } }
    return best;
  }

  /** next lighter (dir>0) or darker (dir<0) tone of colour c: ideal = same hue family with lightness shifted (warm highlights, cool shadows),
   *  snapped to the nearest palette entry that really is lighter/darker. Returns c itself when nothing suitable exists. */
  function shiftTone(palette, c, dir) {
    var hsl = toHSL(c), u = unpack(c), l0 = luma(c);
    var ideal = fromHSL(hsl[0] + (dir > 0 ? -6 : 8), Math.min(1, Math.max(0, hsl[1] * (dir > 0 ? 0.92 : 1.06))), Math.max(0, Math.min(1, hsl[2] + dir * 0.14)), u[3]);
    var best = -1, bd = Infinity;
    for (var i = 0; i < palette.length; i++) {
      var p = palette[i]; if ((luma(p) - l0) * dir < 5) continue;
      var d = dist(ideal, p); if (d < bd) { bd = d; best = i; }
    }
    return best < 0 ? c : palette[best];
  }

  // ---------------------------------------------------------------- built-in palettes
  function L(s) { return s.trim().split(/\s+/).map(function (h) { return parse(h); }); }
  var PALETTES = [
    { id: 'pico8', name: 'PICO-8', colors: L('000000 1d2b53 7e2553 008751 ab5236 5f574f c2c3c7 fff1e8 ff004d ffa300 ffec27 00e436 29adff 83769c ff77a8 ffccaa') },
    { id: 'sweetie16', name: 'Sweetie 16', colors: L('1a1c2c 5d275d b13e53 ef7d57 ffcd75 a7f070 38b764 257179 29366f 3b5dc9 41a6f6 73eff7 f4f4f4 94b0c2 566c86 333c57') },
    { id: 'endesga32', name: 'Endesga 32', colors: L('be4a2f d77643 ead4aa e4a672 b86f50 733e39 3e2731 a22633 e43b44 f77622 feae34 fee761 63c74d 3e8948 265c42 193c3e 124e89 0099db 2ce8f5 ffffff c0cbdc 8b9bb4 5a6988 3a4466 262b44 181425 ff0044 68386c b55088 f6757a e8b796 c28569') },
    { id: 'db16', name: 'DawnBringer 16', colors: L('140c1c 442434 30346d 4e4a4e 854c30 346524 d04648 757161 597dce d27d2c 8595a1 6daa2c d2aa99 6dc2ca dad45e deeed6') },
    { id: 'gameboy', name: 'Game Boy', colors: L('0f380f 306230 8bac0f 9bbc0f') },
    { id: 'c64', name: 'Commodore 64', colors: L('000000 ffffff 68372b 70a4b2 6f3d86 588d43 352879 b8c76f 6f4f25 433900 9a6759 444444 6c6c6c 9ad284 6c5eb5 959595') },
    { id: 'gray8', name: 'Grayscale 8', colors: L('000000 242424 494949 6d6d6d 929292 b6b6b6 dbdbdb ffffff') },
    { id: 'fire', name: 'Fire', colors: L('0b0000 2b0a00 5a1200 8f1d00 c43300 f06a00 ffa400 ffd34d fff3a8 ffffff') },
    { id: 'amerika', name: 'Amerika neon', colors: L('0a0b12 1a1d2e 2c3150 4b5278 8a93b8 d6dbf0 ff2e63 ff9a3c ffe14d 3cf0a8 18d0ff 4b6bff a259ff ff6bd6') }
  ];
  function builtin(id) { for (var i = 0; i < PALETTES.length; i++) if (PALETTES[i].id === id) return PALETTES[i]; return null; }

  // ---------------------------------------------------------------- import / export
  function parseGPL(text) {
    var out = [], lines = text.split(/\r?\n/), name = null;
    for (var i = 0; i < lines.length; i++) {
      var l = lines[i].trim();
      if (!l || l[0] === '#') continue;
      var nm = /^Name:\s*(.*)$/i.exec(l); if (nm) { name = nm[1]; continue; }
      var m = /^(\d{1,3})\s+(\d{1,3})\s+(\d{1,3})(?:\s+.*)?$/.exec(l);
      if (m) out.push(pack(Math.min(255, +m[1]), Math.min(255, +m[2]), Math.min(255, +m[3])));
    }
    return { name: name, colors: out };
  }
  function parseHex(text) { // one colour per line, or whitespace/comma separated
    var out = [];
    text.split(/[\s,;]+/).forEach(function (t) { if (t) { var c = parse(t); if (c !== null) out.push(c); } });
    return out;
  }
  function parseJASC(text) {
    var lines = text.split(/\r?\n/), out = [];
    for (var i = 3; i < lines.length; i++) { var m = /^(\d+)\s+(\d+)\s+(\d+)/.exec(lines[i].trim()); if (m) out.push(pack(+m[1], +m[2], +m[3])); }
    return out;
  }
  function fromImage(img, max) { // unique colours of {rgba} in first-seen order
    var seen = new Set(), out = [], d = img.rgba;
    for (var i = 0; i < d.length; i += 4) {
      if (d[i + 3] === 0) continue;
      var c = pack(d[i], d[i + 1], d[i + 2], d[i + 3]);
      if (!seen.has(c)) { seen.add(c); out.push(c); if (out.length >= (max || 256)) break; }
    }
    return out;
  }
  /** detect by content: PNG bytes, GPL, JASC or hex list */
  function importAny(data) {
    if (typeof data !== 'string') {
      if (data[0] === 137 && data[1] === 80) return { colors: fromImage(PNG.decode(data), 256) };
      data = String.fromCharCode.apply(null, data.subarray(0, 1 << 20));
    }
    if (/^GIMP Palette/i.test(data)) return parseGPL(data);
    if (/^JASC-PAL/.test(data)) return { colors: parseJASC(data) };
    return { colors: parseHex(data) };
  }
  function toGPL(name, colors) {
    return 'GIMP Palette\nName: ' + name + '\nColumns: 8\n#\n' + colors.map(function (c, i) { var u = unpack(c); return (u[0] + '').padStart(3) + ' ' + (u[1] + '').padStart(3) + ' ' + (u[2] + '').padStart(3) + '\tcolor' + i; }).join('\n') + '\n';
  }
  function toHexList(colors) { return colors.map(function (c) { return hex(c).slice(1, 7); }).join('\n') + '\n'; }

  // ---------------------------------------------------------------- palette ops (pure, return new arrays)
  function ramp(a, b, n) { // n colours from a to b inclusive, HSL interpolation with hue shift
    var ha = toHSL(a), hb = toHSL(b), out = [];
    for (var i = 0; i < n; i++) {
      var t = n === 1 ? 0 : i / (n - 1), dh = hb[0] - ha[0]; if (dh > 180) dh -= 360; if (dh < -180) dh += 360;
      out.push(fromHSL(ha[0] + dh * t, ha[1] + (hb[1] - ha[1]) * t, ha[2] + (hb[2] - ha[2]) * t));
    }
    return out;
  }
  function sortPalette(colors, by) {
    var c = colors.slice();
    if (by === 'luma') c.sort(function (a, b) { return luma(a) - luma(b); });
    else if (by === 'hue') c.sort(function (a, b) { var x = toHSL(a), y = toHSL(b); return (x[1] < 0.08 ? -1 : x[0]) - (y[1] < 0.08 ? -1 : y[0]) || x[2] - y[2]; });
    return c;
  }
  /** Map a palette into another by luminance order so recolouring keeps shading: returns array mapping old index -> new colour */
  function remapByLuma(oldColors, newColors) {
    var o = oldColors.map(function (c, i) { return [luma(c), i]; }).sort(function (a, b) { return a[0] - b[0]; });
    var n = sortPalette(newColors, 'luma'), map = new Array(oldColors.length);
    o.forEach(function (e, rank) { map[e[1]] = n[Math.min(n.length - 1, Math.round(rank * (n.length - 1) / Math.max(1, o.length - 1)))]; });
    return map;
  }
  return { pack: pack, unpack: unpack, hex: hex, parse: parse, luma: luma, dist: dist, maxDiff: maxDiff, toHSL: toHSL, fromHSL: fromHSL, nearest: nearest, shiftTone: shiftTone,
    PALETTES: PALETTES, builtin: builtin, parseGPL: parseGPL, parseHex: parseHex, parseJASC: parseJASC, fromImage: fromImage, importAny: importAny,
    toGPL: toGPL, toHexList: toHexList, ramp: ramp, sortPalette: sortPalette, remapByLuma: remapByLuma };
});
