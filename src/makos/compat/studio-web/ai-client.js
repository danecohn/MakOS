/* Studio AI client for the web apps (Sprite, Box): Messages API tool-use loop through the local bridge.
 * Non-streaming (v1). The page never sees the API key or the bridge token: it calls amerikaStudio.request().
 *
 *   const ai = new amerikaStudio.AIClient({
 *     system: "You are ...", tools: [{name, description, input_schema}],
 *     run: async (name, input) => result,            // string | object | {text?, image?:{mime,base64}, images?:[...]}
 *     onEvent: (kind, data) => {}                   // 'request' | 'text' | 'tool_use' | 'tool_result' | 'usage'
 *   });
 *   const out = await ai.send("draw a slime", {images: [{mime: "image/png", base64: "..."}]});
 *   // out = {text, toolCalls, usage, stopped, hitMaxTurns, stopReason}
 *
 * Errors are Error objects with .code in: bridge_down, bridge_auth, no_key, key_rejected, budget, rate_limit, overloaded,
 * invalid_request, too_large, server, stopped. 429/529 are retried with backoff (honouring retry-after).
 */
(function (root) {
  "use strict";
  const MAX_RESULT_CHARS = 60000;

  function apiError(message, code, status, retryAfter) {
    const e = new Error(message);
    e.code = code; e.status = status; e.retryAfter = retryAfter;
    return e;
  }

  function mapError(status, body, retryAfter) {
    const err = (body && body.error) || {};
    const t = err.type || "";
    const msg = err.message || "request failed";
    if (t === "bridge_auth_error") return apiError("The Studio bridge refused this app. Run \"amerika-studio ensure\".", "bridge_auth", status);
    if (t === "no_api_key") return apiError("No Anthropic key is set. Open Studio and choose \"Set up Anthropic key\".", "no_key", status);
    if (t === "budget_exceeded") return apiError(msg, "budget", status);
    if (status === 401 || t === "authentication_error") return apiError("Anthropic rejected the key. Check it in Studio.", "key_rejected", status);
    if (status === 403 || t === "permission_error") return apiError("Anthropic denied this request: " + msg, "key_rejected", status);
    if (status === 413 || t === "request_too_large") return apiError("The request was too large. " + msg, "too_large", status);
    if (status === 429 || t === "rate_limit_error") return apiError("Rate limited by Anthropic; try again in a moment.", "rate_limit", status, retryAfter);
    if (status === 529 || t === "overloaded_error") return apiError("Anthropic is overloaded right now; try again shortly.", "overloaded", status, retryAfter);
    if (status === 400 || t === "invalid_request_error") return apiError("Invalid request: " + msg, "invalid_request", status);
    return apiError("Upstream error (" + status + "): " + msg, "server", status, retryAfter);
  }

  function resultBlocks(result) {
    if (result && typeof result === "object" && !Array.isArray(result) && (result.image || result.images)) {
      const rest = Object.assign({}, result);
      const images = (rest.images || []).slice();
      delete rest.images;
      if (rest.image) { images.unshift(rest.image); delete rest.image; }
      const blocks = [];
      for (const img of images) {
        if (img && img.base64) blocks.push({type: "image", source: {type: "base64", media_type: img.mime || "image/png", data: img.base64}});
      }
      if (Object.keys(rest).length) blocks.unshift({type: "text", text: JSON.stringify(rest).slice(0, MAX_RESULT_CHARS)});
      return blocks.length ? blocks : [{type: "text", text: "ok"}];
    }
    let text = typeof result === "string" ? result : result === undefined || result === null ? "ok" : JSON.stringify(result);
    if (text.length > MAX_RESULT_CHARS) text = text.slice(0, MAX_RESULT_CHARS) + "\n[truncated]";
    return [{type: "text", text}];
  }

  const textOf = (blocks) => blocks.filter((b) => b && b.type === "text").map((b) => b.text).join("");

  class AIClient {
    constructor(opts) {
      opts = opts || {};
      this.model = opts.model || null;
      this.system = opts.system || "";
      this.tools = opts.tools || [];
      this.run = opts.run || (async () => { throw new Error("no tool handler"); });
      this.maxTurns = opts.maxTurns || 12;
      this.maxTokens = opts.maxTokens || 4096;
      this.retries = opts.retries === undefined ? 4 : opts.retries;
      this.onEvent = opts.onEvent || (() => {});
      this.request = opts.request || ((p, b, o) => root.amerikaStudio.request(p, b, o));
      this.sleep = opts.sleep || ((ms) => new Promise((r) => setTimeout(r, ms)));
      this.messages = [];
      this._stop = false;
    }

    stop() { this._stop = true; }
    reset() { this.messages = []; this._stop = false; }

    async defaultModel() {
      if (this.model) return this.model;
      try {
        const r = await this.request("/v1/status");
        if (r.status === 200 && r.json.default_model) { this.model = r.json.default_model; return this.model; }
      } catch (e) { /* fall through */ }
      return "claude-sonnet-5-5";
    }

    async post(payload) {
      let attempt = 0;
      for (;;) {
        if (this._stop) throw apiError("Stopped.", "stopped");
        let r;
        try {
          r = await this.request("/v1/messages", payload);
        } catch (e) {
          throw apiError("Cannot reach the Studio bridge: " + (e.message || e.error || e), "bridge_down");
        }
        if (r.status < 400) return r.json;
        const ra = r.headers && r.headers["retry-after"] ? parseFloat(r.headers["retry-after"]) : undefined;
        const err = mapError(r.status, r.json, ra);
        const retryable = [429, 529, 502, 503].includes(r.status) && !["budget", "bridge_auth", "no_key"].includes(err.code);
        if (retryable && attempt < this.retries) {
          const delay = ra ? ra * 1000 : Math.min(30000, 2 ** attempt * 1000) * (0.75 + Math.random() / 2);
          attempt += 1;
          await this.sleep(Math.min(delay, 60000));
          continue;
        }
        throw err;
      }
    }

    async send(text, opts) {
      opts = opts || {};
      this._stop = false;
      const content = [];
      for (const img of opts.images || []) {
        content.push({type: "image", source: {type: "base64", media_type: img.mime || "image/png", data: img.base64}});
      }
      content.push({type: "text", text});
      const startLen = this.messages.length;
      this.messages.push({role: "user", content});
      const out = {text: "", toolCalls: [], usage: {input_tokens: 0, output_tokens: 0}, stopped: false, hitMaxTurns: false, stopReason: null};
      const model = await this.defaultModel();
      try {
        for (let turn = 0; ; turn++) {
          if (turn >= this.maxTurns) { out.hitMaxTurns = true; break; }
          if (this._stop) { out.stopped = true; break; }
          const payload = {model, max_tokens: this.maxTokens, messages: this.messages};
          if (this.system) payload.system = this.system;
          if (this.tools.length) payload.tools = this.tools;
          this.onEvent("request", {turn: turn + 1});
          const resp = await this.post(payload);
          const u = resp.usage || {};
          out.usage.input_tokens += u.input_tokens || 0;
          out.usage.output_tokens += u.output_tokens || 0;
          this.onEvent("usage", Object.assign({}, out.usage));
          const blocks = resp.content || [];
          this.messages.push({role: "assistant", content: blocks});
          out.stopReason = resp.stop_reason;
          const chunk = textOf(blocks);
          if (chunk) { out.text = chunk; this.onEvent("text", chunk); }
          const uses = blocks.filter((b) => b.type === "tool_use");
          if (resp.stop_reason !== "tool_use" || !uses.length) return out;
          const results = [];
          for (const use of uses) {
            if (this._stop) {
              results.push({type: "tool_result", tool_use_id: use.id, is_error: true, content: [{type: "text", text: "Stopped by the user before this tool ran."}]});
              out.stopped = true;
              continue;
            }
            this.onEvent("tool_use", {name: use.name, input: use.input, id: use.id});
            let ok = true, blocksOut;
            try { blocksOut = resultBlocks(await this.run(use.name, use.input || {}, use.id)); }
            catch (e) { ok = false; blocksOut = [{type: "text", text: "Error: " + (e && e.message ? e.message : e)}]; }
            const entry = {type: "tool_result", tool_use_id: use.id, content: blocksOut};
            if (!ok) entry.is_error = true;
            results.push(entry);
            const summary = textOf(blocksOut).slice(0, 200);
            out.toolCalls.push({name: use.name, input: use.input, ok, summary});
            this.onEvent("tool_result", {name: use.name, ok, summary});
          }
          this.messages.push({role: "user", content: results});
          if (out.stopped) break;
        }
      } catch (e) {
        if (e.code === "stopped") { out.stopped = true; return out; }
        // keep the conversation valid: drop a trailing user turn that never got an answer
        if (this.messages.length > startLen && this.messages[this.messages.length - 1].role === "user" &&
            !(this.messages[this.messages.length - 1].content || []).some((b) => b.type === "tool_result")) this.messages.pop();
        throw e;
      }
      return out;
    }
  }

  AIClient._mapError = mapError;
  AIClient._resultBlocks = resultBlocks;
  if (root.amerikaStudio) root.amerikaStudio.AIClient = AIClient;
  if (typeof module !== "undefined" && module.exports) module.exports = {AIClient};
  else root.AIClient = root.AIClient || AIClient;
})(typeof globalThis !== "undefined" ? globalThis : window);
