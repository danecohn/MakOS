extends Node
## AmerikaGame autoload: score, flags, win/lose rules, level flow and sound for games assembled from a recipe.
## Configuration comes from res://amerika_game.json, which the recipe assembler writes.

signal score_changed(score: int)
signal health_changed(current: int, maximum: int)
signal message(speaker: String, text: String)
signal state_changed(state: String, text: String)
signal level_started(level_name: String)

const CONFIG_PATH := "res://amerika_game.json"

var config: Dictionary = {}
var score: int = 0
var health: int = 0
var max_health: int = 0
var flags: Dictionary = {}
var state: String = "playing" ## playing | won | lost
var frozen: bool = false
var player: Node
var level: Node
var level_meta: Dictionary = {}
var elapsed: float = 0.0
var collected: int = 0
var last_text: String = ""

var _score_at_level_start: int = 0
var _enemies_seen: int = 0
var _check: float = 0.0
var _music: AudioStreamPlayer
var _sfx_cache: Dictionary = {}


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	reload_config()
	_music = AudioStreamPlayer.new()
	_music.name = "Music"
	add_child(_music)


func reload_config() -> void:
	config = {}
	if FileAccess.file_exists(CONFIG_PATH):
		var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(CONFIG_PATH))
		if parsed is Dictionary:
			config = parsed


func cfg(path: String, default: Variant = null) -> Variant:
	var cur: Variant = config
	for part in path.split("."):
		if cur is Dictionary and (cur as Dictionary).has(part):
			cur = (cur as Dictionary)[part]
		else:
			return default
	return cur


# ----------------------------------------------------------------- level flow

func begin_level(node: Node) -> void:
	level = node
	level_meta = {}
	var meta: Variant = node.get("meta")
	if meta is Dictionary:
		level_meta = meta
	state = "playing"
	frozen = false
	elapsed = 0.0
	collected = 0
	_enemies_seen = 0
	_score_at_level_start = score
	last_text = ""
	var music_path: String = str(level_meta.get("music", ""))
	if music_path != "" and ResourceLoader.exists(music_path):
		var stream := load(music_path) as AudioStream
		if stream != null and _music.stream != stream:
			_music.stream = stream
			_music.play()
	level_started.emit(str(node.get("level_name")))


func level_value(key: String, default: Variant = null) -> Variant:
	return level_meta.get(key, default)


func level_index() -> int:
	var levels: Array = cfg("levels", [])
	if level == null:
		return 0
	for i in range(levels.size()):
		if str(levels[i].get("scene", "")) == level.scene_file_path:
			return i
	return 0


func has_next_level() -> bool:
	var levels: Array = cfg("levels", [])
	return level_index() + 1 < levels.size()


func goto_level(level_name: String) -> void:
	var levels: Array = cfg("levels", [])
	for lv in levels:
		if str(lv.get("name", "")) == level_name or str(lv.get("scene", "")) == level_name:
			get_tree().change_scene_to_file.call_deferred(str(lv["scene"]))
			return
	push_warning("goto_level: unknown level '%s'" % level_name)


func next_level() -> void:
	var levels: Array = cfg("levels", [])
	var i := level_index() + 1
	if i < levels.size():
		get_tree().change_scene_to_file.call_deferred(str(levels[i]["scene"]))


func restart() -> void:
	score = _score_at_level_start
	flags = {}
	state = "playing"
	frozen = false
	get_tree().reload_current_scene.call_deferred()


# ------------------------------------------------------------------ gameplay

func add_score(amount: int) -> void:
	score += amount
	score_changed.emit(score)


func set_player_health(current: int, maximum: int) -> void:
	health = current
	max_health = maximum
	health_changed.emit(current, maximum)


func collect(kind: String, value: int, flag: String, node: Node) -> void:
	collected += 1
	match kind:
		"score":
			add_score(value)
		"heal":
			if player != null:
				for c in player.get_children():
					if c.has_method("heal"):
						c.call("heal", value)
		"flag":
			set_flag(flag if flag != "" else node.name)
			if value != 0:
				add_score(value)
		"ammo":
			set_flag("ammo", int(flags.get("ammo", 0)) + value)


func entity_died(_node: Node) -> void:
	pass


func set_flag(flag: String, value: Variant = true) -> void:
	flags[flag] = value
	if value == true:
		message.emit("", "Got %s" % flag.replace("_", " "))


