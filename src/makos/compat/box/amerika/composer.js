/* MakBox: the "Amerika Composer" side panel and its tool-use loop.
 * Talks only to the local Studio bridge through window.amerikaStudio (AIClient / request). No API key lives here. */
(function (root) {
	"use strict";
	const NS = (root.Amerika = root.Amerika || {});

	function el(tag, cls, text) {
		const e = document.createElement(tag);
		if (cls) e.className = cls;
		if (text != null) e.textContent = text;
		return e;
	}

	function friendly(e) {
		const code = e && e.code;
		if (code === "no_key") return { text: "No Anthropic key is set up yet. Open Studio, choose \"Set up Anthropic key\" (or use the Keys... button in this window's toolbar), then press Send again.", key: true };
		if (code === "key_rejected") return { text: "Anthropic rejected the key. Check it in Studio.", key: true };
		if (code === "bridge_down" || code === "bridge_auth") return { text: "The Studio bridge is not reachable. Open Studio (or run: amerika-studio ensure) and try again.", key: true };
		if (code === "budget") return { text: (e.message || "The daily token budget is used up.") };
		if (code === "rate_limit" || code === "overloaded") return { text: e.message };
		return { text: (e && e.message) || String(e) };
	}

	/** Shrink old tool results so long sessions stay cheap. Keeps the newest `keep` messages intact. */
	function compactHistory(messages, keep) {
		for (let i = 0; i < messages.length - keep; i++) {
			const m = messages[i];
			if (m.role !== "user" || !Array.isArray(m.content)) continue;
			m.content.forEach(function (b) {
				if (b.type === "tool_result" && Array.isArray(b.content)) b.content.forEach(function (c) { if (c.type === "text" && c.text.length > 400) c.text = c.text.slice(0, 400) + " ...[older result shortened]"; });
			});
		}
	}

	function stateLine(tools) {
		let j;
		try { j = tools.snapshot(); } catch (e) { return ""; }
		const bars = Math.max.apply(null, [1].concat(j.channels.map(function (c) { return c.sequence.length; })));
		const chans = j.channels.map(function (c, i) {
			let notes = 0; c.sequence.forEach(function (s) { if (s) notes += (c.patterns[s - 1].notes || []).length; });
			const ins = c.instruments[0];
			return (i + 1) + ":" + (c.type === "drum" ? "drum" : "pitch") + "(" + ins.type + (ins.wave ? " " + ins.wave : "") + ", " + notes + " notes)";
		});
		return "[Current song: key " + j.key + ", scale " + j.scale + ", " + j.beatsPerMinute + " bpm, " + j.beatsPerBar + " beats/bar, " + bars + " bars, loop " + j.introBars + "+" + j.loopBars + ". Channels " + chans.join(", ") + "]";
	}

	function Composer(opts) {
		this.opts = opts;
		this.tools = opts.tools;
		this.host = opts.host;
		this.shell = opts.shell;
		this.busy = false;
		this.client = null;
		this.turnCommits = 0;
		this.lastTurnCommits = 0;
		this.usage = { input: 0, output: 0 };
		this.build(opts.root);
		this.refreshStatus();
	}

	Composer.prototype.build = function (root) {
		const P = NS.prompt;
		this.root = root;
		root.textContent = "";
		const head = el("div", "ac-head");
		head.appendChild(el("div", "ac-title", "Amerika Composer"));
		this.statusDot = el("span", "ac-dot");
		this.statusDot.title = "Bridge status";
		head.appendChild(this.statusDot);
		this.modelSel = el("select", "ac-model");
		this.modelSel.title = "Model";
		this.modelSel.addEventListener("change", () => { try { localStorage.setItem("amerika.model", this.modelSel.value); } catch (e) { /* ignore */ } if (this.client) this.client.model = this.modelSel.value || null; });
		head.appendChild(this.modelSel);
		const newChat = el("button", "ac-btn ac-small", "New chat");
		newChat.title = "Forget the conversation (the song stays)";
		newChat.addEventListener("click", () => this.newChat());
		head.appendChild(newChat);
		root.appendChild(head);

		this.log = el("div", "ac-log");
		this.log.setAttribute("role", "log");
		root.appendChild(this.log);
		this.addNote("Describe the music you want, or ask for changes to the current song. I write notes and instruments with BeepBox's own tools, so every step can be undone with Z.");

		const chips = el("div", "ac-chips");
		P.QUICK_PROMPTS.forEach((q) => {
			const b = el("button", "ac-chip", q);
			b.addEventListener("click", () => { this.input.value = q; this.input.focus(); });
			chips.appendChild(b);
		});
		root.appendChild(chips);

		const form = el("div", "ac-form");
		this.input = el("textarea", "ac-input");
		this.input.rows = 3;
		this.input.placeholder = "e.g. \"an upbeat 8-bit boss battle, 150 bpm, minor key, with arpeggiated bass\"";
		this.input.addEventListener("keydown", (ev) => {
			ev.stopPropagation();
			if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); this.submit(); }
		});
		["keyup", "keypress"].forEach((n) => this.input.addEventListener(n, (ev) => ev.stopPropagation()));
		form.appendChild(this.input);
		const row = el("div", "ac-row");
		this.sendBtn = el("button", "ac-btn ac-primary", "Compose");
		this.sendBtn.addEventListener("click", () => this.submit());
		this.stopBtn = el("button", "ac-btn", "Stop");
		this.stopBtn.disabled = true;
		this.stopBtn.addEventListener("click", () => this.stop());
		this.undoBtn = el("button", "ac-btn", "Undo last AI turn");
		this.undoBtn.disabled = true;
		this.undoBtn.addEventListener("click", () => this.undoTurn());
		this.playBtn = el("button", "ac-btn", "Play");
		this.playBtn.addEventListener("click", () => { try { this.host.play({ fromBar: 0 }); } catch (e) { this.addNote(String(e.message || e)); } });
		row.appendChild(this.sendBtn); row.appendChild(this.stopBtn); row.appendChild(this.undoBtn); row.appendChild(this.playBtn);
		form.appendChild(row);
		this.usageEl = el("div", "ac-usage", "");
		form.appendChild(this.usageEl);
		root.appendChild(form);
	};

	Composer.prototype.addNote = function (text, cls) {
		const d = el("div", "ac-msg ac-note" + (cls ? " " + cls : ""), text);
		this.log.appendChild(d); this.scroll(); return d;
	};
	Composer.prototype.addUser = function (text) { const d = el("div", "ac-msg ac-user", text); this.log.appendChild(d); this.scroll(); return d; };
	Composer.prototype.addAssistant = function (text) { const d = el("div", "ac-msg ac-assistant", text); this.log.appendChild(d); this.scroll(); return d; };
	Composer.prototype.addTool = function (name, input) {
		const d = el("div", "ac-tool ac-pending");
		const brief = Object.keys(input || {}).slice(0, 4).map(function (k) { let v = input[k]; if (typeof v === "object") v = JSON.stringify(v); v = String(v); return k + "=" + (v.length > 28 ? v.slice(0, 28) + "…" : v); }).join(" ");
		d.textContent = "▸ " + name + (brief ? "  " + brief : "");
		this.log.appendChild(d); this.scroll(); return d;
	};
	Composer.prototype.scroll = function () { this.log.scrollTop = this.log.scrollHeight; };

	Composer.prototype.setBusy = function (b) {
		this.busy = b;
		this.sendBtn.disabled = b; this.stopBtn.disabled = !b;
		this.root.classList.toggle("ac-busy", b);
		this.undoBtn.disabled = b || !this.lastTurnCommits;
	};

	Composer.prototype.refreshStatus = async function () {
		const S = root.amerikaStudio;
		this.statusDot.className = "ac-dot";
		this.modelSel.textContent = "";
		const auto = el("option", null, "auto model"); auto.value = ""; this.modelSel.appendChild(auto);
		if (!S || !S.request) { this.statusDot.classList.add("bad"); this.statusDot.title = "Not running inside the Studio shell"; return null; }
		try {
			const r = await S.request("/v1/status");
			if (r.status !== 200) throw new Error("status " + r.status);
			const st = r.json || {};
			const hasKey = !!(st.key && (st.key.box || st.key.shared || st.key.default || Object.keys(st.key).some(function (k) { return st.key[k]; })));
			this.statusDot.classList.add(hasKey ? "ok" : "warn");
			this.statusDot.title = hasKey ? "Bridge connected, key available" : "Bridge connected but no Anthropic key is set up";
			(st.models || []).forEach((m) => { const id = typeof m === "string" ? m : m.id; const o = el("option", null, id); o.value = id; this.modelSel.appendChild(o); });
			let saved = ""; try { saved = localStorage.getItem("amerika.model") || ""; } catch (e) { /* ignore */ }
			if (saved && Array.prototype.some.call(this.modelSel.options, function (o) { return o.value === saved; })) this.modelSel.value = saved;
			if (!hasKey && !this.warnedKey) { this.warnedKey = true; this.addNote("No Anthropic key is set up yet. Open Studio and choose \"Set up Anthropic key\". The key stays in the system keyring; this app never sees it.", "ac-warn"); }
			return st;
		} catch (e) {
			this.statusDot.classList.add("bad");
			this.statusDot.title = "Studio bridge unreachable";
			if (!this.warnedBridge) { this.warnedBridge = true; this.addNote("The Studio bridge is not reachable, so the composer is offline. Editing music by hand works as usual.", "ac-warn"); }
			return null;
		}
	};

	Composer.prototype.ensureClient = function () {
		const S = root.amerikaStudio;
		if (!S || !S.AIClient) throw Object.assign(new Error("The AI client is not available in this window (not running inside amerika-studio-webview)."), { code: "no_client" });
		if (this.client) return this.client;
		const self = this;
		const defs = this.tools.definitions.map(function (d) { return { name: d.name, description: d.description, input_schema: d.input_schema }; });
		this.client = new S.AIClient({
			model: this.modelSel.value || null,
			system: NS.prompt.SYSTEM,
			tools: defs,
			maxTurns: 30,
			maxTokens: 8192,
			run: function (name, input) { return self.runTool(name, input); },
			onEvent: function (kind, data) { self.onEvent(kind, data); },
		});
		return this.client;
	};

	Composer.prototype.runTool = async function (name, input) {
		const node = this.currentToolNode;
		try {
			const out = await this.tools.run(name, input);
			if (node) { node.classList.remove("ac-pending"); node.classList.add("ac-ok"); if (out && out.message) node.title = out.message; }
			return out;
		} catch (e) {
			if (node) { node.classList.remove("ac-pending"); node.classList.add("ac-err"); node.title = e.message; node.textContent += "  ✕ " + e.message.slice(0, 120); }
			throw e;
		}
	};

	Composer.prototype.onEvent = function (kind, data) {
		if (kind === "tool_use") this.currentToolNode = this.addTool(data.name, data.input);
		else if (kind === "text") { if (data) this.addAssistant(data); }
		else if (kind === "usage") { this.usage = { input: data.input_tokens, output: data.output_tokens }; this.usageEl.textContent = "this turn: " + data.input_tokens + " in / " + data.output_tokens + " out tokens"; }
		else if (kind === "request") { this.statusLine("thinking…"); }
	};
	Composer.prototype.statusLine = function (t) { this.usageEl.textContent = t; };

	Composer.prototype.newChat = function () {
		if (this.busy) return;
		if (this.client) this.client.reset();
		this.log.textContent = "";
		this.addNote("New conversation. The song is unchanged.");
	};
	Composer.prototype.stop = function () { if (this.client) this.client.stop(); this.statusLine("stopping…"); };
	Composer.prototype.undoTurn = function () {
		if (this.busy || !this.lastTurnCommits) return;
		this.host.undo(this.lastTurnCommits);
		this.addNote("Undid the last AI turn (" + this.lastTurnCommits + " change" + (this.lastTurnCommits === 1 ? "" : "s") + ").");
		this.lastTurnCommits = 0; this.undoBtn.disabled = true;
		if (this.opts.onSongReplaced) this.opts.onSongReplaced();
	};

	Composer.prototype.submit = function () {
		const text = this.input.value.trim();
		if (!text || this.busy) return;
		this.input.value = "";
		this.ask(text).catch(function () { /* shown in the log */ });
	};

	/** Run one user request through the model. Resolves {text, toolCalls, stopped, hitMaxTurns}. Rejects with .code -32002 when busy. */
	Composer.prototype.ask = async function (text, o) {
		o = o || {};
		if (this.busy) throw Object.assign(new Error("the composer is busy with another request"), { code: -32002 });
		this.setBusy(true);
		this.addUser(o.label || text);
		this.host.beginTurn();
		let result;
		try {
			const client = this.ensureClient();
			if (this.modelSel.value) client.model = this.modelSel.value;
			compactHistory(client.messages, 8);
			result = await client.send(stateLine(this.tools) + "\n\n" + text);
			if (result.stopped) this.addNote("Stopped.");
			if (result.hitMaxTurns) this.addNote("Stopped after the maximum number of steps. Ask me to continue if it is unfinished.", "ac-warn");
			if (!result.text && !result.stopped) this.addAssistant("(done)");
			this.usageEl.textContent = "this turn: " + result.usage.input_tokens + " in / " + result.usage.output_tokens + " out tokens";
			return result;
		} catch (e) {
			const f = friendly(e);
			this.addNote(f.text, "ac-warn");
			if (f.key) { this.warnedKey = false; this.refreshStatus(); }
			this.usageEl.textContent = "";
			throw e;
		} finally {
			this.lastTurnCommits = this.host.endTurn();
			this.setBusy(false);
			if (this.opts.onTurnEnd) this.opts.onTurnEnd(this.lastTurnCommits);
		}
	};

	NS.Composer = Composer;
	NS.composerInternals = { compactHistory: compactHistory, stateLine: stateLine, friendly: friendly };
})(typeof window !== "undefined" ? window : globalThis);
