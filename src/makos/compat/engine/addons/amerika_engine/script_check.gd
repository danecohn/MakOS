extends RefCounted
## Parse-checks GDScript source without installing it: loads it into a throwaway GDScript and reports the engine's
## own parse/analysis errors (with line numbers). Needs OS.add_logger (Godot 4.5+) for messages; on older versions
## only the error code is available and a headless --check-only child process is used for the messages.

const LogCapture := "res://addons/amerika_engine/log_capture.gd"


func check(source: String, label: String = "script.gd") -> Dictionary:
	var script := GDScript.new()
	script.source_code = source
	var cap: Object = null
	if OS.has_method("add_logger"):
		var cap_script: Script = load(LogCapture)
		cap = cap_script.new()
		OS.call("add_logger", cap)
	var err := script.reload()
	var errors: Array = []
	if cap != null:
		OS.call("remove_logger", cap)
		for e in cap.get("entries"):
			if e["file"].begins_with("gdscript://") or e["file"] == "" or e["file"].ends_with(label):
				errors.append({"line": e["line"], "message": String(e["message"]).trim_prefix("Parse Error: ")})
	if err != OK and errors.is_empty():
		errors.append({"line": 0, "message": "script failed to compile (%s)" % error_string(err)})
	return {"ok": err == OK, "errors": errors, "error_code": err}


func format(errors: Array) -> String:
	var lines: Array = []
	for e in errors:
		lines.append("line %d: %s" % [e["line"], e["message"]])
	return "\n".join(lines)
