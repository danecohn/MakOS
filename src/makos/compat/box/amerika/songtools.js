/* MakBox: the AI composer's song tools.
 *
 * `create(B, host)` returns {definitions, run, ...}. B is the BeepBox namespace (Song, Synth, Config...), host is
 *   { getSong(): Song, commit(song: Song, label: string): void, play(opts), stop(), undo(steps) }.
 * In the editor, host.commit records a BeepBox ChangeSong (so Edit > Undo works); in tests it just swaps the Song.
 * All edits go through BeepBox's own Song.toJsonObject / fromJsonObject, which validates and clamps everything.
 *
 * API conventions shown to the model: channels, patterns, instruments and bars are numbered from 1 (like the editor UI);
 * pitches are note names (C4 = middle C) or MIDI numbers; times are in beats (a quarter note = 1 beat).
 * MakBox is not affiliated with BeepBox or John Nesky. See NOTICE.
 */
(function (root, factory) {
	if (typeof module === "object" && module.exports) module.exports = factory(require("./theory.js"), require("./audio.js"));
	else { root.Amerika = root.Amerika || {}; root.Amerika.songtools = factory(root.Amerika.theory, root.Amerika.audio); }
})(typeof self !== "undefined" ? self : this, function (T, A) {
	"use strict";

	const clone = function (o) { return JSON.parse(JSON.stringify(o)); };
	const VOL_STEPS = [33, 67, 100];
	function err(msg) { const e = new Error(msg); e.userFacing = true; return e; }

	// parameter -> effect that must be enabled for BeepBox to keep it
	const PARAM_EFFECT = {
		reverb: "reverb", chorus: "chorus", pan: "panning", distortion: "distortion", bitcrusherOctave: "bitcrusher", bitcrusherQuantization: "bitcrusher",
		noteFilter: "note filter", echoSustain: "echo", echoDelayBeats: "echo", pitchShiftSemitones: "pitch shift", detuneCents: "detune",
		vibrato: "vibrato", transition: "transition type", chord: "chord type",
	};

	function create(B, host) {
		const C = B.Config;
		const names = function (list) { return Array.prototype.map.call(list, function (x) { return x && x.name !== undefined ? x.name : x; }); };
		const LIMITS = {
			pitchChannelsMax: C.pitchChannelCountMax, noiseChannelsMax: C.noiseChannelCountMax, barsMax: C.barCountMax,
			beatsPerBar: [C.beatsPerBarMin, C.beatsPerBarMax], tempo: [C.tempoMin, C.tempoMax], chordSizeMax: C.maxChordSize,
			layeredInstrumentsMax: C.layeredInstrumentCountMax, patternInstrumentsMax: C.patternInstrumentCountMax, drumRows: C.drumCount,
		};
		const ENUMS = {
			type: Array.from(C.instrumentTypeNames), wave: names(C.chipWaves), noiseWave: names(C.chipNoises), unison: names(C.unisons),
			effects: Array.from(C.effectNames), transition: names(C.transitions), chord: names(C.chords), vibrato: names(C.vibratos),
			algorithm: names(C.algorithms), feedbackType: names(C.feedbacks), operatorFrequency: names(C.operatorFrequencies),
			envelope: names(C.envelopes), envelopeTarget: names(C.instrumentAutomationTargets), filterType: Array.from(C.filterTypeNames),
			scale: names(C.scales), key: names(C.keys), rhythm: names(C.rhythms),
		};
		const DRUM_TYPES = ["noise", "spectrum", "drumset"];

		// ------------------------------------------------------------ JSON plumbing
		function snapshot() {
			const j = clone(host.getSong().toJsonObject());
			return normalize(j);
		}
		function barCountOf(j) { return Math.max.apply(null, [1].concat(j.channels.map(function (c) { return c.sequence.length; }))); }
		function patternCountOf(j) { return Math.max.apply(null, [1].concat(j.channels.map(function (c) { return c.patterns.length; }))); }
		function normalize(j) {
			const bars = barCountOf(j), pats = patternCountOf(j);
			j.channels.forEach(function (c) {
				while (c.sequence.length < bars) c.sequence.push(0);
				while (c.patterns.length < pats) c.patterns.push({ notes: [] });
			});
			return j;
		}
		function countNotes(j) {
			let n = 0;
			j.channels.forEach(function (c) { c.patterns.forEach(function (p) { n += (p.notes || []).length; }); });
			return n;
		}
		function usedNotes(j) { // notes that will actually sound (referenced by the sequence)
			let n = 0;
			j.channels.forEach(function (c) { c.sequence.forEach(function (s) { if (s > 0 && c.patterns[s - 1]) n += (c.patterns[s - 1].notes || []).length; }); });
			return n;
		}
		/** Validate by loading into a real Song; commit through the host. Returns {song, json, warnings}. */
		function finalize(j, label, opts) {
			opts = opts || {};
			normalize(j);
			const pitchCount = j.channels.filter(function (c) { return c.type !== "drum"; }).length;
			const noiseCount = j.channels.length - pitchCount;
			if (pitchCount > LIMITS.pitchChannelsMax) throw err("too many pitch channels (max " + LIMITS.pitchChannelsMax + ")");
			if (noiseCount > LIMITS.noiseChannelsMax) throw err("too many drum channels (max " + LIMITS.noiseChannelsMax + ")");
			if (pitchCount < 1) throw err("a song needs at least one pitch channel");
			if (barCountOf(j) > LIMITS.barsMax) throw err("song too long: max " + LIMITS.barsMax + " bars");
			const s = new B.Song();
			s.fromJsonObject(j);
			const out = clone(s.toJsonObject());
			const warnings = [];
			if (opts.expectNotes != null) {
				const got = countNotes(out);
				if (got < opts.expectNotes) warnings.push((opts.expectNotes - got) + " note(s) were dropped by BeepBox's validation (out of range, overlapping or outside the bar).");
			}
			host.commit(s, label);
			return { song: s, json: normalize(out), warnings: warnings };
		}

		// ------------------------------------------------------------ pitch / time helpers
		function keyBase(j) { return 12 + (typeof j.key === "string" ? Math.max(0, ENUMS.key.indexOf(j.key)) : 0); }
		function tpb(j) { return j.ticksPerBeat || 4; }
		function isDrum(c) { return c.type === "drum"; }
		function quantStep(j, quant) { return quant === false ? 1 / 24 : 1 / tpb(j); }
		function snapVol(v) {
			if (v == null || isNaN(v)) return 100;
			const size = Math.max(1, Math.min(3, Math.round(v * 3 / 100)));
			return VOL_STEPS[size - 1];
		}
		function pitchName(midi) { return T.midiToNote(midi); }

		/** Parse a pitch token for a channel into a BeepBox pitch (integer). */
		function parsePitch(tok, j, drum) {
			if (typeof tok === "number") return midiOrRow(tok, j, drum);
			const t = String(tok).trim();
			if (drum) {
				if (/^\d+$/.test(t)) return midiOrRow(parseInt(t, 10), j, true);
				const k = t.toLowerCase().replace(/[^a-z0-9]/g, "");
				const alias = { bd: "kick", bassdrum: "kick", sd: "snare", hh: "hat", closedhat: "hat", hihat: "hat", oh: "openhat", tom: "tommid", lowtom: "tomlow", midtom: "tommid", hightom: "tomhigh", tom1: "tomlow", tom2: "tommid", tom3: "tomhigh", cymbal: "crash", rimshot: "rim", cowbell: "bell" };
				const name = alias[k] || k;
				if (name in T.DRUM_ROWS) return T.DRUM_ROWS[name];
				throw err("unknown drum '" + t + "'. Use a row number 0-" + (LIMITS.drumRows - 1) + " or: " + T.DRUM_NAMES.join(", "));
			}
			if (/^\d+$/.test(t)) return midiOrRow(parseInt(t, 10), j, false);
			const m = T.noteToMidi(t);
			if (m == null) throw err("cannot read pitch '" + t + "'. Use note names like C4, F#3, Bb2 or MIDI numbers like 60");
			return midiOrRow(m, j, false);
		}
		function midiOrRow(n, j, drum) {
			if (drum) {
				if (n < 0 || n >= LIMITS.drumRows) throw err("drum row " + n + " out of range 0-" + (LIMITS.drumRows - 1));
				return n;
			}
			const p = n - keyBase(j);
			if (p < 0 || p > C.maxPitch) {
				const lo = keyBase(j), hi = keyBase(j) + C.maxPitch;
				throw err("pitch " + pitchName(n) + " (MIDI " + n + ") is outside this song's range " + pitchName(lo) + " to " + pitchName(hi) + " (MIDI " + lo + "-" + hi + ") in key " + j.key);
			}
			return p;
		}
		function formatPitch(p, j, drum) { return drum ? String(p) : pitchName(p + keyBase(j)); }

		const NOTE_RE = /^([^@\s]+)@(-?\d*\.?\d+)\+(\d*\.?\d+)((?:[vfb]-?\d*\.?\d+)*)$/;
		/** notes spec (string or array) -> events [{pitches:[bbPitch], start, dur, vol, vol2, bend}] in beats */
		function parseNotes(spec, j, drum, warnings) {
			const events = [];
			if (spec == null || spec === "") return events;
			if (typeof spec === "string") {
				const toks = spec.split(/[\s,;|]+/).filter(Boolean);
				toks.forEach(function (tok) {
					const m = NOTE_RE.exec(tok);
					if (!m) throw err("cannot read note token '" + tok + "'. Format: PITCH[/PITCH...]@START+LENGTH[vVOL][fENDVOL][bBEND], e.g. C4@0+1 E4/G4@1+0.5v67");
					const ev = { pitches: m[1].split("/").map(function (p) { return parsePitch(p, j, drum); }), start: parseFloat(m[2]), dur: parseFloat(m[3]), vol: 100 };
					const re = /([vfb])(-?\d*\.?\d+)/g; let mm;
					while ((mm = re.exec(m[4]))) { const val = parseFloat(mm[2]); if (mm[1] === "v") ev.vol = val; else if (mm[1] === "f") ev.vol2 = val; else ev.bend = val; }
					events.push(ev);
				});
			} else if (Array.isArray(spec)) {
				spec.forEach(function (n, i) {
					if (!n || typeof n !== "object") throw err("notes[" + i + "] must be an object {pitches, start, dur}");
					const ps = Array.isArray(n.pitches) ? n.pitches : [n.pitch != null ? n.pitch : n.pitches];
					if (ps.length === 0 || ps[0] == null) throw err("notes[" + i + "] has no pitches");
					const start = +n.start;
					const dur = n.dur != null ? +n.dur : (n.end != null ? +n.end - start : NaN);
					if (!isFinite(start) || !isFinite(dur)) throw err("notes[" + i + "] needs numeric start and dur (beats)");
					events.push({ pitches: ps.map(function (p) { return parsePitch(p, j, drum); }), start: start, dur: dur, vol: n.vol != null ? +n.vol : 100, vol2: n.vol2 != null ? +n.vol2 : (n.end_vol != null ? +n.end_vol : undefined), bend: n.bend != null ? +n.bend : undefined });
				});
			} else throw err("notes must be a compact string or an array of note objects");
			return events;
		}

		/** events (beats within one bar) -> BeepBox JSON notes for that pattern. */
		function eventsToNotes(events, j, quant, warnings, barLabel) {
			const bpb = j.beatsPerBar, step = quantStep(j, quant), t = tpb(j);
			const q = function (x) { return Math.round(x / step) * step; };
			let evs = events.map(function (e) {
				let s = q(e.start), en = q(e.start + e.dur);
				if (en - s < step - 1e-9) en = s + step;
				return { pitches: e.pitches.slice(), start: s, end: en, vol: e.vol, vol2: e.vol2, bend: e.bend, tie: e.tie };
			}).filter(function (e) {
				if (e.start < -1e-9 || e.start >= bpb - 1e-9) { warnings.push((barLabel || "pattern") + ": note at beat " + e.start + " is outside the bar (0 to " + bpb + ") and was dropped"); return false; }
				return true;
			});
			evs.forEach(function (e) { if (e.end > bpb + 1e-9) { warnings.push((barLabel || "pattern") + ": note ending at beat " + e.end + " was shortened to the bar end (" + bpb + ")"); e.end = bpb; } });
			evs.sort(function (a, b) { return a.start - b.start || a.pitches[0] - b.pitches[0]; });
			// merge same-start events into chords
			const merged = [];
			evs.forEach(function (e) {
				const last = merged[merged.length - 1];
				if (last && Math.abs(last.start - e.start) < 1e-9) {
					e.pitches.forEach(function (p) { if (last.pitches.indexOf(p) < 0) last.pitches.push(p); });
					last.end = Math.max(last.end, e.end);
					if (last.pitches.length > LIMITS.chordSizeMax) { warnings.push((barLabel || "pattern") + ": chords hold at most " + LIMITS.chordSizeMax + " pitches; extra pitches at beat " + e.start + " were dropped"); last.pitches.length = LIMITS.chordSizeMax; }
				} else merged.push(e);
			});
			// a channel plays one note (chord) at a time: cut a note when the next one starts
			let clipped = 0;
			for (let i = 0; i < merged.length - 1; i++) if (merged[i].end > merged[i + 1].start + 1e-9) { merged[i].end = merged[i + 1].start; clipped++; }
			if (clipped) warnings.push((barLabel || "pattern") + ": " + clipped + " overlapping note(s) were shortened (a channel plays one note or chord at a time; use chords 'C4/E4/G4@0+1' or another channel for layers)");
			return merged.map(function (e) {
				const v1 = snapVol(e.vol), v2 = e.vol2 != null ? snapVol(e.vol2) : v1;
				const pts = [{ tick: +(e.start * t).toFixed(5), pitchBend: 0, volume: v1 }];
				if (e.bend) pts.push({ tick: +(((e.start + e.end) / 2) * t).toFixed(5), pitchBend: Math.round(e.bend), volume: Math.round((v1 + v2) / 2) });
				pts.push({ tick: +(e.end * t).toFixed(5), pitchBend: Math.round(e.bend || 0), volume: v2 });
				// keep the middle point only if it is strictly between start and end
				if (pts.length === 3 && !(pts[1].tick > pts[0].tick && pts[1].tick < pts[2].tick)) pts.splice(1, 1);
				const o = { pitches: e.pitches, points: pts };
				if (e.start === 0) o.continuesLastPattern = !!e.tie;
				return o;
			});
		}
		function notesToEvents(notes, j) { // pattern JSON notes -> events in beats (pitches are BeepBox pitches)
			const t = tpb(j);
			return (notes || []).map(function (n) {
				const p0 = n.points[0], pl = n.points[n.points.length - 1];
				return { pitches: n.pitches.slice(), start: p0.tick / t, dur: (pl.tick - p0.tick) / t, vol: p0.volume, vol2: pl.volume !== p0.volume ? pl.volume : undefined, bend: pl.pitchBend - p0.pitchBend || undefined, tie: !!n.continuesLastPattern };
			});
		}
		function eventsToText(events, j, drum) {
			const f = function (x) { return String(+x.toFixed(3)); };
			return events.map(function (e) {
				let s = e.pitches.map(function (p) { return formatPitch(p, j, drum); }).join("/") + "@" + f(e.start) + "+" + f(e.dur);
				if (e.vol != null && e.vol !== 100) s += "v" + e.vol;
				if (e.vol2 != null) s += "f" + e.vol2;
				if (e.bend) s += "b" + e.bend;
				return s;
			}).join(" ");
		}

		// ------------------------------------------------------------ channel / pattern helpers
		function chIdx(j, n, what) {
			const i = Math.round(+n) - 1;
			if (!(i >= 0 && i < j.channels.length)) throw err((what || "channel") + " " + n + " does not exist; the song has channels 1-" + j.channels.length + " (use song_info)");
			return i;
		}
		function newPattern() { return { notes: [] }; }
		function ensurePatterns(j, count) {
			if (count > LIMITS.barsMax) throw err("too many patterns (max " + LIMITS.barsMax + ")");
			j.channels.forEach(function (c) { while (c.patterns.length < count) c.patterns.push(newPattern()); });
		}
		function ensureBars(j, count) {
			if (count > LIMITS.barsMax) throw err("song too long: max " + LIMITS.barsMax + " bars (asked for " + count + ")");
			j.channels.forEach(function (c) { while (c.sequence.length < count) c.sequence.push(0); });
		}
		function instrumentIndexFor(j, c, inst, warnings) {
			if (inst == null) return null;
			const n = Math.round(+inst);
			if (!(n >= 1 && n <= c.instruments.length)) throw err("instrument " + inst + " does not exist on this channel (it has " + c.instruments.length + ")");
			if (c.instruments.length > 1 && !j.patternInstruments && !j.layeredInstruments) j.patternInstruments = true;
			return n;
		}
		function patternSignature(p) { return JSON.stringify([p.notes, p.instruments || null]); }
		function setPatternInstruments(j, p, instN) {
			if (instN != null && j.patternInstruments) p.instruments = [instN];
		}
		/** Write per-bar event lists into a channel starting at bar index b0 (0-based). Reuses identical patterns. */
		function writeBars(j, ci, b0, barEvents, opts, warnings) {
			opts = opts || {};
			const c = j.channels[ci];
			const bars = b0 + barEvents.length;
			ensureBars(j, bars);
			const sigToIdx = {};
			c.patterns.forEach(function (p, i) { const s = patternSignature(p); if (p.notes.length && !(s in sigToIdx)) sigToIdx[s] = i + 1; });
			// patterns still referenced by bars outside the written range must not be modified: we only ever append / reuse
			barEvents.forEach(function (evs, k) {
				const bar = b0 + k;
				if (!evs || !evs.length) { c.sequence[bar] = 0; return; }
				const notes = eventsToNotes(evs, j, opts.quant, warnings, "bar " + (bar + 1));
				if (!notes.length) { c.sequence[bar] = 0; return; }
				const p = { notes: notes };
				setPatternInstruments(j, p, opts.instN);
				const sig = patternSignature(p);
				if (!(sig in sigToIdx)) {
					// reuse an empty unreferenced slot before growing
					c.patterns.push(p);
					sigToIdx[sig] = c.patterns.length;
				}
				c.sequence[bar] = sigToIdx[sig];
			});
			ensurePatterns(j, c.patterns.length);
		}
		/** Drop patterns not referenced by any bar and renumber (per channel). */
		function compact(j, ci) {
			const c = j.channels[ci];
			const used = {}; c.sequence.forEach(function (s) { if (s > 0) used[s] = true; });
			const map = {}; const keep = [];
			c.patterns.forEach(function (p, i) { if (used[i + 1]) { keep.push(p); map[i + 1] = keep.length; } });
			c.patterns = keep.length ? keep : [newPattern()];
			c.sequence = c.sequence.map(function (s) { return s > 0 ? map[s] : 0; });
			// BeepBox keeps one pattern count for the whole song: drop trailing empty, unreferenced patterns everywhere
			let need = 1;
			j.channels.forEach(function (ch) {
				const ref = {}; ch.sequence.forEach(function (x) { if (x > 0) ref[x] = true; });
				ch.patterns.forEach(function (p, i) { if (ref[i + 1] || (p.notes || []).length) need = Math.max(need, i + 1); });
			});
			j.channels.forEach(function (ch) { if (ch.patterns.length > need) ch.patterns.length = need; });
		}

		function instrumentSummary(ins, drumChannel) {
			const bits = [ins.type];
			if (ins.wave) bits.push(ins.wave);
			if (ins.algorithm) bits.push("alg " + ins.algorithm);
			if (ins.preset != null && ins.type) { /* upstream preset index, ignored */ }
			bits.push("vol " + ins.volume);
			const fx = (ins.effects || []).filter(function (e) { return e !== "chord type" || ins.chord !== "arpeggio"; });
			if (ins.chord && (ins.effects || []).indexOf("chord type") >= 0) bits.push("chord=" + ins.chord);
			const other = (ins.effects || []).filter(function (e) { return e !== "chord type"; });
			if (other.length) bits.push("fx: " + other.join(", "));
			if (ins.envelopes && ins.envelopes.length) bits.push("env: " + ins.envelopes.map(function (e) { return e.target + "/" + e.envelope; }).join(", "));
			if (ins.unison && ins.unison !== "none") bits.push("unison " + ins.unison);
			return bits.join(", ");
		}
		function seqText(seq) {
			const out = []; let i = 0;
			while (i < seq.length) { let k = i; while (k < seq.length && seq[k] === seq[i]) k++; out.push(k - i > 1 ? seq[i] + "x" + (k - i) : String(seq[i])); i = k; }
			return out.join(" ");
		}
		function parseSequence(spec) {
			if (Array.isArray(spec)) return spec.map(function (x) { const n = Math.round(+x); if (!(n >= 0)) throw err("sequence values must be 0 (empty) or a pattern number"); return n; });
			const out = [];
			String(spec).split(/[\s,;|]+/).filter(Boolean).forEach(function (tok) {
				const m = /^(\d+)(?:[x*×](\d+))?$/.exec(tok);
				if (!m) throw err("cannot read sequence token '" + tok + "'. Use pattern numbers like '1 1 2 3' or '1x4 2x4' (0 = empty bar)");
				const rep = m[2] ? parseInt(m[2], 10) : 1;
				for (let i = 0; i < rep; i++) out.push(parseInt(m[1], 10));
			});
			return out;
		}
		function parseBarList(spec, max) {
			if (Array.isArray(spec)) return spec.map(Number);
			const out = [];
			String(spec).split(/[\s,]+/).filter(Boolean).forEach(function (tok) {
				const m = /^(\d+)(?:-(\d+))?$/.exec(tok);
				if (!m) throw err("cannot read bar list '" + tok + "' (use '1,2,3' or '1-4')");
				const a = parseInt(m[1], 10), b = m[2] ? parseInt(m[2], 10) : a;
				for (let i = a; i <= b; i++) out.push(i);
			});
			return out;
		}

		// ------------------------------------------------------------ instrument validation
		// BeepBox spells some names with an en space (U+2002); models type a normal space. Compare loosely, store canonically.
		const plain = function (t) { return String(t).replace(/[\u2000-\u200a\u00a0]/g, " "); };
		function oneOf(value, list, what) {
			const hit = list.filter(function (x) { return plain(x) === plain(value); })[0];
			if (hit === undefined) throw err("unknown " + what + " '" + value + "'. Allowed: " + list.map(plain).join(" | "));
			return hit;
		}
		function validateInstrument(ins, drumChannel) {
			const fix = function (obj, key, list, what) { if (obj[key] != null) obj[key] = oneOf(obj[key], list, what); };
			if (ins.type != null) ins.type = oneOf(ins.type, drumChannel ? DRUM_TYPES : ENUMS.type.filter(function (t) { return DRUM_TYPES.indexOf(t) < 0; }), (drumChannel ? "drum-channel" : "pitch-channel") + " instrument type");
			fix(ins, "wave", ins.type === "noise" ? ENUMS.noiseWave : ENUMS.wave, ins.type === "noise" ? "noise wave" : "chip wave");
			fix(ins, "unison", ENUMS.unison, "unison"); fix(ins, "chord", ENUMS.chord, "chord type"); fix(ins, "transition", ENUMS.transition, "transition");
			fix(ins, "vibrato", ENUMS.vibrato, "vibrato"); fix(ins, "algorithm", ENUMS.algorithm, "FM algorithm"); fix(ins, "feedbackType", ENUMS.feedbackType, "FM feedback type");
			if (ins.effects) ins.effects = ins.effects.map(function (e) { return oneOf(e, ENUMS.effects, "effect"); });
			(ins.operators || []).forEach(function (o) { fix(o, "frequency", ENUMS.operatorFrequency, "operator frequency"); });
			(ins.envelopes || []).forEach(function (e) { fix(e, "target", ENUMS.envelopeTarget, "envelope target"); fix(e, "envelope", ENUMS.envelope, "envelope"); });
			["eqFilter", "noteFilter"].forEach(function (k) { (ins[k] || []).forEach(function (f) { fix(f, "type", ENUMS.filterType, "filter type"); }); });
			if (ins.type === "FM" && ins.operators && ins.operators.length > 4) throw err("FM instruments have exactly 4 operators");
		}
		function fixEffects(ins) {
			(ins.effects || []).forEach(function (e) { oneOf(e, ENUMS.effects, "effect"); });
			const fx = new Set((ins.effects || []).map(function (e) { return oneOf(e, ENUMS.effects, "effect"); }));
			Object.keys(PARAM_EFFECT).forEach(function (k) { if (ins[k] != null && ins[k] !== "" && !(k === "vibrato" && ins[k] === "none")) fx.add(PARAM_EFFECT[k]); });
			ins.effects = ENUMS.effects.filter(function (e) { return fx.has(e); });
			return ins;
		}
		function resolveInstrument(spec, drumChannel, base) {
			let ins;
			if (spec == null) ins = T.instrumentPreset(drumChannel ? "drum kit" : "square lead");
			else if (typeof spec === "string") ins = T.instrumentPreset(spec);
			else if (typeof spec === "object") {
				const presetName = spec.preset && typeof spec.preset === "string" ? spec.preset : null;
				ins = presetName ? T.instrumentPreset(presetName) : (base && (!spec.type || spec.type === base.type) ? clone(base) : {});
				if (!presetName && !ins.type) ins.type = spec.type || (drumChannel ? "drumset" : "chip");
				Object.keys(spec).forEach(function (k) { if (k !== "preset") ins[k] = spec[k]; });
			} else throw err("instrument must be a preset name or an object");
			fixEffects(ins);
			validateInstrument(ins, drumChannel);
			if (ins.type === "FM") { // BeepBox's blank FM instrument is silent (all operator amplitudes 0): start from an audible one
				const ops = (ins.operators || []).slice(0, 4);
				while (ops.length < 4) ops.push({ frequency: ENUMS.operatorFrequency[0], amplitude: ops.length === 0 ? 15 : 0 });
				if (ops.every(function (o) { return !o.amplitude; })) ops[0].amplitude = 15;
				ins.operators = ops;
				if (ins.algorithm == null) ins.algorithm = ENUMS.algorithm[0];
				if (ins.feedbackType == null) ins.feedbackType = ENUMS.feedbackType[0];
			}
			return ins;
		}

		// ------------------------------------------------------------ the tools
		const tools = {};
		const defs = [];
		function tool(name, description, schema, fn, meta) {
			tools[name] = fn;
			defs.push({ name: name, description: description, input_schema: Object.assign({ type: "object", properties: {}, additionalProperties: false }, schema), mutates: !(meta && meta.read) });
		}
		const int = function (d, extra) { return Object.assign({ type: "integer", description: d }, extra || {}); };
		const str = function (d, extra) { return Object.assign({ type: "string", description: d }, extra || {}); };

		function summary(j) {
			const bars = barCountOf(j);
			return { bars: bars, channels: j.channels.length, tempo: j.beatsPerMinute, seconds: +(bars * j.beatsPerBar * 60 / j.beatsPerMinute).toFixed(1), notes: usedNotes(j) };
		}
		function ok(message, j, warnings, extra) {
			return Object.assign({ ok: true, message: message, song: summary(j) }, warnings && warnings.length ? { warnings: warnings } : {}, extra || {});
		}

		tool("song_info",
			"Describe the current song: key, scale, tempo, beats per bar, bars, loop, and every channel with its instruments, pattern usage, note count, pitch range and bar sequence. Call this first before editing. Channels, patterns, instruments and bars are numbered from 1.",
			{ properties: { detail: str("'summary' (default) or 'patterns' to also list which pattern number is used in each bar and how many notes each pattern has", { enum: ["summary", "patterns"] }) } },
			function (a) {
				const j = snapshot(), bars = barCountOf(j);
				const chans = j.channels.map(function (c, i) {
					const drum = isDrum(c);
					let lo = 999, hi = -1, nn = 0;
					c.sequence.forEach(function (s) { if (s > 0) (c.patterns[s - 1].notes || []).forEach(function (n) { nn++; n.pitches.forEach(function (p) { lo = Math.min(lo, p); hi = Math.max(hi, p); }); }); });
					const o = {
						channel: i + 1, type: drum ? "drum" : "pitch", instruments: c.instruments.map(function (ins, k) { return (k + 1) + ": " + instrumentSummary(ins, drum); }),
						patterns: c.patterns.length, patternsUsed: Object.keys(c.sequence.reduce(function (m, s) { if (s) m[s] = 1; return m; }, {})).length,
						notes: nn, range: hi < 0 ? null : (drum ? "rows " + lo + "-" + hi : pitchName(lo + keyBase(j)) + " to " + pitchName(hi + keyBase(j))),
						sequence: seqText(c.sequence),
					};
					if (!drum) o.octaveView = c.octaveScrollBar + 1;
					if (a && a.detail === "patterns") o.patternNoteCounts = c.patterns.map(function (p) { return (p.notes || []).length; });
					return o;
				});
				return {
					key: j.key, scale: j.scale, tempo: j.beatsPerMinute, beatsPerBar: j.beatsPerBar, rhythm: ENUMS.rhythm[[3, 4, 6, 8, 24].indexOf(tpb(j))] || ("ticksPerBeat " + tpb(j)),
					bars: bars, intro_bars: j.introBars, loop_bars: j.loopBars, seconds: +(bars * j.beatsPerBar * 60 / j.beatsPerMinute).toFixed(2),
					layeredInstruments: j.layeredInstruments, patternInstruments: j.patternInstruments,
					pitchRange: pitchName(keyBase(j)) + " to " + pitchName(keyBase(j) + C.maxPitch), drumRows: LIMITS.drumRows,
					channels: chans, limits: LIMITS,
				};
			}, { read: true });

		tool("new_song",
			"Start a fresh song, replacing the current one. 'standard' creates lead, harmony, bass and drum channels with empty patterns; 'empty' creates one square lead channel and one drum channel.",
			{ properties: { layout: str("channel layout", { enum: ["standard", "empty"] }), key: str("tonic, e.g. C, D, F#, Bb"), scale: str("scale name (see set_song_settings)"), tempo: int("beats per minute", { minimum: 30, maximum: 300 }), bars: int("song length in bars", { minimum: 1, maximum: 128 }), beats_per_bar: int("beats per bar", { minimum: 3, maximum: 16 }) } },
			function (a) {
				const j = { format: "BeepBox", version: 9, scale: "normal :)", key: "C", introBars: 0, loopBars: 8, beatsPerBar: 4, ticksPerBeat: 4, beatsPerMinute: 120, layeredInstruments: false, patternInstruments: false, channels: [] };
				applySettings(j, a || {});
				const bars = (a && a.bars) || 8;
				const mk = function (type, preset, oct) { return { type: type, instruments: [T.instrumentPreset(preset)], patterns: [newPattern()], sequence: new Array(bars).fill(0), octaveScrollBar: oct }; };
				if (!a || a.layout !== "empty") j.channels = [mk("pitch", "square lead", 3), mk("pitch", "chip arp", 2), mk("pitch", "triangle bass", 1), mk("drum", "drum kit")];
				else j.channels = [mk("pitch", "square lead", 3), mk("drum", "drum kit")];
				j.channels.forEach(function (c) { if (c.type === "drum") delete c.octaveScrollBar; });
				j.loopBars = bars;
				const r = finalize(j, "AI: new song");
				return ok("New song created.", r.json, r.warnings);
			});

		function applySettings(j, a) {
			const changed = [];
			if (a.key != null) {
				const k = T.keyIndex(a.key);
				if (k < 0) throw err("unknown key '" + a.key + "'. Use one of: " + ENUMS.key.join(" "));
				j.key = ENUMS.key[k]; changed.push("key");
			}
			if (a.scale != null) {
				const s = T.resolveScale(a.scale);
				if (!s) throw err("unknown scale '" + a.scale + "'. Allowed: " + ENUMS.scale.join(" | ") + " (aliases: major, minor, pentatonic major/minor, blues, harmonic minor...)");
				j.scale = s; changed.push("scale");
			}
			if (a.tempo != null) {
				if (!(a.tempo >= LIMITS.tempo[0] && a.tempo <= LIMITS.tempo[1])) throw err("tempo must be " + LIMITS.tempo[0] + "-" + LIMITS.tempo[1]);
				j.beatsPerMinute = Math.round(a.tempo); changed.push("tempo");
			}
			if (a.beats_per_bar != null) {
				if (!(a.beats_per_bar >= LIMITS.beatsPerBar[0] && a.beats_per_bar <= LIMITS.beatsPerBar[1])) throw err("beats_per_bar must be " + LIMITS.beatsPerBar.join("-"));
				j.beatsPerBar = Math.round(a.beats_per_bar); changed.push("beats_per_bar");
			}
			if (a.rhythm != null) {
				const names3 = { "3": 3, "triplets": 3, "÷3": 3, "4": 4, "standard": 4, "÷4": 4, "6": 6, "÷6": 6, "8": 8, "÷8": 8, "freehand": 24, "24": 24 };
				const key = String(a.rhythm).toLowerCase().replace(/\s*\(.*\)/, "").trim();
				const nt = names3[key] || names3[String(a.rhythm)];
				if (!nt) throw err("unknown rhythm '" + a.rhythm + "'. Use ÷3 (triplets), ÷4 (standard), ÷6, ÷8 or freehand");
				const old = tpb(j);
				if (j.channels) j.channels.forEach(function (c) { c.patterns.forEach(function (p) { (p.notes || []).forEach(function (n) { n.points.forEach(function (pt) { pt.tick = pt.tick * nt / old; }); }); }); });
				j.ticksPerBeat = nt; changed.push("rhythm");
			}
			return changed;
		}

		tool("set_song_settings",
			"Change song-wide settings: key, scale, tempo, beats per bar, rhythm grid, total length in bars, and the loop region (intro bars then loop bars). Existing notes keep their absolute pitches; use transform_notes to move notes into a new key or scale. Changing beats_per_bar drops notes that no longer fit.",
			{ properties: {
				key: str("tonic: C, C#, D, Eb, F#, ..."), scale: str("one of: " + ENUMS.scale.join(", ") + ". Aliases: major, minor, pentatonic major/minor, blues, harmonic minor, whole tone, chromatic"),
				tempo: int("beats per minute 30-300", { minimum: 30, maximum: 300 }), beats_per_bar: int("3-16", { minimum: 3, maximum: 16 }),
				rhythm: str("note grid: ÷3 (triplets), ÷4 (standard 16ths), ÷6, ÷8, freehand"), bars: int("total song length in bars (1-128); shorter truncates, longer adds empty bars", { minimum: 1, maximum: 128 }),
				intro_bars: int("bars before the loop starts (0 = loop from the beginning)", { minimum: 0 }), loop_bars: int("length of the looping section in bars", { minimum: 1 }),
				layered_instruments: { type: "boolean", description: "if true, all instruments of a channel play together (layers)" }, pattern_instruments: { type: "boolean", description: "if true, each pattern chooses which instrument plays" },
			} },
			function (a) {
				const j = snapshot();
				const before = countNotes(j);
				const changed = applySettings(j, a);
				if (a.bars != null) {
					const n = Math.round(a.bars);
					if (!(n >= 1 && n <= LIMITS.barsMax)) throw err("bars must be 1-" + LIMITS.barsMax);
					j.channels.forEach(function (c) { c.sequence.length = n; while (c.sequence.length < n) c.sequence.push(0); });
					changed.push("bars");
				}
				if (a.intro_bars != null) { j.introBars = Math.max(0, Math.round(a.intro_bars)); changed.push("intro_bars"); }
				if (a.loop_bars != null) { j.loopBars = Math.max(1, Math.round(a.loop_bars)); changed.push("loop_bars"); }
				if (a.layered_instruments != null) { j.layeredInstruments = !!a.layered_instruments; changed.push("layered_instruments"); }
				if (a.pattern_instruments != null) { j.patternInstruments = !!a.pattern_instruments; changed.push("pattern_instruments"); }
				if ((a.bars != null) && a.loop_bars == null && j.introBars + j.loopBars > a.bars) j.loopBars = Math.max(1, a.bars - j.introBars);
				if (!changed.length) throw err("nothing to change: give at least one setting");
				const dropsExpected = (a.beats_per_bar != null) ? null : before;
				const r = finalize(j, "AI: song settings");
				const w = r.warnings.slice();
				if (a.beats_per_bar != null && countNotes(r.json) < before) w.push((before - countNotes(r.json)) + " note(s) no longer fit in the shorter bars and were dropped");
				return ok("Updated " + changed.join(", ") + ".", r.json, w);
			});

		tool("add_channel",
			"Add a pitch channel (melody, harmony, bass; up to " + LIMITS.pitchChannelsMax + ") or a drum channel (up to " + LIMITS.noiseChannelsMax + "). The first instrument can be a preset name or a full BeepBox instrument JSON object. Returns the new channel number.",
			{ required: ["type"], properties: {
				type: str("pitch or drum", { enum: ["pitch", "drum"] }),
				instrument: { description: "preset name (" + Object.keys(T.INSTRUMENT_PRESETS).join(", ") + ") or an instrument object like {\"type\":\"chip\",\"wave\":\"square\",\"volume\":80,\"effects\":[\"reverb\"],\"reverb\":25}", anyOf: [{ type: "string" }, { type: "object" }] },
				octave: int("which octave the editor shows for this channel (1-7), default 3 for leads, 1-2 for bass", { minimum: 1, maximum: 7 }),
			} },
			function (a) {
				const j = snapshot();
				const drum = a.type === "drum";
				const ins = resolveInstrument(a.instrument, drum);
				const bars = barCountOf(j);
				const ch = { type: drum ? "drum" : "pitch", instruments: [ins], patterns: new Array(patternCountOf(j)).fill(0).map(newPattern), sequence: new Array(bars).fill(0) };
				if (!drum) ch.octaveScrollBar = Math.max(0, Math.min(6, (a.octave || 3) - 1));
				if (drum) j.channels.push(ch);
				else { const pc = j.channels.filter(function (c) { return !isDrum(c); }).length; j.channels.splice(pc, 0, ch); }
				const r = finalize(j, "AI: add channel");
				const idx = drum ? r.json.channels.length : r.json.channels.filter(function (c) { return !isDrum(c); }).length;
				return ok("Added " + a.type + " channel " + idx + ".", r.json, r.warnings, { channel: idx });
			});

		tool("add_instrument",
			"Add another instrument to a channel. Channels with several instruments need either pattern_instruments (each pattern picks one; write_pattern/write_track take an 'instrument' argument) or layered_instruments (all play together); this tool enables pattern_instruments automatically if neither is on.",
			{ required: ["channel"], properties: { channel: int("channel number (from 1)", { minimum: 1 }), instrument: { description: "preset name or instrument object", anyOf: [{ type: "string" }, { type: "object" }] }, layered: { type: "boolean", description: "make all instruments of the song layered" } } },
			function (a) {
				const j = snapshot(); const ci = chIdx(j, a.channel);
				const c = j.channels[ci];
				const max = a.layered || j.layeredInstruments ? LIMITS.layeredInstrumentsMax : LIMITS.patternInstrumentsMax;
				if (c.instruments.length >= max) throw err("this channel already has the maximum of " + max + " instruments");
				c.instruments.push(resolveInstrument(a.instrument, isDrum(c)));
				if (a.layered) j.layeredInstruments = true; else if (!j.layeredInstruments) j.patternInstruments = true;
				const r = finalize(j, "AI: add instrument");
				return ok("Channel " + a.channel + " now has " + c.instruments.length + " instruments (number " + c.instruments.length + " is new).", r.json, r.warnings, { instrument: c.instruments.length });
			});

		tool("set_instrument",
			"Change an instrument. Give a 'preset' name to replace it, and/or 'settings' to merge BeepBox instrument fields (type chip|FM|noise|spectrum|drumset|harmonics|PWM|Picked String|supersaw, volume 0-100, wave, unison, effects[], chord, transition, vibrato, reverb/chorus/pan/distortion/echoSustain... 0-100, eqFilter/noteFilter point lists, envelopes [{target,envelope}], FM algorithm/operators/feedback, pulseWidth, harmonics[28], spectrum[30], drums[12]). Parameters that need an effect (reverb, chorus, pan, distortion, bitcrusher, echo, vibrato, pitchShiftSemitones, detuneCents, noteFilter, transition, chord) enable it automatically. Invalid names are rejected with the allowed list.",
			{ required: ["channel"], properties: { channel: int("channel number", { minimum: 1 }), instrument: int("instrument number on the channel (default 1)", { minimum: 1 }), preset: str("instrument preset name: " + Object.keys(T.INSTRUMENT_PRESETS).join(", ")), settings: { type: "object", description: "instrument JSON fields to merge" } } },
			function (a) {
				const j = snapshot(); const ci = chIdx(j, a.channel);
				const c = j.channels[ci]; const k = (a.instrument || 1) - 1;
				if (!(k >= 0 && k < c.instruments.length)) throw err("instrument " + a.instrument + " does not exist on channel " + a.channel + " (it has " + c.instruments.length + ")");
				if (!a.preset && !a.settings) throw err("give a preset and/or settings");
				let spec = Object.assign({}, a.settings || {});
				if (a.preset) spec.preset = a.preset;
				c.instruments[k] = resolveInstrument(spec, isDrum(c), c.instruments[k]);
				const r = finalize(j, "AI: set instrument");
				return ok("Instrument " + (k + 1) + " on channel " + a.channel + " is now: " + instrumentSummary(r.json.channels[ci].instruments[k]) + ".", r.json, r.warnings);
			});

		tool("write_pattern",
			"Write the notes of one pattern (one bar of music). Notes are a compact string of tokens PITCH[/PITCH...]@START+LENGTH[vVOL][fENDVOL][bBEND]: pitches are note names (C4 = middle C, F#3, Bb2) or MIDI numbers; in drum channels use row numbers 0-11 (with the 'drum kit' preset: 0 kick 1 snare 2 hat 3 open hat 4-6 toms 7 crash 8 clap 9 rim 10 shaker 11 bell) or those names. START and LENGTH are in beats from the start of the bar; vVOL is 0-100 (only 33, 67, 100 are distinct); fENDVOL fades to that volume; bBEND bends to that many semitones by the end. Chords: C4/E4/G4@0+4 (max 4 pitches; arpeggiate automatically if the instrument's chord type is arpeggio). Example: \"C4@0+1 E4@1+0.5v67 G4/B4@2+2\". Alternatively pass an array of {pitches,start,dur,vol,vol2,bend}. Optionally place the pattern in bars with 'bars' (e.g. \"1-4\" or [1,3]).",
			{ required: ["channel", "pattern", "notes"], properties: {
				channel: int("channel number", { minimum: 1 }), pattern: int("pattern number (from 1). New numbers up to the current count + 1 are created.", { minimum: 1 }),
				notes: { description: "compact string or array of note objects; empty string clears the pattern", anyOf: [{ type: "string" }, { type: "array", items: { type: "object" } }] },
				instrument: int("which instrument of the channel plays this pattern (needs pattern_instruments)", { minimum: 1 }),
				bars: { description: "bars (from 1) to put this pattern in, e.g. '1-4' or [1,2,3]", anyOf: [{ type: "string" }, { type: "array", items: { type: "integer" } }] },
				mode: str("replace (default) or append to existing notes", { enum: ["replace", "append"] }), quantize: { type: "boolean", description: "snap to the rhythm grid (default true)" },
			} },
			function (a) {
				const j = snapshot(); const ci = chIdx(j, a.channel); const c = j.channels[ci]; const drum = isDrum(c);
				const warnings = [];
				const events = parseNotes(a.notes, j, drum, warnings);
				const pidx = Math.round(a.pattern);
				if (!(pidx >= 1)) throw err("pattern numbers start at 1");
				if (pidx > c.patterns.length + 1 && pidx > patternCountOf(j) + 1) throw err("pattern " + pidx + " would leave gaps: the next new pattern number is " + (patternCountOf(j) + 1));
				ensurePatterns(j, Math.max(pidx, patternCountOf(j)));
				const instN = instrumentIndexFor(j, c, a.instrument, warnings);
				let all = events;
				if (a.mode === "append") all = notesToEvents(c.patterns[pidx - 1].notes, j).concat(events);
				const notes = eventsToNotes(all, j, a.quantize, warnings, "pattern " + pidx);
				const p = { notes: notes };
				if (j.patternInstruments) p.instruments = instN != null ? [instN] : (c.patterns[pidx - 1].instruments || [1]);
				c.patterns[pidx - 1] = p;
				if (a.bars != null) {
					const list = parseBarList(a.bars);
					list.forEach(function (b) { if (!(b >= 1)) throw err("bars start at 1"); });
					ensureBars(j, Math.max.apply(null, list));
					list.forEach(function (b) { c.sequence[b - 1] = pidx; });
				}
				const r = finalize(j, "AI: write pattern");
				return ok("Pattern " + pidx + " on channel " + a.channel + " now has " + notes.length + " note(s)" + (a.bars != null ? " and is placed in bars " + a.bars : "") + ".", r.json, warnings.concat(r.warnings));
			});

		tool("write_track",
			"Write a stretch of music on one channel as one continuous note list in beats from the first bar given (bar length = beats_per_bar). Notes crossing a barline are split and tied. Bars are filled with patterns automatically (identical bars reuse one pattern) and the sequence is set. Replaces what was in those bars. Same note format as write_pattern. Best way to write melodies, basslines and drums over many bars.",
			{ required: ["channel", "notes"], properties: {
				channel: int("channel number", { minimum: 1 }), start_bar: int("first bar to write (default 1)", { minimum: 1 }),
				bars: int("number of bars to cover (default: until the last note, rounded up); trailing bars without notes become empty", { minimum: 1 }),
				notes: { description: "compact string or array; START is beats from the start of start_bar (bar 2 of a 4/4 song starts at beat 4)", anyOf: [{ type: "string" }, { type: "array", items: { type: "object" } }] },
				instrument: int("instrument of the channel that plays these bars", { minimum: 1 }), quantize: { type: "boolean" },
				clean: { type: "boolean", description: "drop patterns on this channel that are no longer used (default true)" },
			} },
			function (a) {
				const j = snapshot(); const ci = chIdx(j, a.channel); const c = j.channels[ci]; const drum = isDrum(c);
				const warnings = [];
				const events = parseNotes(a.notes, j, drum, warnings);
				const bpb = j.beatsPerBar, b0 = (a.start_bar || 1) - 1;
				let last = 0; events.forEach(function (e) { last = Math.max(last, e.start + e.dur); });
				const nBars = a.bars || Math.max(1, Math.ceil(last / bpb - 1e-9));
				const perBar = []; for (let i = 0; i < nBars; i++) perBar.push([]);
				let dropped = 0;
				events.forEach(function (e) {
					if (e.start < 0) { dropped++; return; }
					let s = e.start, remaining = e.dur, first = true;
					while (remaining > 1e-9) {
						const bar = Math.floor(s / bpb + 1e-9);
						if (bar >= nBars) { dropped++; break; }
						const inBar = s - bar * bpb, take = Math.min(remaining, bpb - inBar);
						perBar[bar].push({ pitches: e.pitches, start: inBar, dur: take, vol: e.vol, vol2: e.vol2, bend: first ? e.bend : undefined, tie: !first });
						remaining -= take; s += take; first = false;
					}
				});
				if (dropped) warnings.push(dropped + " note(s) fell outside the " + nBars + " bar(s) being written and were ignored");
				const instN = instrumentIndexFor(j, c, a.instrument, warnings);
				writeBars(j, ci, b0, perBar, { quant: a.quantize, instN: instN }, warnings);
				if (a.clean !== false) compact(j, ci);
				const r = finalize(j, "AI: write track");
				return ok("Wrote bars " + (b0 + 1) + "-" + (b0 + nBars) + " on channel " + a.channel + ".", r.json, warnings.concat(r.warnings), { sequence: seqText(r.json.channels[ci].sequence) });
			});

		tool("read_notes",
			"Read the notes of a channel bar by bar in the same compact format write_track accepts (START is beats from the start of each bar). Use it before changing existing music.",
			{ required: ["channel"], properties: { channel: int("channel number", { minimum: 1 }), from_bar: int("first bar (default 1)", { minimum: 1 }), bars: int("how many bars (default all, max 64)", { minimum: 1, maximum: 64 }) } },
			function (a) {
				const j = snapshot(); const ci = chIdx(j, a.channel); const c = j.channels[ci]; const drum = isDrum(c);
				const from = (a.from_bar || 1) - 1, n = Math.min(a.bars || 64, 64, c.sequence.length - from);
				const out = [];
				for (let b = from; b < from + n; b++) {
					const s = c.sequence[b];
					out.push("bar " + (b + 1) + " (pattern " + s + (j.patternInstruments && s && c.patterns[s - 1].instruments ? ", instrument " + c.patterns[s - 1].instruments.join(",") : "") + "): " + (s ? eventsToText(notesToEvents(c.patterns[s - 1].notes, j), j, drum) || "(empty)" : "(no pattern)"));
				}
				return { channel: a.channel, type: drum ? "drum" : "pitch", beatsPerBar: j.beatsPerBar, text: out.join("\n") };
			}, { read: true });

		tool("set_sequence",
			"Set which pattern plays in each bar of a channel. 'sequence' is pattern numbers (0 = empty bar), e.g. '1 1 2 3' or '1x4 2x4'. Starts at start_bar and extends the song if needed. Patterns must already exist (create with write_pattern).",
			{ required: ["channel", "sequence"], properties: { channel: int("channel number", { minimum: 1 }), sequence: { description: "pattern numbers as array or string with xN repeats", anyOf: [{ type: "string" }, { type: "array", items: { type: "integer" } }] }, start_bar: int("first bar to set (default 1)", { minimum: 1 }) } },
			function (a) {
				const j = snapshot(); const ci = chIdx(j, a.channel); const c = j.channels[ci];
				const seq = parseSequence(a.sequence); const b0 = (a.start_bar || 1) - 1;
				seq.forEach(function (p) { if (p > c.patterns.length) throw err("pattern " + p + " does not exist on channel " + a.channel + " (it has " + c.patterns.length + "; create one with write_pattern)"); });
				ensureBars(j, b0 + seq.length);
				seq.forEach(function (p, i) { c.sequence[b0 + i] = p; });
				const r = finalize(j, "AI: set sequence");
				return ok("Sequence set.", r.json, r.warnings, { sequence: seqText(r.json.channels[ci].sequence) });
			});

		tool("clear",
			"Clear music without deleting channels: a pattern's notes, a range of bars on a channel (sets them to empty), or an entire channel's notes and sequence.",
			{ required: ["channel"], properties: { channel: int("channel number", { minimum: 1 }), pattern: int("clear the notes of this pattern", { minimum: 1 }), bars: { description: "bars to empty, e.g. '5-8'", anyOf: [{ type: "string" }, { type: "array", items: { type: "integer" } }] } } },
			function (a) {
				const j = snapshot(); const ci = chIdx(j, a.channel); const c = j.channels[ci];
				let what;
				if (a.pattern != null) { if (a.pattern > c.patterns.length) throw err("pattern " + a.pattern + " does not exist"); c.patterns[a.pattern - 1] = { notes: [] }; what = "pattern " + a.pattern; }
				else if (a.bars != null) { parseBarList(a.bars).forEach(function (b) { if (b >= 1 && b <= c.sequence.length) c.sequence[b - 1] = 0; }); what = "bars " + a.bars; }
				else { c.patterns = c.patterns.map(newPattern); c.sequence = c.sequence.map(function () { return 0; }); what = "all of channel " + a.channel; }
				const r = finalize(j, "AI: clear");
				return ok("Cleared " + what + ".", r.json, r.warnings);
			});

		tool("delete",
			"Delete a whole channel, or one instrument from a channel. A song keeps at least one pitch channel and one instrument per channel.",
			{ required: ["channel"], properties: { channel: int("channel number", { minimum: 1 }), instrument: int("if given, delete only this instrument", { minimum: 1 }) } },
			function (a) {
				const j = snapshot(); const ci = chIdx(j, a.channel); const c = j.channels[ci];
				if (a.instrument != null) {
					const k = a.instrument - 1;
					if (c.instruments.length <= 1) throw err("a channel needs at least one instrument");
					if (!(k >= 0 && k < c.instruments.length)) throw err("instrument " + a.instrument + " does not exist");
					c.instruments.splice(k, 1);
					c.patterns.forEach(function (p) { if (p.instruments) p.instruments = p.instruments.map(function (n) { return n - 1 === k ? 1 : (n - 1 > k ? n - 1 : n); }); });
					const r = finalize(j, "AI: delete instrument");
					return ok("Deleted instrument " + a.instrument + " of channel " + a.channel + ".", r.json, r.warnings);
				}
				if (!isDrum(c) && j.channels.filter(function (x) { return !isDrum(x); }).length <= 1) throw err("a song needs at least one pitch channel");
				j.channels.splice(ci, 1);
				const r = finalize(j, "AI: delete channel");
				return ok("Deleted channel " + a.channel + ". Later channels were renumbered.", r.json, r.warnings);
			});

		function noteScaleMap(from, to, keyPc) {
			const a = T.SCALES[T.resolveScale(from)], b = T.SCALES[T.resolveScale(to)];
			if (!a || !b) throw err("unknown scale in scale_map (from '" + from + "', to '" + to + "')");
			return function (midi) {
				const rel = (((midi - keyPc) % 12) + 12) % 12, oct = Math.floor((midi - keyPc) / 12);
				let deg = -1;
				for (let i = 0; i < a.length; i++) if (a[i] <= rel) deg = i;
				const off = rel - a[deg];
				const nd = Math.round(deg * b.length / a.length);
				return keyPc + 12 * oct + b[Math.min(b.length - 1, nd)] + off;
			};
		}
		tool("transform_notes",
			"Transform existing notes in place: transpose by semitones or octaves, remap scale degrees from one scale to another (e.g. major to minor to make a melody sadder), and scale volumes. Optionally limit to some channels and a bar range (shared patterns are copied so bars outside the range are untouched). Drum channels are skipped for pitch changes.",
			{ properties: {
				channels: { type: "array", items: { type: "integer" }, description: "channel numbers (default: all pitch channels)" }, from_bar: int("first bar (default 1)", { minimum: 1 }), to_bar: int("last bar (default: end)", { minimum: 1 }),
				transpose: int("semitones, positive up"), octaves: int("octaves, positive up"),
				scale_map: { type: "object", description: "{from, to} scale names; each note moves to the same scale degree in the new scale", properties: { from: { type: "string" }, to: { type: "string" } } },
				volume_scale: { type: "number", description: "multiply note volumes, e.g. 0.67" },
			} },
			function (a) {
				const j = snapshot(); const warnings = [];
				const chans = (a.channels && a.channels.length ? a.channels.map(function (n) { return chIdx(j, n); }) : j.channels.map(function (c, i) { return i; }).filter(function (i) { return !isDrum(j.channels[i]); }));
				const kb = keyBase(j);
				const semis = (a.transpose || 0) + 12 * (a.octaves || 0);
				const mapper = a.scale_map ? noteScaleMap(a.scale_map.from, a.scale_map.to, kb % 12) : null;
				if (!semis && !mapper && a.volume_scale == null) throw err("give transpose, octaves, scale_map or volume_scale");
				let moved = 0;
				chans.forEach(function (ci) {
					const c = j.channels[ci], drum = isDrum(c);
					const from = (a.from_bar || 1) - 1, to = Math.min(a.to_bar || c.sequence.length, c.sequence.length) - 1;
					const cow = {};
					for (let b = from; b <= to; b++) {
						const s = c.sequence[b]; if (!s) continue;
						let target = s;
						const usedOutside = c.sequence.some(function (x, bi) { return x === s && (bi < from || bi > to); });
						if (usedOutside) {
							if (!(s in cow)) { c.patterns.push(clone(c.patterns[s - 1])); cow[s] = c.patterns.length; }
							target = cow[s]; c.sequence[b] = target;
						}
						if (b > from && c.sequence.slice(from, b).indexOf(target) >= 0 && !usedOutside) continue; // already transformed in this pass
						const p = c.patterns[target - 1];
						(p.notes || []).forEach(function (n) {
							if (!drum) n.pitches = n.pitches.map(function (pp) {
								let m = pp + kb; if (mapper) m = mapper(m);
								m += semis; const np = m - kb;
								return Math.max(0, Math.min(C.maxPitch, np));
							});
							n.pitches = n.pitches.filter(function (x, i, arr) { return arr.indexOf(x) === i; });
							if (a.volume_scale != null) n.points.forEach(function (pt) { pt.volume = snapVol(pt.volume * a.volume_scale); });
							moved++;
						});
					}
				});
				ensurePatterns(j, patternCountOf(j));
				const r = finalize(j, "AI: transform notes");
				return ok("Transformed " + moved + " note(s) on channel(s) " + chans.map(function (i) { return i + 1; }).join(", ") + ".", r.json, warnings.concat(r.warnings));
			});

		tool("get_song_json",
			"Return BeepBox's own song JSON (the same structure BeepBox's JSON export uses: format, version, scale, key, introBars, loopBars, beatsPerBar, ticksPerBeat, beatsPerMinute, channels[{type, instruments[], patterns[{notes[{pitches[], points[{tick, pitchBend, volume}]}]}], sequence[]}]). In this JSON, pitches are raw BeepBox pitches (MIDI note minus 12 minus the key index), ticks are in units of 1/ticksPerBeat beat, sequence entries are 1-based pattern numbers (0 = empty). It can be large: use omit_notes or channels to trim.",
			{ properties: { omit_notes: { type: "boolean", description: "return only settings, instruments and sequences" }, channels: { type: "array", items: { type: "integer" }, description: "only these channel numbers" } } },
			function (a) {
				const j = snapshot();
				if (a && a.channels && a.channels.length) { const keep = a.channels.map(function (n) { return chIdx(j, n); }); j.channels = j.channels.filter(function (c, i) { return keep.indexOf(i) >= 0; }); }
				if (a && a.omit_notes) j.channels.forEach(function (c) { c.patterns = c.patterns.map(function (p) { return { noteCount: (p.notes || []).length }; }); });
				return { song: j };
			}, { read: true });

		tool("set_song_json",
			"Replace the whole song with BeepBox song JSON (object, JSON string, or a BeepBox URL hash like '#6n31s0k0l00e0...'). The data is validated and normalized through BeepBox's own Song.fromJsonObject; the result says how many notes survived. Use for large rewrites; prefer the other tools for small edits.",
			{ required: ["song"], properties: { song: { description: "BeepBox song JSON object or string", anyOf: [{ type: "object" }, { type: "string" }] } } },
			function (a) {
				let j = a.song;
				if (typeof j === "string") {
					const t = j.trim();
					if (t[0] === "{") { try { j = JSON.parse(t); } catch (e) { throw err("song is not valid JSON: " + e.message); } }
					else { try { const s = new B.Song(t.replace(/^.*#/, "")); j = clone(s.toJsonObject()); } catch (e) { throw err("could not read the BeepBox URL hash: " + e.message); } }
				}
				if (!j || typeof j !== "object" || !Array.isArray(j.channels) || !j.channels.length) throw err("song JSON needs a non-empty 'channels' array");
				j = clone(j);
				j.channels.forEach(function (c, i) {
					if (!Array.isArray(c.instruments) || !c.instruments.length) throw err("channel " + (i + 1) + " needs an instruments array");
					c.patterns = c.patterns || []; c.sequence = c.sequence || [];
					c.instruments.forEach(function (ins) { fixEffects(ins); validateInstrument(ins, c.type === "drum"); });
				});
				// keep pitch channels before drum channels, as BeepBox does
				j.channels = j.channels.filter(function (c) { return c.type !== "drum"; }).concat(j.channels.filter(function (c) { return c.type === "drum"; }));
				const expected = countNotes(j);
				const r = finalize(j, "AI: set song JSON", { expectNotes: expected });
				return ok("Song replaced (" + countNotes(r.json) + " of " + expected + " notes kept).", r.json, r.warnings);
			});

		// ---------------- generators
		function chordsForBars(j, a, nBars) {
			const keyPc = (kbIndex(j));
			const minor = /:\(/.test(j.scale);
			const text = a.progression ? (T.PROGRESSIONS[a.progression] || a.progression) : (minor ? "i bVI bVII i" : "I V vi IV");
			let list;
			try { list = T.parseProgression(text, keyPc, minor); } catch (e) { throw err(e.message); }
			const per = a.chords_per_bar || 1;
			const out = [];
			for (let b = 0; b < nBars; b++) { const row = []; for (let k = 0; k < per; k++) row.push(list[(b * per + k) % list.length]); out.push(row); }
			return out;
		}
		function kbIndex(j) { return Math.max(0, ENUMS.key.indexOf(j.key)); }
		function shiftEvents(evs, offset, scale) { return evs.map(function (e) { return Object.assign({}, e, { start: offset + e.start * scale, dur: e.dur * scale }); }); }
		function toBB(evs, j) { // events with midi pitches -> events with BeepBox pitches (throws if out of range)
			return evs.map(function (e) { return Object.assign({}, e, { pitches: e.pitches.map(function (m) { return midiOrRow(m, j, false); }) }); });
		}
		function generateBars(j, ci, a, nBars, startBar) {
			const c = j.channels[ci], drum = isDrum(c), bpb = j.beatsPerBar;
			const kind = a.kind;
			const rand = T.rng(a.seed || 7);
			const chordRows = chordsForBars(j, a, nBars);
			const barEvents = [];
			const octave = a.octave != null ? a.octave : (kind === "bass" ? 2 : kind === "arpeggio" || kind === "chords" ? 4 : 5);
			const root = 12 * (octave + 1);
			for (let b = 0; b < nBars; b++) {
				const row = chordRows[b], sub = bpb / row.length;
				let evs = [];
				row.forEach(function (ch, k) {
					let part;
					const off = k * sub;
					if (kind === "drums") part = [];
					else if (kind === "arpeggio") part = T.arpeggioEvents(T.chordMidi(ch, root), sub, { step: a.step || 0.25, style: a.style || "up", vol: a.vol || 100, octaves: a.octaves });
					else if (kind === "bass") part = T.bassEvents(ch, sub, { style: a.style || "eighths", vol: a.vol || 100, lowMidi: root });
					else if (kind === "pad" || kind === "chords") part = T.padEvents(T.chordMidi(ch, root), sub, { vol: a.vol || 67 });
					else if (kind === "melody") part = T.melodyEvents(ch, kbIndex(j), j.scale, sub, { rand: rand, lowMidi: root, highMidi: root + 19, vol: a.vol });
					else throw err("unknown kind '" + kind + "'");
					evs = evs.concat(shiftEvents(part, off, 1));
				});
				if (kind !== "drums") evs = toBB(evs, j);
				barEvents.push(evs);
			}
			if (kind === "drums") {
				if (!drum) throw err("drums can only be written to a drum channel");
				const tmpl = a.template || "chiptune march";
				for (let b = 0; b < nBars; b++) {
					const fill = a.fill_every && (b + 1) % a.fill_every === 0;
					const evs = T.drumTemplateEvents(fill ? (a.fill_template || "tom fill") : tmpl, bpb);
					barEvents[b] = fill && a.fill_template !== "none" ? evs.concat(T.drumTemplateEvents(tmpl, bpb).filter(function (e) { return e.start < bpb / 2; })) : evs;
				}
			} else if (drum) throw err("channel " + (ci + 1) + " is a drum channel; use kind 'drums' there");
			return barEvents;
		}
		tool("generate_part",
			"Generate a musical part from a chord progression and write it to a channel: 'arpeggio' (chord tones one by one), 'bass' (styles: eighths, quarters, octaves, rootfifth, walking, half, whole, arp), 'pad'/'chords' (sustained chords), 'melody' (rule-based tune over the chords; replace it with your own notes when you want a specific tune), or 'drums' (on a drum channel; template names from theory/drum_templates, with fill_every to add a fill every N bars). The progression uses roman numerals relative to the song key (i VI III VII, I V vi IV, bVII) or chord names (Am F C G), or a preset name from theory/progressions. Replaces the bars it writes.",
			{ required: ["channel", "kind"], properties: {
				channel: int("channel number", { minimum: 1 }), kind: str("part type", { enum: ["arpeggio", "bass", "pad", "chords", "melody", "drums"] }),
				progression: str("e.g. 'i VI III VII' or 'Am F C G' or a preset name. Default depends on the scale."), bars: int("number of bars to write (default 8)", { minimum: 1, maximum: 128 }), start_bar: int("first bar (default 1)", { minimum: 1 }),
				chords_per_bar: int("1 (default) or 2 chords per bar", { minimum: 1, maximum: 4 }), style: str("arpeggio: up, down, updown, broken. bass: see description"), step: { type: "number", description: "arpeggio note length in beats (default 0.25)" },
				octave: int("octave of the part's root (default: arpeggio 4, bass 2, melody 5)"), vol: int("0-100", { minimum: 0, maximum: 100 }), template: str("drum template name"), fill_every: int("drums: put a fill every N bars", { minimum: 2 }), fill_template: str("drum fill template (default 'tom fill'; 'none' to skip)"), seed: int("random seed for melody"),
				instrument: int("instrument number to use for these bars", { minimum: 1 }),
			} },
			function (a) {
				const j = snapshot(); const ci = chIdx(j, a.channel);
				const nBars = a.bars || 8, b0 = (a.start_bar || 1) - 1; const warnings = [];
				const barEvents = generateBars(j, ci, a, nBars, b0);
				const instN = instrumentIndexFor(j, j.channels[ci], a.instrument, warnings);
				writeBars(j, ci, b0, barEvents, { instN: instN }, warnings);
				compact(j, ci);
				const r = finalize(j, "AI: generate " + a.kind);
				return ok("Wrote a " + a.kind + " part for bars " + (b0 + 1) + "-" + (b0 + nBars) + " on channel " + a.channel + ".", r.json, warnings.concat(r.warnings), { sequence: seqText(r.json.channels[ci].sequence) });
			});

		tool("theory",
			"Music theory lookups. action: 'scale' (notes of a key+scale over octaves), 'progression' (roman numerals or chord names -> chord tones in the song key), 'chord' (one symbol), 'progressions' (preset names), 'drum_templates' (rhythm templates and what they contain), 'genres' (genre presets), 'instrument_presets' (names), 'rhythms' (note grids), 'pitch_range' (playable range in the current key).",
			{ required: ["action"], properties: {
				action: str("what to look up", { enum: ["scale", "progression", "chord", "progressions", "drum_templates", "genres", "instrument_presets", "rhythms", "pitch_range"] }),
				key: str("tonic (default: the song key)"), scale: str("scale name (default: the song scale)"), progression: str("roman numerals or chord names, or a preset name"), symbol: str("a chord symbol like Am7 or bVII"), low: str("lowest note e.g. C3"), high: str("highest note e.g. C6"), octave: int("octave for voicing (default 3)"),
			} },
			function (a) {
				const j = snapshot(); const keyName = a.key || j.key; const kpc = T.keyIndex(keyName);
				if (kpc < 0) throw err("unknown key '" + keyName + "'");
				const scaleName = T.resolveScale(a.scale || j.scale);
				if (!scaleName) throw err("unknown scale '" + a.scale + "'");
				const minor = /:\(/.test(scaleName);
				switch (a.action) {
					case "scale": {
						const lo = T.noteToMidi(a.low || "C3"), hi = T.noteToMidi(a.high || "C6");
						return { key: keyName, scale: scaleName, notes: T.scaleNotes(kpc, scaleName, lo, hi).map(pitchName).join(" "), intervals: T.SCALES[scaleName].join(" ") };
					}
					case "chord": {
						const ch = T.parseChord(a.symbol || "I", kpc, minor); const o = 12 * ((a.octave != null ? a.octave : 3) + 1);
						return { chord: ch.name, notes: T.chordMidi(ch, o).map(pitchName).join(" "), midi: T.chordMidi(ch, o) };
					}
					case "progression": {
						const text = T.PROGRESSIONS[a.progression] || a.progression || "I V vi IV";
						let list; try { list = T.parseProgression(text, kpc, minor); } catch (e) { throw err(e.message); }
						const o = 12 * ((a.octave != null ? a.octave : 3) + 1);
						return { key: keyName, mode: minor ? "minor" : "major", progression: text, chords: list.map(function (c) { return { chord: c.name, notes: T.chordMidi(c, o).map(pitchName).join(" ") }; }) };
					}
					case "progressions": return { presets: T.PROGRESSIONS };
					case "drum_templates": {
						const out = {}; Object.keys(T.DRUM_TEMPLATES).forEach(function (k) { out[k] = T.DRUM_TEMPLATES[k].description; });
						return { templates: out, drumRows: T.DRUM_ROWS, note: "rows apply to the 'drum kit' preset; templates are used by generate_part kind 'drums'" };
					}
					case "genres": { const out = {}; Object.keys(T.GENRES).forEach(function (k) { const g = T.GENRES[k]; out[k] = g.description + " [" + g.tempo + " bpm, " + g.key + " " + g.scale + ", " + g.progression + "]"; }); return { genres: out }; }
					case "instrument_presets": return { presets: Object.keys(T.INSTRUMENT_PRESETS) };
					case "rhythms": return { rhythms: ENUMS.rhythm };
					case "pitch_range": return { key: j.key, lowest: pitchName(keyBase(j)), highest: pitchName(keyBase(j) + C.maxPitch), note: "drum channels use rows 0-" + (LIMITS.drumRows - 1) };
					default: throw err("unknown theory action");
				}
			}, { read: true });

		// ---------------- genre presets (complete starting songs)
		function buildGenre(name, a) {
			const g = T.GENRES[name];
			if (!g) throw err("unknown genre '" + name + "'. Available: " + Object.keys(T.GENRES).join(", "));
			const bars = a.bars || g.bars;
			const j = { format: "BeepBox", version: 9, scale: T.resolveScale(a.scale || g.scale), key: ENUMS.key[T.keyIndex(a.key || g.key)], introBars: 0, loopBars: bars, beatsPerBar: a.beats_per_bar || 4, ticksPerBeat: 4, beatsPerMinute: a.tempo || g.tempo, layeredInstruments: false, patternInstruments: false, channels: [] };
			const roles = [];
			const mk = function (role, type, ins, oct) { const c = { type: type, instruments: [typeof ins === "string" ? T.instrumentPreset(ins) : ins], patterns: [newPattern()], sequence: new Array(bars).fill(0) }; if (type === "pitch") c.octaveScrollBar = oct; roles.push(role); j.channels.push(c); };
			mk("melody", "pitch", g.lead, 3);
			if (g.arp) mk("arpeggio", "pitch", "chip arp", 2);
			if (g.pad) mk("pad", "pitch", g.pad, 2);
			mk("bass", "pitch", g.bass === "arp" || g.bass === "octaves" ? "saw bass" : "triangle bass", 1);
			if (g.drums) mk("drums", "drum", "drum kit");
			const warnings = [];
			j.channels.forEach(function (c, ci) {
				const role = roles[ci];
				const part = { progression: g.progression, seed: a.seed || 11, chords_per_bar: 1, kind: role };
				if (role === "melody") { part.octave = 5; part.vol = 100; }
				if (role === "arpeggio") { part.octave = 4; part.vol = 67; part.step = g.tempo > 130 ? 0.25 : 0.5; }
				if (role === "pad") { part.octave = 3; part.vol = 67; }
				if (role === "bass") { part.octave = 2; part.style = g.bass; part.vol = 100; }
				if (role === "drums") { part.template = g.drums; part.fill_every = g.fillEvery || undefined; }
				writeBars(j, ci, 0, generateBars(j, ci, part, bars, 0), {}, warnings);
				compact(j, ci);
			});
			if (g.jingle) j.channels.forEach(function (c) { c.sequence = c.sequence.slice(0, bars); });
			return { j: j, warnings: warnings };
		}
		tool("genre_preset",
			"Build a complete starting arrangement from a genre preset (chiptune, battle, boss, town, dungeon, victory, defeat, menu, ambient) and load it, replacing the current song. Overrides: bars, key, scale, tempo, seed. Then refine with the other tools. Without a name, lists the presets.",
			{ properties: { name: str("genre preset name"), bars: int("length in bars", { minimum: 1, maximum: 128 }), key: str("tonic override"), scale: str("scale override"), tempo: int("bpm override", { minimum: 30, maximum: 300 }), seed: int("random seed for the melody"), beats_per_bar: int("3-16", { minimum: 3, maximum: 16 }) } },
			function (a) {
				if (!a || !a.name) { const out = {}; Object.keys(T.GENRES).forEach(function (k) { out[k] = T.GENRES[k].description; }); return { genres: out }; }
				const b = buildGenre(String(a.name).toLowerCase(), a);
				const r = finalize(b.j, "AI: genre preset " + a.name);
				return ok("Loaded the '" + a.name + "' preset (" + b.j.channels.length + " channels). Refine it with write_track, set_instrument, etc.", r.json, b.warnings.concat(r.warnings));
			});

		// ---------------- audio
		async function renderForAnalysis(opts) {
			const song = host.getSong();
			const loops = 1;
			return A.renderSong(B, song, { sampleRate: opts.sampleRate || 32000, loops: loops, intro: true, outro: true, maxSeconds: opts.maxSeconds || 90, yieldEvery: host.yieldEvery || 0, solo: opts.solo, isCanceled: host.isCanceled });
		}
		async function analyzeSong(opts) {
			const r = await renderForAnalysis(opts);
			const res = A.analyze(r);
			if (opts.perChannel) {
				const j = snapshot(); const chans = [];
				for (let i = 0; i < j.channels.length; i++) {
					const rr = await renderForAnalysis({ solo: i, sampleRate: 32000, maxSeconds: opts.maxSeconds });
					const m = A.mixToMono(rr.L, rr.R);
					chans.push({ channel: i + 1, type: j.channels[i].type, rmsDbfs: +A.rmsDb(m).toFixed(1), peakDbfs: +(20 * Math.log10(Math.max(1e-6, A.peakOf(rr.L, rr.R)))).toFixed(1) });
				}
				res.channels = chans;
				const t = res.text.split("\n"); t.splice(t.length - 1, 0, "Per-channel (solo, RMS dBFS): " + chans.map(function (c) { return "ch" + c.channel + " " + c.rmsDbfs; }).join(", ")); res.text = t.join("\n");
			}
			return res;
		}
		function trimAnalysis(res) { const o = Object.assign({}, res); return o; }
		tool("render_preview",
			"Render the whole song offline with BeepBox's synthesizer (you cannot hear it, but you get measurements) and return a text report: length, peak/RMS level, clipping, per-bar loudness, spectrum balance by band, estimated tempo, and advice. Use it after writing music to check it is audible, balanced and not clipping. The user can hear the song with 'play'.",
			{ properties: { max_seconds: { type: "number", description: "render at most this many seconds (default 90)" } } },
			async function (a) {
				const res = await analyzeSong({ maxSeconds: a && a.max_seconds, perChannel: false });
				return { text: res.text, peakDbfs: res.peakDbfs, rmsDbfs: res.rmsDbfs, seconds: res.seconds, silent: res.silent, clipped: res.clippedSamples > 0, advice: res.advice };
			}, { read: true });
		tool("analyze_audio",
			"Detailed audio analysis of the current song: everything render_preview reports plus per-channel loudness (each channel soloed) so you can balance the mix (aim: drums and bass strong, lead clearly above arps and pads, no channel more than ~12 dB below the loudest unless it is meant to be subtle).",
			{ properties: { per_channel: { type: "boolean", description: "include per-channel loudness (default true)" }, max_seconds: { type: "number" } } },
			async function (a) {
				const res = await analyzeSong({ maxSeconds: a && a.max_seconds, perChannel: !a || a.per_channel !== false });
				return { text: res.text, bands: res.bands, channels: res.channels, perBarRmsDb: res.perBarRmsDb, spectralCentroidHz: res.spectralCentroidHz, advice: res.advice };
			}, { read: true });
		tool("play", "Start playback in the editor so the user can hear the song. Optionally start from a bar.",
			{ properties: { from_bar: int("bar to start from (default: the beginning)", { minimum: 1 }) } },
			function (a) { host.play({ fromBar: a && a.from_bar ? a.from_bar - 1 : 0 }); return { ok: true, message: "Playing." + (host.silent ? " (no audio device in this context)" : "") }; }, { read: true });
		tool("stop", "Stop playback in the editor.", {}, function () { host.stop(); return { ok: true, message: "Stopped." }; }, { read: true });
		tool("undo", "Undo the last change(s) made to the song (BeepBox's own undo history; the user can also press Z).",
			{ properties: { steps: int("how many changes to undo (default 1)", { minimum: 1, maximum: 50 }) } },
			async function (a) { await host.undo((a && a.steps) || 1); const j = snapshot(); return ok("Undone.", j); });

		async function run(name, input) {
			const f = tools[name];
			if (!f) throw err("unknown tool '" + name + "'. Available: " + Object.keys(tools).join(", "));
			return await f(input || {});
		}
		return { definitions: defs, run: run, LIMITS: LIMITS, ENUMS: ENUMS, snapshot: snapshot, analyzeSong: analyzeSong, buildGenre: buildGenre, parseNotes: parseNotes, tools: tools };
	}

	return { create: create };
});
