@tool
extends EditorPlugin
## Engine editor plugin: chat dock + control endpoint + project tools.

const Tools := preload("res://addons/amerika_engine/tools.gd")
const AiClient := preload("res://addons/amerika_engine/ai_client.gd")
const Dock := preload("res://addons/amerika_engine/dock.gd")
const ControlServer := preload("res://addons/amerika_engine/control_server.gd")

var tools: RefCounted
var ai: Node
var dock: Control
var server: Node
var logger: Object


func _enter_tree() -> void:
	tools = Tools.new(get_tree())
	tools.plugin = self
	if OS.has_method("add_logger"):
		logger = load("res://addons/amerika_engine/log_capture.gd").new()
		OS.call("add_logger", logger)
		tools.editor_log = logger
	ai = AiClient.new()
	ai.tools = tools
	tools.ai = ai
	add_child(ai)
	server = ControlServer.new()
	server.tools = tools
	server.ai = ai
	add_child(server)
	server.start()
	if DisplayServer.get_name() != "headless":
		dock = Dock.new()
		dock.setup(ai, tools)
		add_control_to_dock(DOCK_SLOT_RIGHT_UL, dock)


func _exit_tree() -> void:
	if dock != null:
		remove_control_from_docks(dock)
		dock.queue_free()
	if server != null:
		server.stop()
		server.queue_free()
	if logger != null:
		OS.call("remove_logger", logger)
	if tools != null:
		tools.runner.stop()
	if ai != null:
		ai.queue_free()
