/* MakBox: music theory helpers, instrument presets, part generators and genre presets.
 *
 * Pure JavaScript with no DOM access, so it runs in the editor window and in Node tests.
 * Everything here talks in MIDI note numbers (C4 = 60) and beats (a quarter note = 1 beat);
 * songtools.js converts to BeepBox pitches (midi - keyBase) and ticks.
 * MakBox is not affiliated with BeepBox or John Nesky. See NOTICE.
 */
(function (root, factory) {
	if (typeof module === "object" && module.exports) module.exports = factory();
	else { root.Amerika = root.Amerika || {}; root.Amerika.theory = factory(); }
})(typeof self !== "undefined" ? self : this, function () {
	"use strict";

	const KEY_NAMES = ["C", "C♯", "D", "D♯", "E", "F", "F♯", "G", "G♯", "A", "A♯", "B"];
	const PC_SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
	const LETTER_PC = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };

	/** "C4", "F#3", "Bb2", "c♯5" -> MIDI number (C4 = 60). Returns null when not a note name. */
	function noteToMidi(name) {
		const m = /^([A-Ga-g])([#♯b♭]?)(-?\d)$/.exec(String(name).trim());
		if (!m) return null;
		let pc = LETTER_PC[m[1].toUpperCase()];
		if (m[2] === "#" || m[2] === "♯") pc += 1;
		else if (m[2] === "b" || m[2] === "♭") pc -= 1;
		return pc + 12 * (parseInt(m[3], 10) + 1);
	}
	function midiToNote(midi) {
		const pc = ((midi % 12) + 12) % 12;
		return PC_SHARP[pc] + (Math.floor(midi / 12) - 1);
	}
	/** BeepBox key name or letter ("C", "C♯", "F#", "Bb") -> key index 0..11, or -1. */
	function keyIndex(name) {
		if (typeof name === "number") return ((name % 12) + 12) % 12;
		const m = /^([A-Ga-g])([#♯b♭]?)$/.exec(String(name).trim());
		if (!m) return -1;
		let pc = LETTER_PC[m[1].toUpperCase()];
		if (m[2] === "#" || m[2] === "♯") pc += 1;
		else if (m[2] === "b" || m[2] === "♭") pc -= 1;
		return ((pc % 12) + 12) % 12;
	}

	// Scale interval sets in semitones from the tonic, keyed by BeepBox scale name.
	const SCALES = {
		"easy :)": [0, 2, 4, 7, 9], "easy :(": [0, 3, 5, 7, 10],
		"island :)": [0, 4, 6, 7, 11], "island :(": [0, 1, 3, 7, 8],
		"blues :)": [0, 2, 3, 4, 7, 9], "blues :(": [0, 3, 5, 6, 7, 10],
		"normal :)": [0, 2, 4, 5, 7, 9, 11], "normal :(": [0, 2, 3, 5, 7, 8, 10],
		"double harmonic :)": [0, 1, 4, 5, 7, 8, 11], "double harmonic :(": [0, 2, 3, 6, 7, 8, 11],
		"strange": [0, 2, 4, 6, 8, 10], "expert": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
	};
	const SCALE_ALIASES = {
		"major": "normal :)", "ionian": "normal :)", "minor": "normal :(", "natural minor": "normal :(", "aeolian": "normal :(",
		"pentatonic major": "easy :)", "major pentatonic": "easy :)", "pentatonic minor": "easy :(", "minor pentatonic": "easy :(",
		"blues": "blues :(", "blues major": "blues :)", "ryukyu": "island :)", "pelog": "island :(", "pelog selisir": "island :(",
		"harmonic minor": "double harmonic :(", "double harmonic": "double harmonic :)", "whole tone": "strange", "chromatic": "expert",
	};
	function resolveScale(name) {
		if (SCALES[name]) return name;
		const k = String(name).toLowerCase().trim();
		if (SCALES[k]) return k;
		return SCALE_ALIASES[k] || null;
	}

	/** Notes of a scale as MIDI numbers over a range. */
	function scaleNotes(keyPc, scaleName, lowMidi, highMidi) {
		const iv = SCALES[resolveScale(scaleName)] || SCALES["normal :)"];
		const out = [];
		for (let m = lowMidi; m <= highMidi; m++) if (iv.indexOf((((m - keyPc) % 12) + 12) % 12) >= 0) out.push(m);
		return out;
	}

	// ---------------------------------------------------------------- chords
	const CHORD_QUALITIES = {
		"": [0, 4, 7], maj: [0, 4, 7], m: [0, 3, 7], min: [0, 3, 7], dim: [0, 3, 6], aug: [0, 4, 8],
		sus2: [0, 2, 7], sus4: [0, 5, 7], "5": [0, 7, 12],
		"7": [0, 4, 7, 10], maj7: [0, 4, 7, 11], m7: [0, 3, 7, 10], min7: [0, 3, 7, 10], dim7: [0, 3, 6, 9], m7b5: [0, 3, 6, 10],
		"6": [0, 4, 7, 9], m6: [0, 3, 7, 9], add9: [0, 4, 7, 14], madd9: [0, 3, 7, 14], "9": [0, 4, 7, 10, 14],
	};
	const MAJOR_DEG = [0, 2, 4, 5, 7, 9, 11];
	const MINOR_DEG = [0, 2, 3, 5, 7, 8, 10];
	const ROMAN = { i: 0, ii: 1, iii: 2, iv: 3, v: 4, vi: 5, vii: 6 };

	/** Parse one chord symbol. Accepts names ("Am7", "F#m", "Bb") and roman numerals ("i", "VI", "bVII", "V7", "iv").
	 *  Roman numerals are relative to `keyPc` and `minor` (true: degrees come from the natural minor scale). */
	function parseChord(sym, keyPc, minor) {
		sym = String(sym).trim();
		const rm = /^([b♭#♯]?)(VII|VI|IV|V|III|II|I|vii|vi|iv|v|iii|ii|i)(°|o|dim)?(maj7|M7|7|9|6|sus2|sus4|add9)?$/.exec(sym);
		if (rm) {
			const deg = ROMAN[rm[2].toLowerCase()];
			// An accidental is always relative to the MAJOR scale degree (bVI = 8 semitones, bVII = 10), a bare numeral follows the song mode.
			let root;
			if (rm[1]) root = keyPc + MAJOR_DEG[deg] + ((rm[1] === "b" || rm[1] === "♭") ? -1 : 1);
			else root = keyPc + (minor ? MINOR_DEG : MAJOR_DEG)[deg];
			const lower = rm[2] === rm[2].toLowerCase();
			let q = rm[3] ? "dim" : (lower ? "m" : "");
			const ext = rm[4];
			if (ext === "7") q = rm[3] ? "dim7" : (lower ? "m7" : "7");
			else if (ext === "maj7" || ext === "M7") q = lower ? "m" : "maj7";
			else if (ext === "9") q = lower ? "m7" : "9";
			else if (ext) q = ext;
			return makeChord(((root % 12) + 12) % 12, q);
		}
		const nm = /^([A-Ga-g])([#♯b♭]?)(.*)$/.exec(sym);
		if (nm) {
			const pc = keyIndex(nm[1] + nm[2]);
			let q = nm[3].replace(/^min/, "m").replace(/^M$/, "");
			if (!(q in CHORD_QUALITIES)) throw new Error("unknown chord quality in '" + sym + "'");
			return makeChord(pc, q);
		}
		throw new Error("cannot parse chord '" + sym + "' (use roman numerals like i VI III VII or names like Am F C G)");
	}
	function makeChord(rootPc, quality) {
		const iv = CHORD_QUALITIES[quality];
		return { rootPc: rootPc, quality: quality, intervals: iv.slice(), name: PC_SHARP[rootPc] + (quality === "maj" ? "" : quality) };
	}
	/** Progression string -> chords. Separators: spaces, commas, dashes with spaces, or '|'. */
	function parseProgression(text, keyPc, minor) {
		const parts = Array.isArray(text) ? text : String(text).split(/[\s,|]+|\s-\s/).filter(Boolean);
		return parts.map(function (p) { return parseChord(p, keyPc, minor); });
	}
	/** Voice a chord near `centerMidi`: returns sorted MIDI notes (root position, closest octave to center). */
	function chordMidi(chord, octaveRootMidi) {
		let root = chord.rootPc + 12 * Math.floor(octaveRootMidi / 12);
		if (root < octaveRootMidi - 6) root += 12;
		return chord.intervals.map(function (i) { return root + i; });
	}

	const PROGRESSIONS = {
		"pop (I V vi IV)": "I V vi IV", "sad pop (vi IV I V)": "vi IV I V", "50s (I vi IV V)": "I vi IV V",
		"minor epic (i VI III VII)": "i VI III VII", "minor andalusian (i VII VI V)": "i bVII bVI V",
		"minor driving (i i bVII bVI)": "i i bVII bVI", "boss (i bVI bVII i)": "i bVI bVII i", "dark (i iv v i)": "i iv v i",
		"adventure (I IV V I)": "I IV V I", "town (I iii IV V)": "I iii IV V", "calm (I IV I V)": "I IV I V",
		"victory (I IV V I)": "I IV V I", "defeat (i iv i V)": "i iv i V", "ambient (i VI iv VII)": "i VI iv VII",
		"blues (I I I I IV IV I I V IV I V)": "I I I I IV IV I I V IV I V",
	};

	// ---------------------------------------------------------------- rhythm / drum templates (beats within a 4-beat bar)
	// Drum rows of the MakBox "drum kit" preset: 0 kick, 1-3 toms (low to high), 4 clap, 5 snare, 6 rim, 7 shaker, 8 hat, 9 open hat, 10 crash, 11 bell.
	const DRUM_ROWS = { kick: 0, tomlow: 1, tommid: 2, tomhigh: 3, clap: 4, snare: 5, rim: 6, shaker: 7, hat: 8, openhat: 9, crash: 10, bell: 11 };
	const DRUM_NAMES = Object.keys(DRUM_ROWS);
	const range = function (a, b, s) { const r = []; for (let x = a; x < b - 1e-9; x += s) r.push(+x.toFixed(4)); return r; };
	const DRUM_TEMPLATES = {
		"four on the floor": { kick: range(0, 4, 1), snare: [1, 3], hat: range(0.5, 4, 1), description: "kick every beat, snare on 2 and 4, offbeat hats" },
		"rock backbeat": { kick: [0, 2, 2.5], snare: [1, 3], hat: range(0, 4, 0.5), description: "kick 1 and 3, snare 2 and 4, straight eighth hats" },
		"boss double kick": { kick: [0, 0.5, 1.5, 2, 2.5, 3.5], snare: [1, 3], hat: range(0, 4, 0.5), crash: [0], description: "driving double kicks, snare on 2 and 4, eighth hats, crash on 1" },
		"chiptune march": { kick: [0, 2], snare: [1, 3], hat: range(0, 4, 0.5), description: "NES style: kick 1 and 3, snare 2 and 4, eighth hats" },
		"half time": { kick: [0, 2.5], snare: [2], hat: range(0, 4, 1), description: "snare on 3, relaxed" },
		"sixteenth hats": { kick: [0, 2], snare: [1, 3], hat: range(0, 4, 0.25), description: "kick 1 and 3, snare 2 and 4, sixteenth hats" },
		"breakbeat": { kick: [0, 0.75, 2.5], snare: [1, 3, 3.75], hat: range(0, 4, 0.5), description: "syncopated breakbeat" },
		"shuffle": { kick: [0, 2], snare: [1, 3], hat: [0, 0.667, 1, 1.667, 2, 2.667, 3, 3.667], description: "swung triplet hats (use rhythm ÷3 for exact feel)" },
		"waltz": { kick: [0], snare: [1, 2], hat: [0, 1, 2], description: "3/4: kick on 1, snare on 2 and 3", beatsPerBar: 3 },
		"calm": { kick: [0], rim: [2], shaker: range(0.5, 4, 1), description: "soft kick, rim on 3, off-beat shaker" },
		"sparse": { kick: [0], hat: [2], description: "very sparse pulse for ambient sections" },
		"tom fill": { tomhigh: [2, 2.25], tommid: [2.5, 2.75], tomlow: [3, 3.25], snare: [3.5, 3.75], kick: [0], crash: [0], description: "one-bar fill, use as every 4th bar" },
		"snare roll fill": { snare: range(2, 4, 0.25), kick: [0], description: "snare roll over the last two beats" },
	};
	/** Convert a drum template to events (beats, pitch rows) for one bar of `beatsPerBar` beats, scaled to fit. */
	function drumTemplateEvents(name, beatsPerBar, opts) {
		const t = DRUM_TEMPLATES[name];
		if (!t) throw new Error("unknown drum template '" + name + "'. Available: " + Object.keys(DRUM_TEMPLATES).join(", "));
		opts = opts || {};
		const out = [];
		for (const k of DRUM_NAMES) {
			if (!t[k]) continue;
			for (const b of t[k]) {
				if (b >= beatsPerBar - 1e-9) continue;
				const dur = (k === "kick" || k === "snare" || k === "clap") ? 0.25 : (k === "crash" || k === "openhat") ? 1 : 0.125;
				let vol = k === "hat" || k === "shaker" ? 67 : k === "crash" ? 67 : 100;
				if (k === "hat" && Math.abs(b - Math.round(b)) < 1e-6) vol = 100;
				out.push({ pitches: [DRUM_ROWS[k]], start: b, dur: Math.min(dur, beatsPerBar - b), vol: vol });
			}
		}
		return out;
	}

	// ---------------------------------------------------------------- note events + arrangement generators
	// An "event" is {pitches:[midi...], start (beats), dur (beats), vol (0-100), bend?}.
	function arpeggioEvents(chordNotes, beatsPerBar, opts) {
		opts = opts || {};
		const step = opts.step || 0.25, style = opts.style || "up", vol = opts.vol || 100;
		let seq = chordNotes.slice().sort(function (a, b) { return a - b; });
		if (opts.octaves > 1) { const base = seq.slice(); for (let o = 1; o < opts.octaves; o++) base.forEach(function (n) { seq.push(n + 12 * o); }); }
		let order;
		if (style === "down") order = seq.slice().reverse();
		else if (style === "updown") order = seq.concat(seq.slice(1, -1).reverse());
		else if (style === "broken") order = [seq[0], seq[2] != null ? seq[2] : seq[1], seq[1], seq[2] != null ? seq[2] : seq[1]];
		else order = seq;
		const out = [];
		let i = 0;
		for (let t = 0; t < beatsPerBar - 1e-9; t += step, i++) {
			out.push({ pitches: [order[i % order.length]], start: +t.toFixed(4), dur: Math.min(step, beatsPerBar - t), vol: vol });
		}
		return out;
	}
	function bassEvents(chord, beatsPerBar, opts) {
		opts = opts || {};
		const style = opts.style || "eighths", vol = opts.vol || 100;
		const root = chordMidi(chord, opts.lowMidi || 36)[0];
		const fifth = root + 7, oct = root + 12;
		const E = function (p, s, d, v) { return { pitches: [p], start: s, dur: Math.min(d, beatsPerBar - s), vol: v == null ? vol : v }; };
		const out = [];
		if (style === "whole") out.push(E(root, 0, beatsPerBar));
		else if (style === "half") for (let t = 0; t < beatsPerBar; t += 2) out.push(E(t % 4 === 0 ? root : fifth, t, 2));
		else if (style === "quarters") for (let t = 0; t < beatsPerBar; t++) out.push(E(root, t, 0.9));
		else if (style === "octaves") for (let t = 0; t < beatsPerBar; t += 0.5) out.push(E(((t * 2) % 2 === 0) ? root : oct, t, 0.45));
		else if (style === "walking") {
			const pat = [root, root + 4 - (chord.intervals[1] === 3 ? 1 : 0), fifth, root + 9 - (chord.intervals[1] === 3 ? 0 : 0)];
			for (let t = 0; t < beatsPerBar; t++) out.push(E(pat[t % 4], t, 0.95));
		} else if (style === "rootfifth") for (let t = 0; t < beatsPerBar; t += 0.5) out.push(E(Math.floor(t * 2) % 4 === 3 ? fifth : root, t, 0.45));
		else if (style === "arp") out.push({ pitches: [root, root + (chord.intervals[1] || 4), fifth].slice(0, 3), start: 0, dur: beatsPerBar, vol: vol });
		else /* eighths */ for (let t = 0; t < beatsPerBar; t += 0.5) out.push(E(root, t, 0.45, t % 1 === 0 ? vol : Math.round(vol * 0.67)));
		return out;
	}
	function padEvents(chordNotes, beatsPerBar, opts) {
		opts = opts || {};
		return [{ pitches: chordNotes.slice(0, 4), start: 0, dur: beatsPerBar, vol: opts.vol || 67 }];
	}

	// Small deterministic PRNG so presets are reproducible.
	function rng(seed) {
		let s = (seed >>> 0) || 1;
		return function () { s ^= s << 13; s >>>= 0; s ^= s >>> 17; s ^= s << 5; s >>>= 0; return s / 4294967296; };
	}
	/** Rule-based melody: stepwise random walk through scale tones, leaning on chord tones on strong beats. */
	function melodyEvents(chord, keyPc, scaleName, beatsPerBar, opts) {
		opts = opts || {};
		const rand = opts.rand || rng(1);
		const lo = opts.lowMidi || 60, hi = opts.highMidi || 79;
		const pool = scaleNotes(keyPc, scaleName, lo, hi);
		const tones = pool.filter(function (m) { return chord.intervals.some(function (i) { return ((m - chord.rootPc - i) % 12 + 12) % 12 === 0; }); });
		const cells = opts.cells || [[1, 1, 1, 1], [1.5, 0.5, 1, 1], [0.5, 0.5, 1, 0.5, 0.5, 1], [2, 1, 1], [1, 0.5, 0.5, 1, 1], [0.5, 0.5, 0.5, 0.5, 1, 1]];
		const rest = opts.restChance == null ? 0.1 : opts.restChance;
		const cell = cells[Math.floor(rand() * cells.length)];
		let cur = opts.startMidi != null ? opts.startMidi : tones[Math.floor(tones.length / 2)] || pool[Math.floor(pool.length / 2)];
		const out = [];
		let t = 0, k = 0;
		while (t < beatsPerBar - 1e-9) {
			const d = Math.min(cell[k % cell.length], beatsPerBar - t);
			if (!(k > 0 && rand() < rest)) {
				const strong = Math.abs(t - Math.round(t)) < 1e-6 && Math.round(t) % 2 === 0;
				let cand;
				if (strong) cand = tones.length ? tones.reduce(function (a, b) { return Math.abs(b - cur) + rand() * 3 < Math.abs(a - cur) + rand() * 3 ? b : a; }) : cur;
				else {
					const idx = Math.max(0, pool.indexOf(cur));
					const move = [-2, -1, -1, 1, 1, 2][Math.floor(rand() * 6)];
					cand = pool[Math.max(0, Math.min(pool.length - 1, idx + move))];
				}
				cur = cand;
				out.push({ pitches: [cur], start: +t.toFixed(4), dur: d * (opts.legato ? 1 : 0.9), vol: strong ? 100 : 83 });
			}
			t += d; k++;
		}
		return out;
	}

	// ---------------------------------------------------------------- instrument presets (BeepBox instrument JSON)
	const FX_CHORD_ARP = { effects: ["chord type"], chord: "arpeggio" };
	function chip(wave, extra) { return Object.assign({ type: "chip", volume: 100, wave: wave, unison: "none", eqFilter: [], envelopes: [], fadeInSeconds: 0, fadeOutTicks: -1 }, FX_CHORD_ARP, extra || {}); }
	// Drum kit (type "drumset"): each of the 12 rows has its own spectrum (30 points, 0-100) and filter envelope.
	function spectrum(from, to, level, shape) {
		const a = [];
		for (let i = 0; i < 30; i++) {
			if (i < from || i > to) { a.push(0); continue; }
			const p = (i - from) / Math.max(1, to - from);
			a.push(Math.round(level * (shape === "peak" ? 1 - Math.abs(p - 0.5) * 1.2 : shape === "falling" ? 1 - p * 0.6 : shape === "rising" ? 0.4 + p * 0.6 : 1)));
		}
		return a;
	}
	// Drum rows are ordered by the pitch of their noise wave: in a BeepBox drumset, row r plays its spectrum
	// with a base frequency of about 32.7 Hz * 2^(r/2), and spectrum point i sits 1/7 octave above point i-1.
	// So rows are assigned by how high each drum must reach: kick at the bottom, cymbals at the top.
	function drumKit() {
		const d = function (env, sp) { return { filterEnvelope: env, spectrum: sp }; };
		return {
			type: "drumset", volume: 100, eqFilter: [], effects: ["chord type"], chord: "arpeggio", envelopes: [],
			drums: [
				d("twang 2", spectrum(0, 9, 57, "flat")),        // 0 kick
				d("twang 2", spectrum(5, 13, 71, "flat")),       // 1 low tom
				d("twang 2", spectrum(5, 14, 71, "flat")),       // 2 mid tom
				d("twang 2", spectrum(5, 14, 71, "flat")),       // 3 high tom
				d("decay 1", spectrum(9, 27, 100, "flat")),      // 4 clap
				d("decay 1", spectrum(3, 28, 100, "flat")),      // 5 snare
				d("twang 3", spectrum(12, 24, 100, "flat")),     // 6 rim / click
				d("decay 1", spectrum(10, 29, 100, "flat")),     // 7 shaker
				d("twang 3", spectrum(12, 29, 100, "flat")),     // 8 closed hat
				d("twang 1", spectrum(10, 29, 100, "flat")),     // 9 open hat
				d("decay 2", spectrum(7, 29, 100, "flat")),      // 10 crash
				d("twang 1", spectrum(0, 14, 100, "flat")),      // 11 bell / ride
			],
		};
	}
	const INSTRUMENT_PRESETS = {
		"square lead": function () { return chip("square", { effects: ["chord type", "vibrato"], vibrato: "delayed", volume: 80 }); },
		"pulse lead": function () { return chip("1/4 pulse", { volume: 80 }); },
		"thin pulse lead": function () { return chip("1/8 pulse", { volume: 80 }); },
		"saw lead": function () { return chip("sawtooth", { volume: 70, unison: "shimmer" }); },
		"triangle bass": function () { return chip("triangle", { volume: 100 }); },
		"square bass": function () { return chip("square", { volume: 80, eqFilter: [{ type: "low-pass", cutoffHz: 1500, linearGain: 1 }] }); },
		"saw bass": function () { return chip("sawtooth", { volume: 80, eqFilter: [{ type: "low-pass", cutoffHz: 1000, linearGain: 1 }] }); },
		"chip arp": function () { return chip("square", { volume: 60, fadeOutTicks: -3 }); },
		"soft pad": function () { return chip("triangle", { volume: 60, effects: ["chord type", "reverb"], chord: "simultaneous", reverb: 50, fadeInSeconds: 0.1, fadeOutTicks: 12 }); },
		"pluck": function () { return { type: "Picked String", volume: 80, eqFilter: [], effects: ["chord type"], chord: "simultaneous", fadeInSeconds: 0, fadeOutTicks: -1, harmonics: [100, 100, 86, 86, 86, 71, 71, 71, 0, 0, 86, 86, 86, 86, 57, 57, 57, 57, 57, 57, 57, 57, 57, 57, 57, 57, 57, 57], unison: "none", stringSustain: 50, stringSustainType: "bright", envelopes: [] }; },
		"organ": function () { return { type: "harmonics", volume: 60, eqFilter: [], effects: ["chord type", "reverb"], chord: "simultaneous", reverb: 25, fadeInSeconds: 0.01, fadeOutTicks: -3, harmonics: [100, 0, 100, 0, 100, 0, 71, 0, 71, 0, 57, 0, 57, 0, 43, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0], unison: "none", envelopes: [] }; },
		"fm bell": function () { return { type: "FM", volume: 70, eqFilter: [], effects: ["chord type", "reverb"], chord: "simultaneous", reverb: 25, fadeInSeconds: 0, fadeOutTicks: -1, algorithm: "1←(2\u20023\u20024)", feedbackType: "1⟲", feedbackAmplitude: 0, operators: [{ frequency: "1×", amplitude: 15 }, { frequency: "3×", amplitude: 6 }, { frequency: "5×", amplitude: 4 }, { frequency: "1×", amplitude: 0 }], envelopes: [{ target: "operatorAmplitude", envelope: "twang 2", index: 1 }, { target: "noteVolume", envelope: "twang 3" }] }; },
		"fm bass": function () { return { type: "FM", volume: 90, eqFilter: [], effects: ["chord type"], chord: "simultaneous", fadeInSeconds: 0, fadeOutTicks: -1, algorithm: "1←(2\u20023\u20024)", feedbackType: "1⟲", feedbackAmplitude: 4, operators: [{ frequency: "1×", amplitude: 15 }, { frequency: "1×", amplitude: 9 }, { frequency: "1×", amplitude: 0 }, { frequency: "1×", amplitude: 0 }], envelopes: [{ target: "operatorAmplitude", envelope: "decay 2", index: 1 }] }; },
		"fm electric piano": function () { return { type: "FM", volume: 70, eqFilter: [], effects: ["chord type", "reverb"], chord: "simultaneous", reverb: 25, fadeInSeconds: 0, fadeOutTicks: -1, algorithm: "1←3\u20032←4", feedbackType: "1⟲", feedbackAmplitude: 0, operators: [{ frequency: "1×", amplitude: 15 }, { frequency: "1×", amplitude: 5 }, { frequency: "1×", amplitude: 12 }, { frequency: "7×", amplitude: 3 }], envelopes: [{ target: "operatorAmplitude", envelope: "twang 3", index: 1 }, { target: "operatorAmplitude", envelope: "twang 2", index: 3 }] }; },
		"pwm lead": function () { return { type: "PWM", volume: 70, eqFilter: [], effects: ["chord type", "vibrato"], chord: "arpeggio", vibrato: "light", fadeInSeconds: 0, fadeOutTicks: -1, pulseWidth: 25, envelopes: [{ target: "pulseWidth", envelope: "swell 1" }] }; },
		"supersaw pad": function () { return { type: "supersaw", volume: 55, eqFilter: [], effects: ["chord type", "reverb"], chord: "simultaneous", reverb: 50, fadeInSeconds: 0.05, fadeOutTicks: 6, pulseWidth: 50, dynamism: 70, spread: 50, shape: 0, envelopes: [] }; },
		"noise hat": function () { return { type: "noise", volume: 60, eqFilter: [], effects: ["chord type"], chord: "arpeggio", fadeInSeconds: 0, fadeOutTicks: -1, wave: "white", envelopes: [{ target: "noteVolume", envelope: "twang 3" }] }; },
		"retro noise": function () { return { type: "noise", volume: 80, eqFilter: [], effects: ["chord type"], chord: "arpeggio", fadeInSeconds: 0, fadeOutTicks: -1, wave: "retro", envelopes: [{ target: "noteVolume", envelope: "decay 1" }] }; },
		"drum kit": drumKit,
		"spectrum snare": function () { return { type: "spectrum", volume: 80, eqFilter: [], effects: ["chord type"], chord: "arpeggio", fadeInSeconds: 0, fadeOutTicks: -1, spectrum: spectrum(7, 21, 85, "peak"), envelopes: [{ target: "noteVolume", envelope: "decay 1" }] }; },
	};
	// Note: BeepBox spells multi-part FM algorithm names with an en space (U+2002) inside groups and an em space (U+2003) between them.
	function instrumentPreset(name) {
		const f = INSTRUMENT_PRESETS[String(name).toLowerCase().trim()];
		if (!f) throw new Error("unknown instrument preset '" + name + "'. Available: " + Object.keys(INSTRUMENT_PRESETS).join(", "));
		return JSON.parse(JSON.stringify(f()));
	}

	// ---------------------------------------------------------------- genre presets
	// Each preset builds a complete arrangement description; songtools.buildGenreSong turns it into song JSON.
	const GENRES = {
		chiptune: { description: "generic 8-bit game tune: square lead, triangle bass, chip arps, march drums", tempo: 140, key: "C", scale: "normal :)", progression: "I V vi IV", drums: "chiptune march", bass: "eighths", lead: "square lead", arp: true, bars: 16, fillEvery: 4 },
		battle: { description: "fast minor-key fight music with arpeggiated bass, hard drums, fills every 4 bars", tempo: 160, key: "D", scale: "normal :(", progression: "i bVI bVII i", drums: "boss double kick", bass: "octaves", lead: "pulse lead", arp: true, bars: 16, fillEvery: 4 },
		boss: { description: "intense boss battle: 150 bpm, minor key, double-kick drums, driving arpeggios", tempo: 150, key: "A", scale: "normal :(", progression: "i bVI bVII v", drums: "boss double kick", bass: "arp", lead: "saw lead", arp: true, bars: 16, fillEvery: 4 },
		town: { description: "calm cheerful town theme: major key, plucks and soft pad, light percussion", tempo: 100, key: "G", scale: "normal :)", progression: "I iii IV V", drums: "calm", bass: "half", lead: "fm bell", arp: false, pad: "soft pad", bars: 16, fillEvery: 0 },
		dungeon: { description: "dark, slow, sparse dungeon crawl: low drones, sparse beat, eerie lead", tempo: 80, key: "E", scale: "normal :(", progression: "i iv i bVI", drums: "sparse", bass: "whole", lead: "pwm lead", arp: false, pad: "supersaw pad", bars: 16, fillEvery: 0 },
		victory: { description: "short triumphant fanfare/jingle, major key, bright and fast, does not loop", tempo: 150, key: "C", scale: "normal :)", progression: "I IV V I", drums: "chiptune march", bass: "quarters", lead: "square lead", arp: true, bars: 4, fillEvery: 0, jingle: true },
		defeat: { description: "short sad game-over jingle, slow minor, falling melody, does not loop", tempo: 70, key: "C", scale: "normal :(", progression: "i iv i V", drums: "sparse", bass: "whole", lead: "fm electric piano", arp: false, bars: 4, fillEvery: 0, jingle: true },
		menu: { description: "friendly looping menu music, mid tempo, major, soft arps and pad", tempo: 110, key: "F", scale: "normal :)", progression: "I vi IV V", drums: "half time", bass: "half", lead: "fm electric piano", arp: true, pad: "soft pad", bars: 16, fillEvery: 0 },
		ambient: { description: "slow ambient bed: pads, bell tones, almost no drums", tempo: 70, key: "D", scale: "normal :(", progression: "i VI iv VII", drums: null, bass: "whole", lead: "fm bell", arp: false, pad: "supersaw pad", bars: 16, fillEvery: 0 },
	};

	return {
		KEY_NAMES: KEY_NAMES, SCALES: SCALES, CHORD_QUALITIES: CHORD_QUALITIES, PROGRESSIONS: PROGRESSIONS,
		DRUM_ROWS: DRUM_ROWS, DRUM_NAMES: DRUM_NAMES, DRUM_TEMPLATES: DRUM_TEMPLATES, GENRES: GENRES, INSTRUMENT_PRESETS: INSTRUMENT_PRESETS,
		noteToMidi: noteToMidi, midiToNote: midiToNote, keyIndex: keyIndex, resolveScale: resolveScale, scaleNotes: scaleNotes,
		parseChord: parseChord, parseProgression: parseProgression, chordMidi: chordMidi,
		drumTemplateEvents: drumTemplateEvents, arpeggioEvents: arpeggioEvents, bassEvents: bassEvents, padEvents: padEvents, melodyEvents: melodyEvents,
		instrumentPreset: instrumentPreset, rng: rng,
	};
});
