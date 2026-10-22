/* Sprite UI toolkit: DOM helper, modal dialogs, menus, toasts, keymap, pixel icons. Original code. */
(function (root, factory) {
  root.AS = root.AS || {}; root.AS.ui = factory(function (n) { return root.AS[n]; });
})(window, function (dep) {
  'use strict';

  function h(tag, attrs) {
    var el = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      var v = attrs[k];
      if (v === undefined || v === null || v === false) return;
      if (k === 'class') el.className = v; else if (k === 'text') el.textContent = v;
      else if (k.slice(0, 2) === 'on') el.addEventListener(k.slice(2), v);
      else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
      else if (k === 'dataset') Object.keys(v).forEach(function (d) { el.dataset[d] = v[d]; });
      else el.setAttribute(k, v === true ? '' : v);
    });
    for (var i = 2; i < arguments.length; i++) add(el, arguments[i]);
    return el;
  }
  function add(el, c) {
    if (c === undefined || c === null || c === false) return;
    if (Array.isArray(c)) c.forEach(function (x) { add(el, x); });
    else el.appendChild(typeof c === 'string' || typeof c === 'number' ? document.createTextNode(String(c)) : c);
  }

  // ---------------------------------------------------------------- pixel icons (11x11 bitmaps; # = chrome, + = neon accent)
  var ICONS = {
    pencil: ['........##.', '.......#++#', '......#++#.', '.....#++#..', '....#++#...', '...#++#....', '..#++#.....', '.#++#......', '.#+#.......', '.##........', '...........'],
    eraser: ['...........', '......####.', '.....#++##.', '....#++#+#.', '...#++#++#.', '..#++#++#..', '..#+#++#...', '..##++#....', '...###.....', '...........', '###########'],
    bucket: ['.....##....', '....#..#...', '...#.##.#..', '..#.#..#.#.', '.#.#....##.', '#..#....#.+', '.#.#...#..+', '..##..#..++', '...#.#...++', '....#.....+', '...........'],
    line: ['..........+', '.........+.', '........+..', '.......+...', '......#....', '.....#.....', '....#......', '...#.......', '..#........', '.#.........', '#..........'],
    rect: ['...........', '.#########.', '.#+++++++#.', '.#+++++++#.', '.#+++++++#.', '.#+++++++#.', '.#+++++++#.', '.#########.', '...........', '...........', '...........'],
    ellipse: ['...........', '...#####....', '..#+++++#..', '.#+++++++#.', '.#+++++++#.', '.#+++++++#.', '.#+++++++#.', '..#+++++#..', '...#####...', '...........', '...........'],
    polygon: ['....#......', '...#+#.....', '..#+++#....', '.#+++++#...', '#+++++++#..', '#+++++++#..', '.#+++++#...', '..#####....', '...........', '...........', '...........'],
    select: ['#.#.#.#.#.#', '...........', '#.........#', '...........', '#.........#', '...........', '#.........#', '...........', '#.........#', '...........', '#.#.#.#.#.#'],
    lasso: ['...#####...', '..#.....#..', '.#.......#.', '.#.......#.', '..#.....#..', '...#####...', '....#..+...', '.....#+....', '....#+#....', '...#+..#...', '...#...#...'],
    wand: ['.......+...', '......+#+..', '.....+#+...', '....#+#....', '...#+#.....', '..#+#......', '.#+#.......', '#+#........', '+#.........', '...........', '...........'],
    move: ['.....#.....', '....###....', '.....#.....', '..#..#..#..', '.##..#..##.', '#########.#', '.##..#..##.', '..#..#..#..', '.....#.....', '....###....', '.....#.....'],
    eyedropper: ['.......###.', '......#+++#', '.....#++##.', '....#+##...', '...#+#.....', '..#+#......', '.#+#.......', '#+#........', '##.........', '#..........', '...........'],
    shade: ['...........', '.##..##..##', '.##..##..##', '...........', '##..##..##.', '##..##..##.', '...........', '.##..##..##', '.##..##..##', '...........', '...........'],
    dither: ['#.#.#.#.#.#', '.#.#.#.#.#.', '#.#.#.#.#.#', '.#.#.#.#.#.', '#.#.#.#.#.#', '.#.#.#.#.#.', '#.#.#.#.#.#', '.#.#.#.#.#.', '#.#.#.#.#.#', '.#.#.#.#.#.', '#.#.#.#.#.#'],
    gradient: ['###########', '###########', '##.#######.', '##.#.#####.', '#.#.#.#.##.', '#.#.#.#.#.#', '.#.#.#.#.#.', '.#.#.#.....', '..#.#......', '...........', '...........'],
    hand: ['....#.#.#...', '...#+#+#+#..', '...#+++++#.#', '.#.#+++++#+#', '#+##+++++++#', '#+++++++++#.', '.#+++++++#..', '..#+++++#...', '...#####....', '...........', '...........'],
    zoom: ['...####....', '..#....#...', '.#......#..', '.#..+...#..', '.#.+++..#..', '.#..+...#..', '..#....#...', '...####.#..', '........##.', '.........##', '..........#'],
    play: ['...........', '..#........', '..###......', '..#####....', '..#######..', '..#########', '..#######..', '..#####....', '..###......', '..#........', '...........'],
    stop: ['...........', '...........', '..#######..', '..#######..', '..#######..', '..#######..', '..#######..', '..#######..', '..#######..', '...........', '...........'],
    prev: ['...........', '.#.....#...', '.#...###...', '.#.#####...', '.#######...', '.#.#####...', '.#...###...', '.#.....#...', '...........', '...........', '...........'],
    next: ['...........', '...#.....#.', '...###...#.', '...#####.#.', '...#######.', '...#####.#.', '...###...#.', '...#.....#.', '...........', '...........', '...........'],
    onion: ['...........', '...###.....', '..#...#.##.', '.#..#..#..#', '.#.###.#..#', '.#..#..#..#', '..#...#.##.', '...###.....', '...........', '...........', '...........'],
    loop: ['...#####...', '..#.....#..', '.#.......#.', '.#......###', '.#.......#.', '..#.....#..', '...#####...', '...........', '...........', '...........', '...........'],
    eye: ['...........', '...........', '...#####...', '..#..#..#..', '.#..###..#.', '..#..#..#..', '...#####...', '...........', '...........', '...........', '...........'],
    lock: ['...###.....', '..#...#....', '..#...#....', '.#######...', '.#######...', '.###.###...', '.###.###...', '.#######...', '.#######...', '...........', '...........'],
    plus: ['...........', '.....#.....', '.....#.....', '.....#.....', '.....#.....', '.#########.', '.....#.....', '.....#.....', '.....#.....', '.....#.....', '...........'],
    minus: ['...........', '...........', '...........', '...........', '...........', '.#########.', '...........', '...........', '...........', '...........', '...........'],
    trash: ['...........', '...#####...', '.#########.', '...........', '..#.#.#.#..', '..#.#.#.#..', '..#.#.#.#..', '..#.#.#.#..', '..#.#.#.#..', '..#######..', '...........'],
    copy: ['...........', '.#####.....', '.#...#.....', '.#.#########', '.#.#.......#', '.#.#.......#', '.###.......#', '...#.......#', '...#.......#', '...#########', '...........'],
    up: ['...........', '.....#.....', '....###....', '...#####...', '..#######..', '....###....', '....###....', '....###....', '...........', '...........', '...........'],
    down: ['...........', '...........', '...........', '....###....', '....###....', '....###....', '..#######..', '...#####...', '....###....', '.....#.....', '...........'],
    ai: ['.....#.....', '.....#.....', '....###....', '..#######..', '#.#######.#', '..#######..', '....###....', '.....#...#.', '..#.......#', '.###....###', '..#.....#.#'],
    grid: ['.#..#..#...', '###########', '.#..#..#...', '.#..#..#...', '###########', '.#..#..#...', '.#..#..#...', '###########', '.#..#..#...', '...........', '...........'],
    tile: ['###.###.###', '#.#.#.#.#.#', '###.###.###', '...........', '###.###.###', '#.#.#.#.#.#', '###.###.###', '...........', '###.###.###', '#.#.#.#.#.#', '###.###.###'],
    symx: ['.....#.....', '.....#.....', '.##..#..##.', '.#+#.#.#+#.', '.#++###++#.', '.#+#.#.#+#.', '.##..#..##.', '.....#.....', '.....#.....', '...........', '...........'],
    symy: ['...........', '...........', '.##########', '.#++++++++#', '...........', '###########', '...........', '.#++++++++#', '.##########', '...........', '...........'],
    key: ['...###.....', '..#...#....', '..#...#....', '...###.....', '....#......', '....##.....', '....#......', '....##.....', '...........', '...........', '...........']
  };
  var iconCache = {};
  function iconURL(name, color, accent) {
    var k = name + color + accent; if (iconCache[k]) return iconCache[k];
    var rows = ICONS[name]; if (!rows) return '';
    var c = document.createElement('canvas'); c.width = rows[0].length; c.height = rows.length;
    var g = c.getContext('2d');
    for (var y = 0; y < rows.length; y++) for (var x = 0; x < rows[y].length; x++) {
      var ch = rows[y][x]; if (ch === '#') g.fillStyle = color; else if (ch === '+') g.fillStyle = accent; else continue;
      g.fillRect(x, y, 1, 1);
    }
    return (iconCache[k] = c.toDataURL());
  }
  /** <span class="ico"> element showing the bitmap icon in the theme's colours (follows CSS vars at creation time) */
  function icon(name, size) {
    var cs = getComputedStyle(document.documentElement), col = cs.getPropertyValue('--ico').trim() || '#c9d1f2', acc = cs.getPropertyValue('--ico-accent').trim() || '#18d0ff';
    var el = h('span', { class: 'ico', 'aria-hidden': 'true' });
    el.style.backgroundImage = 'url(' + iconURL(name, col, acc) + ')'; el.style.width = el.style.height = ((size || 1) * 11 * 2) + 'px';
    el.style.backgroundSize = '100% 100%'; el.dataset.name = name;
    return el;
  }

  // ---------------------------------------------------------------- toasts
  var toastBox = null;
  function toast(msg, kind) {
    if (!toastBox) { toastBox = h('div', { class: 'toasts', role: 'status', 'aria-live': 'polite' }); document.body.appendChild(toastBox); }
    var t = h('div', { class: 'toast ' + (kind || '') }, msg);
    toastBox.appendChild(t); setTimeout(function () { t.classList.add('out'); setTimeout(function () { t.remove(); }, 400); }, kind === 'error' ? 6000 : 2600);
  }

  // ---------------------------------------------------------------- modal dialogs
  var openDialogs = 0;
  /**
   * dialog({title, fields:[{id,label,type:'number'|'text'|'select'|'check'|'color'|'range'|'note'|'textarea', value, options:[[v,label]], min,max,step}], ok:'OK', cancel:true, buttons:[{label,id}]})
   * resolves values object (+ .__button) or null when cancelled
   */
  function dialog(o) {
    return new Promise(function (resolve) {
      var inputs = {}, body = h('div', { class: 'dlg-body' });
      (o.fields || []).forEach(function (f) {
        var el;
        if (f.type === 'note') { body.appendChild(h('p', { class: 'dlg-note' }, f.text || f.label)); return; }
        if (f.type === 'select') el = h('select', null, (f.options || []).map(function (op) { return h('option', { value: op[0], selected: String(op[0]) === String(f.value) }, op[1]); }));
        else if (f.type === 'check') { el = h('input', { type: 'checkbox' }); el.checked = !!f.value; }
        else if (f.type === 'textarea') { el = h('textarea', { rows: f.rows || 6, spellcheck: 'false' }); el.value = f.value || ''; }
        else { el = h('input', { type: f.type === 'color' ? 'color' : f.type === 'range' ? 'range' : f.type === 'number' ? 'number' : 'text', min: f.min, max: f.max, step: f.step }); el.value = f.value === undefined ? '' : f.value; }
        el.id = 'dlg-' + f.id; inputs[f.id] = { el: el, f: f };
        body.appendChild(h('label', { class: 'dlg-row' + (f.type === 'check' ? ' check' : ''), for: el.id }, h('span', null, f.label), el, f.hint ? h('small', null, f.hint) : null));
      });
      var back = h('div', { class: 'dlg-back' });
      var box = h('div', { class: 'dlg', role: 'dialog', 'aria-modal': 'true', 'aria-label': o.title }, h('div', { class: 'dlg-title' }, o.title), body);
      function collect(btn) {
        var v = {}; Object.keys(inputs).forEach(function (id) {
          var i = inputs[id], t = i.f.type;
          v[id] = t === 'check' ? i.el.checked : (t === 'number' || t === 'range') ? parseFloat(i.el.value) : i.el.value;
        });
        v.__button = btn; return v;
      }
      function close(val) { document.removeEventListener('keydown', onKey, true); back.remove(); openDialogs--; resolve(val); }
      function onKey(e) {
        if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(null); }
        else if (e.key === 'Enter' && e.target.tagName !== 'TEXTAREA' && e.target.tagName !== 'BUTTON') { e.preventDefault(); e.stopPropagation(); close(collect('ok')); }
        else e.stopPropagation();
      }
      var btns = h('div', { class: 'dlg-btns' });
      (o.buttons || []).forEach(function (b) { btns.appendChild(h('button', { class: 'btn', onclick: function () { close(collect(b.id)); } }, b.label)); });
      if (o.cancel !== false) btns.appendChild(h('button', { class: 'btn', onclick: function () { close(null); } }, 'Cancel'));
      btns.appendChild(h('button', { class: 'btn primary', onclick: function () { close(collect('ok')); } }, o.ok || 'OK'));
      box.appendChild(btns); back.appendChild(box); document.body.appendChild(back); openDialogs++;
      document.addEventListener('keydown', onKey, true);
      var first = box.querySelector('input,select,textarea'); if (first) { first.focus(); if (first.select && first.type !== 'color' && first.type !== 'checkbox') try { first.select(); } catch (e) {} } else btns.lastChild.focus();
    });
  }
  function isModal() { return openDialogs > 0; }
  function confirmBox(title, text, ok) { return dialog({ title: title, fields: [{ type: 'note', text: text }], ok: ok || 'OK' }).then(function (v) { return !!v; }); }

  // ---------------------------------------------------------------- menus
  /** menu spec: [{label, items:[{label, action, shortcut(fn returning string), checked(fn), disabled(fn), submenu:[...]}| '-']}] */
  function buildMenubar(spec, run, shortcutOf) {
    var bar = h('nav', { class: 'menubar', role: 'menubar' }), openEl = null, popup = null, subs = [];
    function closeSubs() { subs.forEach(function (s) { s.remove(); }); subs = []; }
    function closeAll() { closeSubs(); if (popup) { popup.remove(); popup = null; } if (openEl) openEl.classList.remove('open'); openEl = null; document.removeEventListener('mousedown', outside, true); }
    function outside(e) { var inSub = subs.some(function (s) { return s.contains(e.target); }); if (popup && !popup.contains(e.target) && !bar.contains(e.target) && !inSub) closeAll(); }
    function renderItems(items, depth) {
      var ul = h('div', { class: 'menu', role: 'menu' });
      items.forEach(function (it) {
        if (it === '-') { ul.appendChild(h('div', { class: 'sep', role: 'separator' })); return; }
        var dis = it.disabled && it.disabled(), chk = it.checked && it.checked();
        var row = h('div', { class: 'mi' + (dis ? ' disabled' : ''), role: it.checked ? 'menuitemcheckbox' : 'menuitem', 'aria-checked': it.checked ? String(!!chk) : false, tabindex: -1 },
          h('span', { class: 'chk' }, chk ? '\u25A0' : ''), h('span', { class: 'lbl' }, typeof it.label === 'function' ? it.label() : it.label),
          h('span', { class: 'sc' }, it.submenu ? '\u25B6' : (it.action && shortcutOf ? shortcutOf(it.action) : '')));
        row.addEventListener('mouseenter', function () {
          while (subs.length > depth) subs.pop().remove();
          if (!it.submenu) return;
          var sub = renderItems(typeof it.submenu === 'function' ? it.submenu() : it.submenu, depth + 1); sub.classList.add('sub');
          var r = row.getBoundingClientRect(); sub.style.left = r.right - 2 + 'px'; sub.style.top = r.top - 4 + 'px'; document.body.appendChild(sub);
          var sr = sub.getBoundingClientRect(); if (sr.right > innerWidth) sub.style.left = Math.max(0, r.left - sr.width + 2) + 'px'; if (sr.bottom > innerHeight) sub.style.top = Math.max(0, innerHeight - sr.height - 2) + 'px';
          subs.push(sub);
        });
        if (!it.submenu && !dis) row.addEventListener('click', function () { closeAll(); run(it.action, it.arg); });
        ul.appendChild(row);
      });
      return ul;
    }
    spec.forEach(function (m) {
      var btn = h('button', { class: 'mb', role: 'menuitem', 'aria-haspopup': 'true' }, m.label);
      function openMenu() {
        closeAll(); openEl = btn; btn.classList.add('open');
        popup = renderItems(typeof m.items === 'function' ? m.items() : m.items, 0);
        var r = btn.getBoundingClientRect(); popup.style.left = r.left + 'px'; popup.style.top = r.bottom + 'px'; document.body.appendChild(popup);
        document.addEventListener('mousedown', outside, true);
      }
      btn.addEventListener('click', function () { if (openEl === btn) closeAll(); else openMenu(); });
      btn.addEventListener('mouseenter', function () { if (openEl && openEl !== btn) openMenu(); });
      bar.appendChild(btn);
    });
    bar.closeAll = closeAll;
    return bar;
  }

  // ---------------------------------------------------------------- keymap
  var KEYMAP_STORE = 'amerika-sprite.keymap.v1';
  function normKey(e) {
    var k = e.key; if (k === ' ') k = 'space'; if (k.length === 1) k = k.toLowerCase();
    if (['Control', 'Shift', 'Alt', 'Meta'].indexOf(k) >= 0) return null;
    var parts = []; if (e.ctrlKey || e.metaKey) parts.push('ctrl'); if (e.altKey) parts.push('alt');
    // shift is part of the combo only for non-printable keys or when ctrl/alt present; printable shifted symbols already differ ('+' vs '=')
    if (e.shiftKey && (k.length > 1 || e.ctrlKey || e.altKey || e.metaKey || /^[a-z]$/.test(k))) parts.push('shift');
    parts.push(k.length > 1 ? k.toLowerCase() : k);
    return parts.join('+');
  }
  function Keymap(defaults) {
    this.defaults = defaults; this.map = Object.assign({}, defaults);
    try { var s = localStorage.getItem(KEYMAP_STORE); if (s) Object.assign(this.map, JSON.parse(s)); } catch (e) {}
  }
  Keymap.prototype.save = function () { try { var diff = {}; var self = this; Object.keys(this.map).forEach(function (k) { if (self.map[k] !== self.defaults[k]) diff[k] = self.map[k]; }); localStorage.setItem(KEYMAP_STORE, JSON.stringify(diff)); } catch (e) {} };
  Keymap.prototype.actionFor = function (combo) { for (var a in this.map) if (this.map[a] === combo) return a; return null; };
  Keymap.prototype.set = function (action, combo) { var other = combo && this.actionFor(combo); if (other && other !== action) this.map[other] = ''; this.map[action] = combo; this.save(); };
  Keymap.prototype.reset = function () { this.map = Object.assign({}, this.defaults); try { localStorage.removeItem(KEYMAP_STORE); } catch (e) {} };
  function prettyKey(c) { if (!c) return ''; return c.split('+').map(function (p) { return p === 'ctrl' ? 'Ctrl' : p === 'alt' ? 'Alt' : p === 'shift' ? 'Shift' : p === 'space' ? 'Space' : p.length === 1 ? p.toUpperCase() : p.charAt(0).toUpperCase() + p.slice(1).replace('arrow', ''); }).join('+'); }

  return { h: h, icon: icon, iconURL: iconURL, ICONS: ICONS, toast: toast, dialog: dialog, confirmBox: confirmBox, isModal: isModal, buildMenubar: buildMenubar, Keymap: Keymap, normKey: normKey, prettyKey: prettyKey };
});
