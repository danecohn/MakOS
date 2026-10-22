/* Sprite: handlers for the sprite.* control endpoint (see src/os/studio/tools.json). Pure logic, host injected. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(function (n) { return require('./' + n + '.js'); });
  else { root.AS = root.AS || {}; root.AS.rpc = factory(function (n) { return root.AS[n]; }); }
})(typeof window !== 'undefined' ? window : globalThis, function (dep) {
  'use strict';
  var Tools = dep('tools'), PNG = dep('png');

  function rpcError(msg, code) { var e = new Error(msg); e.code = code || -32000; return e; }
  function strip(res) { // tool results carry ascii previews; the agent gets compact JSON
    return res;
  }
  /**
   * createRpc(host) where host = {session, io:{write}, prompt(message,timeoutS)->Promise<{reply,tool_calls}>, assistant}
   * returns async (method, params) -> JSON-able result
   */
  function createRpc(host) {
    var S = function () { return host.session; };
    function guardBusy() { if (S().busy) throw rpcError('the assistant is busy with another request', -32002); }
    function viewImage() {
      var im = Tools.viewResult(S(), {});
      return { mime: 'image/png', base64: PNG.toBase64(PNG.encode(im.width, im.height, im.rgba)) };
    }
    var H = {
      'canvas.info': function () { var i = Tools.info(S()); i.dirty = S().doc.dirty(); return i; },
      'canvas.describe_to_sprite': async function (p) {
        if (!p || typeof p.description !== 'string' || !p.description.trim()) throw rpcError('description is required', -32602);
        guardBusy();
        if (p.width || p.height) await Tools.run(S(), 'set_canvas', { width: p.width, height: p.height });
        if (Array.isArray(p.palette) && p.palette.length) await Tools.run(S(), 'set_palette', { colors: p.palette });
        var r = await host.prompt('Draw this sprite on the current frame (canvas ' + S().doc.w + 'x' + S().doc.h + '): ' + p.description.trim(), 600);
        return { ok: true, reply: r.reply, tool_calls: r.tool_calls, canvas: Tools.info(S()), images: [viewImage()] };
      },
      'canvas.apply_change': async function (p) {
        if (!p || typeof p.instruction !== 'string' || !p.instruction.trim()) throw rpcError('instruction is required', -32602);
        guardBusy();
        var r = await host.prompt('Change the current sprite: ' + p.instruction.trim(), 600);
        return { ok: true, reply: r.reply, tool_calls: r.tool_calls, images: [viewImage()] };
      },
      'frames.list': function () {
        var doc = S().doc;
        return { current: S().fi, frames: doc.frames.map(function (f, i) {
          var has = doc.layers.some(function (l) { var c = doc.cel(l.id, f.id); if (!c) return false; for (var k = 0; k < c.length; k++) if (c[k]) return true; return false; });
          return { index: i, duration: f.duration, thumbnail: has };
        }) };
      },
      'frames.add': async function (p) { guardBusy(); var r = await Tools.run(S(), 'new_frame', { index: p && p.index, copy_from: p && p.copy_from }); return { ok: true, index: r.frame_index, frame_count: r.frame_count }; },
      'frames.delete': async function (p) { guardBusy(); return Tools.run(S(), 'delete_frame', { index: p && p.index }); },
      'frames.duplicate': async function (p) {
        guardBusy(); var i = p && p.index; var doc = S().doc;
        if (typeof i !== 'number' || i < 0 || i >= doc.frames.length) throw rpcError('index out of range', -32602);
        var r = await Tools.run(S(), 'new_frame', { index: i + 1, copy_from: i }); return { ok: true, index: r.frame_index, frame_count: r.frame_count };
      },
      'frames.select': async function (p) { var i = p && p.index; if (typeof i !== 'number' || i < 0 || i >= S().doc.frames.length) throw rpcError('index out of range', -32602); S().setFrame(i); return { ok: true, current: S().fi }; },
      'frames.set_duration': async function (p) { guardBusy(); await Tools.run(S(), 'set_frame_duration', { frame: p && p.index, duration_ms: p && p.ms }); return { ok: true }; },
      'palette.get': function () { var doc = S().doc; return { mode: doc.mode, colors: doc.palette.map(function (c) { return require_hex(c); }) }; },
      'palette.set': async function (p) {
        guardBusy(); if (!p || !Array.isArray(p.colors) || !p.colors.length) throw rpcError('colors is required', -32602);
        return Tools.run(S(), 'set_palette', { colors: p.colors, mode: 'replace' });
      },
      'export': async function (p) {
        guardBusy(); if (!p || !p.format || !p.path) throw rpcError('format and path are required', -32602);
        if (['png', 'gif', 'sheet'].indexOf(p.format) < 0) throw rpcError('format must be png, gif or sheet', -32602);
        try { return await Tools.run(S(), 'export', { format: p.format, path: p.path, scale: p.scale }, host.io); }
        catch (e) { if (e && /path_not_allowed|confined|outside/.test(String(e.message || e.error || ''))) throw rpcError('path outside project', -32003); throw e; }
      },
      'app.prompt': async function (p) {
        if (!p || typeof p.message !== 'string' || !p.message.trim()) throw rpcError('message is required', -32602);
        guardBusy();
        var r = await host.prompt(p.message, p.timeout_s || 600);
        return { ok: true, reply: r.reply, tool_calls: r.tool_calls, images: [viewImage()] };
      }
    };
    function require_hex(c) { return dep('color').hex(c); }
    var handler = async function (method, params) {
      var h = H[method];
      if (!h) throw rpcError('unknown method ' + method, -32601);
      try { return await h(params || {}); }
      catch (e) {
        if (e && e.toolError && typeof e.code === 'number') throw e;
        if (e && typeof e.code === 'number') throw e;
        var err = rpcError(String((e && e.message) || e), -32000); throw err;
      }
    };
    handler.methods = Object.keys(H);
    return handler;
  }
  return { createRpc: createRpc };
});
