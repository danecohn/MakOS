/* MakBox: offline rendering with BeepBox's own synth, WAV encoding (with loop points), and audio analysis.
 * Pure JavaScript; works in the editor window and in Node (tests). Not affiliated with BeepBox; see NOTICE. */
(function (root, factory) {
	if (typeof module === "object" && module.exports) module.exports = factory();
	else { root.Amerika = root.Amerika || {}; root.Amerika.audio = factory(); }
})(typeof self !== "undefined" ? self : this, function () {
	"use strict";

	/** Render a BeepBox Song offline. B is the beepbox namespace (Song, Synth). Returns {L, R, sampleRate, frames, seconds, ...}.
	 *  opts: sampleRate=48000, loops=1, intro=true, outro=true, muted:[channel idx] or solo:int, maxSeconds, yieldEvery (ms), onProgress(0..1), isCanceled() */
	async function renderSong(B, song, opts) {
		opts = opts || {};
		// BeepBox's drum filters become unstable below ~32 kHz, so never render below that.
		const sampleRate = Math.max(32000, opts.sampleRate || 48000);
		const loops = Math.max(1, opts.loops || 1);
		const intro = opts.intro !== false, outro = opts.outro !== false;
		// Work on a copy so the playing/editing song is never touched.
		const copy = new B.Song();
		copy.fromJsonObject(song.toJsonObject());
		if (opts.solo != null) copy.channels.forEach(function (c, i) { c.muted = i !== opts.solo; });
		else if (opts.muted) opts.muted.forEach(function (i) { if (copy.channels[i]) copy.channels[i].muted = true; });
		const synth = new B.Synth(copy);
		synth.samplesPerSecond = sampleRate;
		synth.loopRepeatCount = loops - 1;
		if (!intro) for (let i = 0; i < copy.loopStart; i++) synth.goToNextBar();
		const samplesPerBar = synth.getSamplesPerBar();
		const totalBars = synth.getTotalBars(intro, outro);
		let total = Math.ceil(samplesPerBar * totalBars);
		if (opts.maxSeconds) total = Math.min(total, Math.ceil(opts.maxSeconds * sampleRate));
		const L = new Float32Array(total), R = new Float32Array(total);
		const now = (typeof performance !== "undefined" ? performance : Date);
		let idx = 0, chunk = 4096, lastYield = now.now();
		while (idx < total) {
			const stop = Math.min(idx + chunk, total);
			synth.synthesize(L.subarray(idx, stop), R.subarray(idx, stop), stop - idx);
			idx = stop;
			if (opts.onProgress) opts.onProgress(idx / total);
			if (opts.yieldEvery && now.now() - lastYield > opts.yieldEvery) {
				await new Promise(function (r) { setTimeout(r, 0); });
				lastYield = now.now();
				if (opts.isCanceled && opts.isCanceled()) throw new Error("render canceled");
			}
		}
		for (let i = 0; i < total; i++) { if (!(L[i] === L[i]) || !isFinite(L[i])) L[i] = 0; if (!(R[i] === R[i]) || !isFinite(R[i])) R[i] = 0; }
		return {
			L: L, R: R, sampleRate: sampleRate, frames: total, seconds: total / sampleRate,
			samplesPerBar: samplesPerBar, totalBars: totalBars, introBars: copy.loopStart, loopBars: copy.loopLength, bpm: copy.tempo,
			beatsPerBar: copy.beatsPerBar,
		};
	}

	/** Render for a game: intro + one perfectly cyclic loop (the tail of the loop wraps into its start, so the
	 *  file loops without a click or gap). Returns {L, R, sampleRate, loopStart, loopEnd (frames), ...}. */
	async function renderGameLoop(B, song, opts) {
		opts = Object.assign({}, opts || {});
		const r = await renderSong(B, song, Object.assign({}, opts, { loops: 2, intro: true, outro: false }));
		const spb = r.samplesPerBar;
		const introFrames = Math.round(spb * r.introBars);
		const loopFrames = Math.round(spb * r.loopBars);
		// intro as rendered, then the second pass of the loop, which already contains the wrapped reverb/echo tail.
		const total = introFrames + loopFrames;
		const L = new Float32Array(total), R = new Float32Array(total);
		L.set(r.L.subarray(0, introFrames), 0);
		R.set(r.R.subarray(0, introFrames), 0);
		L.set(r.L.subarray(introFrames + loopFrames, introFrames + 2 * loopFrames), introFrames);
		R.set(r.R.subarray(introFrames + loopFrames, introFrames + 2 * loopFrames), introFrames);
		return Object.assign({}, r, { L: L, R: R, frames: total, seconds: total / r.sampleRate, loopStart: introFrames, loopEnd: total, loopFrames: loopFrames, introFrames: introFrames });
	}

	function peakOf(L, R) {
		let p = 0;
		for (let i = 0; i < L.length; i++) { const a = Math.abs(L[i]); if (a > p) p = a; }
		if (R) for (let i = 0; i < R.length; i++) { const a = Math.abs(R[i]); if (a > p) p = a; }
		return p;
	}

	function normalizeTo(L, R, targetPeakDb) {
		const p = peakOf(L, R);
		if (p <= 1e-9) return 1;
		const gain = Math.pow(10, targetPeakDb / 20) / p;
		for (let i = 0; i < L.length; i++) { L[i] *= gain; R[i] *= gain; }
		return gain;
	}

	/** 16-bit PCM stereo WAV. loop: {start, end} in frames adds a 'smpl' chunk (Godot, many samplers honour it). */
	function encodeWav(L, R, sampleRate, opts) {
		opts = opts || {};
		const frames = L.length, ch = 2, bytes = 2;
		const dataBytes = frames * ch * bytes;
		const loop = opts.loop;
		const smplBytes = loop ? 8 + 36 + 24 : 0;
		const buf = new ArrayBuffer(44 + dataBytes + smplBytes);
		const v = new DataView(buf);
		let o = 0;
		const u32be = function (x) { v.setUint32(o, x, false); o += 4; };
		const u32 = function (x) { v.setUint32(o, x, true); o += 4; };
		const u16 = function (x) { v.setUint16(o, x, true); o += 2; };
		u32be(0x52494646); u32(36 + dataBytes + smplBytes); u32be(0x57415645);
		u32be(0x666d7420); u32(16); u16(1); u16(ch); u32(sampleRate); u32(sampleRate * ch * bytes); u16(ch * bytes); u16(16);
		u32be(0x64617461); u32(dataBytes);
		for (let i = 0; i < frames; i++) {
			let l = Math.max(-1, Math.min(1, L[i])), r = Math.max(-1, Math.min(1, R[i]));
			v.setInt16(o, Math.round(l < 0 ? l * 32768 : l * 32767), true); o += 2;
			v.setInt16(o, Math.round(r < 0 ? r * 32768 : r * 32767), true); o += 2;
		}
		if (loop) {
			u32be(0x736d706c); u32(60);
			u32(0); u32(0); u32(Math.round(1e9 / sampleRate)); u32(60); u32(0); u32(0); u32(0); u32(1); u32(0); // manufacturer..sampler data
			u32(0); u32(0); u32(loop.start); u32(Math.max(loop.start, loop.end - 1)); u32(0); u32(0); // one forward loop, infinite
		}
		return new Uint8Array(buf);
	}

	/** Minimal WAV reader (PCM 16/24/32 or float32), returns {sampleRate, channels, L, R, loop?}. */
	function decodeWav(bytes) {
		const v = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
		const tag = function (p) { return String.fromCharCode(v.getUint8(p), v.getUint8(p + 1), v.getUint8(p + 2), v.getUint8(p + 3)); };
		if (tag(0) !== "RIFF" || tag(8) !== "WAVE") throw new Error("not a WAV file");
		let p = 12, fmt = null, data = null, loop = null;
		while (p + 8 <= bytes.length) {
			const id = tag(p), size = v.getUint32(p + 4, true);
			if (id === "fmt ") fmt = { format: v.getUint16(p + 8, true), channels: v.getUint16(p + 10, true), sampleRate: v.getUint32(p + 12, true), bits: v.getUint16(p + 22, true) };
			else if (id === "data") data = { at: p + 8, size: size };
			else if (id === "smpl" && v.getUint32(p + 8 + 28, true) > 0) loop = { start: v.getUint32(p + 8 + 44, true), end: v.getUint32(p + 8 + 48, true) + 1 };
			p += 8 + size + (size & 1);
		}
		if (!fmt || !data) throw new Error("incomplete WAV");
		const bps = fmt.bits / 8, frames = Math.floor(data.size / (bps * fmt.channels));
		const L = new Float32Array(frames), R = new Float32Array(frames);
		let q = data.at;
		for (let i = 0; i < frames; i++) {
			for (let c = 0; c < fmt.channels; c++) {
				let s;
				if (fmt.format === 3) s = v.getFloat32(q, true);
				else if (fmt.bits === 16) s = v.getInt16(q, true) / 32768;
				else if (fmt.bits === 24) s = ((v.getUint8(q) | (v.getUint8(q + 1) << 8) | (v.getInt8(q + 2) << 16)) / 8388608);
				else s = v.getInt32(q, true) / 2147483648;
				q += bps;
				if (c === 0) L[i] = s; if (c === 1 || fmt.channels === 1) R[i] = s;
			}
		}
		return { sampleRate: fmt.sampleRate, channels: fmt.channels, L: L, R: R, frames: frames, loop: loop };
	}

	// ---------------------------------------------------------------- analysis
	function fft(re, im) {
		const n = re.length;
		for (let i = 1, j = 0; i < n; i++) {
			let bit = n >> 1;
			for (; j & bit; bit >>= 1) j ^= bit;
			j ^= bit;
			if (i < j) { let t = re[i]; re[i] = re[j]; re[j] = t; t = im[i]; im[i] = im[j]; im[j] = t; }
		}
		for (let len = 2; len <= n; len <<= 1) {
			const ang = -2 * Math.PI / len, wr = Math.cos(ang), wi = Math.sin(ang);
			for (let i = 0; i < n; i += len) {
				let cr = 1, ci = 0;
				for (let k = 0; k < len / 2; k++) {
					const a = i + k, b = i + k + len / 2;
					const tr = re[b] * cr - im[b] * ci, ti = re[b] * ci + im[b] * cr;
					re[b] = re[a] - tr; im[b] = im[a] - ti; re[a] += tr; im[a] += ti;
					const ncr = cr * wr - ci * wi; ci = cr * wi + ci * wr; cr = ncr;
				}
			}
		}
	}

	const BANDS = [["sub", 20, 60], ["bass", 60, 250], ["low-mid", 250, 500], ["mid", 500, 2000], ["high-mid", 2000, 4000], ["presence", 4000, 8000], ["air", 8000, 20000]];
	const dB = function (x) { return 10 * Math.log10(Math.max(x, 1e-12)); };

	/** Average power spectrum (Welch, Hann, 50% overlap) of a mono signal. Returns {freqs power} arrays of bins. */
	function powerSpectrum(x, sampleRate, size) {
		size = size || 4096;
		const win = new Float64Array(size);
		for (let i = 0; i < size; i++) win[i] = 0.5 - 0.5 * Math.cos(2 * Math.PI * i / (size - 1));
		const power = new Float64Array(size / 2);
		let count = 0;
		const re = new Float64Array(size), im = new Float64Array(size);
		const hop = size / 2;
		for (let s = 0; s + size <= x.length; s += hop) {
			for (let i = 0; i < size; i++) { re[i] = x[s + i] * win[i]; im[i] = 0; }
			fft(re, im);
			for (let i = 0; i < size / 2; i++) power[i] += re[i] * re[i] + im[i] * im[i];
			count++;
		}
		if (count) for (let i = 0; i < power.length; i++) power[i] /= count;
		return { power: power, binHz: sampleRate / size, count: count };
	}

	function mixToMono(L, R) {
		const m = new Float32Array(L.length);
		for (let i = 0; i < L.length; i++) m[i] = 0.5 * (L[i] + R[i]);
		return m;
	}

	function rmsDb(x, from, to) {
		let s = 0; from = from || 0; to = to == null ? x.length : to;
		for (let i = from; i < to; i++) s += x[i] * x[i];
		return dB(s / Math.max(1, to - from));
	}

	/** Detailed analysis of a rendered song. Returns plain JSON plus a `text` summary the model can read. */
	function analyze(render, opts) {
		opts = opts || {};
		const L = render.L, R = render.R, sr = render.sampleRate, n = L.length;
		const mono = mixToMono(L, R);
		const peak = peakOf(L, R);
		let clipped = 0;
		for (let i = 0; i < n; i++) if (Math.abs(L[i]) >= 0.999 || Math.abs(R[i]) >= 0.999) clipped++;
		const rms = rmsDb(mono);
		// per-bar loudness
		const spb = render.samplesPerBar || (sr * 60 / (render.bpm || 120) * (render.beatsPerBar || 4));
		const bars = Math.max(1, Math.round(n / spb));
		const perBar = [];
		for (let b = 0; b < bars; b++) perBar.push(+rmsDb(mono, Math.floor(b * spb), Math.min(n, Math.floor((b + 1) * spb))).toFixed(1));
		// spectrum bands
		const sp = powerSpectrum(mono, sr, 4096);
		const bandPower = BANDS.map(function (b) {
			let s = 0;
			for (let i = Math.max(1, Math.floor(b[1] / sp.binHz)); i < Math.min(sp.power.length, Math.ceil(b[2] / sp.binHz)); i++) s += sp.power[i];
			return s;
		});
		const totalPower = bandPower.reduce(function (a, b) { return a + b; }, 1e-30);
		let cn = 0, cd = 1e-30, cum = 0, rolloff = 0;
		for (let i = 1; i < sp.power.length; i++) cd += sp.power[i];
		for (let i = 1; i < sp.power.length; i++) { cn += i * sp.binHz * sp.power[i]; cum += sp.power[i]; if (!rolloff && cum >= 0.85 * cd) rolloff = i * sp.binHz; }
		const centroid = cn / cd;
		// stereo
		let side = 0, mid = 0;
		for (let i = 0; i < n; i++) { const m = 0.5 * (L[i] + R[i]), s = 0.5 * (L[i] - R[i]); mid += m * m; side += s * s; }
		// silence
		const quiet = 1e-4;
		let first = -1, last = -1;
		for (let i = 0; i < n; i++) if (Math.abs(mono[i]) > quiet) { first = i; break; }
		for (let i = n - 1; i >= 0; i--) if (Math.abs(mono[i]) > quiet) { last = i; break; }
		const res = {
			seconds: +(n / sr).toFixed(3), sampleRate: sr, bars: bars,
			peakDbfs: +dB(peak * peak).toFixed(1), rmsDbfs: +rms.toFixed(1), crestDb: +(dB(peak * peak) - rms).toFixed(1),
			clippedSamples: clipped, silent: peak < 1e-4,
			firstSoundSec: first < 0 ? null : +(first / sr).toFixed(3), lastSoundSec: last < 0 ? null : +(last / sr).toFixed(3),
			perBarRmsDb: perBar,
			bands: BANDS.map(function (b, i) { return { name: b[0], hz: b[1] + "-" + b[2], sharePct: +(100 * bandPower[i] / totalPower).toFixed(1), db: +dB(bandPower[i] / totalPower).toFixed(1) }; }),
			spectralCentroidHz: Math.round(centroid), rolloff85Hz: Math.round(rolloff),
			stereoWidthPct: +(100 * side / Math.max(1e-30, mid + side)).toFixed(1),
		};
		if (opts.tempo !== false) res.estimatedBpm = estimateBpm(mono, sr, render.bpm);
		res.advice = advice(res);
		res.text = summarize(res);
		return res;
	}

	/** Onset-envelope autocorrelation tempo estimate, folded to 60..180 bpm. Cheap and good enough to sanity-check tempo. */
	function estimateBpm(x, sr) {
		const hop = Math.round(sr / 200); // 5 ms
		const env = [];
		let prev = 0;
		for (let i = 0; i + hop <= x.length; i += hop) {
			let s = 0;
			for (let j = 0; j < hop; j++) s += x[i + j] * x[i + j];
			const e = Math.sqrt(s / hop);
			env.push(Math.max(0, e - prev)); prev = e;
		}
		if (env.length < 400) return null;
		const rate = 200;
		const minLag = Math.round(rate * 60 / 200), maxLag = Math.round(rate * 60 / 55);
		let mean = 0; for (const v of env) mean += v; mean /= env.length;
		const ac = [];
		let best = 0;
		for (let lag = minLag; lag <= maxLag; lag++) {
			let c = 0;
			for (let i = 0; i + lag < env.length; i++) c += (env[i] - mean) * (env[i + lag] - mean);
			c /= (env.length - lag);
			ac[lag] = c; if (c > best) best = c;
		}
		// the shortest lag that is a local peak and nearly as strong as the best one (avoids picking a multiple of the beat)
		let bestLag = 0;
		for (let lag = minLag + 1; lag < maxLag; lag++) if (ac[lag] >= 0.8 * best && ac[lag] >= ac[lag - 1] && ac[lag] >= ac[lag + 1]) { bestLag = lag; break; }
		if (!bestLag) return null;
		// beat or bar? if half the lag is also a clear peak, the shorter period is the beat
		for (let pass = 0; pass < 2; pass++) {
			const half = Math.round(bestLag / 2);
			if (half - 2 < minLag) break;
			let lo = half, v = -Infinity;
			for (let l = half - 2; l <= half + 2; l++) if (ac[l] > v) { v = ac[l]; lo = l; }
			if (v >= 0.5 * ac[bestLag]) bestLag = lo; else break;
		}
		const y0 = ac[bestLag - 1], y1 = ac[bestLag], y2 = ac[bestLag + 1], den = y0 - 2 * y1 + y2;
		const lagF = bestLag + (den ? Math.max(-1, Math.min(1, 0.5 * (y0 - y2) / den)) : 0);   // parabolic peak refinement
		let bpm = 60 * rate / lagF;
		while (bpm > 200) bpm /= 2;
		while (bpm < 60) bpm *= 2;
		return +bpm.toFixed(1);
	}

	function advice(a) {
		const out = [];
		if (a.silent) { out.push("The render is silent. Check that channels have notes and are not empty, and that instrument volume is above 0."); return out; }
		if (a.clippedSamples > 0) out.push("Clipping detected (" + a.clippedSamples + " samples). Lower instrument volumes or thin out chords.");
		if (a.peakDbfs < -18) out.push("Very quiet (peak " + a.peakDbfs + " dBFS). Raise instrument volumes (up to 100) or add a layer; export can also normalize.");
		const sh = {}; a.bands.forEach(function (b) { sh[b.name] = b.sharePct; });
		if (sh.sub + sh.bass > 70) out.push("Bass heavy (" + (sh.sub + sh.bass).toFixed(0) + "% of energy below 250 Hz). Lower the bass volume or raise the lead/arp.");
		if (sh["high-mid"] + sh.presence + sh.air > 55) out.push("Bright/harsh: lots of energy above 2 kHz. Use a low-pass eqFilter, softer waves (triangle/rounded) or lower the lead volume.");
		if (sh.sub + sh.bass < 8) out.push("Almost no low end. Add a bass channel or raise its volume.");
		if (a.crestDb < 6) out.push("Very compressed/dense (crest " + a.crestDb + " dB). Leave space: shorter notes, fewer simultaneous layers.");
		const q = a.perBarRmsDb.filter(function (v) { return v < -60; }).length;
		if (q > 0) out.push(q + " bar(s) are silent or nearly silent.");
		if (a.lastSoundSec != null && a.seconds - a.lastSoundSec > 1.5) out.push("Trailing silence of " + (a.seconds - a.lastSoundSec).toFixed(1) + " s at the end.");
		if (!out.length) out.push("No obvious problems: levels and balance look reasonable.");
		return out;
	}

	function summarize(a) {
		const l = [];
		l.push("Length " + a.seconds + " s (" + a.bars + " bars rendered at " + a.sampleRate + " Hz). Peak " + a.peakDbfs + " dBFS, RMS " + a.rmsDbfs + " dBFS, crest " + a.crestDb + " dB, clipped samples " + a.clippedSamples + ".");
		l.push("Spectrum share: " + a.bands.map(function (b) { return b.name + " " + b.sharePct + "%"; }).join(", ") + ". Centroid " + a.spectralCentroidHz + " Hz, 85% rolloff " + a.rolloff85Hz + " Hz.");
		l.push("Stereo side energy " + a.stereoWidthPct + "%." + (a.estimatedBpm ? " Estimated tempo " + a.estimatedBpm + " bpm." : ""));
		l.push("Per-bar RMS (dBFS): " + a.perBarRmsDb.join(" "));
		if (a.channels) l.push("Per-channel (solo): " + a.channels.map(function (c) { return "ch" + c.channel + " " + c.rmsDbfs + " dBFS (peak " + c.peakDbfs + ")"; }).join("; "));
		l.push("Advice: " + a.advice.join(" "));
		return l.join("\n");
	}

	return {
		renderSong: renderSong, renderGameLoop: renderGameLoop, encodeWav: encodeWav, decodeWav: decodeWav, normalizeTo: normalizeTo, peakOf: peakOf,
		analyze: analyze, estimateBpm: estimateBpm, powerSpectrum: powerSpectrum, mixToMono: mixToMono, rmsDb: rmsDb, BANDS: BANDS,
	};
});
