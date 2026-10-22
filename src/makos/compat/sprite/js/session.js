/* Sprite: editing session = document + current frame/layer/colour/selection. Shared by UI, AI tools and RPC. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(function (n) { return require('./' + n + '.js'); });
  else { root.AS = root.AS || {}; root.AS.session = factory(function (n) { return root.AS[n]; }); }
})(typeof window !== 'undefined' ? window : globalThis, function (dep) {
  'use strict';
  var M = dep('model'), C = dep('color');

  function Session(doc) {
    this.listeners = [];
    this.setDoc(doc || new M.Doc({ w: 32, h: 32, mode: 'rgba' }));
  }
  var P = Session.prototype;
  P.setDoc = function (doc) {
    var self = this;
    this.doc = doc; this.fi = 0; this.li = doc.layers.length - 1; this.sel = null;
    this.fg = doc.palette.length > 1 ? doc.palette[1] : C.pack(0, 0, 0, 255); this.bg = 0;
    doc.onChange(function (kind) {
      if (self.fi >= doc.frames.length) self.fi = doc.frames.length - 1;
      if (self.li >= doc.layers.length) self.li = doc.layers.length - 1;
      if (self.sel && self.sel.length !== doc.w * doc.h) self.sel = null;
      self.emit(kind);
    });
    this.emit('doc');
  };
  P.onChange = function (fn) { this.listeners.push(fn); };
  P.emit = function (kind) { for (var i = 0; i < this.listeners.length; i++) this.listeners[i](kind); };
  P.layer = function () { return this.doc.layers[this.li]; };
  P.frame = function () { return this.doc.frames[this.fi]; };
  P.setFrame = function (i) { i = Math.max(0, Math.min(this.doc.frames.length - 1, i | 0)); if (i !== this.fi) { this.fi = i; this.emit('frame'); } };
  P.setLayer = function (i) { i = Math.max(0, Math.min(this.doc.layers.length - 1, i | 0)); if (i !== this.li) { this.li = i; this.emit('layer'); } };
  P.setSelection = function (m) { this.sel = m; this.emit('selection'); };
  P.setFg = function (c) { this.fg = c >>> 0; this.emit('color'); };
  P.fgValue = function () { return this.doc.rgbaToValue(this.fg); };
  P.celBuf = function () { return this.doc.celAt(this.li, this.fi); };
  P.compositeCurrent = function () { return this.doc.composite(this.fi); };
  return { Session: Session };
});
