extends Node
## AmerikaDebug autoload: lets the Engine assistant and CI drive a game it launched.
## It does nothing unless the game was started with `--amerika-agent` after the `--` separator, so shipped games are unaffected.
##
## Flags (all after `--`):
##   --amerika-agent                 enable this node
##   --amerika-frames=N              after N physics frames write the report, take the screenshot, and quit
##   --amerika-input=ACTION@T0-T1,.. press an input action between two times (seconds of game time at 60 ticks/s)
##   --amerika-shot=PATH             save a PNG of the viewport at the end (needs a real display, not --headless)
##   --amerika-report=PATH           write a JSON state report at the end
##   --amerika-ctl=DIR               poll DIR/shot.request for ad-hoc screenshots while running (path inside the file)

var enabled: bool = false
var frames_limit: int = 0
var shot_path: String = ""
var report_path: String = ""
var ctl_dir: String = ""
var inputs: Array = [] ## [action, start_frame, end_frame]
var _frame: int = 0
var _held: Dictionary = {}
var _errors: Array[String] = []


func _ready() -> void:
	var args := OS.get_cmdline_user_args()
	for a in args:
		if a == "--amerika-agent":
			enabled = true
		elif a.begins_with("--amerika-frames="):
			frames_limit = int(a.get_slice("=", 1))
		elif a.begins_with("--amerika-shot="):
			shot_path = a.substr("--amerika-shot=".length())
		elif a.begins_with("--amerika-report="):
			report_path = a.substr("--amerika-report=".length())
		elif a.begins_with("--amerika-ctl="):
			ctl_dir = a.substr("--amerika-ctl=".length())
		elif a.begins_with("--amerika-input="):
			_parse_inputs(a.substr("--amerika-input=".length()))
	if not enabled:
		set_process(false)
		set_physics_process(false)
		queue_free()
		return
	process_mode = Node.PROCESS_MODE_ALWAYS
	print("[amerika] debug agent active (frames=%d, inputs=%d)" % [frames_limit, inputs.size()])


func _parse_inputs(spec: String) -> void:
	var tps := float(Engine.physics_ticks_per_second)
	for part in spec.split(",", false):
		var action := part.get_slice("@", 0)
		var span := part.get_slice("@", 1)
		inputs.append([action, int(float(span.get_slice("-", 0)) * tps), int(float(span.get_slice("-", 1)) * tps)])


func _physics_process(_delta: float) -> void:
	_frame += 1
	for item in inputs:
		var action: String = item[0]
		if not InputMap.has_action(action):
			continue
		var should_hold: bool = _frame >= int(item[1]) and _frame < int(item[2])
		if should_hold and not _held.has(action):
			Input.action_press(action)
			_held[action] = true
		elif not should_hold and _held.has(action) and _frame >= int(item[2]):
			Input.action_release(action)
			_held.erase(action)
	if ctl_dir != "" and _frame % 6 == 0:
		_poll_ctl()
	if frames_limit > 0 and _frame >= frames_limit:
		_finish()


func _poll_ctl() -> void:
	var req := ctl_dir.path_join("shot.request")
	if not FileAccess.file_exists(req):
		return
	var target := FileAccess.get_file_as_string(req).strip_edges()
	DirAccess.remove_absolute(req)
	var err := await capture(target)
	var f := FileAccess.open(ctl_dir.path_join("shot.done"), FileAccess.WRITE)
	if f != null:
		f.store_string(JSON.stringify({"path": target, "error": error_string(err), "ok": err == OK}))


func capture(path: String) -> int:
	if DisplayServer.get_name() == "headless":
		push_warning("[amerika] screenshot unavailable: the game runs with --headless (no renderer)")
		return ERR_UNAVAILABLE
	await RenderingServer.frame_post_draw
	var img := get_viewport().get_texture().get_image()
	if img == null or img.is_empty():
		return ERR_CANT_CREATE
	DirAccess.make_dir_recursive_absolute(path.get_base_dir())
	return img.save_png(path)


func report() -> Dictionary:
	var g := get_node_or_null("/root/AmerikaGame")
	var data := {"frames": _frame, "display": DisplayServer.get_name()}
	if g != null:
		var p: Variant = g.get("player")
		data["state"] = g.get("state")
		data["score"] = g.get("score")
		data["health"] = g.get("health")
		data["flags"] = g.get("flags")
		data["collected"] = g.get("collected")
		data["elapsed"] = g.get("elapsed")
		if p is Node2D:
			data["player"] = [snappedf((p as Node2D).global_position.x, 0.01), snappedf((p as Node2D).global_position.y, 0.01)]
		elif p is Node3D:
			var q := (p as Node3D).global_position
			data["player"] = [snappedf(q.x, 0.01), snappedf(q.y, 0.01), snappedf(q.z, 0.01)]
	var scene := get_tree().current_scene
	data["scene"] = scene.scene_file_path if scene != null else ""
	data["nodes"] = get_tree().get_node_count()
	return data


func _finish() -> void:
	set_physics_process(false)
	if shot_path != "":
		var err := await capture(shot_path)
		print("[amerika] screenshot %s -> %s" % [shot_path, error_string(err)])
	if report_path != "":
		DirAccess.make_dir_recursive_absolute(report_path.get_base_dir())
		var f := FileAccess.open(report_path, FileAccess.WRITE)
		if f != null:
			f.store_string(JSON.stringify(report(), "\t"))
	get_tree().quit()
