/* Sprite: AI assistant glue. System prompt, tool loop (uses the shell's AIClient, with a local fallback that only
   talks to the bridge through amerikaStudio.request), and "one history step per AI turn". No API keys anywhere. Original code. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(function (n) { return require('./' + n + '.js'); });
  else { root.AS = root.AS || {}; root.AS.ai = factory(function (n) { return root.AS[n]; }); }
})(typeof window !== 'undefined' ? window : globalThis, function (dep) {
  'use strict';
  var Tools = dep('tools');

  var SYSTEM_PROMPT = [
    'You are the pixel artist inside Sprite, a pixel-art editor. The user describes what they want and you build or change the sprite by calling tools. You can see the sprite with view_canvas (an upscaled image with a pixel ruler) and with the ASCII picture that most tools return. You draw by choosing palette indices; you never write code.',
    '',
    'WORKFLOW (iterate, do not draw everything blind):',
    '1. Look: call canvas_info (size, palette, layers, frames, ASCII of the current frame). If the user edits existing art, view_canvas first.',
    '2. Plan in one or two sentences: subject, canvas size, light direction (default top-left), 8-16 palette colours grouped in ramps of 3-5 tones (dark to light, hue-shifted: shadows cooler/more saturated, highlights warmer), plus one near-black outline colour. Call set_canvas (indexed mode is best) and set_palette. Keep the palette order stable: ramps dark to light, so a shading pass can use neighbours.',
    '3. Silhouette: block the whole shape in flat mid-tones with draw_shape (fill) or draw_pixels (rows). The silhouette must read at a glance: strong, simple, distinct head/body/limbs; characters about 3 to 4 heads tall for chibi style, 6 to 7 for realistic.',
    '4. Shade: apply base, shadow and highlight tones consistently from one light direction (shade_by_light_direction gives a first pass; refine by hand). 2-3 tones per material is plenty.',
    '5. Details and outline: add eyes, plume, buckles, specular highlights with a few pixels. Outline with outline (selective outlining: a darker shade of each material, or one dark colour on the outside only; no outline inside where two lit areas meet).',
    '6. Check: view_canvas, compare with the intention, fix proportions and stray pixels with small draw_pixels patches. Do at least one check pass before you finish; do not stop after the first draw call.',
    '7. Animate when asked: use layers for parts that move independently if needed; new_frame / copy_frame_with_transform to build frames; keep the silhouette volume consistent; set_frame_duration (idle 120-200 ms per frame, walk/run 80-120 ms); tag the ranges with set_tag ("idle", "walk", "attack"). Walk cycle: 4 to 8 frames (contact, down, passing, up for each leg), with a 1 px body bob; the contact frames have the legs furthest apart. Idle: 2 to 4 frames with a 1 px breath/bob or a slight cloth/hair sway. Always view_canvas with all_frames=true to review the whole animation.',
    '',
    'PIXEL-ART RULES:',
    '- Hard pixels only: no anti-aliasing, no blur, no gradients except deliberate dithering patterns. No colour outside the palette.',
    '- Limited palette (8 to 32 colours). Reuse colours across the sprite; avoid near-duplicates. Prefer a known palette when the user names a style (SNES: 16-32 colours with rich ramps; NES: 4 colours per sprite; Game Boy: the 4 greens; PICO-8: pico8 preset; "fire palette": preset fire).',
    '- Clean lines: avoid jaggies (uneven stair-step lengths) and "doubles" (L-shaped corner pixels in 1 px lines). Curves use runs that grow or shrink monotonically (1,2,3,... not 1,3,2).',
    '- One light source for the whole sprite. Lit side gets lighter tones, the side facing away gets darker tones, cast shadows go on the opposite side. Keep the top-left light unless told otherwise.',
    '- Avoid pillow shading (shading that follows the outline) and banding (parallel stripes of equal width).',
    '- Mirror symmetrical sprites: draw one half and use mirror(mode=copy_left_to_right) then add asymmetric details.',
    '- Tiles: for tilesets and seamless textures keep edges matching (draw with wrap-around thinking); check with view_canvas by comparing the opposite edges; a forest tileset is usually 16x16 or 32x32 tiles on a grid with ground, grass, tree, bush, water, path variants, laid out in one frame or as frames you export with the sheet layout.',
    '',
    'TOOL TIPS:',
    '- draw_pixels rows: each character is a palette index (0-9, a-z, A-Z = indices 0-61), "." is transparent, rows start at (x,y). Whole-canvas rows replace the picture; smaller patches leave other pixels alone. For big flat areas use rects or draw_shape fill; for long runs use rle ("12x. 4xa 2xb").',
    '- Coordinates are 0-based from the top-left. The ruler in view_canvas shows pixel numbers every 8 px.',
    '- Every tool call is checked; errors tell you what to fix. If a result looks wrong, call undo and retry differently instead of piling fixes on top.',
    '- Work on the current layer/frame unless you pass layer/frame. Layers: keep line art, colour and effects separate when it helps editing; for a single sprite one layer is fine.',
    '- Export only when the user asks (export tool; paths are relative to the project folder).',
    '',
    'STYLE OF REPLY: after you are done, answer in two or three short sentences describing what you made and the choices (size, palette, light), and offer one or two follow-up ideas. Do not paste pixel data into the chat.'
  ].join('\n');

  /** Fallback tool-use loop: same surface as amerikaStudio.AIClient. request(path, body) -> Promise<{status,json}> */
  function LocalAIClient(o) {
    this.o = o; this.messages = []; this.stopped = false;
  }
  LocalAIClient.prototype.reset = function () { this.messages = []; this.stopped = false; };
  LocalAIClient.prototype.stop = function () { this.stopped = true; };
  LocalAIClient.prototype.send = async function (text, opts) {
    var o = this.o, self = this, request = o.request, toolCalls = [], usage = { input_tokens: 0, output_tokens: 0 }, finalText = '', stopped = false;
    this.stopped = false;
    var content = [];
    ((opts && opts.images) || []).forEach(function (im) { content.push({ type: 'image', source: { type: 'base64', media_type: im.mime || 'image/png', data: im.base64 } }); });
    content.push({ type: 'text', text: text });
    this.messages.push({ role: 'user', content: content });
    var maxTurns = o.maxTurns || 12;
    for (var turn = 0; turn < maxTurns; turn++) {
      if (this.stopped) { stopped = true; break; }
      var body = { model: o.model || 'claude-sonnet-5-5', max_tokens: o.maxTokens || 4096, system: o.system, tools: o.tools, messages: this.messages };
      var res = null;
      for (var attempt = 0; attempt < 4; attempt++) {
        res = await request('/v1/messages', body, { timeoutMs: 300000 });
        if (res.status === 429 || res.status === 529 || res.status === 503) { await new Promise(function (r) { setTimeout(r, (o.retryMs === undefined ? 1500 : o.retryMs) * (attempt + 1)); }); continue; }
        break;
      }
      if (res.status !== 200) {
        var err = new Error((res.json && res.json.error && res.json.error.message) || ('bridge error ' + res.status));
        err.code = res.status === 401 || res.status === 403 ? 'no_key' : res.status === 429 ? 'rate_limited' : 'api_error'; err.status = res.status; throw err;
      }
      var msg = res.json; this.messages.push({ role: 'assistant', content: msg.content });
      if (msg.usage) { usage.input_tokens += msg.usage.input_tokens || 0; usage.output_tokens += msg.usage.output_tokens || 0; }
      var uses = [], texts = [];
      (msg.content || []).forEach(function (b) { if (b.type === 'text') texts.push(b.text); else if (b.type === 'tool_use') uses.push(b); });
      if (texts.length) { finalText = texts.join('\n'); if (o.onText) o.onText(finalText); }
      if (!uses.length) break;
      var results = [];
      for (var k = 0; k < uses.length; k++) {
        var u = uses[k], r;
        if (this.stopped) { results.push({ type: 'tool_result', tool_use_id: u.id, is_error: true, content: 'Stopped by the user.' }); stopped = true; continue; }
        toolCalls.push({ name: u.name, input: u.input });
        try {
          var out = await o.run(u.name, u.input);
          var blocks = [], textOut = '';
          if (out && typeof out === 'object' && (out.image || out.text !== undefined)) {
            textOut = out.text !== undefined ? String(out.text) : '';
            if (out.image) blocks.push({ type: 'image', source: { type: 'base64', media_type: out.image.mime, data: out.image.base64 } });
            if (textOut) blocks.unshift({ type: 'text', text: textOut });
          } else blocks.push({ type: 'text', text: typeof out === 'string' ? out : JSON.stringify(out) });
          results.push({ type: 'tool_result', tool_use_id: u.id, content: blocks });
        } catch (e) { results.push({ type: 'tool_result', tool_use_id: u.id, is_error: true, content: String(e && e.message || e) }); }
      }
      this.messages.push({ role: 'user', content: results });
      if (stopped) break;
    }
    return { text: finalText, toolCalls: toolCalls, usage: usage, stopped: stopped };
  };

  /**
   * createAssistant({session, io, request, AIClient, onEvent, model}) -> {send, stop, reset, busy}
   * onEvent({type:'tool'|'text'|'error'|'done', ...}) for the UI.
   */
  function createAssistant(o) {
    var S = o.session, busy = false;
    var Client = o.AIClient || LocalAIClient;
    function run(name, input) {
      if (o.onEvent) o.onEvent({ type: 'tool', name: name, input: input });
      return Tools.run(S, name, input, o.io).then(function (res) {
        if (o.onEvent) o.onEvent({ type: 'tool_result', name: name, ok: true, image: res && res.image });
        return res;
      }, function (e) { if (o.onEvent) o.onEvent({ type: 'tool_result', name: name, ok: false, error: e.message }); throw e; });
    }
    var client = new Client({ model: o.model, system: SYSTEM_PROMPT, tools: Tools.definitions(), run: run, maxTurns: 40, maxTokens: 8192, request: o.request, onText: function (t) { if (o.onEvent) o.onEvent({ type: 'text', text: t }); },
      onEvent: function (kind, data) { if (kind === 'text' && o.onEvent) o.onEvent({ type: 'text', text: data }); } });
    var api = {
      get busy() { return busy; },
      reset: function () { client.reset(); },
      stop: function () { client.stop(); },
      send: async function (text, opts) {
        if (busy) { var e = new Error('the assistant is busy'); e.code = -32002; throw e; }
        busy = true; S.busy = true; S.emit('busy');
        var doc = S.doc, mark = doc.undoStack.length;
        var head = '[Sprite: ' + doc.w + 'x' + doc.h + ' ' + doc.mode + ', ' + doc.palette.length + ' colours, ' + doc.layers.length + ' layer(s), ' + doc.frames.length + ' frame(s), frame ' + S.fi + ', layer ' + S.li + ']\n';
        try {
          var res = await client.send(head + text, opts);
          return res;
        } finally {
          if (S.doc === doc) doc.collapseSince(mark, 'AI: ' + String(text).slice(0, 40));
          busy = false; S.busy = false; S.emit('busy'); if (S.doc === doc) doc.emit('edit');
        }
      }
    };
    return api;
  }
  return { SYSTEM_PROMPT: SYSTEM_PROMPT, LocalAIClient: LocalAIClient, createAssistant: createAssistant };
});
