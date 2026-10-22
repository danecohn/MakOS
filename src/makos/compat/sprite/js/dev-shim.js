/* Sprite: minimal stand-in for window.amerikaStudio when the page is opened in a plain browser (development only).
   The real shell (amerika-studio-webview) injects the real thing before this file runs, so this does nothing there. */
(function () {
  'use strict';
  if (window.amerikaStudio) return;
  function pick(accept) {
    return new Promise(function (resolve) {
      var i = document.createElement('input'); i.type = 'file'; i.accept = accept || '';
      i.onchange = function () {
        var f = i.files[0]; if (!f) return resolve(null);
        var r = new FileReader(); var text = /\.(json|gpl|hex|txt)$/i.test(f.name);
        r.onload = function () { resolve({ path: f.name, name: f.name, binary: !text, data: text ? r.result : r.result.split(',')[1] }); };
        if (text) r.readAsText(f); else r.readAsDataURL(f);
      };
      i.click();
    });
  }
  function download(name, data, enc) {
    var bytes = enc === 'base64' ? Uint8Array.from(atob(data), function (c) { return c.charCodeAt(0); }) : new TextEncoder().encode(data);
    var a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([bytes])); a.download = name; a.click();
  }
  window.amerikaStudio = {
    info: { app: 'sprite', version: 'dev', projectDir: '/dev/null', shell: 'dev-shim' },
    request: function () { return Promise.reject({ error: 'bridge_unreachable', message: 'no bridge in the dev shim' }); },
    fs: {
      open: function () { return pick(); }, save: function (o) { download(o.suggestedName || 'file', o.data, o.encoding); return Promise.resolve({ path: o.suggestedName, name: o.suggestedName }); },
      readFile: function () { return Promise.reject(new Error('path_not_allowed')); }, writeProject: function (p, d, o) { download(p.split('/').pop(), d, o && o.encoding); return Promise.resolve({ path: p }); }, listProject: function () { return Promise.resolve([]); }
    },
    recent: { list: function () { return Promise.resolve([]); }, add: function () { return Promise.resolve(); }, clear: function () { return Promise.resolve(); } },
    window: { setTitle: function (t) { document.title = t; }, setDirty: function () {}, close: function () { window.close(); } }
  };
})();
