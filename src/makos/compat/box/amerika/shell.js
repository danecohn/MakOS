/* MakBox: thin adapter over window.amerikaStudio (the amerika-studio-webview JS bridge, see docs/studio/webview.md).
 * Outside the shell (plain browser, tests) it falls back to in-memory storage and blob downloads so the editor still works. */
(function (root) {
	"use strict";
	const NS = (root.Amerika = root.Amerika || {});

	function bytesToBase64(bytes) {
		let s = "";
		const CH = 0x8000;
		for (let i = 0; i < bytes.length; i += CH) s += String.fromCharCode.apply(null, bytes.subarray(i, i + CH));
		return root.btoa(s);
	}
	function base64ToBytes(b64) {
		const s = root.atob(b64);
		const out = new Uint8Array(s.length);
		for (let i = 0; i < s.length; i++) out[i] = s.charCodeAt(i);
		return out;
	}
	async function blobToBase64(blob) {
		return bytesToBase64(new Uint8Array(await blob.arrayBuffer()));
	}

	const S = root.amerikaStudio || null;
	const memory = {};
	const SONG_FILTERS = [{ name: "BeepBox songs", patterns: ["*.json", "*.beepbox"] }, { name: "All files", patterns: ["*"] }];

	const shell = {
		available: !!S,
		info: S ? S.info : { app: "box", version: "dev", projectDir: "", shell: "none" },
		bytesToBase64: bytesToBase64, base64ToBytes: base64ToBytes,

		async openSongDialog() {
			if (S) return S.fs.open({ title: "Open song", filters: SONG_FILTERS });
			return new Promise(function (resolve) {
				const i = document.createElement("input"); i.type = "file"; i.accept = ".json,.beepbox";
				i.onchange = async function () { const f = i.files[0]; resolve(f ? { path: f.name, name: f.name, binary: false, data: await f.text() } : null); };
				i.click();
			});
		},
		/** Save a text file through the native dialog. Resolves {path, name} or null. */
		async saveText(name, text, title) {
			if (S) return S.fs.save({ title: title || "Save song", suggestedName: name, data: text, encoding: "utf8", filters: SONG_FILTERS });
			const a = document.createElement("a"); a.download = name; a.href = URL.createObjectURL(new Blob([text])); a.click();
			return { path: name, name: name };
		},
		async saveBlob(blob, name, title) {
			const filters = /\.wav$/i.test(name) ? [{ name: "WAV audio", patterns: ["*.wav"] }] : /\.mp3$/i.test(name) ? [{ name: "MP3 audio", patterns: ["*.mp3"] }] : /\.mid$/i.test(name) ? [{ name: "MIDI", patterns: ["*.mid", "*.midi"] }] : [{ name: "All files", patterns: ["*"] }];
			if (S) return S.fs.save({ title: title || "Save file", suggestedName: name, data: await blobToBase64(blob), encoding: "base64", filters: filters });
			const a = document.createElement("a"); a.download = name; a.href = URL.createObjectURL(blob); a.click();
			return { path: name, name: name };
		},
		/** Write inside ~/Studio/Box. data is a string (utf8) or Uint8Array. */
		async writeProject(rel, data, overwrite) {
			const bin = typeof data !== "string";
			const payload = bin ? bytesToBase64(data) : data;
			if (S) return S.fs.writeProject(rel, payload, { encoding: bin ? "base64" : "utf8", overwrite: overwrite !== false });
			memory[rel] = data; return { path: "(memory)/" + rel };
		},
		async readProject(rel, binary) {
			if (S) {
				const dir = S.info && S.info.projectDir;
				const r = await S.fs.readFile(dir ? dir.replace(/\/+$/, "") + "/" + rel : rel, { binary: !!binary });
				return r && r.data != null ? r.data : r;
			}
			if (!(rel in memory)) throw new Error("not found: " + rel);
			return memory[rel];
		},
		async listProject(dir) {
			if (S) return S.fs.listProject(dir || ".");
			return Object.keys(memory).map(function (n) { return { name: n, dir: false, size: 0 }; });
		},
		async recent() { return S ? S.recent.list() : []; },
		async recentAdd(p) { return S ? S.recent.add(p) : null; },
		async readFile(path, binary) { return S ? S.fs.readFile(path, { binary: !!binary }) : null; },
		setTitle(t) { if (S) S.window.setTitle(t).catch(function () {}); else document.title = t + " - MakBox"; },
		setDirty(d) { if (S) S.window.setDirty(!!d).catch(function () {}); },
	};
	NS.shell = shell;
})(typeof window !== "undefined" ? window : globalThis);
