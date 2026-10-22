extends RefCounted
## Runs the project as a separate Godot process and captures its output. Used by run_project / get_output_and_errors /
## game_screenshot. One game at a time; processes are tracked by exact PID and only ever stopped by that PID.

const LOG_PATH := "res://.amerika/run.log"
const MAX_LINES := 3000

var pid: int = -1
var started_ms: int = 0
var exit_code: int = -1
var lines: Array = [] ## recent output lines {t, stream, text}
var args_used: Array = []
var ctl_dir: String = ""
var last_report_path: String = ""
var _threads: Array = []
var _mutex := Mutex.new()
var _stop_readers: bool = false


func running() -> bool:
	return pid > 0 and OS.is_process_running(pid)


func project_dir() -> String:
	return ProjectSettings.globalize_path("res://").rstrip("/")


func has_display() -> bool:
	return DisplayServer.get_name() != "headless" or OS.get_environment("WAYLAND_DISPLAY") != "" or OS.get_environment("DISPLAY") != ""


func display_driver_args() -> Array:
	var name_ := DisplayServer.get_name().to_lower()
	if name_ == "headless":
		name_ = "wayland" if OS.get_environment("WAYLAND_DISPLAY") != "" else "x11"
	if name_ in ["x11", "wayland", "windows", "macos"]:
		return ["--display-driver", name_]
	return []


## Start the game. opts: scene (res://), frames, input (spec string), headless (bool), shot (abs png path), report (abs path),
## fixed_fps (bool), extra (Array of engine args)
func start(opts: Dictionary = {}) -> Dictionary:
	if running():
		return {"ok": false, "error": "a game is already running (pid %d); stop it first" % pid}
	lines = []
	exit_code = -1
	_stop_readers = false
	var argv: Array = []
	var headless: bool = bool(opts.get("headless", (not has_display()) or (DisplayServer.get_name() == "headless" and not opts.has("shot"))))
	if headless:
		argv.append("--headless")
	else:
		argv.append_array(display_driver_args())
	argv.append_array(["--path", project_dir()])
	if bool(opts.get("fixed_fps", headless)):
		argv.append_array(["--fixed-fps", "60"])
	for e in opts.get("extra", []):
		argv.append(str(e))
	if opts.get("scene", "") != "":
		argv.append(String(opts["scene"]))
	argv.append("--")
	argv.append("--amerika-agent")
	ctl_dir = project_dir().path_join(".amerika/ctl")
	DirAccess.make_dir_recursive_absolute(ctl_dir)
	for f in ["shot.request", "shot.done"]:
		if FileAccess.file_exists(ctl_dir.path_join(f)):
			DirAccess.remove_absolute(ctl_dir.path_join(f))
	argv.append("--amerika-ctl=" + ctl_dir)
	if int(opts.get("frames", 0)) > 0:
		argv.append("--amerika-frames=%d" % int(opts["frames"]))
	if str(opts.get("input", "")) != "":
		argv.append("--amerika-input=" + str(opts["input"]))
	if str(opts.get("shot", "")) != "":
		argv.append("--amerika-shot=" + str(opts["shot"]))
	last_report_path = str(opts.get("report", ""))
	if last_report_path != "":
		argv.append("--amerika-report=" + last_report_path)
	args_used = argv
	var proc := OS.execute_with_pipe(OS.get_executable_path(), argv)
	if proc.is_empty():
		return {"ok": false, "error": "could not start the Godot executable " + OS.get_executable_path()}
	pid = int(proc["pid"])
	started_ms = Time.get_ticks_msec()
	_start_reader(proc["stdio"], "out")
	_start_reader(proc["stderr"], "err")
	return {"ok": true, "pid": pid, "headless": headless, "args": argv}


func _start_reader(pipe: FileAccess, stream: String) -> void:
	var t := Thread.new()
	t.start(_read_loop.bind(pipe, stream))
	_threads.append(t)


func _read_loop(pipe: FileAccess, stream: String) -> void:
	var my_pid := pid
	while not _stop_readers:
		var text := pipe.get_line()
		if text == "":
			if not OS.is_process_running(my_pid):
				break
			OS.delay_msec(15)
			continue
		_mutex.lock()
		lines.append({"t": Time.get_ticks_msec() - started_ms, "stream": stream, "text": text})
		if lines.size() > MAX_LINES:
			lines.pop_front()
		_mutex.unlock()


## Reap reader threads once the process is gone; call from time to time.
func poll() -> void:
	if pid > 0 and not OS.is_process_running(pid):
		if exit_code == -1:
			exit_code = OS.get_process_exit_code(pid)
			_save_log()
		_join()


func _join() -> void:
	_stop_readers = true
	for t in _threads:
		if t.is_started():
			t.wait_to_finish()
	_threads = []


func stop() -> Dictionary:
	if pid <= 0:
		return {"ok": true, "was_running": false}
	var was := running()
	if was:
		OS.kill(pid)
		var t0 := Time.get_ticks_msec()
		while OS.is_process_running(pid) and Time.get_ticks_msec() - t0 < 3000:
			OS.delay_msec(20)
	exit_code = OS.get_process_exit_code(pid) if not OS.is_process_running(pid) else -1
	_join()
	_save_log()
	return {"ok": true, "was_running": was, "pid": pid}


func _save_log() -> void:
	DirAccess.make_dir_recursive_absolute("res://.amerika")
	var f := FileAccess.open(LOG_PATH, FileAccess.WRITE)
	if f == null:
		return
	_mutex.lock()
	for l in lines:
		f.store_line(l["text"])
	_mutex.unlock()


func snapshot(max_lines: int = 200) -> Array:
	_mutex.lock()
	var out := lines.slice(maxi(0, lines.size() - max_lines))
	_mutex.unlock()
	return out


## Pull errors, script errors and warnings (with their "at:" lines) out of captured output lines.
func parse_problems(src: Array) -> Array:
	var problems: Array = []
	var i := 0
	while i < src.size():
		var t: String = src[i]["text"]
		var kind := ""
		for prefix in ["SCRIPT ERROR:", "ERROR:", "WARNING:", "USER ERROR:", "USER WARNING:", "USER SCRIPT ERROR:"]:
			if t.begins_with(prefix):
				kind = "warning" if prefix.contains("WARNING") else "error"
				break
		if kind != "":
			var p := {"kind": kind, "message": t, "at": ""}
			var j := i + 1
			while j < src.size() and j < i + 6 and (src[j]["text"].strip_edges().begins_with("at:") or src[j]["text"].strip_edges().begins_with("GDScript backtrace") or src[j]["text"].strip_edges().begins_with("[")):
				if src[j]["text"].strip_edges().begins_with("at:"):
					p["at"] = src[j]["text"].strip_edges().trim_prefix("at:").strip_edges()
				else:
					p["message"] += "\n" + src[j]["text"].strip_edges()
				j += 1
			problems.append(p)
			i = j
			continue
		i += 1
	return problems
