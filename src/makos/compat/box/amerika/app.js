/* MakBox: start-up, toolbar, file handling, autosave, export dialogs. Glues BeepBox's editor to the Amerika layer. */
(function (root) {
	"use strict";
	const NS = (root.Amerika = root.Amerika || {});
	const B = root.beepbox;
	const $ = function (id) { return document.getElementById(id); };
	const shell = NS.shell;
	const ST = {}; // exposed for tests and debugging: root.Amerika.state

	let doc = null, editor = null, host = null, tools = null, composer = null;
	let currentPath = null, currentName = "Untitled", savedHash = "", lastHash = "", dirty = false;
	let changeTimer = null, autosaveTimer = null, opening = false;

	function lsGet(k) { try { return root.localStorage.getItem(k); } catch (e) { return null; } }
	function lsSet(k, v) { try { root.localStorage.setItem(k, v); } catch (e) { /* ignore */ } }
	const sleep = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };
	const nextFrame = function () { return Promise.race([new Promise(function (r) { requestAnimationFrame(function () { setTimeout(r, 0); }); }), sleep(250)]); };

	// ---------------------------------------------------------------- first-run preferences (must precede the editor)
	if (!lsGet("layout")) lsSet("layout", "long");
	if (!lsGet("colorTheme")) lsSet("colorTheme", "amerika");
	// Keep the song out of the address bar: undo history lives in sessionStorage instead of the (file://) URL.
	if (lsGet("displayBrowserUrl") == null) lsSet("displayBrowserUrl", "false");
	NS.theme.install();

	// ---------------------------------------------------------------- BeepBox's export "Save File" goes through the shell dialog
	root.amerikaSaveBlob = function (blob, name) {
		shell.saveBlob(blob, name, "Export " + name).then(function (r) { if (r) toast("Saved " + (r.path || r.name)); }).catch(function (e) { toast("Could not save: " + (e && e.message || e), true); });
	};

	// ---------------------------------------------------------------- small UI helpers
	let toastTimer = null;
	function toast(text, bad) {
		const b = $("amBanner");
		b.textContent = text; b.style.borderColor = bad ? "var(--am-bad)" : "var(--am-cyan)"; b.classList.add("open");
		clearTimeout(toastTimer); toastTimer = setTimeout(function () { b.classList.remove("open"); }, bad ? 7000 : 3200);
	}
	function banner(text, buttons) {
		const b = $("amBanner"); b.textContent = ""; b.style.borderColor = "var(--am-amber)";
		const s = document.createElement("span"); s.textContent = text; b.appendChild(s);
		buttons.forEach(function (x) { const bt = document.createElement("button"); bt.className = "am-btn"; bt.textContent = x.label; bt.addEventListener("click", function () { b.classList.remove("open"); x.run(); }); b.appendChild(bt); });
		b.classList.add("open"); clearTimeout(toastTimer);
	}
	function modal(build) {
		const m = $("amModal"), card = $("amCard"); card.textContent = "";
		const close = function () { m.classList.remove("open"); };
		build(card, close);
		m.classList.add("open");
		m.onclick = function (e) { if (e.target === m && !m.dataset.locked) close(); };
		return close;
	}
	function h(tag, props, kids) {
		const e = document.createElement(tag);
		Object.keys(props || {}).forEach(function (k) { if (k === "text") e.textContent = props[k]; else if (k === "class") e.className = props[k]; else e.setAttribute(k, props[k]); });
		(kids || []).forEach(function (c) { e.appendChild(c); });
		return e;
	}
	// BeepBox only repaints after user input events; after programmatic changes ask its notifier to run on the next frame.
	function refresh() { requestAnimationFrame(function () { try { if (doc) doc.notifier.notifyWatchers(); } catch (e) { /* ignore */ } }); }
	function closeMenus() { document.querySelectorAll(".am-drop.open").forEach(function (d) { d.classList.remove("open"); }); }
	function toggleMenu(id) { const d = $(id); const was = d.classList.contains("open"); closeMenus(); if (!was) d.classList.add("open"); return !was; }

	// ---------------------------------------------------------------- song files
	function songHash() { return doc.song.toBase64String(); }
	function songToText() { return JSON.stringify(doc.song.toJsonObject(), null, 1) + "\n"; }
	function stem(name) { return String(name || "song").replace(/\.(json|beepbox)$/i, ""); }
	function parseSongText(text) {
		const t = String(text).trim();
		if (!t) throw new Error("the file is empty");
		if (t[0] === "{") {
			const j = JSON.parse(t);
			if (!j || !Array.isArray(j.channels)) throw new Error("this JSON is not a BeepBox song (no 'channels')");
			const s = new B.Song(); s.fromJsonObject(j); return s;
		}
		return new B.Song(t.replace(/^.*#/, ""));
	}
	function setBaseline(name, path) {
		currentName = name || "Untitled"; currentPath = path || null;
		savedHash = songHash(); lastHash = savedHash; dirty = false; refreshTitle();
	}
	function refreshTitle() {
		shell.setTitle(currentName + (dirty ? " *" : ""));
		shell.setDirty(dirty);
		const s = $("amStatus"); s.textContent = currentPath ? currentPath : currentName; s.classList.toggle("dirty", dirty);
	}
	function onChanged() {
		clearTimeout(changeTimer);
		changeTimer = setTimeout(function () {
			if (!doc) return;
			let h2; try { h2 = songHash(); } catch (e) { return; }
			if (h2 === lastHash) return;
			lastHash = h2; dirty = h2 !== savedHash; refreshTitle();
			clearTimeout(autosaveTimer);
			if (dirty) autosaveTimer = setTimeout(autosave, 5000);
		}, 250);
	}
	async function autosave() {
		try { await shell.writeProject("autosave/autosave.json", songToText(), true); ST.lastAutosave = Date.now(); } catch (e) { /* project folder not writable: ignore quietly */ }
	}
	function confirmDiscard() { return !dirty || root.confirm("This song has unsaved changes. Discard them?"); }

	function loadSong(song, name, path) {
		doc.record(new B.ChangeSong(doc, song.toBase64String()), false, true);
		doc.goBackToStart();
		refresh();
		setBaseline(name, path);
		if (composer) composer.lastTurnCommits = 0;
	}
	async function openFile(file) {
		if (!file) return;
		if (file.binary) { toast("That is an audio/MIDI file; MakBox opens .json and .beepbox songs.", true); return; }
		if (!confirmDiscard()) return;
		try {
			const song = parseSongText(file.data);
			loadSong(song, stem(file.name), file.path);
			if (file.path) shell.recentAdd(file.path).catch(function () {});
			toast("Opened " + file.name);
		} catch (e) { toast("Could not open " + (file.name || "file") + ": " + (e && e.message || e), true); }
	}
	async function openDialog() { try { const f = await shell.openSongDialog(); if (f) await openFile(f); } catch (e) { toast("Open failed: " + (e && e.message || e), true); } }
	function newSong() {
		if (!confirmDiscard()) return;
		doc.record(new B.ChangeSong(doc, ""), false, true);
		doc.goBackToStart();
		refresh();
		setBaseline("Untitled", null);
	}
	function projectRelative(path) {
		const dir = shell.info && shell.info.projectDir;
		if (!dir || !path || path.indexOf(dir.replace(/\/+$/, "") + "/") !== 0) return null;
		return path.slice(dir.replace(/\/+$/, "").length + 1);
	}
	async function save(forceAs) {
		try {
			const text = songToText();
			let rel = !forceAs && currentPath ? projectRelative(currentPath) : null;
			if (rel) { await shell.writeProject(rel, text, true); }
			else {
				const r = await shell.saveText(stem(currentName) + ".beepbox", text, forceAs ? "Save song as" : "Save song");
				if (!r) return false;
				currentPath = r.path || null; currentName = stem(r.name || currentName);
				if (r.path) shell.recentAdd(r.path).catch(function () {});
			}
			savedHash = songHash(); lastHash = savedHash; dirty = false; refreshTitle(); toast("Saved");
			return true;
		} catch (e) { toast("Save failed: " + (e && e.message || e), true); return false; }
	}

	// ---------------------------------------------------------------- recent
	async function fillRecent() {
		const drop = $("amRecentDrop"); drop.textContent = "";
		let items = []; try { items = await shell.recent(); } catch (e) { /* ignore */ }
		items = (items || []).filter(function (p) { return /\.(json|beepbox)$/i.test(p); });
		if (!items.length) { drop.appendChild(h("div", { class: "am-empty", text: "No recent songs yet" })); return; }
		items.forEach(function (p) {
			const b = h("button", { text: p.split("/").pop(), title: p });
			b.addEventListener("click", async function () { closeMenus(); try { const f = await shell.readFile(p, false); if (f) await openFile(f); } catch (e) { toast("Cannot open " + p + ": " + (e && e.message || e), true); } });
			drop.appendChild(b);
		});
		const sep = h("div", { class: "am-sep" }); drop.appendChild(sep);
		const clr = h("button", { text: "Clear list" }); clr.addEventListener("click", function () { closeMenus(); if (root.amerikaStudio) root.amerikaStudio.recent.clear(); }); drop.appendChild(clr);
	}

	// ---------------------------------------------------------------- export
	function openBeepBoxExport(format) {
		lsSet("exportFormat", format);
		doc.openPrompt("export");
		doc.notifier.changed();
		refresh();
	}
	function exportGameDialog() {
		modal(function (card, close) {
			card.appendChild(h("h2", { text: "Export for game" }));
			card.appendChild(h("p", { text: "Renders the song's intro plus one seamless loop and writes a folder into your Studio/Box project: a WAV with embedded loop points, an Ogg Vorbis copy when ffmpeg is installed, loop metadata JSON, the editable song, and Godot import presets." }));
			const name = h("input", { type: "text", value: stem(currentName === "Untitled" ? "music" : currentName) });
			const sr = h("select", {}, [h("option", { value: "44100", text: "44100 Hz" }), h("option", { value: "48000", text: "48000 Hz" })]);
			const norm = h("input", { type: "checkbox", checked: "checked" });
			const ogg = h("input", { type: "checkbox", checked: "checked" });
			const f1 = h("div", { class: "am-field" }, [h("label", { text: "Name" }), name]);
			const f2 = h("div", { class: "am-field" }, [h("label", { text: "Sample rate" }), sr]);
			const f3 = h("div", { class: "am-field" }, [h("label", { text: "Normalize to -1 dBFS" }), norm]);
			const f4 = h("div", { class: "am-field" }, [h("label", { text: "Also write .ogg" }), ogg]);
			[f1, f2, f3, f4].forEach(function (f) { card.appendChild(f); });
			const prog = h("div", { class: "am-progress" }, [h("i")]); card.appendChild(prog);
			const msg = h("p", { text: "" }); card.appendChild(msg);
			const go = h("button", { class: "am-btn am-accent", text: "Export" }), cancel = h("button", { class: "am-btn", text: "Close" });
			cancel.addEventListener("click", close);
			go.addEventListener("click", async function () {
				go.disabled = true; prog.style.display = "block"; msg.textContent = "";
				try {
					const res = await exportGame({ name: name.value, sampleRate: parseInt(sr.value, 10), normalizeDb: norm.checked ? -1 : null, ogg: ogg.checked }, function (f, label) { prog.firstChild.style.width = Math.round(f * 100) + "%"; msg.textContent = label; });
					msg.textContent = "Done: " + res.dir + " (" + res.files.join(", ") + ")" + (res.ogg !== "ok" && ogg.checked ? ". Ogg: " + res.ogg : "");
				} catch (e) { msg.textContent = "Export failed: " + (e && e.message || e); }
				go.disabled = false;
			});
			card.appendChild(h("div", { class: "am-actions" }, [cancel, go]));
		});
	}
	function oggIO() {
		// The ffmpeg helper (amerika-box-ogg --watch, started by the amerika-box launcher) watches exports/.jobs/.
		return async function requestOgg(job) {
			const id = "j" + Date.now().toString(36);
			await shell.writeProject("exports/.jobs/" + id + ".job.json", JSON.stringify(job), true);
			const t0 = Date.now();
			for (;;) {
				await sleep(400);
				let names = [];
				try { names = (await shell.listProject("exports/.jobs")).map(function (f) { return f.name; }); } catch (e) { /* ignore */ }
				if (names.indexOf(id + ".result.json") >= 0) {
					try { return JSON.parse(await shell.readProject("exports/.jobs/" + id + ".result.json", false)); } catch (e) { return { ok: false, error: "unreadable helper result" }; }
				}
				const picked = names.indexOf(id + ".working.json") >= 0;
				if (!picked && Date.now() - t0 > 6000) return { ok: false, error: "no Ogg helper is running (it needs ffmpeg; start MakBox from its launcher). The WAV and metadata were written; run amerika-box-ogg on the WAV later." };
				if (Date.now() - t0 > 180000) return { ok: false, error: "the Ogg helper timed out" };
			}
		};
	}
	async function exportGame(opts, progress) {
		const res = await NS.exporter.buildGameBundle(B, doc.song, Object.assign({ yieldEvery: 40 }, opts), {
			write: function (rel, data) { return shell.writeProject(rel, data, true); },
			requestOgg: opts.ogg === false ? null : oggIO(),
			progress: progress,
		});
		toast("Game bundle written to " + res.dir);
		return res;
	}

	// ---------------------------------------------------------------- about
	function aboutDialog() {
		const A = NS.about;
		modal(function (card, close) {
			card.appendChild(h("h2", { text: "MakBox" }));
			card.appendChild(h("p", { text: "MakBox " + A.appVersion + " is a desktop copy of BeepBox " + A.beepboxVersion + " with the Amerika Composer, an AI music assistant that writes and edits songs through BeepBox's own song format." }));
			card.appendChild(h("p", { text: "BeepBox is created by John Nesky and contributors, and is distributed under the MIT licence (reproduced below). MakBox is not affiliated with, or endorsed by, BeepBox or John Nesky. The hosted website beepbox.co is a separate service." }));
			card.appendChild(h("p", { text: "Source: github.com/johnnesky/beepbox at commit " + A.beepboxCommit.slice(0, 10) + ". Amerika additions: Copyright Amerika LLC. The MP3 encoder (lamejs, based on LAME) is used under the LGPL." }));
			card.appendChild(h("p", { text: "Your songs stay on this computer. The composer talks only to the local Studio bridge; no API key is stored in this app, and BeepBox's online features (URL shortener, embeds, service worker) are removed." }));
			card.appendChild(h("pre", { text: A.beepboxLicense }));
			const ok = h("button", { class: "am-btn am-accent", text: "Close" }); ok.addEventListener("click", close);
			card.appendChild(h("div", { class: "am-actions" }, [ok]));
		});
	}

	// ---------------------------------------------------------------- the editor hook
	function init(e) {
		editor = e.detail.editor; doc = e.detail.doc;
		let turnCommits = 0, inTurn = false;
		host = {
			yieldEvery: 30,
			silent: false,
			isCanceled: function () { return false; },
			getSong: function () { return doc.song; },
			commit: function (song, label) {
				doc.record(new B.ChangeSong(doc, song.toBase64String()), false, false);
				if (inTurn) turnCommits++;
				ST.lastLabel = label;
				refresh();
			},
			beginTurn: function () { turnCommits = 0; inTurn = true; },
			endTurn: function () { inTurn = false; return turnCommits; },
			play: function (o) {
				const synth = doc.synth;
				if (synth.playing) doc.performance.pause();
				synth.goToBar((o && o.fromBar) || 0);
				synth.snapToBar();
				doc.performance.play();
				try { editor.updatePlayButton(); } catch (err) { /* ignore */ }
				doc.notifier.changed();
				refresh();
			},
			stop: function () { doc.performance.pause(); try { editor.updatePlayButton(); } catch (err) { /* ignore */ } doc.notifier.changed(); refresh(); },
			undo: async function (n) { for (let i = 0; i < n; i++) { doc.undo(); await sleep(60); } doc.notifier.changed(); refresh(); await sleep(80); },
		};
		const base = NS.songtools.create(B, host);
		// every mutating tool gets its own history step: wait a frame after it so BeepBox's batched history update runs
		const rawRun = base.run;
		tools = Object.assign({}, base, {
			run: async function (name, input) {
				const def = base.definitions.filter(function (d) { return d.name === name; })[0];
				const out = await rawRun(name, input);
				if (def && def.mutates) { await nextFrame(); onChanged(); }
				return out;
			},
		});
		composer = new NS.Composer({ root: $("composer"), tools: tools, host: host, shell: shell, onTurnEnd: function () { onChanged(); } });
		const S = root.amerikaStudio;
		NS.rpc.install({ B: B, host: host, tools: tools, composer: composer, shell: shell, exporter: NS.exporter, audio: NS.audio, S: S });
		if (S) S.onOpen = openFile;

		doc.notifier.watch(onChanged);
		setBaseline("Untitled", null);
		wireToolbar();
		ST.doc = doc; ST.editor = editor; ST.host = host; ST.tools = tools; ST.composer = composer; ST.B = B;
		if (S) restoreOffer();
	}

	async function restoreOffer() {
		await sleep(900);
		if (opening || dirty || currentPath) return;
		let list = [];
		try { list = await shell.listProject("autosave"); } catch (e) { return; }
		if (!list.some(function (f) { return f.name === "autosave.json" && f.size > 200; })) return;
		banner("An autosaved song from your last session is available.", [
			{ label: "Restore", run: async function () { try { const t = await shell.readProject("autosave/autosave.json", false); loadSong(parseSongText(t), "Recovered song", null); dirty = true; refreshTitle(); toast("Autosave restored. Use Save to keep it."); } catch (err) { toast("Could not restore: " + (err && err.message || err), true); } } },
			{ label: "Dismiss", run: function () {} },
		]);
	}

	function wireToolbar() {
		$("amNew").addEventListener("click", newSong);
		$("amOpen").addEventListener("click", openDialog);
		$("amSave").addEventListener("click", function () { save(false); });
		$("amSaveAs").addEventListener("click", function () { save(true); });
		$("amRecent").addEventListener("click", function (ev) { ev.stopPropagation(); if (toggleMenu("amRecentDrop")) fillRecent(); });
		$("amExport").addEventListener("click", function (ev) { ev.stopPropagation(); toggleMenu("amExportDrop"); });
		document.querySelectorAll("#amExportDrop button").forEach(function (b) {
			b.addEventListener("click", function () { closeMenus(); const f = b.getAttribute("data-export"); if (f === "game") exportGameDialog(); else openBeepBoxExport(f); });
		});
		$("amToggle").addEventListener("click", function () {
			const app = $("amerikaApp"); const hidden = app.classList.toggle("no-composer");
			$("amToggle").setAttribute("aria-pressed", hidden ? "false" : "true");
			root.dispatchEvent(new Event("resize"));
		});
		$("amTheme").addEventListener("click", function () {
			const names = NS.theme.names; const cur = doc.prefs.colorTheme;
			const next = names[(names.indexOf(cur) + 1) % names.length];
			doc.prefs.colorTheme = next; B.ColorConfig.setTheme(next); doc.prefs.save(); doc.notifier.changed();
			toast("Theme: " + next);
		});
		$("amAbout").addEventListener("click", aboutDialog);
		document.addEventListener("click", closeMenus);
		// desktop shortcuts (BeepBox itself maps Ctrl+S to its export dialog and Ctrl+O to import)
		root.addEventListener("keydown", function (ev) {
			if (!(ev.ctrlKey || ev.metaKey) || ev.altKey) return;
			const k = ev.key.toLowerCase();
			if (k === "s") { ev.preventDefault(); ev.stopImmediatePropagation(); save(ev.shiftKey); }
			else if (k === "o") { ev.preventDefault(); ev.stopImmediatePropagation(); openDialog(); }
			else if (k === "n" && !ev.shiftKey) { ev.preventDefault(); ev.stopImmediatePropagation(); newSong(); }
		}, true);
		// links must never navigate the window (the shell blocks them anyway)
		document.addEventListener("click", function (ev) { const a = ev.target && ev.target.closest && ev.target.closest("a[href]"); if (a && /^https?:/i.test(a.getAttribute("href"))) { ev.preventDefault(); toast("External links are disabled in MakBox."); } }, true);
	}

	root.addEventListener("amerika-editor-ready", init);
	function start() {
		if (!B || !B.SongEditor) { document.getElementById("beepboxEditorContainer").textContent = "The BeepBox editor failed to load."; return; }
		new B.SongEditor(document.getElementById("beepboxEditorContainer"));
	}
	NS.state = ST;
	NS.app = { start: start, exportGame: exportGame, save: save, openFile: openFile, newSong: newSong, parseSongText: parseSongText, toast: toast };
	if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})(typeof window !== "undefined" ? window : globalThis);
