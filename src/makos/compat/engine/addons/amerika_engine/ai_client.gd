extends Node
## The tool-use loop in GDScript. Talks ONLY to the local Studio bridge (loopback, bearer token read from a file);
## there is no API key in the plugin. Non-streaming Messages API. One request at a time.

const Bridge := preload("res://addons/amerika_engine/bridge.gd")
const Prompt := preload("res://addons/amerika_engine/system_prompt.gd")
const CHAT_PATH := "res://.amerika/chat.json"
const MODELS_FALLBACK := ["claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5"]

signal assistant_text(text: String)
signal tool_started(id: String, tool_name: String, input: Dictionary)
signal tool_finished(id: String, tool_name: String, summary: String, ok: bool)
signal approval_needed(id: String, tool_name: String, input: Dictionary)
signal status(text: String)
signal busy_changed(busy: bool)
signal finished(result: Dictionary)
signal _http_finished
signal _approval_resolved(id: String, approved: bool)

var tools: RefCounted ## tools.gd instance
var bridge := Bridge.new()
var model: String = "claude-sonnet-5-5"
var review: bool = true ## ask before running scripts the model wrote
var auto_approve: bool = false ## never ask (used for app.prompt from Amerika Agent, which has its own approval)
var max_turns: int = 30
var max_tokens: int = 8000
var busy: bool = false
var messages: Array = []
var last_usage: Dictionary = {}

var _http: HTTPRequest
var _stop: bool = false
var _resp: Dictionary = {}
var _pending_id: String = ""


func _ensure_http() -> void:
	if _http != null:
		return
	_http = HTTPRequest.new()
	_http.timeout = 240.0
	add_child(_http)
	_http.request_completed.connect(_on_completed)


func _on_completed(result: int, code: int, headers: PackedStringArray, body: PackedByteArray) -> void:
	_resp = {"result": result, "code": code, "headers": headers, "body": body}
	_http_finished.emit()


# ------------------------------------------------------------------ public API

func stop() -> void:
	if not busy:
		return
	_stop = true
	if _http != null:
		_http.cancel_request()
	_resp = {"result": -1, "code": 0, "headers": PackedStringArray(), "body": PackedByteArray()}
	_http_finished.emit()
	if _pending_id != "":
		_approval_resolved.emit(_pending_id, false)


func resolve_approval(id: String, approved: bool) -> void:
	_approval_resolved.emit(id, approved)


func clear_chat() -> void:
	messages = []
	if FileAccess.file_exists(CHAT_PATH):
		DirAccess.remove_absolute(CHAT_PATH)


func fetch_models() -> Array:
	var req := HTTPRequest.new()
	add_child(req)
	var err := req.request(bridge.base_url() + "/v1/status", bridge.headers(), HTTPClient.METHOD_GET)
	if err != OK:
		req.queue_free()
		return MODELS_FALLBACK
	var res: Array = await req.request_completed
	req.queue_free()
	if res[1] == 200:
		var parsed: Variant = JSON.parse_string((res[3] as PackedByteArray).get_string_from_utf8())
		if parsed is Dictionary and parsed.get("models") is Array and not (parsed["models"] as Array).is_empty():
			var out: Array = []
			for m in parsed["models"]:
				out.append(m if m is String else str(m.get("id", m)))
			return out
	return MODELS_FALLBACK


