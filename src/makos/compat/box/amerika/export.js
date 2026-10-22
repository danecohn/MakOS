/* MakBox: "Export for game" bundles and plain WAV export into ~/Studio/Box.
 *
 * A game bundle is a folder  exports/<name>/  containing
 *   <name>.wav            16-bit stereo, intro + one loop, with a 'smpl' loop chunk (Godot and most engines honour it)
 *   <name>.ogg            (when ffmpeg + the amerika-box-ogg helper are available) same audio, Vorbis, LOOPSTART/LOOPLENGTH tags
 *   <name>.json           loop/tempo metadata for code (seconds and samples)
 *   <name>.song.json      the BeepBox song itself, so the track can be re-opened and edited
 *   <name>.ogg.import / <name>.wav.import   Godot 4 import presets (loop on, loop_offset, bpm, beat_count, bar_beats)
 *   README.txt            how to drop it into a Godot project
 * Pure JS; the I/O is injected so Node tests can run it against memory.
 */
(function (root, factory) {
	if (typeof module === "object" && module.exports) module.exports = factory(require("./audio.js"));
	else { root.Amerika = root.Amerika || {}; root.Amerika.exporter = factory(root.Amerika.audio); }
})(typeof self !== "undefined" ? self : this, function (A) {
	"use strict";

	const GENERATOR = "MakBox (BeepBox 4.2.2 synth)";

	function safeName(name) {
		const n = String(name || "song").trim().replace(/[^A-Za-z0-9._ -]+/g, "").replace(/\s+/g, "_").replace(/^[.-]+/, "").slice(0, 60);
		return n || "song";
	}

	function metadata(r, song, name, files, opts) {
		const sr = r.sampleRate, spb = r.samplesPerBar;
		const totalBeats = (r.introFrames + r.loopFrames) / spb * r.beatsPerBar;
		const loopBeats = r.loopFrames / spb * r.beatsPerBar;
		const j = song.toJsonObject();
		return {
			name: name, generator: GENERATOR, created: new Date().toISOString(),
			sample_rate: sr, channels: 2, bit_depth: 16,
			bpm: r.bpm, beats_per_bar: r.beatsPerBar, key: j.key, scale: j.scale,
			intro_bars: r.introBars, loop_bars: r.loopBars,
			length_seconds: +(r.frames / sr).toFixed(6), length_samples: r.frames,
			loop_start_seconds: +(r.loopStart / sr).toFixed(6), loop_end_seconds: +(r.loopEnd / sr).toFixed(6),
			loop_start_samples: r.loopStart, loop_end_samples: r.loopEnd, loop_length_samples: r.loopFrames,
			seamless_loop: true,
			godot: { importer_loop: true, loop_offset: +(r.loopStart / sr).toFixed(6), bpm: r.bpm, beat_count: Math.round(totalBeats), bar_beats: r.beatsPerBar, loop_beat_count: Math.round(loopBeats) },
			peak_normalized_db: opts.normalizeDb == null ? null : opts.normalizeDb,
			files: files,
		};
	}

	function godotImport(kind, meta, resPath) {
		const g = meta.godot;
		const loopOffset = g.loop_offset;
		if (kind === "ogg") {
			return "[remap]\n\nimporter=\"oggvorbisstr\"\ntype=\"AudioStreamOggVorbis\"\n\n[deps]\n\nsource_file=\"" + resPath + "\"\n\n[params]\n\nloop=true\nloop_offset=" + loopOffset + "\nbpm=" + g.bpm + "\nbeat_count=" + g.beat_count + "\nbar_beats=" + g.bar_beats + "\n";
		}
		return "[remap]\n\nimporter=\"wav\"\ntype=\"AudioStreamWAV\"\n\n[deps]\n\nsource_file=\"" + resPath + "\"\n\n[params]\n\nforce/8_bit=false\nforce/mono=false\nforce/max_rate=false\nedit/trim=false\nedit/normalize=false\nedit/loop_mode=2\nedit/loop_begin=" + meta.loop_start_samples + "\nedit/loop_end=" + meta.loop_end_samples + "\ncompress/mode=0\n";
	}

	function readme(name, meta, hasOgg) {
		return [
			name + " - exported from MakBox",
			"",
			"Files",
			"  " + name + ".wav        intro + one seamless loop (" + meta.length_seconds + " s), loop points embedded",
			hasOgg ? "  " + name + ".ogg        same audio as Ogg Vorbis (smaller; use this one in games)" : "  (no .ogg: ffmpeg or the amerika-box-ogg helper was not available; run `amerika-box-ogg " + name + ".wav` later)",
			"  " + name + ".json       loop and tempo metadata",
			"  " + name + ".song.json  the BeepBox song, open it in MakBox to edit",
			"",
			"Loop: starts at " + meta.loop_start_seconds + " s (" + meta.loop_start_samples + " samples), ends at " + meta.loop_end_seconds + " s (" + meta.loop_end_samples + " samples).",
			"",
			"Godot 4",
			"  1. Copy this folder to res://audio/music/" + name + "/ in your project.",
			"  2. The .import files set loop = true and loop_offset = " + meta.godot.loop_offset + " (seconds) so the intro plays once and the loop repeats.",
			"     If Godot shows the file with default settings, select it, open the Import dock, tick Loop, set Loop Offset to " + meta.godot.loop_offset + " and press Reimport.",
			"  3. Load it with: var stream: AudioStream = load(\"res://audio/music/" + name + "/" + name + (hasOgg ? ".ogg" : ".wav") + "\")",
			"     $AudioStreamPlayer.stream = stream ; $AudioStreamPlayer.play()",
			"",
			"BeepBox is by John Nesky (MIT licence). MakBox is not affiliated with BeepBox.",
			"",
		].join("\n");
	}

	/** Render and write a game bundle. io = {write(rel, data), requestOgg(job) -> Promise<{ok,error}> | undefined, progress(f, label)} */
	async function buildGameBundle(B, song, opts, io) {
		opts = opts || {};
		const name = safeName(opts.name);
		const dir = "exports/" + name;
		const progress = io.progress || function () {};
		progress(0.02, "Rendering");
		const r = await A.renderGameLoop(B, song, { sampleRate: opts.sampleRate || 44100, yieldEvery: opts.yieldEvery, onProgress: function (f) { progress(0.02 + f * 0.6, "Rendering"); } });
		if (A.peakOf(r.L, r.R) < 1e-4) throw new Error("The song renders as silence. Add notes first.");
		let gain = 1;
		if (opts.normalizeDb != null) gain = A.normalizeTo(r.L, r.R, opts.normalizeDb);
		const wav = A.encodeWav(r.L, r.R, r.sampleRate, { loop: { start: r.loopStart, end: r.loopEnd } });
		const files = [name + ".wav"];
		const meta = metadata(r, song, name, files, opts);
		meta.gain_applied = +gain.toFixed(4);
		progress(0.7, "Writing WAV");
		await io.write(dir + "/" + name + ".wav", wav);
		let ogg = null;
		if (opts.ogg !== false && io.requestOgg) {
			progress(0.75, "Encoding Ogg Vorbis");
			ogg = await io.requestOgg({ wav: dir + "/" + name + ".wav", ogg: dir + "/" + name + ".ogg", loop_start: r.loopStart, loop_length: r.loopFrames, sample_rate: r.sampleRate, quality: opts.oggQuality == null ? 5 : opts.oggQuality, title: name });
			if (ogg && ogg.ok) files.push(name + ".ogg");
		}
		const json = song.toJsonObject();
		files.push(name + ".json", name + ".song.json", name + ".wav.import");
		if (ogg && ogg.ok) files.push(name + ".ogg.import");
		files.push("README.txt");
		meta.files = files;
		await io.write(dir + "/" + name + ".json", JSON.stringify(meta, null, 2) + "\n");
		await io.write(dir + "/" + name + ".song.json", JSON.stringify(json, null, 1) + "\n");
		const res = "res://audio/music/" + name + "/";
		await io.write(dir + "/" + name + ".wav.import", godotImport("wav", meta, res + name + ".wav"));
		if (ogg && ogg.ok) await io.write(dir + "/" + name + ".ogg.import", godotImport("ogg", meta, res + name + ".ogg"));
		await io.write(dir + "/README.txt", readme(name, meta, !!(ogg && ogg.ok)));
		progress(1, "Done");
		return { dir: dir, name: name, files: files, metadata: meta, ogg: ogg ? (ogg.ok ? "ok" : (ogg.error || "failed")) : "not requested", wavBytes: wav.length };
	}

	/** Plain WAV of the song as BeepBox's own exporter would render it (48 kHz). */
	async function renderWav(B, song, opts) {
		opts = opts || {};
		const r = await A.renderSong(B, song, { sampleRate: opts.sampleRate || 48000, loops: opts.loops || 1, intro: opts.intro !== false, outro: opts.outro !== false, yieldEvery: opts.yieldEvery, onProgress: opts.onProgress });
		let gain = 1;
		if (opts.normalizeDb != null) gain = A.normalizeTo(r.L, r.R, opts.normalizeDb);
		const wav = A.encodeWav(r.L, r.R, r.sampleRate);
		const peak = A.peakOf(r.L, r.R);
		return { wav: wav, sampleRate: r.sampleRate, seconds: r.seconds, frames: r.frames, peakDbfs: +(20 * Math.log10(Math.max(1e-9, peak))).toFixed(1), gain: gain };
	}

	return { buildGameBundle: buildGameBundle, renderWav: renderWav, safeName: safeName, metadata: metadata, godotImport: godotImport };
});