func has_flag(flag: String) -> bool:
	var v: Variant = flags.get(flag, false)
	if typeof(v) == TYPE_BOOL:
		return v
	if typeof(v) == TYPE_INT or typeof(v) == TYPE_FLOAT:
		return v != 0
	return v != null


func say(speaker: String, text: String) -> void:
	last_text = text
	message.emit(speaker, text)


func win(text: String = "") -> void:
	if state != "playing":
		return
	state = "won"
	frozen = true
	var t := text if text != "" else str(cfg("ui.win_text", "You win!"))
	if has_next_level():
		t = text if text != "" else "Level complete!"
	last_text = t
	state_changed.emit("won", t)


func lose(text: String = "") -> void:
	if state != "playing":
		return
	state = "lost"
	frozen = true
	var t := text if text != "" else str(cfg("ui.lose_text", "Game over"))
	last_text = t
	state_changed.emit("lost", t)


# --------------------------------------------------------------------- update

func _process(delta: float) -> void:
	if state == "playing":
		elapsed += delta
		_check -= delta
		if _check <= 0.0:
			_check = 0.2
			_evaluate_rules()
	elif Input.is_action_just_pressed("ui_accept") or Input.is_action_just_pressed("restart"):
		if state == "won" and has_next_level():
			next_level()
		else:
			restart()


func _alive_in_group(group: String) -> int:
	var n := 0
	for node in get_tree().get_nodes_in_group(group):
		if not node.is_queued_for_deletion():
			n += 1
	return n


func _evaluate_rules() -> void:
	if level == null:
		return
	var enemies := _alive_in_group("enemy")
	_enemies_seen = maxi(_enemies_seen, enemies)
	var win_rule: Variant = cfg("rules.win", null)
	if win_rule is Dictionary:
		match str((win_rule as Dictionary).get("type", "")):
			"collect_all":
				if collected > 0 and _alive_in_group("collectible") == 0:
					win()
			"kill_all":
				if _enemies_seen > 0 and enemies == 0:
					win()
			"score":
				if score >= int((win_rule as Dictionary).get("target", 1)):
					win()
			"survive":
				if elapsed >= float((win_rule as Dictionary).get("seconds", 30)):
					win()
	var lose_rule: Variant = cfg("rules.lose", null)
	if lose_rule is Dictionary and str((lose_rule as Dictionary).get("type", "")) == "timer":
		if elapsed >= float((lose_rule as Dictionary).get("seconds", 60)):
			lose("Time is up")


# ---------------------------------------------------------------------- sound

func play_sfx(sfx_name: String) -> void:
	if DisplayServer.get_name() == "headless":
		return
	var stream := _sfx_stream(sfx_name)
	if stream == null:
		return
	var p := AudioStreamPlayer.new()
	p.stream = stream
	p.volume_db = -8.0
	add_child(p)
	p.finished.connect(p.queue_free)
	p.play()


func _sfx_stream(sfx_name: String) -> AudioStream:
	if _sfx_cache.has(sfx_name):
		return _sfx_cache[sfx_name]
	var stream: AudioStream = null
	var path: String = str(cfg("audio.sfx." + sfx_name, ""))
	if path != "" and ResourceLoader.exists(path):
		stream = load(path) as AudioStream
	if stream == null:
		stream = _synth(sfx_name)
	_sfx_cache[sfx_name] = stream
	return stream


## A tiny placeholder beep so every game makes noise before real audio is assigned.
func _synth(sfx_name: String) -> AudioStreamWAV:
	var freqs := {"pickup": 880.0, "jump": 440.0, "hurt": 150.0, "hit": 200.0, "shoot": 660.0, "win": 1040.0, "stomp": 300.0}
	var freq: float = freqs.get(sfx_name, 520.0)
	var rate := 22050
	var count := int(rate * 0.12)
	var data := PackedByteArray()
	data.resize(count * 2)
	for i in range(count):
		var env := 1.0 - float(i) / count
		var v := int((1.0 if sin(TAU * freq * i / rate) > 0.0 else -1.0) * 9000.0 * env)
		data.encode_s16(i * 2, v)
	var wav := AudioStreamWAV.new()
	wav.format = AudioStreamWAV.FORMAT_16_BITS
	wav.mix_rate = rate
	wav.data = data
	return wav