## Run one user request through the model/tool loop. Returns {ok, text, tool_calls, turns, error?}.
func run_prompt(user_text: String, label: String = "") -> Dictionary:
	if busy:
		return {"ok": false, "error": "the assistant is busy", "code": -32002}
	if tools == null:
		return {"ok": false, "error": "no tools attached", "code": -32004}
	if bridge.read_token() == "":
		var msg := "No Studio token found (%s). Start Studio (amerika-studio ensure) and set up your Anthropic key there." % bridge.token_path()
		finished.emit({"ok": false, "error": msg})
		return {"ok": false, "error": msg, "code": -32004}
	while not is_inside_tree():
		await Engine.get_main_loop().process_frame
	busy = true
	_stop = false
	busy_changed.emit(true)
	var own_session: bool = not tools.history.active()
	if own_session:
		tools.history.begin(label if label != "" else user_text.left(60))
	messages.append({"role": "user", "content": [{"type": "text", "text": user_text}]})
	var final_text := ""
	var calls: Array = []
	var error := ""
	var turns := 0
	while turns < max_turns:
		turns += 1
		if _stop:
			error = "stopped"
			break
		status.emit("Thinking...")
		_trim_history()
		var resp := await _call_api()
		if not resp["ok"]:
			error = str(resp["error"])
			break
		var body: Dictionary = resp["body"]
		last_usage = body.get("usage", {})
		var content: Array = body.get("content", [])
		messages.append({"role": "assistant", "content": content})
		var uses: Array = []
		for block in content:
			if block.get("type") == "text" and str(block.get("text", "")).strip_edges() != "":
				final_text = str(block["text"])
				assistant_text.emit(final_text)
			elif block.get("type") == "tool_use":
				uses.append(block)
		if body.get("stop_reason") == "max_tokens" and uses.is_empty():
			error = "the reply was cut off (max_tokens); ask for a smaller step"
			break
		if uses.is_empty():
			break
		var results: Array = []
		for tu in uses:
			var tname: String = str(tu.get("name", ""))
			var targs: Dictionary = tu.get("input", {}) if tu.get("input") is Dictionary else {}
			var tid: String = str(tu.get("id", ""))
			if _stop:
				results.append({"type": "tool_result", "tool_use_id": tid, "content": "Stopped by the user before this tool ran.", "is_error": true})
				continue
			calls.append(tname)
			tool_started.emit(tid, tname, targs)
			status.emit("Running %s..." % tname)
			var result: Dictionary
			if review and not auto_approve and tools.needs_review(tname, targs):
				_pending_id = tid
				approval_needed.emit(tid, tname, targs)
				var answer: Array = await _approval_resolved
				while answer[0] != tid:
					answer = await _approval_resolved
				_pending_id = ""
				if not bool(answer[1]):
					result = {"ok": false, "error": "The user declined to run this change. Ask what they want instead.", "code": -32001}
				else:
					result = await tools.call_tool(tname, targs)
			else:
				result = await tools.call_tool(tname, targs)
			var summary := _summarize(result)
			tool_finished.emit(tid, tname, summary, bool(result.get("ok", false)))
			results.append(_tool_result_block(tid, result))
		messages.append({"role": "user", "content": results})
		if turns >= max_turns:
			error = "stopped after %d steps without finishing" % max_turns
	var manifest: Dictionary = {}
	if own_session:
		manifest = tools.finish_session()
	save_chat()
	busy = false
	busy_changed.emit(false)
	status.emit("")
	var out := {"ok": error == "", "text": final_text, "tool_calls": calls, "turns": turns, "changed": manifest.get("files", []).size() if not manifest.is_empty() else 0, "usage": last_usage}
	if error != "":
		out["error"] = error
	finished.emit(out)
	return out


# ------------------------------------------------------------------ internals

func _summarize(result: Dictionary) -> String:
	if not result.get("ok", false):
		return str(result.get("error", "failed")).left(240)
	for k in ["path", "scene", "message"]:
		if result.has(k):
			return str(result[k])
	if result.has("files"):
		return "%d files" % (result["files"] as Array).size()
	return "ok"


func _tool_result_block(id: String, result: Dictionary) -> Dictionary:
	var images: Array = result.get("images", [])
	var plain := result.duplicate()
	plain.erase("images")
	var text := JSON.stringify(plain)
	if text.length() > 24000:
		text = text.left(24000) + "...[truncated]"
	var block := {"type": "tool_result", "tool_use_id": id, "is_error": not bool(result.get("ok", false))}
	if images.is_empty():
		block["content"] = text
	else:
		var parts: Array = [{"type": "text", "text": text}]
		for im in images:
			parts.append({"type": "image", "source": {"type": "base64", "media_type": im["mime"], "data": im["base64"]}})
		block["content"] = parts
	return block


func _trim_history() -> void:
	var size := JSON.stringify(messages).length()
	if size < 300000:
		return
	var keep_from := maxi(0, messages.size() - 8)
	for i in range(keep_from):
		var m: Dictionary = messages[i]
		if m["content"] is Array:
			for block in m["content"]:
				if block.get("type") == "tool_result":
					var c: Variant = block.get("content")
					if c is Array:
						block["content"] = "[earlier tool result with image removed]"
					elif c is String and (c as String).length() > 600:
						block["content"] = (c as String).left(600) + "...[older result truncated]"
				elif block.get("type") == "tool_use":
					var inp: Variant = block.get("input")
					if inp is Dictionary:
						for k in (inp as Dictionary).keys():
							if inp[k] is String and (inp[k] as String).length() > 800:
								inp[k] = (inp[k] as String).left(800) + "...[truncated]"
	if JSON.stringify(messages).length() > 700000:
		messages = messages.slice(messages.size() - 12)
		while not messages.is_empty() and not (messages[0]["role"] == "user" and messages[0]["content"] is Array and messages[0]["content"][0].get("type") == "text"):
			messages.pop_front()


