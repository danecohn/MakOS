/* Development shim: a mock window.amerikaStudio for working on a Studio web app in a plain browser.
 * Load it BEFORE the app scripts when `window.amerikaStudio` is missing. Nothing here talks to the real bridge:
 * request() returns canned answers (or calls window.__studioMockRequest if the page defines it). */
(function (root) {
  "use strict";
  if (root.amerikaStudio) return;
  const store = {};
  const mock = {
    info: {app: "dev", version: "dev", projectDir: "/tmp/studio-dev", shell: "dev-shim"},
    async request(path, body) {
      if (root.__studioMockRequest) return root.__studioMockRequest(path, body);
      if (path === "/v1/status") return {status: 200, json: {key: {}, models: ["claude-sonnet-5-5"], default_model: "claude-sonnet-5-5", version: "dev", budget: {daily_tokens: 0, used_today: 0}}};
      return {status: 403, json: {type: "error", error: {type: "no_api_key", message: "dev shim: no real bridge"}}};
    },
    fs: {
      open: () => new Promise((resolve) => {
        const i = document.createElement("input"); i.type = "file";
        i.onchange = async () => { const f = i.files[0]; resolve(f ? {path: f.name, name: f.name, binary: false, data: await f.text()} : null); };
        i.click();
      }),
      save: async (o) => { const a = document.createElement("a"); a.download = o.suggestedName || "file";
        a.href = o.encoding === "base64" ? "data:application/octet-stream;base64," + o.data : URL.createObjectURL(new Blob([o.data])); a.click(); return {path: a.download, name: a.download}; },
      readFile: async (p) => { if (!(p in store)) throw new Error("path_not_allowed"); return store[p]; },
      writeProject: async (p, data) => { store[p] = {path: p, data}; return {path: "/tmp/studio-dev/" + p}; },
      listProject: async () => Object.keys(store).map((name) => ({name, dir: false, size: 0})),
    },
    recent: {list: async () => [], add: async () => ({}), clear: async () => ({})},
    window: {setTitle: async (t) => { document.title = t; }, setDirty: async () => ({}), close: async () => ({})},
    onRpc: null, onOpen: null,
  };
  root.amerikaStudio = mock;
})(typeof globalThis !== "undefined" ? globalThis : window);
