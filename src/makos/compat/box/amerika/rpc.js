/* MakBox: control endpoint for Amerika Agent.
 * Installs window.amerikaStudio.onRpc with handlers for the box.* tools in src/os/studio/tools.json:
 *   song.get, song.set, song.compose_from_description, song.apply_change, play, stop, export.wav, app.prompt
 * Methods arrive WITHOUT the "box." prefix. Results are plain JSON; errors carry a JSON-RPC code in .code. */
(function (root) {
	"use strict";
	const NS = (root.Amerika = root.Amerika || {});

	function rpcError(code, message) { return Object.assign(new Error(message), { code: code }); }
	function need(params, key, type) {
		if (!params || typeof params !== "object" || params[key] === undefined || params[key] === null) throw rpcError(-32602, "missing parameter '" + key + "'");
		if (typeof params[key] !== type) throw rpcError(-32602, "parameter '" + key + "' must be a " + type);
		return params[key];
	}
	function checkRelPath(p) {
		if (typeof p !== "string" || !p) throw rpcError(-32602, "path must be a non-empty string");
		if (p.indexOf("\0") >= 0 || p.length > 512) throw rpcError(-32602, "invalid path");
		if (/^([\\/~]|[A-Za-z]:)/.test(p)) throw rpcError(-32003, "absolute paths are not allowed: use a path relative to the project folder (~/Studio/Box)");
		if (p.replace(/\\/g, "/").split("/").indexOf("..") >= 0) throw rpcError(-32003, "'..' is not allowed in project paths");
		return p.replace(/\\/g, "/");
	}
	function withTimeout(promise, seconds, onTimeout) {
		let t;
		const timer = new Promise(function (_, reject) { t = setTimeout(function () { try { onTimeout(); } catch (e) { /* ignore */ } reject(rpcError(-32000, "timeout after " + seconds + " s (the composer was stopped; the song may be partly changed, see song.get)")); }, seconds * 1000); });
		return Promise.race([promise, timer]).finally(function () { clearTimeout(t); });
	}

	function install(ctx) {
		/** ctx: {B, host, tools, composer, shell, exporter, audio, S} */
		const handlers = {
			"song.get": async function () {
				const song = ctx.tools.snapshot();
				return { song: song, summary: (await ctx.tools.run("song_info", {})) };
			},
			"song.set": async function (p) {
				if (!p || typeof p.song !== "object" || p.song === null) throw rpcError(-32602, "parameter 'song' must be a BeepBox song JSON object");
				try { return await ctx.tools.run("set_song_json", { song: p.song }); } catch (e) { throw rpcError(-32602, e.message); }
			},
			"play": async function () { ctx.host.play({ fromBar: 0 }); return { ok: true, playing: true }; },
			"stop": async function () { ctx.host.stop(); return { ok: true, playing: false }; },
			"export.wav": async function (p) {
				const rel = checkRelPath(need(p, "path", "string"));
				const loops = p.loops == null ? 1 : p.loops;
				if (!Number.isInteger(loops) || loops < 1 || loops > 8) throw rpcError(-32602, "loops must be an integer from 1 to 8");
				const path = /\.wav$/i.test(rel) ? rel : rel + ".wav";
				const out = await ctx.exporter.renderWav(ctx.B, ctx.host.getSong(), { loops: loops, yieldEvery: 40 });
				if (out.peakDbfs < -80) throw rpcError(-32000, "the song renders as silence; add notes first");
				const w = await ctx.shell.writeProject(path, out.wav, true);
				const res = { ok: true, path: (w && w.path) || path, project_path: path, bytes: out.wav.length, seconds: +out.seconds.toFixed(3), sample_rate: out.sampleRate, loops: loops, peak_dbfs: out.peakDbfs };
				if (p.return_audio === true && out.wav.length <= 6 * 1024 * 1024) res.audio = { mime: "audio/wav", base64: ctx.shell.bytesToBase64(out.wav) };
				return res;
			},
			"app.prompt": async function (p) {
				const message = need(p, "message", "string");
				const secs = p.timeout_s == null ? 600 : p.timeout_s;
				if (!Number.isInteger(secs) || secs < 5 || secs > 900) throw rpcError(-32602, "timeout_s must be an integer from 5 to 900");
				return runPrompt(message, secs, message);
			},
			"song.compose_from_description": async function (p) {
				const d = need(p, "description", "string");
				if (p.bars != null && (!Number.isInteger(p.bars) || p.bars < 1 || p.bars > 256)) throw rpcError(-32602, "bars must be an integer from 1 to 256");
				const msg = "Compose a new chiptune song from this description and load it in the editor, replacing the current song (the user asked for this explicitly): " + d + (p.bars ? "\nLength: about " + p.bars + " bars." : "") + "\nCheck it with render_preview before you finish.";
				return runPrompt(msg, 600, "Compose: " + d);
			},
			"song.apply_change": async function (p) {
				const ins = need(p, "instruction", "string");
				return runPrompt("Change the current song as follows, keeping everything else: " + ins, 600, ins);
			},
		};

		async function runPrompt(message, secs, label) {
			if (ctx.composer.busy) throw rpcError(-32002, "the composer is busy with another request");
			let result;
			try {
				result = await withTimeout(ctx.composer.ask(message, { label: "(agent) " + label }), secs, function () { ctx.composer.stop(); });
			} catch (e) {
				if (e && e.code === -32002) throw e;
				if (e && typeof e.code === "number") throw e;
				const code = e && e.code;
				throw rpcError(code === "no_key" || code === "no_client" || code === "bridge_down" || code === "bridge_auth" ? -32004 : -32000, (e && e.message) || String(e));
			}
			return {
				reply: result.text || "",
				stopped: !!result.stopped, hit_max_turns: !!result.hitMaxTurns,
				tool_calls: (result.toolCalls || []).map(function (t) { return { name: t.name, ok: t.ok, summary: t.summary }; }),
				usage: result.usage,
				song: summaryOf(ctx),
			};
		}
		function summaryOf(c) {
			const j = c.tools.snapshot();
			const bars = Math.max.apply(null, [1].concat(j.channels.map(function (x) { return x.sequence.length; })));
			return { key: j.key, scale: j.scale, tempo: j.beatsPerMinute, bars: bars, channels: j.channels.length };
		}

		const onRpc = async function (method, params) {
			const h = handlers[method];
			if (!h) throw rpcError(-32601, "unknown method '" + method + "'");
			return h(params || {});
		};
		if (ctx.S) ctx.S.onRpc = onRpc;
		return { onRpc: onRpc, handlers: handlers };
	}

	NS.rpc = { install: install, checkRelPath: checkRelPath };
})(typeof window !== "undefined" ? window : globalThis);
