extends Logger
## Captures engine errors/warnings in-process (OS.add_logger needs Godot 4.5+). Loaded with load() only when available,
## so the rest of the plugin still parses on older 4.x versions.

var entries: Array = []
var limit: int = 400


func _log_error(function: String, file: String, line: int, code: String, rationale: String, _editor_notify: bool, error_type: int, _backtraces: Array) -> void:
	var text := code
	if rationale != "":
		text = "%s (%s)" % [rationale, code] if code != "" else rationale
	_push({"kind": "warning" if error_type == 1 else ("script" if error_type == 2 else "error"), "message": text, "file": file, "line": line, "function": function})


func _log_message(message: String, error: bool) -> void:
	if error:
		_push({"kind": "stderr", "message": message.strip_edges(), "file": "", "line": 0, "function": ""})


func _push(e: Dictionary) -> void:
	entries.append(e)
	if entries.size() > limit:
		entries.pop_front()