func _call_api() -> Dictionary:
	_ensure_http()
	var comps: Dictionary = tools.get("_components") if tools.get("_components") != null else {}
	var body := {
		"model": model,
		"max_tokens": max_tokens,
		"system": Prompt.new().build(comps, tools.project_summary()),
		"tools": tools.anthropic_tools(),
		"messages": messages,
	}
	var payload := JSON.stringify(body)
	var attempt := 0
	while true:
		attempt += 1
		_resp = {}
		var err := _http.request(bridge.base_url() + "/v1/messages", bridge.headers(), HTTPClient.METHOD_POST, payload)
		if err != OK:
			return {"ok": false, "error": "could not start the request to the Studio bridge (%s)" % error_string(err)}
		await _http_finished
		if _stop:
			return {"ok": false, "error": "stopped"}
		var r: int = _resp.get("result", -1)
		var code: int = _resp.get("code", 0)
		var text := (_resp.get("body", PackedByteArray()) as PackedByteArray).get_string_from_utf8()
		if r != HTTPRequest.RESULT_SUCCESS:
			return {"ok": false, "error": "Cannot reach the Studio bridge at %s (HTTP result %d). Start it with `amerika-studio ensure` or open Studio." % [bridge.base_url(), r]}
		var parsed: Variant = JSON.parse_string(text)
		if code == 200 and parsed is Dictionary:
			return {"ok": true, "body": parsed}
		var etype := ""
		var emsg := text.left(300)
		if parsed is Dictionary and parsed.get("error") is Dictionary:
			etype = str(parsed["error"].get("type", ""))
			emsg = str(parsed["error"].get("message", emsg))
		elif parsed is Dictionary and parsed.get("error") is String:
			emsg = str(parsed["error"])
		if code in [429, 502, 503, 529] and etype != "budget_exceeded" and attempt < 4:
			var wait := 1.5 * attempt
			for h in (_resp["headers"] as PackedStringArray):
				if h.to_lower().begins_with("retry-after:"):
					wait = clampf(float(h.get_slice(":", 1).strip_edges()), 1.0, 20.0)
			status.emit("Busy, retrying in %d s..." % int(wait))
			await get_tree().create_timer(wait).timeout
			continue
		if code == 401 or code == 403:
			if etype == "no_api_key" or emsg.to_lower().contains("key"):
				return {"ok": false, "error": "No Anthropic key is set up. Open Studio and choose 'Set up Anthropic key'."}
			return {"ok": false, "error": "The Studio bridge refused the token (%s). Restart Studio." % emsg}
		return {"ok": false, "error": "%s (HTTP %d%s)" % [emsg, code, (", " + etype) if etype != "" else ""]}
	return {"ok": false, "error": "unreachable"}


# ------------------------------------------------------------------ persistence

func save_chat() -> void:
	var slim: Array = []
	for m in messages.slice(maxi(0, messages.size() - 60)):
		slim.append(_strip_images(m))
	DirAccess.make_dir_recursive_absolute("res://.amerika")
	var f := FileAccess.open(CHAT_PATH, FileAccess.WRITE)
	if f != null:
		f.store_string(JSON.stringify(slim))


func _strip_images(m: Dictionary) -> Dictionary:
	var copy: Dictionary = m.duplicate(true)
	if copy["content"] is Array:
		for block in copy["content"]:
			if block.get("type") == "tool_result" and block.get("content") is Array:
				var txt := ""
				for part in block["content"]:
					if part.get("type") == "text":
						txt = str(part["text"])
				block["content"] = txt + " [image omitted]"
	return copy


func load_chat() -> void:
	if not FileAccess.file_exists(CHAT_PATH):
		return
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(CHAT_PATH))
	if parsed is Array:
		messages = parsed
		while not messages.is_empty() and not (messages[0]["role"] == "user" and messages[0]["content"] is Array and (messages[0]["content"] as Array).size() > 0 and messages[0]["content"][0].get("type") == "text"):
			messages.pop_front()
