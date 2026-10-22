/* Sprite: IMPORT-ONLY reader for the documented .ase/.aseprite file format.
   Written from the public file-format specification (docs/ase-file-specs.md); no Aseprite source code was used.
   Sprite is not Aseprite and is not affiliated with it. There is deliberately no .aseprite writer. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(function (n) { return require('./' + n + '.js'); });
  else { root.AS = root.AS || {}; root.AS.aseprite = factory(function (n) { return root.AS[n]; }); }
})(typeof window !== 'undefined' ? window : globalThis, function (dep) {
  'use strict';
  var Z = dep('zlib'), M = dep('model'), C = dep('color');
  var BLEND = { 0: 'normal', 1: 'multiply', 2: 'screen', 3: 'overlay', 4: 'darken', 5: 'lighten', 6: 'colordodge', 7: 'colorburn', 8: 'hardlight', 9: 'softlight', 10: 'difference', 11: 'exclusion', 16: 'add', 17: 'subtract' };
  var DIRS = ['forward', 'reverse', 'pingpong', 'pingpong_reverse'];
  var MAX_PIXELS = 4096 * 4096;

  function read(bytes) {
    var dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength), p = 0, warnings = [];
    function u8() { return dv.getUint8(p++); }
    function u16() { var v = dv.getUint16(p, true); p += 2; return v; }
    function s16() { var v = dv.getInt16(p, true); p += 2; return v; }
    function u32() { var v = dv.getUint32(p, true); p += 4; return v; }
    function str() { var n = u16(); var s = new TextDecoder('utf-8').decode(bytes.subarray(p, p + n)); p += n; return s; }
    if (bytes.length < 128) throw new Error('aseprite: file too small');
    u32(); // file size
    if (u16() !== 0xA5E0) throw new Error('aseprite: bad magic number (not an .aseprite file)');
    var nFrames = u16(), W = u16(), H = u16(), depth = u16(), flags = u32(), speed = u16();
    p += 8; var transparentIndex = u8(); p += 3; var nColors = u16();
    p = 128;
    if (!(depth === 32 || depth === 16 || depth === 8)) throw new Error('aseprite: unsupported colour depth ' + depth);
    if (!W || !H || W * H > MAX_PIXELS) throw new Error('aseprite: bad canvas size');
    var indexed = depth === 8;
    var doc = new M.Doc({ w: W, h: H, mode: 'rgba' }); doc.layers = []; doc.frames = []; doc.palette = [];
    var layerList = [];      // file layer index -> {doc layer | null, flags, level}
    var palette = [], oldPalette = null, tags = [];
    var celBufs = [];        // per frame: Map(fileLayerIndex -> Uint32Array)
    var stack = [];          // group visibility stack by child level

    for (var fr = 0; fr < nFrames; fr++) {
      var fstart = p, fbytes = u32(), fmagic = u16(), oldChunks = u16(), dur = u16(); p += 2; var newChunks = u32();
      if (fmagic !== 0xF1FA) throw new Error('aseprite: bad frame magic');
      var nChunks = newChunks || oldChunks;
      doc.frames.push({ id: doc.nextId++, duration: Math.max(10, dur || speed || 100) });
      var frameCels = new Map(); celBufs.push(frameCels);
      for (var ci = 0; ci < nChunks; ci++) {
        var cstart = p, csize = u32(), ctype = u16(), cend = cstart + csize;
        if (csize < 6 || cend > bytes.length) throw new Error('aseprite: truncated chunk');
        if (ctype === 0x2004) { // layer
          var lf = u16(), lt = u16(), level = u16(); u16(); u16(); var blend = u16(), opac = u8(); p += 3; var lname = str();
          if (lt === 2) { u32(); }
          stack.length = level;
          var visible = !!(lf & 1);
          var parentsVisible = stack.every(function (v) { return v; });
          stack[level] = visible && parentsVisible;
          var entry = { flags: lf, type: lt, level: level, layer: null };
          if (lt === 0) {
            var dl = { id: doc.nextId++, name: lname, visible: visible && parentsVisible, opacity: opac, blend: BLEND[blend] || 'normal', locked: !(lf & 2) };
            if (blend && !BLEND[blend]) warnings.push('layer "' + lname + '": blend mode ' + blend + ' imported as normal');
            doc.layers.push(dl); entry.layer = dl;
          } else if (lt === 2) warnings.push('tilemap layer "' + lname + '" skipped (tilemaps are not imported)');
          layerList.push(entry);
        } else if (ctype === 0x2005) { // cel
          var li = u16(), cx = s16(), cy = s16(), copac = u8(), ctp = u16(); s16(); p += 5;
          var L = layerList[li], buf = null;
          if (ctp === 1) { var linkFrame = u16(); var src = celBufs[linkFrame] && celBufs[linkFrame].get(li); if (src) buf = src.slice(); }
          else if (ctp === 0 || ctp === 2) {
            var cw = u16(), ch = u16(), bpp = depth / 8, raw;
            if (cw * ch > MAX_PIXELS) throw new Error('aseprite: cel too large');
            if (ctp === 0) raw = bytes.subarray(p, p + cw * ch * bpp); else raw = Z.inflate(bytes.subarray(p, cend), cw * ch * bpp);
            if (raw.length < cw * ch * bpp) throw new Error('aseprite: cel data too short');
            if (L && L.layer) {
              buf = new Uint32Array(W * H);
              var bg = !!(L.flags & 8);
              for (var y = 0; y < ch; y++) {
                var ty = y + cy; if (ty < 0 || ty >= H) continue;
                for (var x = 0; x < cw; x++) {
                  var tx = x + cx; if (tx < 0 || tx >= W) continue;
                  var o = (y * cw + x) * bpp, v;
                  if (depth === 32) { var a = raw[o + 3]; if (copac !== 255) a = Math.round(a * copac / 255); v = a ? (raw[o] | (raw[o + 1] << 8) | (raw[o + 2] << 16) | (a << 24)) >>> 0 : 0; }
                  else if (depth === 16) { var ga = raw[o + 1]; if (copac !== 255) ga = Math.round(ga * copac / 255); v = ga ? C.pack(raw[o], raw[o], raw[o], ga) : 0; }
                  else { var idx = raw[o]; v = (!bg && idx === transparentIndex) ? 0 : idx + 1; }
                  buf[ty * W + tx] = v;
                }
              }
            }
          } else if (ctp === 3) warnings.push('tilemap cel skipped');
          if (buf && L && L.layer) frameCels.set(li, buf);
        } else if (ctype === 0x2019) { // palette
          var size = u32(), first = u32(), last = u32(); p += 8;
          for (var i = first; i <= last; i++) { var pf = u16(), r = u8(), g = u8(), b = u8(), al = u8(); palette[i] = C.pack(r, g, b, al); if (pf & 1) str(); }
        } else if (ctype === 0x0004 || ctype === 0x0011) { // old palettes (used only when no new palette chunk is present)
          oldPalette = oldPalette || []; var packets = u16(), at = 0;
          for (var k = 0; k < packets; k++) {
            at += u8(); var cnt = u8() || 256;
            for (var j = 0; j < cnt; j++) { var rr = u8(), gg = u8(), bb = u8(); if (ctype === 0x0011) { rr = (rr << 2) | (rr >> 4); gg = (gg << 2) | (gg >> 4); bb = (bb << 2) | (bb >> 4); } oldPalette[at++] = C.pack(rr, gg, bb); }
          }
        } else if (ctype === 0x2018) { // tags
          var nt = u16(); p += 8;
          for (var t = 0; t < nt; t++) {
            var from = u16(), to = u16(), dir = u8(), rep = u16(); p += 6; var tr = u8(), tg = u8(), tb = u8(); p += 1; var tn = str();
            tags.push({ name: tn, from: from, to: to, dir: DIRS[dir] || 'forward', repeat: rep, color: C.hex(C.pack(tr, tg, tb)) });
          }
        }
        // 0x2007 colour profile, 0x2020 user data, 0x2022 slice, 0x2023 tileset, 0x2016 mask, 0x2017 path: ignored
        p = cend;
      }
      p = fstart + fbytes;
    }
    if (!doc.layers.length) throw new Error('aseprite: file has no image layers');
    var pal = palette.length ? palette : (oldPalette || []);
    pal = Array.from(pal, function (c) { return c === undefined ? 0xFF000000 : c; });
    if (indexed) {
      if (!pal.length) throw new Error('aseprite: indexed file without a palette');
      doc.mode = 'indexed'; doc.palette = pal.slice(0, 256);
    } else doc.palette = pal.length && pal.length <= 256 ? pal : C.builtin('pico8').colors.slice();
    for (var f = 0; f < doc.frames.length; f++) {
      layerList.forEach(function (L, li) { var b = celBufs[f].get(li); if (b && L.layer) doc.cels.set(L.layer.id + ':' + doc.frames[f].id, b); });
    }
    tags.forEach(function (t) {
      if (t.from < doc.frames.length) doc.tags.push({ id: doc.nextId++, name: t.name, from: t.from, to: Math.min(t.to, doc.frames.length - 1), dir: t.dir, repeat: t.repeat, color: t.color });
    });
    return { doc: doc, warnings: warnings, info: { width: W, height: H, depth: depth, frames: nFrames, layers: doc.layers.length, tags: tags.length, flags: flags } };
  }
  return { read: read };
});
