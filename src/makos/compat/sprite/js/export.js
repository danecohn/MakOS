/* Sprite: spritesheet / animation exporters (PNG sheet, Aseprite-compatible JSON array, Godot SpriteFrames .tres,
   AtlasTexture snippet, GIF/APNG frame lists). Original code. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(function (n) { return require('./' + n + '.js'); });
  else { root.AS = root.AS || {}; root.AS.exporter = factory(function (n) { return root.AS[n]; }); }
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  function scaleRGBA(rgba, w, h, s) {
    if (s === 1) return rgba;
    var nw = w * s, out = new Uint8ClampedArray(nw * h * s * 4), i32 = new Uint32Array(rgba.buffer, rgba.byteOffset, w * h), o32 = new Uint32Array(out.buffer);
    for (var y = 0; y < h * s; y++) { var sy = Math.floor(y / s); for (var x = 0; x < nw; x++) o32[y * nw + x] = i32[sy * w + Math.floor(x / s)]; }
    return out;
  }
  /** frame indices in playback order for a tag (or all frames when tag is null) */
  function tagFrames(doc, tag) {
    var from = tag ? tag.from : 0, to = tag ? tag.to : doc.frames.length - 1, dir = tag ? tag.dir : 'forward', i, o = [];
    if (dir === 'reverse') { for (i = to; i >= from; i--) o.push(i); }
    else if (dir === 'pingpong') { for (i = from; i <= to; i++) o.push(i); for (i = to - 1; i > from; i--) o.push(i); }
    else if (dir === 'pingpong_reverse') { for (i = to; i >= from; i--) o.push(i); for (i = from + 1; i < to; i++) o.push(i); }
    else for (i = from; i <= to; i++) o.push(i);
    return o;
  }
  function findTag(doc, name) { for (var i = 0; i < doc.tags.length; i++) if (doc.tags[i].name === name) return doc.tags[i]; return null; }
  /** frame selection: undefined/'all' | 'tag:name' | array of indices */
  function selectFrames(doc, sel) {
    if (Array.isArray(sel)) return sel.filter(function (i) { return i >= 0 && i < doc.frames.length; });
    if (typeof sel === 'string' && sel.indexOf('tag:') === 0) { var t = findTag(doc, sel.slice(4)); if (!t) throw new Error('no tag named ' + sel.slice(4)); return tagFrames(doc, t); }
    return doc.frames.map(function (f, i) { return i; });
  }
  function animationFrames(doc, opts) {
    opts = opts || {}; var s = Math.max(1, Math.min(32, opts.scale | 0 || 1));
    return selectFrames(doc, opts.frames).map(function (fi) { return { rgba: scaleRGBA(doc.composite(fi), doc.w, doc.h, s), delay: doc.frames[fi].duration, index: fi }; });
  }

  function trimBox(rgba, w, h) {
    var x0 = w, y0 = h, x1 = -1, y1 = -1;
    for (var y = 0; y < h; y++) for (var x = 0; x < w; x++) if (rgba[(y * w + x) * 4 + 3]) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
    return x1 < 0 ? { x: 0, y: 0, w: 1, h: 1, empty: true } : { x: x0, y: y0, w: x1 - x0 + 1, h: y1 - y0 + 1 };
  }
  function crop(rgba, w, box) {
    var out = new Uint8ClampedArray(box.w * box.h * 4);
    for (var y = 0; y < box.h; y++) out.set(rgba.subarray(((box.y + y) * w + box.x) * 4, ((box.y + y) * w + box.x + box.w) * 4), y * box.w * 4);
    return out;
  }
  function fnum(n) { var s = (Math.round(n * 10000) / 10000).toString(); return s.indexOf('.') < 0 && s.indexOf('e') < 0 ? s + '.0' : s; }
  function safeName(s) { return String(s || 'sprite').replace(/[^A-Za-z0-9_\-]+/g, '_').replace(/^_+|_+$/g, '') || 'sprite'; }

  /**
   * buildSheet(doc, opts)
   * opts: frames, scale, trim, layout('horizontal'|'vertical'|'grid'|'packed'), columns, padding (sheet border), spacing (between frames),
   *       innerPadding (transparent ring around each frame), name, image (png file name for json/tres), godotPath ('res://...' prefix dir), tags(bool)
   * returns {width,height,rgba,frames:[{index,x,y,w,h,ox,oy,sw,sh,trimmed,duration}], json, jsonText, tres, atlas}
   */
  function buildSheet(doc, opts) {
    opts = opts || {};
    var s = Math.max(1, Math.min(32, opts.scale | 0 || 1)), trim = !!opts.trim, pad = Math.max(0, opts.padding | 0), sp = Math.max(0, opts.spacing | 0), ip = Math.max(0, opts.innerPadding | 0);
    var name = safeName(opts.name || doc.name), imageName = opts.image || name + '.png', idxs = selectFrames(doc, opts.frames);
    if (!idxs.length) throw new Error('no frames to export');
    var items = idxs.map(function (fi) {
      var full = scaleRGBA(doc.composite(fi), doc.w, doc.h, s), W = doc.w * s, H = doc.h * s, box = trim ? trimBox(full, W, H) : { x: 0, y: 0, w: W, h: H };
      var img = trim ? crop(full, W, box) : full;
      return { index: fi, img: img, bx: box.x, by: box.y, w: box.w + ip * 2, h: box.h + ip * 2, iw: box.w, ih: box.h, sw: W, sh: H, trimmed: trim && (box.w !== W || box.h !== H), duration: doc.frames[fi].duration };
    });
    var layout = opts.layout || 'horizontal', n = items.length, cols = Math.max(1, opts.columns | 0);
    if (layout === 'horizontal') cols = n; else if (layout === 'vertical') cols = 1; else if (layout === 'grid') cols = cols || Math.ceil(Math.sqrt(n));
    var W2 = 0, H2 = 0;
    if (layout === 'packed') { // shelf packing, tallest first, target width ~ sqrt(area)
      var order = items.map(function (it, i) { return i; }).sort(function (a, b) { return items[b].h - items[a].h || a - b; });
      var area = 0, maxw = 0; items.forEach(function (it) { area += (it.w + sp) * (it.h + sp); maxw = Math.max(maxw, it.w); });
      var target = Math.max(maxw, Math.ceil(Math.sqrt(area))), x = 0, y = 0, rowH = 0;
      order.forEach(function (i) {
        var it = items[i]; if (x > 0 && x + it.w > target) { x = 0; y += rowH + sp; rowH = 0; }
        it.x = x; it.y = y; x += it.w + sp; rowH = Math.max(rowH, it.h); W2 = Math.max(W2, it.x + it.w); H2 = Math.max(H2, it.y + it.h);
      });
    } else {
      var cw = 0, chh = 0; items.forEach(function (it) { cw = Math.max(cw, it.w); chh = Math.max(chh, it.h); });
      var rows = Math.ceil(n / cols);
      items.forEach(function (it, i) { it.x = (i % cols) * (cw + sp); it.y = Math.floor(i / cols) * (chh + sp); });
      W2 = cols * cw + (cols - 1) * sp; H2 = rows * chh + (rows - 1) * sp;
    }
    var width = W2 + pad * 2, height = H2 + pad * 2, sheet = new Uint8ClampedArray(width * height * 4);
    items.forEach(function (it) {
      it.x += pad; it.y += pad;
      for (var yy = 0; yy < it.ih; yy++) sheet.set(it.img.subarray(yy * it.iw * 4, (yy + 1) * it.iw * 4), ((it.y + ip + yy) * width + it.x + ip) * 4);
    });
    var frames = items.map(function (it) {
      return { index: it.index, x: it.x, y: it.y, w: it.w, h: it.h, rx: it.x + ip, ry: it.y + ip, rw: it.iw, rh: it.ih, ox: it.bx, oy: it.by, sw: it.sw, sh: it.sh, trimmed: it.trimmed, duration: it.duration };
    });
    // map doc frame index -> position in exported list
    var pos = new Map(); frames.forEach(function (f, i) { if (!pos.has(f.index)) pos.set(f.index, i); });

    var tags = [];
    if (opts.tags !== false) doc.tags.forEach(function (t) {
      var a = null, b = null;
      for (var i = t.from; i <= t.to; i++) if (pos.has(i)) { if (a === null) a = pos.get(i); b = pos.get(i); }
      if (a !== null) tags.push({ name: t.name, from: a, to: b, direction: t.dir, repeat: t.repeat, _t: t });
    });
    var json = {
      frames: frames.map(function (f, i) {
        return { filename: name + ' ' + f.index, frame: { x: f.rx, y: f.ry, w: f.rw, h: f.rh }, rotated: false, trimmed: f.trimmed,
          spriteSourceSize: { x: f.ox, y: f.oy, w: f.rw, h: f.rh }, sourceSize: { w: f.sw, h: f.sh }, duration: f.duration };
      }),
      meta: {
        app: 'Sprite (Aseprite-compatible JSON array; not affiliated with Aseprite)', version: '1.0', image: imageName, format: 'RGBA8888',
        size: { w: width, h: height }, scale: String(s),
        frameTags: tags.map(function (t) { return { name: t.name, from: t.from, to: t.to, direction: t.direction }; }),
        layers: doc.layers.map(function (l) { return { name: l.name, opacity: l.opacity, blendMode: l.blend }; }), slices: []
      }
    };
    var res = { width: width, height: height, rgba: sheet, frames: frames, json: json, jsonText: JSON.stringify(json, null, 2) + '\n', name: name, image: imageName };
    res.tres = buildSpriteFrames(doc, res, tags, opts);
    res.atlas = buildAtlasSnippet(res, opts);
    return res;
  }

  function buildSpriteFrames(doc, sheet, tags, opts) {
    var frames = sheet.frames, dir = opts.godotPath === undefined ? 'res://' : opts.godotPath;
    if (dir && dir[dir.length - 1] !== '/') dir += '/';
    var anims = [];
    if (tags.length) tags.forEach(function (t) {
      var order = tagFrames({ frames: frames.map(function () { return {}; }) }, { from: t.from, to: t.to, dir: t.direction });
      anims.push({ name: t.name, order: order, loop: !(t.repeat === 1) });
    });
    else anims.push({ name: 'default', order: frames.map(function (f, i) { return i; }), loop: true });
    var subs = new Map(), lines = [];
    anims.forEach(function (a) { a.order.forEach(function (i) { if (!subs.has(i)) subs.set(i, 'AtlasTexture_' + i); }); });
    var steps = 2 + subs.size;
    lines.push('[gd_resource type="SpriteFrames" load_steps=' + steps + ' format=3]', '', '[ext_resource type="Texture2D" path="' + dir + sheet.image + '" id="1_sheet"]', '');
    Array.from(subs.keys()).sort(function (a, b) { return a - b; }).forEach(function (i) {
      var f = frames[i], w = f.rw, h = f.rh;
      lines.push('[sub_resource type="AtlasTexture" id="' + subs.get(i) + '"]', 'atlas = ExtResource("1_sheet")', 'region = Rect2(' + f.rx + ', ' + f.ry + ', ' + w + ', ' + h + ')');
      if (f.trimmed) lines.push('margin = Rect2(' + f.ox + ', ' + f.oy + ', ' + (f.sw - w) + ', ' + (f.sh - h) + ')');
      lines.push('');
    });
    lines.push('[resource]', 'animations = [' + anims.map(function (a) {
      var base = Math.min.apply(null, a.order.map(function (i) { return frames[i].duration; })), fps = 1000 / base;
      return '{\n"frames": [' + a.order.map(function (i) { return '{\n"duration": ' + fnum(frames[i].duration / base) + ',\n"texture": SubResource("' + subs.get(i) + '")\n}'; }).join(', ') +
        '],\n"loop": ' + (a.loop ? 'true' : 'false') + ',\n"name": &"' + a.name.replace(/"/g, '') + '",\n"speed": ' + fnum(fps) + '\n}';
    }).join(', ') + ']', '');
    return lines.join('\n');
  }
  function buildAtlasSnippet(sheet, opts) {
    var dir = opts.godotPath === undefined ? 'res://' : opts.godotPath; if (dir && dir[dir.length - 1] !== '/') dir += '/';
    var f0 = sheet.frames[0];
    var s = '# Sprite: AtlasTexture helper for ' + sheet.image + ' (' + sheet.frames.length + ' frames)\n' +
      'const SHEET: Texture2D = preload("' + dir + sheet.image + '")\n' +
      'const FRAME_RECTS := [\n' + sheet.frames.map(function (f) { return '\tRect2(' + f.rx + ', ' + f.ry + ', ' + f.rw + ', ' + f.rh + ')'; }).join(',\n') + '\n]\n\n' +
      'func frame_texture(i: int) -> AtlasTexture:\n\tvar t := AtlasTexture.new()\n\tt.atlas = SHEET\n\tt.region = FRAME_RECTS[i]\n\treturn t\n\n' +
      '# Frame size: ' + f0.rw + 'x' + f0.rh + '. Use with a Sprite2D: $Sprite2D.texture = frame_texture(0)\n';
    return s;
  }
  return { scaleRGBA: scaleRGBA, tagFrames: tagFrames, findTag: findTag, selectFrames: selectFrames, animationFrames: animationFrames, buildSheet: buildSheet, trimBox: trimBox, safeName: safeName };
});
