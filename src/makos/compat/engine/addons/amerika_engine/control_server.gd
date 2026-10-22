extends Node
## Loopback JSON-RPC 2.0 server for Amerika Agent (via amerika-studio-mcp): POST /rpc with `Authorization: Bearer <token>`,
## method engine.<tool> (see tools.gd RPC table), app.ping, app.prompt. Descriptor: $XDG_RUNTIME_DIR/amerika/studio-engine.json.

const Bridge := preload("res://addons/amerika_engine/bridge.gd")
const VERSION := "3.1.1"

var tools: RefCounted
var ai: Node
var bridge := Bridge.new()
var port: int = 0
var token: String = ""
var ready_flag: bool = false
var _server := TCPServer.new()
var _clients: Array = [] ## {peer, buf, t}
var _busy: bool = false


func start() -> bool:
	if _server.listen(0, "127.0.0.1") != OK:
		return false
	port = _server.get_local_port()
	var crypto := Crypto.new()
	token = Marshalls.raw_to_base64(crypto.generate_random_bytes(24)).replace("+", "-").replace("/", "_").replace("=", "")
	ready_flag = true
	bridge.write_descriptor(port, token, VERSION)
	return true


func stop() -> void:
	_server.stop()
	var path := bridge.descriptor_path()
	if path != "" and FileAccess.file_exists(path):
		var d: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
		if d is Dictionary and int(d.get("pid", -1)) == OS.get_process_id():
			bridge.remove_descriptor()


func _exit_tree() -> void:
	stop()


func _process(_delta: float) -> void:
	if not _server.is_listening():
		return
	while _server.is_connection_available():
		_clients.append({"peer": _server.take_connection(), "buf": PackedByteArray(), "t": Time.get_ticks_msec(), "busy": false})
	for c in _clients.duplicate():
		if c["busy"]:
			continue
		var peer: StreamPeerTCP = c["peer"]
		peer.poll()
		if peer.get_status() != StreamPeerTCP.STATUS_CONNECTED:
			_clients.erase(c)
			continue
		var n := peer.get_available_bytes()
		if n > 0:
			c["buf"].append_array(peer.get_data(n)[1])
		if Time.get_ticks_msec() - c["t"] > 30000:
			_reply(c, 408, {"error": "timeout"})
			continue
		var req := _parse(c["buf"])
		if req.is_empty():
			continue
		if req.has("error"):
			_reply(c, 400, {"error": req["error"]})
			continue
		c["busy"] = true
		_handle(c, req)


func _parse(buf: PackedByteArray) -> Dictionary:
	var text := buf.get_string_from_utf8()
	var split := text.find("\r\n\r\n")
	if split < 0:
		return {} if buf.size() < 65536 else {"error": "headers too large"}
	var head := text.substr(0, split)
	var lines := head.split("\r\n")
	var first := lines[0].split(" ")
	if first.size() < 2:
		return {"error": "bad request line"}
	var headers := {}
	for l in lines.slice(1):
		var i := l.find(":")
		if i > 0:
			headers[l.substr(0, i).strip_edges().to_lower()] = l.substr(i + 1).strip_edges()
	var length := int(headers.get("content-length", "0"))
	if length > 4000000:
		return {"error": "body too large"}
	var body_start := head.to_utf8_buffer().size() + 4
	if buf.size() < body_start + length:
		return {}
	return {"method": first[0], "path": first[1], "headers": headers, "body": buf.slice(body_start, body_start + length).get_string_from_utf8()}


func _reply(c: Dictionary, status_code: int, obj: Variant) -> void:
	var body := JSON.stringify(obj).to_utf8_buffer()
	var reason := {200: "OK", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found", 408: "Request Timeout"}.get(status_code, "Error")
	var head := "HTTP/1.1 %d %s\r\nContent-Type: application/json\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % [status_code, reason, body.size()]
	var peer: StreamPeerTCP = c["peer"]
	peer.put_data(head.to_utf8_buffer())
	peer.put_data(body)
	peer.disconnect_from_host()
	_clients.erase(c)


func _rpc_error(id: Variant, code: int, message: String) -> Dictionary:
	return {"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}}


func _handle(c: Dictionary, req: Dictionary) -> void:
	var host: String = str(req["headers"].get("host", ""))
	if not (host.begins_with("127.0.0.1") or host.begins_with("localhost") or host.begins_with("[::1]")):
		_reply(c, 403, {"error": "bad host"})
		return
	if req["headers"].has("origin"):
		_reply(c, 403, {"error": "browser requests are refused"})
		return
	var auth: String = str(req["headers"].get("authorization", ""))
	if not auth.begins_with("Bearer ") or not _const_eq(auth.substr(7), token):
		_reply(c, 401, {"error": "bad token"})
		return
	if req["method"] != "POST" or req["path"] != "/rpc":
		_reply(c, 404, {"error": "POST /rpc only"})
		return
	var msg: Variant = JSON.parse_string(req["body"])
	if not (msg is Dictionary) or not msg.has("method"):
		_reply(c, 200, _rpc_error(null, -32600, "invalid request"))
		return
	var id: Variant = msg.get("id")
	var params: Dictionary = msg.get("params", {}) if msg.get("params") is Dictionary else {}
	var result: Dictionary = await dispatch(str(msg["method"]), params)
	if result.get("ok", true) == false and result.has("error") and result.has("code"):
		_reply(c, 200, _rpc_error(id, int(result["code"]), str(result["error"])))
	else:
		_reply(c, 200, {"jsonrpc": "2.0", "id": id, "result": result})


func _const_eq(a: String, b: String) -> bool:
	if a.length() != b.length():
		return false
	var d := 0
	for i in range(a.length()):
		d |= a.unicode_at(i) ^ b.unicode_at(i)
	return d == 0


## Also used directly by tests.
func dispatch(method: String, params: Dictionary) -> Dictionary:
	if method == "app.ping":
		return {"ok": true, "app": "engine", "version": VERSION, "ready": ready_flag}
	if method == "app.prompt":
		if ai == null:
			return {"ok": false, "error": "assistant not available", "code": -32004}
		if _busy or ai.busy:
			return {"ok": false, "error": "the assistant is busy", "code": -32002}
		_busy = true
		var prev: bool = ai.auto_approve
		ai.auto_approve = true
		var timeout := float(params.get("timeout_s", 300))
		var timer := get_tree().create_timer(timeout)
		timer.timeout.connect(func() -> void: if ai.busy: ai.stop())
		var r: Dictionary = await ai.run_prompt(str(params.get("message", "")), "agent: " + str(params.get("message", "")).left(50))
		ai.auto_approve = prev
		_busy = false
		return r
	if not method.begins_with("engine."):
		return {"ok": false, "error": "unknown method " + method, "code": -32601}
	var tool_name: String = tools.tool_for_rpc(method)
	if tool_name == "":
		return {"ok": false, "error": "unknown method " + method, "code": -32601}
	if _busy:
		return {"ok": false, "error": "busy with another request", "code": -32002}
	_busy = true
	var res: Dictionary = await tools.call_tool(tool_name, params)
	_busy = false
	return res
