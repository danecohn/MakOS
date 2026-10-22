/* Injected by amerika-studio-webview at document start. Defines window.amerikaStudio (see docs/studio/webview.md).
 * Everything goes through the WebKit script-message handler "amerika"; the Python shell holds the bridge token. */
(function (root) {
  "use strict";
  if (root.amerikaStudio) return;
  const INFO = __AMERIKA_INFO__;
  const handler = root.webkit && root.webkit.messageHandlers && root.webkit.messageHandlers.amerika;
  async function call(cmd, args) {
    if (!handler) throw new Error("amerikaStudio is only available inside amerika-studio-webview");
    const raw = await handler.postMessage({cmd, args: args || {}});
    const o = JSON.parse(raw);
    if (o.error) throw Object.assign(new Error(o.error.message || o.error.code || "error"), o.error);
    return o.result;
  }
  let onRpc = null, onOpen = null;
  const studio = {
    info: INFO,
    request: (path, body, opts) => call("request", {path, body: body === undefined ? null : body, timeoutMs: opts && opts.timeoutMs}),
    fs: {
      open: (o) => call("fs.open", o || {}),
      save: (o) => call("fs.save", o || {}),
      readFile: (path, o) => call("fs.readFile", {path, binary: !!(o && o.binary)}),
      writeProject: (path, data, o) => call("fs.writeProject", {path, data, encoding: (o && o.encoding) || "utf8", overwrite: !!(o && o.overwrite)}),
      listProject: (dir) => call("fs.listProject", {path: dir || "."}),
    },
    recent: {list: () => call("recent.list"), add: (path) => call("recent.add", {path}), clear: () => call("recent.clear")},
    window: {
      setTitle: (title) => call("window.setTitle", {title: String(title)}),
      setDirty: (dirty) => call("window.setDirty", {dirty: !!dirty}),
      close: () => call("window.close"),
    },
    get onRpc() { return onRpc; },
    set onRpc(fn) { onRpc = fn; call("rpc.ready", {ready: typeof fn === "function"}).catch(() => {}); },
    get onOpen() { return onOpen; },
    set onOpen(fn) { onOpen = fn; call("open.ready", {ready: typeof fn === "function"}).catch(() => {}); },
    /* called by the shell */
    __dispatchRpc(id, method, params) {
      Promise.resolve().then(() => {
        if (typeof onRpc !== "function") throw Object.assign(new Error("the app is not ready"), {code: -32004});
        return onRpc(method, params);
      }).then(
        (result) => call("rpc.result", {id, result: result === undefined ? {ok: true} : result}),
        (err) => call("rpc.result", {id, error: {code: (err && err.code) || -32000, message: String((err && err.message) || err)}}));
    },
    __dispatchOpen(file) {
      Promise.resolve().then(() => (typeof onOpen === "function" ? onOpen(file) : null)).catch((e) => console.error("onOpen failed", e));
    },
  };
  Object.defineProperty(root, "amerikaStudio", {value: studio, writable: false, configurable: false});
  /* defence in depth: the page may only load local resources (navigation is also restricted by the shell) */
  try {
    const meta = document.createElement("meta");
    meta.httpEquiv = "Content-Security-Policy";
    meta.content = "default-src file: data: blob: 'unsafe-inline' 'unsafe-eval'; connect-src file: data: blob:; worker-src file: blob: data:";
    const head = document.head || document.documentElement.appendChild(document.createElement("head"));
    head.appendChild(meta);
  } catch (e) { /* ignore */ }
})(typeof globalThis !== "undefined" ? globalThis : window);
