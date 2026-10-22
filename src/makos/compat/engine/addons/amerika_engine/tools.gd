extends RefCounted
## The tools the assistant (and Amerika Agent over JSON-RPC) can call. Every tool takes a Dictionary and returns a
## Dictionary: {ok: true, ...} or {ok: false, error: "...", code: -32xxx}. All file access is confined to res://.
## Works with or without the editor: `plugin` is null when running from the command line / tests.

const Assembler := preload("res://addons/amerika_engine/recipe_assembler.gd")
const RecipeScript := preload("res://addons/amerika_engine/recipe.gd")
const ScriptCheck := preload("res://addons/amerika_engine/script_check.gd")
const History := preload("res://addons/amerika_engine/history.gd")
const Runner := preload("res://addons/amerika_engine/runner.gd")
const InputMapper := preload("res://addons/amerika_engine/input_map.gd")
const ExportPresets := preload("res://addons/amerika_engine/export_presets.gd")

const ERR_OTHER := -32000
const ERR_BUSY := -32002
const ERR_PATH := -32003
const ERR_NOT_READY := -32004
const ERR_PARAMS := -32602
const ERR_METHOD := -32601

const WRITE_EXT := ["gd", "tscn", "tres", "json", "cfg", "md", "txt", "gdshader", "csv", "svg"]
const READ_EXT := ["gd", "tscn", "tres", "json", "cfg", "md", "txt", "gdshader", "csv", "svg", "godot", "import", "uid", "po", "ini", "yml", "yaml", "toml", "xml", "html", "css", "js"]
const ASSET_EXT := ["glb", "gltf", "bin", "png", "jpg", "jpeg", "webp", "svg", "wav", "ogg", "mp3"]
const HIDDEN_ROOTS := [".godot", ".git", ".amerika", ".import"]
const MAX_FILE := 1000000

## RPC method (tools.json) -> tool name.
const RPC := {
	"project.info": "project_info", "files.list": "list_files", "files.read": "read_file", "files.write": "write_file",
	"scene.create": "create_scene", "scene.describe": "describe_scene", "script.create": "create_script",
	"script.edit": "edit_script", "recipe.get": "get_recipe", "recipe.set": "set_recipe", "recipe.assemble": "assemble_recipe",
	"project.run": "run_project", "project.stop": "stop_project", "project.logs": "get_output_and_errors",
	"import.model": "import_model",
	# not in tools.json (yet): reachable over JSON-RPC as engine.<name>
	"game.screenshot": "game_screenshot", "node.add": "add_node", "node.set_property": "set_property",
	"script.attach": "attach_script", "input.set": "set_input_map", "export.set_preset": "set_export_preset",
	"recipe.validate": "validate_recipe", "history.list": "history_list", "history.undo": "history_undo", "history.redo": "history_redo",
}

var plugin: Object = null ## EditorPlugin when running inside the editor
var tree: SceneTree
var history := History.new()
var runner := Runner.new()
var scripts := ScriptCheck.new()
var ai: Object = null ## ai_client.gd instance (for description-based requests); optional
var editor_log: Object = null ## log_capture.gd instance installed by the plugin; optional
var _components: Dictionary = {}
var _shot_counter: int = 0
var _specs: Array = []


func _init(p_tree: SceneTree = null) -> void:
	tree = p_tree if p_tree != null else (Engine.get_main_loop() as SceneTree)
	_components = RecipeScript.new().components()
	history.on_restored = _on_history_restored


# ================================================================== specs

func _schema(props: Dictionary, required: Array = []) -> Dictionary:
	return {"type": "object", "properties": props, "required": required, "additionalProperties": false}


func _p(type: String, desc: String, extra: Dictionary = {}) -> Dictionary:
	var d := {"type": type, "description": desc}
	d.merge(extra, true)
	return d


func tool_specs() -> Array:
	if not _specs.is_empty():
		return _specs
	var path_p := _p("string", "Path inside the project, relative or res://... (never absolute, never containing ..)")
	var scene_p := _p("string", "Scene path (.tscn) inside the project")
	_specs = [
		{"name": "project_info", "mutating": false, "description": "Project name, directory, Godot version, main scene, autoloads, open scenes, whether a game is running, and whether a recipe exists.", "input_schema": _schema({})},
		{"name": "list_files", "mutating": false, "description": "List files in the project (.godot, .git and .amerika are hidden).", "input_schema": _schema({"path": path_p, "recursive": _p("boolean", "Recurse into folders"), "limit": _p("integer", "Max entries", {"minimum": 1, "maximum": 5000})})},
		{"name": "read_file", "mutating": false, "description": "Read a text file from the project (scripts, scenes, json, cfg, md).", "input_schema": _schema({"path": path_p, "max_bytes": _p("integer", "Truncate after this many bytes", {"minimum": 1, "maximum": MAX_FILE})}, ["path"])},
		{"name": "write_file", "mutating": true, "description": "Write a text file inside the project (gd, tscn, tres, json, cfg, md, txt, gdshader, csv, svg). Overwriting needs overwrite=true; a backup is kept. GDScript is parse-checked first and refused if it does not compile.", "input_schema": _schema({"path": path_p, "content": _p("string", "File content", {"maxLength": MAX_FILE}), "overwrite": _p("boolean", "Allow replacing an existing file"), "allow_errors": _p("boolean", "Write a .gd file even if it has parse errors")}, ["path", "content"])},
		{"name": "create_scene", "mutating": true, "description": "Create a .tscn scene with a root node and optional child nodes ({name, type, parent, properties, script}). Parents must appear before children.", "input_schema": _schema({"path": scene_p, "root_type": _p("string", "Godot node class of the root, e.g. Node2D, Node3D, Control (default Node2D)"), "root_name": _p("string", "Root node name (default: file name)"), "nodes": {"type": "array", "description": "Child nodes to add", "items": {"type": "object"}}, "overwrite": _p("boolean", "Replace an existing scene")}, ["path"])},
		{"name": "describe_scene", "mutating": false, "description": "Describe a scene's node tree (names, types, scripts, groups, changed properties, instanced scenes) as structured JSON.", "input_schema": _schema({"path": scene_p}, ["path"])},
		{"name": "add_node", "mutating": true, "description": "Add a node to a scene: type is a Godot class, parent a node path inside the scene ('.' = root), properties are applied with type conversion (arrays become Vector2/Vector3/Color, strings become resources when they start with res://).", "input_schema": _schema({"scene": scene_p, "parent": _p("string", "Parent node path, '.' for the root"), "type": _p("string", "Node class, e.g. Sprite2D"), "name": _p("string", "Node name"), "properties": {"type": "object", "description": "Property name -> value"}}, ["scene", "type", "name"])},
		{"name": "set_property", "mutating": true, "description": "Set a property on a node in a scene (value converted to the property type; sub-properties like 'shape:size' work).", "input_schema": _schema({"scene": scene_p, "node": _p("string", "Node path inside the scene ('.' = root)"), "property": _p("string", "Property name"), "value": {"description": "New value"}}, ["scene", "node", "property", "value"])},
		{"name": "attach_script", "mutating": true, "description": "Attach an existing script (.gd) to a node of a scene.", "input_schema": _schema({"scene": scene_p, "node": _p("string", "Node path inside the scene ('.' = root)"), "script": _p("string", "Script path (.gd)")}, ["scene", "node", "script"])},
		{"name": "create_script", "mutating": true, "description": "Create a GDScript file from explicit code. The code is compiled in a throwaway script first; if it does not parse, nothing is written and the errors are returned.", "input_schema": _schema({"path": path_p, "code": _p("string", "Complete GDScript source", {"maxLength": 200000}), "extends": _p("string", "Base class used when only a description is given"), "description": _p("string", "What the script should do (only used when code is absent)"), "overwrite": _p("boolean", "Replace an existing file")}, ["path"])},
		{"name": "edit_script", "mutating": true, "description": "Edit a script with exact text patches: edits is a list of {old, new, all?}; each old must match exactly once (or set all=true). The result is parse-checked; if it fails the file is left untouched.", "input_schema": _schema({"path": path_p, "edits": {"type": "array", "description": "Patches", "items": {"type": "object", "properties": {"old": {"type": "string"}, "new": {"type": "string"}, "all": {"type": "boolean"}}, "required": ["old", "new"]}}, "instruction": _p("string", "Natural-language change (only for callers without exact patches)")}, ["path"])},
		{"name": "get_recipe", "mutating": false, "description": "Without a name: the project's current recipe (amerika_recipe.json) with validation issues, saved recipes, and the starter templates. With a name: that recipe ('main' = current, or a recipes/<name>.json, or a template id).", "input_schema": _schema({"name": _p("string", "Recipe or template name")})},
		{"name": "set_recipe", "mutating": true, "description": "Save a recipe (name 'main' = res://amerika_recipe.json, else recipes/<name>.json). It is validated first (schema + references + component parameters); invalid recipes are not saved and the issues are returned.", "input_schema": _schema({"name": _p("string", "Recipe name; main is the game itself"), "recipe": {"type": "object", "description": "The recipe (see the system prompt)"}}, ["recipe"])},
		{"name": "validate_recipe", "mutating": false, "description": "Validate a recipe object (or a saved one by name) without saving it.", "input_schema": _schema({"name": _p("string", "Saved recipe name"), "recipe": {"type": "object", "description": "Recipe to check"}})},
		{"name": "assemble_recipe", "mutating": true, "description": "Generate scenes, input map, autoloads and project settings from a recipe ('main' by default, or a template id when the project has none). Files edited by hand since the last assembly are kept unless overwrite=true.", "input_schema": _schema({"recipe": _p("string", "Recipe name (default main) or template id"), "overwrite": _p("boolean", "Replace hand-edited generated files"), "description": _p("string", "Free-text game description (asks the assistant to write the recipe first)")})},
		{"name": "import_model", "mutating": true, "description": "Copy an asset (.glb/.gltf/.png/.jpg/.webp/.svg/.wav/.ogg/.mp3) from ~/Studio or the project into the project and wait for the import. Returns the res:// path (and node/animation names for models).", "input_schema": _schema({"source_path": _p("string", "Source file under ~/Studio (Render/Sprite/Box exports) or inside the project"), "dest": _p("string", "Destination folder inside the project (default models/ for 3D, sprites/ for images, audio/ for sounds)")}, ["source_path"])},
		{"name": "run_project", "mutating": false, "description": "Run the game. With frames (e.g. 300) it runs headless for that many frames at 60 fps (optionally pressing keys via input like 'move_right@0.2-2.0,jump@0.6-0.7'), waits, and returns errors, output and a state report (score, health, player position). Without frames it opens the game in its own window and returns immediately.", "input_schema": _schema({"scene": _p("string", "Scene to run (default: main scene)"), "frames": _p("integer", "Run this many frames headless and wait", {"minimum": 1, "maximum": 20000}), "input": _p("string", "Scripted input: action@start-end,... in seconds"), "timeout_s": _p("integer", "Max seconds to wait with frames", {"minimum": 5, "maximum": 300})})},
		{"name": "stop_project", "mutating": false, "description": "Stop the running game.", "input_schema": _schema({})},
		{"name": "get_output_and_errors", "mutating": false, "description": "Output of the running or last game (stdout/stderr) with errors, script errors and warnings parsed out, plus errors seen by the editor itself.", "input_schema": _schema({"lines": _p("integer", "Number of output lines", {"minimum": 1, "maximum": 2000}), "errors_only": _p("boolean", "Only return problems")})},
		{"name": "game_screenshot", "mutating": false, "description": "Take a screenshot of the game. Captures the running game window if one is open, otherwise starts the game for a moment (needs a display). Returns the image.", "input_schema": _schema({"scene": _p("string", "Scene (default main scene)"), "frames": _p("integer", "Frames to run before capturing (default 90)", {"minimum": 2, "maximum": 3000}), "input": _p("string", "Scripted input before the capture, action@start-end,..."), "width": _p("integer", "Max image width (default 960)", {"minimum": 160, "maximum": 1920})})},
		{"name": "set_input_map", "mutating": true, "description": "Define input actions: {action: [key names]} with key names like 'A', 'Left', 'Space', 'Shift', 'Mouse:Left'. An empty list removes the action. Also stored in the recipe.", "input_schema": _schema({"actions": {"type": "object", "description": "Action -> key names"}}, ["actions"])},
		{"name": "set_export_preset", "mutating": true, "description": "Add or replace an export preset (linux, windows, macos, web) and write export_presets.cfg.", "input_schema": _schema({"name": _p("string", "Preset name"), "platform": _p("string", "linux | windows | macos | web", {"enum": ["linux", "windows", "macos", "web"]}), "path": _p("string", "Output path inside the project, e.g. build/game.x86_64"), "arch": _p("string", "x86_64 or arm64", {"enum": ["x86_64", "arm64"]}), "remove": _p("boolean", "Remove the preset instead")}, ["platform"])},
		{"name": "history_list", "mutating": false, "model": false, "description": "List undo checkpoints.", "input_schema": _schema({})},
		{"name": "history_undo", "mutating": false, "model": false, "description": "Undo the last request (or a given checkpoint id).", "input_schema": _schema({"id": {"type": "string"}})},
		{"name": "history_redo", "mutating": false, "model": false, "description": "Redo an undone checkpoint.", "input_schema": _schema({"id": {"type": "string"}})},
	]
	return _specs


## Tool definitions in the Anthropic messages format.
func anthropic_tools() -> Array:
	var out: Array = []
	for s in tool_specs():
		if s.get("model", true):
			out.append({"name": s["name"], "description": s["description"], "input_schema": s["input_schema"]})
	return out


func spec_for(tool_name: String) -> Dictionary:
	for s in tool_specs():
		if s["name"] == tool_name:
			return s
	return {}


func is_mutating(tool_name: String) -> bool:
	return bool(spec_for(tool_name).get("mutating", false))


func tool_for_rpc(method: String) -> String:
	return RPC.get(method.trim_prefix("engine."), "")


## Scripts that the model writes and runs need review when the dock's Review switch is on.
func needs_review(tool_name: String, args: Dictionary) -> bool:
	if tool_name in ["create_script", "edit_script"]:
		return true
	if tool_name == "write_file":
		return str(args.get("path", "")).ends_with(".gd")
	return false


# ================================================================== helpers

func err(message: String, code: int = ERR_OTHER, extra: Dictionary = {}) -> Dictionary:
	var d := {"ok": false, "error": message, "code": code}
	d.merge(extra, true)
	return d


func _ei() -> Object:
	if plugin != null and Engine.is_editor_hint() and Engine.has_singleton("EditorInterface"):
		return Engine.get_singleton("EditorInterface")
	return null


## Confine a user-supplied path to the project. Returns {ok, res, rel} or an error dict.
func resolve(path: String, write: bool = false) -> Dictionary:
	var p := path.strip_edges()
	if p == "" or p.to_utf8_buffer().has(0):
		return err("empty path", ERR_PATH)
	if p.begins_with("res://"):
		p = p.substr(6)
	elif p.begins_with("user://"):
		return err("only project (res://) paths are allowed", ERR_PATH)
	p = p.replace("\\", "/")
	if p.begins_with("/") or p.begins_with("~") or (p.length() > 1 and p[1] == ":") or p.contains("://"):
		return err("absolute paths are not allowed: " + path, ERR_PATH)
	var parts: Array = []
	for part in p.split("/", false):
		if part == "..":
			return err("'..' is not allowed in paths: " + path, ERR_PATH)
		if part != ".":
			parts.append(part)
	if not parts.is_empty() and HIDDEN_ROOTS.has(parts[0]):
		return err("%s is not accessible" % parts[0], ERR_PATH)
	if write and parts.size() >= 2 and parts[0] == "addons" and parts[1] == "amerika_engine":
		return err("the Engine plugin files are read-only", ERR_PATH)
	if write and parts.size() == 1 and parts[0] in ["project.godot", "override.cfg"]:
		return err("%s cannot be written directly; use set_input_map / assemble_recipe" % parts[0], ERR_PATH)
	var da := DirAccess.open("res://")
	var cur := "res://"
	for part in parts:
		cur = cur.path_join(part)
		if da != null and da.is_link(cur):
			return err("symbolic links are not allowed: " + cur, ERR_PATH)
	var res := "res://" + "/".join(PackedStringArray(parts))
	return {"ok": true, "res": res, "rel": "/".join(PackedStringArray(parts)), "ext": res.get_extension().to_lower()}


func _json_pretty(v: Variant) -> String:
	return JSON.stringify(v, "  ") + "\n"


func _read_json(path: String) -> Variant:
	if not FileAccess.file_exists(path):
		return null
	return JSON.parse_string(FileAccess.get_file_as_string(path))


func _write_text(path: String, text: String) -> int:
	history.record(path)
	DirAccess.make_dir_recursive_absolute(path.get_base_dir())
	var f := FileAccess.open(path, FileAccess.WRITE)
	if f == null:
		return FileAccess.get_open_error()
	f.store_string(text)
	f.close()
	_editor_file_changed(path)
	return OK


func _editor_file_changed(path: String) -> void:
	var ei := _ei()
	if ei == null:
		return
	var fs: Object = ei.call("get_resource_filesystem")
	fs.call("update_file", path)
	if path.ends_with(".tscn") and (ei.call("get_open_scenes") as PackedStringArray).has(path):
		ei.call("reload_scene_from_path", path)


func _on_history_restored(changed: Array) -> void:
	for p in changed:
		_editor_file_changed(str(p))
	var ei := _ei()
	if ei != null:
		(ei.call("get_resource_filesystem") as Object).call("scan")


func _wait_frames(n: int = 1) -> void:
	for i in range(n):
		await tree.process_frame


func _wait_seconds(sec: float) -> void:
	await tree.create_timer(sec).timeout


func _scan_editor() -> void:
	var ei := _ei()
	if ei == null:
		return
	var fs: Object = ei.call("get_resource_filesystem")
	fs.call("scan")
	await _wait_frames(2)
	var t0 := Time.get_ticks_msec()
	while bool(fs.call("is_scanning")) and Time.get_ticks_msec() - t0 < 20000:
		await _wait_frames(2)


## Import new assets outside the editor by running a headless import in a child process (blocking).
func _import_blocking() -> bool:
	var out: Array = []
	var code := OS.execute(OS.get_executable_path(), ["--headless", "--path", ProjectSettings.globalize_path("res://").rstrip("/"), "--import"], out, true)
	return code == 0


func project_summary() -> String:
	var info := _project_info({})
	var lines: Array = ["name: %s" % info["name"], "main scene: %s" % info["main_scene"], "godot: %s" % info["godot_version"]]
	if info["recipe"]["present"]:
		lines.append("recipe: genre %s, %s" % [info["recipe"]["genre"], "valid" if info["recipe"]["valid"] else "HAS ISSUES"])
	else:
		lines.append("recipe: none yet")
	return "\n".join(PackedStringArray(lines))


# ================================================================== dispatch

## Run a tool by model-facing name. Always `await` this.
func call_tool(tool_name: String, args: Dictionary) -> Dictionary:
	var spec := spec_for(tool_name)
	if spec.is_empty():
		return err("unknown tool '%s'" % tool_name, ERR_METHOD)
	var problems := _check_args(spec["input_schema"], args)
	if not problems.is_empty():
		return err("invalid arguments: " + "; ".join(PackedStringArray(problems)), ERR_PARAMS)
	var own := false
	if spec["mutating"] and not history.active():
		history.begin("engine." + tool_name)
		own = true
	var result: Dictionary = await _dispatch(tool_name, args)
	if own:
		finish_session()
	return result


## End the current history session and register it with the editor's undo stack.
func finish_session() -> Dictionary:
	var manifest := history.end()
	if manifest.is_empty():
		return manifest
	if plugin != null and plugin.has_method("get_undo_redo"):
		var ur: Object = plugin.call("get_undo_redo")
		if ur != null:
			ur.call("create_action", "Amerika: " + str(manifest["label"]).left(60))
			ur.call("add_do_method", history, "redo_session", manifest["id"])
			ur.call("add_undo_method", history, "undo_session", manifest["id"])
			ur.call("commit_action", false)
	return manifest


func _check_args(schema: Dictionary, args: Dictionary) -> Array:
	var problems: Array = []
	for r in schema.get("required", []):
		if not args.has(r):
			problems.append('missing "%s"' % r)
	var props: Dictionary = schema.get("properties", {})
	for k in args.keys():
		if not props.has(k):
			problems.append('unknown argument "%s"' % k)
			continue
		var t: String = str(props[k].get("type", ""))
		var v: Variant = args[k]
		var ok := true
		match t:
			"string":
				ok = v is String
			"integer":
				ok = typeof(v) == TYPE_INT or (typeof(v) == TYPE_FLOAT and is_equal_approx(v, roundf(v)))
			"number":
				ok = typeof(v) == TYPE_INT or typeof(v) == TYPE_FLOAT
			"boolean":
				ok = typeof(v) == TYPE_BOOL
			"object":
				ok = v is Dictionary
			"array":
				ok = v is Array
		if not ok:
			problems.append('"%s" must be %s' % [k, t])
	return problems


func _dispatch(tool_name: String, a: Dictionary) -> Dictionary:
	match tool_name:
		"project_info":
			return _project_info(a)
		"list_files":
			return _list_files(a)
		"read_file":
			return _read_file(a)
		"write_file":
			return await _write_file(a)
		"create_scene":
			return await _create_scene(a)
		"describe_scene":
			return _describe_scene(a)
		"add_node":
			return await _add_node(a)
		"set_property":
			return await _set_property(a)
		"attach_script":
			return await _attach_script(a)
		"create_script":
			return await _create_script(a)
		"edit_script":
			return await _edit_script(a)
		"get_recipe":
			return _get_recipe(a)
		"set_recipe":
			return _set_recipe(a)
		"validate_recipe":
			return _validate_recipe(a)
		"assemble_recipe":
			return await _assemble_recipe(a)
		"import_model":
			return await _import_model(a)
		"run_project":
			return await _run_project(a)
		"stop_project":
			return runner.stop()
		"get_output_and_errors":
			return _get_output(a)
		"game_screenshot":
			return await _game_screenshot(a)
		"set_input_map":
			return _set_input_map(a)
		"set_export_preset":
			return _set_export_preset(a)
		"history_list":
			return {"ok": true, "sessions": history.list_sessions()}
		"history_undo", "history_redo":
			var id: String = str(a.get("id", ""))
			if id == "":
				var all := history.list_sessions()
				if all.is_empty():
					return err("nothing to undo")
				id = str(all[all.size() - 1]["id"])
			return history.restore(id, tool_name == "history_redo")
	return err("unhandled tool " + tool_name, ERR_METHOD)


# ================================================================== project / files

func _recipe_state() -> Dictionary:
	var out := {"present": false, "genre": "", "valid": false, "name": ""}
	var r: Variant = _read_json("res://amerika_recipe.json")
	if r is Dictionary:
		out["present"] = true
		out["genre"] = str(r.get("genre", ""))
		out["name"] = str(r.get("name", ""))
		var issues: Array = RecipeScript.new().validate(r, "res://")
		out["valid"] = RecipeScript.new().errors_of(issues).is_empty()
	return out


func _project_info(_a: Dictionary) -> Dictionary:
	var autoloads := {}
	for p in ProjectSettings.get_property_list():
		var pname: String = p["name"]
		if pname.begins_with("autoload/"):
			autoloads[pname.trim_prefix("autoload/")] = str(ProjectSettings.get_setting(pname)).trim_prefix("*")
	var open_scenes: Array = []
	var ei := _ei()
	if ei != null:
		for s in (ei.call("get_open_scenes") as PackedStringArray):
			open_scenes.append(s)
	var v := Engine.get_version_info()
	return {
		"ok": true,
		"name": str(ProjectSettings.get_setting("application/config/name", "")),
		"path": ProjectSettings.globalize_path("res://").rstrip("/"),
		"godot_version": "%d.%d.%d" % [v["major"], v["minor"], v["patch"]],
		"main_scene": str(ProjectSettings.get_setting("application/run/main_scene", "")),
		"autoloads": autoloads,
		"open_scenes": open_scenes,
		"running": runner.running(),
		"editor": ei != null,
		"display": DisplayServer.get_name(),
		"renderer": str(ProjectSettings.get_setting("rendering/renderer/rendering_method", "forward_plus")),
		"recipe": _recipe_state(),
	}


func _list_files(a: Dictionary) -> Dictionary:
	var r := resolve(str(a.get("path", ".")), false) if str(a.get("path", ".")) not in [".", "", "res://"] else {"ok": true, "res": "res://", "rel": ""}
	if not r["ok"]:
		return r
	var limit := int(a.get("limit", 500))
	var out: Array = []
	var truncated := _walk(r["res"], bool(a.get("recursive", false)), limit, out)
	return {"ok": true, "path": r["res"], "entries": out, "truncated": truncated}


func _walk(dir: String, recursive: bool, limit: int, out: Array) -> bool:
	var d := DirAccess.open(dir)
	if d == null:
		return false
	var dirs := Array(d.get_directories())
	dirs.sort()
	var files := Array(d.get_files())
	files.sort()
	for n in dirs:
		if HIDDEN_ROOTS.has(n) and dir == "res://":
			continue
		if out.size() >= limit:
			return true
		out.append({"path": dir.path_join(n), "type": "dir"})
		if recursive and _walk(dir.path_join(n), true, limit, out):
			return true
	for n in files:
		if n.ends_with(".import") or n.ends_with(".uid"):
			continue
		if out.size() >= limit:
			return true
		var p := dir.path_join(n)
		var fh := FileAccess.open(p, FileAccess.READ)
		out.append({"path": p, "type": "file", "size": fh.get_length() if fh != null else 0})
	return false


func _read_file(a: Dictionary) -> Dictionary:
	var r := resolve(str(a["path"]), false)
	if not r["ok"]:
		return r
	if not READ_EXT.has(r["ext"]):
		return err("'.%s' files are not readable as text (allowed: %s)" % [r["ext"], ", ".join(PackedStringArray(READ_EXT))])
	if not FileAccess.file_exists(r["res"]):
		return err("no such file: " + r["res"])
	var f := FileAccess.open(r["res"], FileAccess.READ)
	if f == null:
		return err("cannot open %s (%s)" % [r["res"], error_string(FileAccess.get_open_error())])
	var size := f.get_length()
	var cap := int(a.get("max_bytes", 200000))
	var buf := f.get_buffer(mini(size, cap))
	return {"ok": true, "path": r["res"], "content": buf.get_string_from_utf8(), "size": size, "truncated": size > cap}


func _write_file(a: Dictionary) -> Dictionary:
	var r := resolve(str(a["path"]), true)
	if not r["ok"]:
		return r
	if not WRITE_EXT.has(r["ext"]):
		return err("'.%s' is not an allowed file type for write_file (allowed: %s)" % [r["ext"], ", ".join(PackedStringArray(WRITE_EXT))])
	var content: String = a["content"]
	if content.length() > MAX_FILE:
		return err("content is larger than %d bytes" % MAX_FILE)
	var existed := FileAccess.file_exists(r["res"])
	if existed and not bool(a.get("overwrite", false)):
		return err("%s already exists; pass overwrite=true to replace it (the previous version is kept in the undo history)" % r["res"])
	if r["ext"] == "gd" and not bool(a.get("allow_errors", false)):
		var chk := scripts.check(content, r["res"])
		if not chk["ok"]:
			return err("GDScript does not compile; nothing was written:\n" + scripts.format(chk["errors"]), ERR_OTHER, {"errors": chk["errors"]})
	if r["ext"] == "json" and JSON.parse_string(content) == null and content.strip_edges() != "null":
		return err("content is not valid JSON; nothing was written")
	var e := _write_text(r["res"], content)
	if e != OK:
		return err("could not write %s (%s)" % [r["res"], error_string(e)])
	return {"ok": true, "path": r["res"], "bytes": content.to_utf8_buffer().size(), "overwrote": existed}


# ================================================================== scenes

func _load_scene(res: String) -> PackedScene:
	return ResourceLoader.load(res, "PackedScene", ResourceLoader.CACHE_MODE_REPLACE) as PackedScene


func _save_scene(root: Node, res: String) -> Dictionary:
	var ps := PackedScene.new()
	var e := ps.pack(root)
	if e != OK:
		return err("could not pack the scene (%s)" % error_string(e))
	history.record(res)
	DirAccess.make_dir_recursive_absolute(res.get_base_dir())
	e = ResourceSaver.save(ps, res)
	if e != OK:
		return err("could not save %s (%s)" % [res, error_string(e)])
	_editor_file_changed(res)
	return {"ok": true}


func _node_class_ok(type: String) -> bool:
	return ClassDB.class_exists(type) and ClassDB.is_parent_class(type, "Node") and ClassDB.can_instantiate(type)


## Convert a JSON-ish value to what `node.<prop>` expects.
func convert_value(node: Object, prop: String, v: Variant) -> Dictionary:
	var target_type := TYPE_NIL
	var hint_class := ""
	if prop.contains(":"):
		var cur: Variant = node.get_indexed(NodePath(prop))
		target_type = typeof(cur)
	else:
		for p in node.get_property_list():
			if p["name"] == prop:
				target_type = p["type"]
				hint_class = str(p.get("class_name", ""))
				break
		if target_type == TYPE_NIL and not (prop in node):
			return err("%s has no property '%s'" % [node.get_class(), prop])
	if prop == "script":
		if v is String and FileAccess.file_exists(v):
			return {"ok": true, "value": load(v)}
		return err("script must be the path of an existing .gd file")
	match target_type:
		TYPE_VECTOR2:
			if v is Array and v.size() == 2:
				return {"ok": true, "value": Vector2(v[0], v[1])}
		TYPE_VECTOR2I:
			if v is Array and v.size() == 2:
				return {"ok": true, "value": Vector2i(int(v[0]), int(v[1]))}
		TYPE_VECTOR3:
			if v is Array and v.size() == 3:
				return {"ok": true, "value": Vector3(v[0], v[1], v[2])}
		TYPE_VECTOR3I:
			if v is Array and v.size() == 3:
				return {"ok": true, "value": Vector3i(int(v[0]), int(v[1]), int(v[2]))}
		TYPE_RECT2:
			if v is Array and v.size() == 4:
				return {"ok": true, "value": Rect2(v[0], v[1], v[2], v[3])}
		TYPE_COLOR:
			if v is String and (v.begins_with("#") or Color.html_is_valid(v) or v.is_valid_html_color()):
				return {"ok": true, "value": Color(v)}
			if v is Array and v.size() >= 3:
				return {"ok": true, "value": Color(v[0], v[1], v[2], v[3] if v.size() > 3 else 1.0)}
			if v is String and Color.from_string(v, Color(-1, -1, -1)) != Color(-1, -1, -1):
				return {"ok": true, "value": Color.from_string(v, Color.WHITE)}
		TYPE_INT:
			if typeof(v) == TYPE_FLOAT or typeof(v) == TYPE_INT or typeof(v) == TYPE_BOOL:
				return {"ok": true, "value": int(v)}
		TYPE_FLOAT:
			if typeof(v) == TYPE_FLOAT or typeof(v) == TYPE_INT:
				return {"ok": true, "value": float(v)}
		TYPE_BOOL:
			if typeof(v) == TYPE_BOOL:
				return {"ok": true, "value": v}
		TYPE_STRING:
			return {"ok": true, "value": str(v)}
		TYPE_STRING_NAME:
			return {"ok": true, "value": StringName(str(v))}
		TYPE_NODE_PATH:
			return {"ok": true, "value": NodePath(str(v))}
		TYPE_OBJECT:
			if v == null:
				return {"ok": true, "value": null}
			if v is String and v.begins_with("res://"):
				if not ResourceLoader.exists(v):
					return err("resource not found: " + v)
				return {"ok": true, "value": load(v)}
			if v is String and ClassDB.class_exists(v) and ClassDB.is_parent_class(v, "Resource") and ClassDB.can_instantiate(v):
				return {"ok": true, "value": ClassDB.instantiate(v)}
		TYPE_PACKED_STRING_ARRAY:
			if v is Array:
				return {"ok": true, "value": PackedStringArray(v)}
		TYPE_PACKED_VECTOR2_ARRAY:
			if v is Array:
				var pts := PackedVector2Array()
				for i in range(0, v.size() - 1, 2):
					pts.append(Vector2(v[i], v[i + 1]))
				return {"ok": true, "value": pts}
		TYPE_ARRAY, TYPE_DICTIONARY:
			return {"ok": true, "value": v}
	if v is String and target_type != TYPE_STRING:
		var parsed: Variant = str_to_var(v)
		if parsed != null:
			return {"ok": true, "value": parsed}
	if target_type == TYPE_NIL:
		return {"ok": true, "value": v}
	return err("cannot convert %s to %s for '%s'" % [JSON.stringify(v), type_string(target_type), prop])


func _apply_props(node: Node, props: Dictionary) -> Dictionary:
	for k in props.keys():
		var c := convert_value(node, str(k), props[k])
		if not c["ok"]:
			return c
		node.set_indexed(NodePath(str(k)), c["value"])
	return {"ok": true}


func _create_scene(a: Dictionary) -> Dictionary:
	var r := resolve(str(a["path"]), true)
	if not r["ok"]:
		return r
	if r["ext"] != "tscn":
		return err("scene paths must end in .tscn")
	if FileAccess.file_exists(r["res"]) and not bool(a.get("overwrite", false)):
		return err("%s already exists; pass overwrite=true to replace it" % r["res"])
	if a.has("description") and not a.has("nodes"):
		return await _delegate("Create the scene %s with root type %s. It should contain: %s" % [r["res"], a.get("root_type", "Node2D"), a["description"]])
	var root_type := str(a.get("root_type", "Node2D"))
	if not _node_class_ok(root_type):
		return err("'%s' is not a Node class you can instantiate" % root_type)
	var root: Node = ClassDB.instantiate(root_type)
	root.name = str(a.get("root_name", r["res"].get_file().get_basename().capitalize().replace(" ", "")))
	var added: Array = []
	for n in a.get("nodes", []):
		if not (n is Dictionary) or not n.has("type") or not n.has("name"):
			root.free()
			return err("each node needs name and type")
		if not _node_class_ok(str(n["type"])):
			root.free()
			return err("'%s' is not a Node class you can instantiate" % n["type"])
		var parent: Node = root.get_node_or_null(str(n.get("parent", "."))) if str(n.get("parent", ".")) != "." else root
		if parent == null:
			root.free()
			return err("parent '%s' of node '%s' does not exist (parents must come first)" % [n.get("parent"), n["name"]])
		var node: Node = ClassDB.instantiate(str(n["type"]))
		node.name = str(n["name"])
		parent.add_child(node)
		node.owner = root
		var pr := _apply_props(node, n.get("properties", {}))
		if not pr["ok"]:
			root.free()
			return pr
		if n.has("script"):
			var sr := convert_value(node, "script", n["script"])
			if not sr["ok"]:
				root.free()
				return sr
			node.set_script(sr["value"])
		added.append(node.name)
	var saved := _save_scene(root, r["res"])
	root.free()
	if not saved["ok"]:
		return saved
	return {"ok": true, "path": r["res"], "root": root_type, "nodes": added}


func _describe_scene(a: Dictionary) -> Dictionary:
	var r := resolve(str(a["path"]), false)
	if not r["ok"]:
		return r
	if not FileAccess.file_exists(r["res"]):
		return err("no such scene: " + r["res"])
	var ps := _load_scene(r["res"])
	if ps == null:
		return err("could not load %s as a scene" % r["res"])
	var st := ps.get_state()
	var by_path := {}
	var root_dict: Dictionary = {}
	var scripts_used: Array = []
	for i in range(st.get_node_count()):
		var d := {"name": str(st.get_node_name(i)), "type": str(st.get_node_type(i)), "children": []}
		var inst := st.get_node_instance(i)
		if inst != null:
			d["instance"] = inst.resource_path
			if d["type"] == "":
				d["type"] = "(instance)"
		var groups := st.get_node_groups(i)
		if not groups.is_empty():
			d["groups"] = Array(groups)
		var props := {}
		for k in range(st.get_node_property_count(i)):
			var pname := str(st.get_node_property_name(i, k))
			var val: Variant = st.get_node_property_value(i, k)
			if pname == "script" and val is Script:
				d["script"] = (val as Script).resource_path
				scripts_used.append(d["script"])
				continue
			props[pname] = _brief(val)
		if not props.is_empty():
			d["properties"] = props
		var npath := str(st.get_node_path(i))
		by_path[npath] = d
		if i == 0:
			root_dict = d
		else:
			var parent_path := str(st.get_node_path(i, true))
			if by_path.has(parent_path):
				by_path[parent_path]["children"].append(d)
			elif by_path.has("."):
				by_path["."]["children"].append(d)
	return {"ok": true, "path": r["res"], "tree": root_dict, "node_count": st.get_node_count(), "scripts": scripts_used}


func _brief(v: Variant) -> String:
	if v is Resource:
		var rp := (v as Resource).resource_path
		return "<%s%s>" % [(v as Resource).get_class(), (" " + rp) if rp != "" else ""]
	var s := var_to_str(v).replace("\n", " ")
	return s if s.length() <= 140 else s.left(137) + "..."


func _find_in_scene(root: Node, node_path: String) -> Node:
	if node_path in [".", "", root.name]:
		return root
	return root.get_node_or_null(node_path)


func _edit_scene(scene: String, editor: Callable) -> Dictionary:
	var r := resolve(scene, true)
	if not r["ok"]:
		return r
	if r["ext"] != "tscn" or not FileAccess.file_exists(r["res"]):
		return err("no such scene: " + str(scene))
	var ps := _load_scene(r["res"])
	if ps == null:
		return err("could not load " + r["res"])
	var root := ps.instantiate(PackedScene.GEN_EDIT_STATE_MAIN)
	if root == null:
		return err("could not instantiate " + r["res"])
	var result: Dictionary = editor.call(root)
	if result.get("ok", false):
		var saved := _save_scene(root, r["res"])
		if not saved["ok"]:
			result = saved
		else:
			result["scene"] = r["res"]
	root.free()
	return result


func _add_node(a: Dictionary) -> Dictionary:
	var type := str(a["type"])
	if not _node_class_ok(type):
		return err("'%s' is not a Node class you can instantiate" % type)
	return _edit_scene(str(a["scene"]), func(root: Node) -> Dictionary:
		var parent := _find_in_scene(root, str(a.get("parent", ".")))
		if parent == null:
			return err("parent '%s' not found in the scene" % a.get("parent", "."))
		if parent.get_node_or_null(str(a["name"])) != null:
			return err("'%s' already has a child named '%s'" % [parent.name, a["name"]])
		var node: Node = ClassDB.instantiate(type)
		node.name = str(a["name"])
		parent.add_child(node, true)
		node.owner = root
		var props: Dictionary = a.get("properties", {})
		var pr := _apply_props(node, props)
		if not pr["ok"]:
			return pr
		return {"ok": true, "node": str(root.get_path_to(node)), "type": type})


func _set_property(a: Dictionary) -> Dictionary:
	return _edit_scene(str(a["scene"]), func(root: Node) -> Dictionary:
		var node := _find_in_scene(root, str(a["node"]))
		if node == null:
			return err("node '%s' not found in the scene" % a["node"])
		var c := convert_value(node, str(a["property"]), a["value"])
		if not c["ok"]:
			return c
		node.set_indexed(NodePath(str(a["property"])), c["value"])
		return {"ok": true, "node": str(a["node"]), "property": a["property"], "value": _brief(c["value"])})


func _attach_script(a: Dictionary) -> Dictionary:
	var sr := resolve(str(a["script"]), false)
	if not sr["ok"]:
		return sr
	if sr["ext"] != "gd" or not FileAccess.file_exists(sr["res"]):
		return err("script not found or not a .gd file: " + str(a["script"]))
	return _edit_scene(str(a["scene"]), func(root: Node) -> Dictionary:
		var node := _find_in_scene(root, str(a["node"]))
		if node == null:
			return err("node '%s' not found in the scene" % a["node"])
		var script := ResourceLoader.load(sr["res"], "Script", ResourceLoader.CACHE_MODE_REPLACE) as Script
		if script == null:
			return err("script failed to load (does it have parse errors?): " + sr["res"])
		node.set_script(script)
		return {"ok": true, "node": str(a["node"]), "script": sr["res"]})


# ================================================================== scripts

func _create_script(a: Dictionary) -> Dictionary:
	var r := resolve(str(a["path"]), true)
	if not r["ok"]:
		return r
	if r["ext"] != "gd":
		return err("script paths must end in .gd")
	if FileAccess.file_exists(r["res"]) and not bool(a.get("overwrite", false)):
		return err("%s already exists; use edit_script, or pass overwrite=true" % r["res"])
	var code := str(a.get("code", ""))
	if code == "":
		if a.has("description"):
			return await _delegate("Create the GDScript %s (extends %s). It should: %s" % [r["res"], a.get("extends", "Node"), a["description"]])
		code = "extends %s\n\n\nfunc _ready() -> void:\n\tpass\n" % str(a.get("extends", "Node"))
	var chk := scripts.check(code, r["res"])
	if not chk["ok"]:
		return err("GDScript does not compile; nothing was written:\n" + scripts.format(chk["errors"]), ERR_OTHER, {"errors": chk["errors"]})
	var e := _write_text(r["res"], code)
	if e != OK:
		return err("could not write %s (%s)" % [r["res"], error_string(e)])
	return {"ok": true, "path": r["res"], "lines": code.count("\n") + 1}


func apply_edits(source: String, edits: Array) -> Dictionary:
	var text := source
	var n := 0
	for i in range(edits.size()):
		var e: Dictionary = edits[i]
		var old := str(e.get("old", ""))
		if old == "":
			return {"ok": false, "error": "edit %d: 'old' is empty" % i}
		var count := text.count(old)
		if count == 0:
			return {"ok": false, "error": "edit %d: the text to replace was not found (it must match exactly, including tabs): %s" % [i, old.left(80)]}
		if count > 1 and not bool(e.get("all", false)):
			return {"ok": false, "error": "edit %d: the text matches %d places; add more context or set all=true" % [i, count]}
		text = text.replace(old, str(e.get("new", ""))) if count > 1 else text.replace(old, str(e.get("new", "")))
		n += count
	return {"ok": true, "text": text, "replacements": n}


func _edit_script(a: Dictionary) -> Dictionary:
	var r := resolve(str(a["path"]), true)
	if not r["ok"]:
		return r
	if r["ext"] != "gd" or not FileAccess.file_exists(r["res"]):
		return err("no such script: " + str(a["path"]))
	if not a.has("edits"):
		if a.has("instruction"):
			return await _delegate("Edit the script %s: %s" % [r["res"], a["instruction"]])
		return err("give edits [{old,new}] (or an instruction)")
	var source := FileAccess.get_file_as_string(r["res"])
	var patched := apply_edits(source, a["edits"])
	if not patched["ok"]:
		return err(str(patched["error"]))
	var chk := scripts.check(patched["text"], r["res"])
	if not chk["ok"]:
		return err("the edited script does not compile; the file was left untouched:\n" + scripts.format(chk["errors"]), ERR_OTHER, {"errors": chk["errors"]})
	var e := _write_text(r["res"], patched["text"])
	if e != OK:
		return err("could not write %s (%s)" % [r["res"], error_string(e)])
	return {"ok": true, "path": r["res"], "replacements": patched["replacements"]}


func _delegate(prompt: String) -> Dictionary:
	if ai == null:
		return err("the assistant is not available in this context; give explicit code/edits instead", ERR_NOT_READY)
	if bool(ai.get("busy")):
		return err("the assistant is already working on a request; call this tool with explicit arguments instead", ERR_BUSY)
	var res: Dictionary = await ai.call("run_prompt", prompt)
	res["delegated"] = true
	return res


# ================================================================== recipes

func template_dirs() -> Array:
	var dirs: Array = []
	var env := OS.get_environment("AMERIKA_ENGINE_TEMPLATES")
	if env != "":
		dirs.append(env)
	dirs.append("/usr/share/amerika-engine/templates")
	dirs.append(ProjectSettings.globalize_path("res://addons/amerika_engine/templates"))
	return dirs


func list_templates() -> Array:
	var out: Array = []
	var seen := {}
	for base in template_dirs():
		var d := DirAccess.open(base)
		if d == null:
			continue
		var names := Array(d.get_directories())
		names.sort()
		for n in names:
			if seen.has(n) or not FileAccess.file_exists(base.path_join(n).path_join("amerika_recipe.json")):
				continue
			seen[n] = true
			var meta: Variant = _read_json(base.path_join(n).path_join("template.json"))
			out.append({"id": n, "title": meta.get("title", n) if meta is Dictionary else n, "genre": meta.get("genre", "") if meta is Dictionary else "", "description": meta.get("description", "") if meta is Dictionary else ""})
	return out


func _template_recipe(id: String) -> Variant:
	for base in template_dirs():
		var p: String = base.path_join(id).path_join("amerika_recipe.json")
		if FileAccess.file_exists(p):
			return JSON.parse_string(FileAccess.get_file_as_string(p))
	return null


func _recipe_path(name_: String) -> String:
	if name_ in ["", "main", "current", "amerika_recipe"]:
		return "res://amerika_recipe.json"
	return "res://recipes/%s.json" % name_


func _valid_recipe_name(name_: String) -> bool:
	var re := RegEx.new()
	re.compile("^[a-z0-9][a-z0-9_-]{0,40}$")
	return name_ in ["", "main", "current"] or re.search(name_) != null


func _get_recipe(a: Dictionary) -> Dictionary:
	var name_ := str(a.get("name", ""))
	var rec := RecipeScript.new()
	if name_ == "":
		var saved: Array = []
		var d := DirAccess.open("res://recipes")
		if d != null:
			for f in d.get_files():
				if f.ends_with(".json"):
					saved.append(f.get_basename())
		var out := {"ok": true, "templates": list_templates(), "saved": saved, "has_recipe": false}
		var cur: Variant = _read_json("res://amerika_recipe.json")
		if cur is Dictionary:
			out["has_recipe"] = true
			out["recipe"] = cur
			out["issues"] = rec.validate(cur, "res://")
		return out
	if not _valid_recipe_name(name_):
		return err("bad recipe name '%s'" % name_)
	var p := _recipe_path(name_)
	var data: Variant = _read_json(p)
	var source := p
	if data == null:
		data = _template_recipe(name_)
		source = "template:" + name_
	if not (data is Dictionary):
		return err("no recipe or template named '%s'" % name_)
	return {"ok": true, "name": name_, "source": source, "recipe": data, "issues": rec.validate(data, "res://")}


func _validate_recipe(a: Dictionary) -> Dictionary:
	var data: Variant = a.get("recipe")
	if data == null and a.has("name"):
		data = _read_json(_recipe_path(str(a["name"])))
	if not (data is Dictionary):
		data = _read_json("res://amerika_recipe.json")
	if not (data is Dictionary):
		return err("no recipe to validate")
	var rec := RecipeScript.new()
	var issues: Array = rec.validate(data, "res://")
	return {"ok": rec.errors_of(issues).is_empty(), "issues": issues}


func _set_recipe(a: Dictionary) -> Dictionary:
	var name_ := str(a.get("name", "main"))
	if not _valid_recipe_name(name_):
		return err("recipe names use lowercase letters, digits, - and _")
	var data: Dictionary = a["recipe"]
	var rec := RecipeScript.new()
	var issues: Array = rec.validate(data, "res://")
	var errors := rec.errors_of(issues)
	if not errors.is_empty():
		return err("the recipe is invalid; nothing was saved", ERR_PARAMS, {"issues": issues})
	var p := _recipe_path(name_)
	var e := _write_text(p, _json_pretty(data))
	if e != OK:
		return err("could not write %s (%s)" % [p, error_string(e)])
	return {"ok": true, "path": p, "issues": issues, "next": "assemble_recipe" if name_ in ["main", "current"] else ""}


func _assemble_recipe(a: Dictionary) -> Dictionary:
	var name_ := str(a.get("recipe", "main"))
	if name_ == "" and a.has("description"):
		name_ = "main"
	var data: Variant = _read_json(_recipe_path(name_))
	var from_template := ""
	if data == null:
		if a.has("description") and not a.has("recipe"):
			return await _delegate("Write the project's amerika_recipe.json (set_recipe, name main) for this game and assemble it: " + str(a["description"]))
		data = _template_recipe(name_)
		from_template = name_
	if not (data is Dictionary):
		return err("no recipe '%s' in the project and no such template. Use get_recipe to see templates, then set_recipe." % name_)
	if from_template != "":
		var e := _write_text("res://amerika_recipe.json", _json_pretty(data))
		if e != OK:
			return err("could not write the recipe (%s)" % error_string(e))
	var report: Dictionary = Assembler.new().assemble(data, {"overwrite": bool(a.get("overwrite", false)), "before_write": history.record})
	if not report["ok"]:
		report["error"] = "assembly failed: " + "; ".join(PackedStringArray(report["errors"]))
		report["code"] = ERR_PARAMS
		return report
	await _scan_editor()
	var load_errors: Array = []
	for f in report["files"]:
		if str(f).ends_with(".tscn"):
			var res := ResourceLoader.load(str(f), "", ResourceLoader.CACHE_MODE_REPLACE)
			if res == null:
				load_errors.append("could not load " + str(f))
	report["scene_load_errors"] = load_errors
	if from_template != "":
		report["from_template"] = from_template
	report["next"] = "run_project with frames to check for errors, then game_screenshot"
	return report


# ================================================================== assets

func studio_root() -> String:
	var env := OS.get_environment("AMERIKA_STUDIO_DIR")
	if env != "":
		return env
	return OS.get_environment("HOME").path_join("Studio")


func _real(path: String) -> String:
	return path.simplify_path()


func _path_has_link(abs_path: String) -> bool:
	var parts := abs_path.split("/", false)
	var cur := "/"
	for part in parts:
		cur = cur.path_join(part)
		var da := DirAccess.open(cur.get_base_dir())
		if da != null and da.is_link(cur):
			return true
	return false


func _import_model(a: Dictionary) -> Dictionary:
	var src := _real(str(a["source_path"]).replace("~", OS.get_environment("HOME")))
	if src.begins_with("res://"):
		src = ProjectSettings.globalize_path(src)
	if not src.begins_with("/"):
		src = ProjectSettings.globalize_path("res://").path_join(src)
	src = _real(src)
	var allowed_roots := [_real(studio_root()), _real(ProjectSettings.globalize_path("res://").rstrip("/"))]
	var inside := false
	for root_dir in allowed_roots:
		if src.begins_with(str(root_dir) + "/"):
			inside = true
	if not inside:
		return err("source must be under %s or inside the project" % studio_root(), ERR_PATH)
	if _path_has_link(src):
		return err("symbolic links are not followed", ERR_PATH)
	var ext := src.get_extension().to_lower()
	if not ASSET_EXT.has(ext):
		return err("'.%s' is not an importable asset type (allowed: %s)" % [ext, ", ".join(PackedStringArray(ASSET_EXT))])
	if not FileAccess.file_exists(src):
		return err("no such file: " + src)
	var default_dest := "models" if ext in ["glb", "gltf", "bin"] else ("audio" if ext in ["wav", "ogg", "mp3"] else "sprites")
	var dr := resolve(str(a.get("dest", default_dest)), true)
	if not dr["ok"]:
		return dr
	var to_copy: Array = [src]
	if ext == "gltf":
		var j: Variant = JSON.parse_string(FileAccess.get_file_as_string(src))
		if j is Dictionary:
			for key in ["buffers", "images"]:
				for item in j.get(key, []):
					var uri := str(item.get("uri", ""))
					if uri != "" and not uri.begins_with("data:") and not uri.contains("..") and not uri.begins_with("/"):
						to_copy.append(src.get_base_dir().path_join(uri))
	var imported: Array = []
	for s in to_copy:
		if not FileAccess.file_exists(s):
			return err("referenced file missing: " + s)
		var dest_res: String = dr["res"].path_join(str(s).trim_prefix(src.get_base_dir() + "/"))
		history.record(dest_res)
		DirAccess.make_dir_recursive_absolute(dest_res.get_base_dir())
		var e := DirAccess.copy_absolute(s, ProjectSettings.globalize_path(dest_res))
		if e != OK:
			return err("copy failed for %s (%s)" % [s, error_string(e)])
		imported.append(dest_res)
	var ei := _ei()
	if ei != null:
		await _scan_editor()
		var fs: Object = ei.call("get_resource_filesystem")
		fs.call("reimport_files", PackedStringArray(imported))
	else:
		_import_blocking()
	var main_res: String = imported[0]
	var result := {"ok": true, "path": main_res, "files": imported}
	if ext in ["glb", "gltf"]:
		var scene := ResourceLoader.load(main_res, "PackedScene", ResourceLoader.CACHE_MODE_REPLACE) as PackedScene
		if scene != null:
			var inst := scene.instantiate()
			var nodes: Array = []
			var anims: Array = []
			for n in inst.find_children("*", "", true, false):
				nodes.append("%s (%s)" % [inst.get_path_to(n), n.get_class()])
				if n is AnimationPlayer:
					anims.append_array(Array((n as AnimationPlayer).get_animation_list()))
			result["root_type"] = inst.get_class()
			result["nodes"] = nodes.slice(0, 60)
			result["animations"] = anims
			inst.free()
		else:
			result["warning"] = "the model was copied but did not import as a scene yet; try again in a moment"
	elif ext in ["png", "jpg", "jpeg", "webp"]:
		var img := Image.load_from_file(ProjectSettings.globalize_path(main_res))
		if img != null:
			result["size"] = [img.get_width(), img.get_height()]
	return result


# ================================================================== running

func _get_output(a: Dictionary) -> Dictionary:
	runner.poll()
	var n := int(a.get("lines", 150))
	var src := runner.snapshot(2000)
	var problems := runner.parse_problems(src)
	var out := {"ok": true, "running": runner.running(), "pid": runner.pid, "exit_code": runner.exit_code, "problems": problems.slice(maxi(0, problems.size() - 40))}
	if not bool(a.get("errors_only", false)):
		var texts: Array = []
		for l in src.slice(maxi(0, src.size() - n)):
			texts.append(l["text"])
		out["output"] = "\n".join(PackedStringArray(texts))
		if src.is_empty() and FileAccess.file_exists(Runner.LOG_PATH):
			out["output"] = FileAccess.get_file_as_string(Runner.LOG_PATH).right(20000)
			out["note"] = "from the previous session's run.log"
	if editor_log != null:
		var entries: Array = editor_log.get("entries")
		out["editor_errors"] = entries.slice(maxi(0, entries.size() - 30))
	return out


func _run_project(a: Dictionary) -> Dictionary:
	if runner.running():
		runner.stop()
	var scene := ""
	if a.has("scene"):
		var r := resolve(str(a["scene"]), false)
		if not r["ok"]:
			return r
		if not FileAccess.file_exists(r["res"]):
			return err("no such scene: " + r["res"])
		scene = r["res"]
	elif str(ProjectSettings.get_setting("application/run/main_scene", "")) == "":
		return err("the project has no main scene yet; assemble a recipe or create a scene and set it as main")
	var frames := int(a.get("frames", 0))
	var opts := {"scene": scene}
	var report_path := ""
	if frames > 0:
		report_path = ProjectSettings.globalize_path("res://.amerika/ctl/report.json")
		if FileAccess.file_exists(report_path):
			DirAccess.remove_absolute(report_path)
		opts.merge({"frames": frames, "input": str(a.get("input", "")), "headless": true, "report": report_path, "extra": ["--quit-after", str(frames + 600)]}, true)
	elif str(a.get("input", "")) != "":
		opts["input"] = str(a["input"])
	var started := runner.start(opts)
	if not started["ok"]:
		return err(started["error"])
	if frames == 0:
		return {"ok": true, "running": true, "pid": runner.pid, "headless": started["headless"], "hint": "use get_output_and_errors to read its output"}
	var timeout_ms := int(a.get("timeout_s", 60)) * 1000
	var t0 := Time.get_ticks_msec()
	while runner.running() and Time.get_ticks_msec() - t0 < timeout_ms:
		await _wait_seconds(0.05)
	var timed_out := runner.running()
	if timed_out:
		runner.stop()
	runner.poll()
	var src := runner.snapshot(2000)
	var problems := runner.parse_problems(src)
	var texts: Array = []
	for l in src.slice(maxi(0, src.size() - 40)):
		texts.append(l["text"])
	var res := {"ok": true, "finished": not timed_out, "exit_code": runner.exit_code, "frames": frames,
		"problems": problems.slice(0, 30), "problem_count": problems.size(), "output_tail": "\n".join(PackedStringArray(texts))}
	var rep: Variant = _read_json(report_path)
	if rep is Dictionary:
		res["report"] = rep
	if timed_out:
		res["warning"] = "the game did not finish within %d s and was stopped" % (timeout_ms / 1000)
	var errs := 0
	for p in problems:
		if p["kind"] == "error":
			errs += 1
	res["clean"] = errs == 0 and not timed_out and runner.exit_code == 0
	return res


func _png_result(path: String, max_w: int) -> Dictionary:
	var img := Image.load_from_file(path)
	if img == null or img.is_empty():
		return err("the screenshot could not be read")
	var size := [img.get_width(), img.get_height()]
	if img.get_width() > max_w:
		img.resize(max_w, int(float(img.get_height()) * max_w / img.get_width()), Image.INTERPOLATE_LANCZOS)
	var bytes := img.save_png_to_buffer()
	return {"ok": true, "size": size, "path": path, "images": [{"mime": "image/png", "base64": Marshalls.raw_to_base64(bytes)}]}


func _game_screenshot(a: Dictionary) -> Dictionary:
	_shot_counter += 1
	var dir := ProjectSettings.globalize_path("res://.amerika/shots")
	DirAccess.make_dir_recursive_absolute(dir)
	var target := dir.path_join("shot_%d_%d.png" % [Time.get_unix_time_from_system(), _shot_counter])
	var max_w := int(a.get("width", 960))
	if runner.running() and not a.has("frames") and not a.has("scene") and not a.has("input"):
		# capture the game window that is already open
		var req := runner.ctl_dir.path_join("shot.request")
		var done := runner.ctl_dir.path_join("shot.done")
		if FileAccess.file_exists(done):
			DirAccess.remove_absolute(done)
		var f := FileAccess.open(req, FileAccess.WRITE)
		if f == null:
			return err("could not talk to the running game")
		f.store_string(target)
		f.close()
		var t0 := Time.get_ticks_msec()
		while not FileAccess.file_exists(done) and Time.get_ticks_msec() - t0 < 8000 and runner.running():
			await _wait_seconds(0.1)
		if FileAccess.file_exists(done) and FileAccess.file_exists(target):
			return _png_result(target, max_w)
		return err("the running game did not answer; it may be headless (no renderer). Stop it and call game_screenshot again.")
	if not runner.has_display():
		return err("no display is available, so the game cannot render a screenshot here. Use run_project with frames and read the state report instead.", ERR_NOT_READY)
	var frames := int(a.get("frames", 90))
	var opts := {"headless": false, "frames": frames, "shot": target, "input": str(a.get("input", "")), "extra": ["--quit-after", str(frames + 900)]}
	if a.has("scene"):
		var r := resolve(str(a["scene"]), false)
		if not r["ok"]:
			return r
		opts["scene"] = r["res"]
	var started := runner.start(opts)
	if not started["ok"]:
		return err(started["error"])
	var t1 := Time.get_ticks_msec()
	while runner.running() and Time.get_ticks_msec() - t1 < 90000:
		await _wait_seconds(0.1)
	if runner.running():
		runner.stop()
	runner.poll()
	if not FileAccess.file_exists(target):
		var problems := runner.parse_problems(runner.snapshot(500))
		return err("no screenshot was produced", ERR_OTHER, {"problems": problems.slice(0, 15), "output_tail": runner.snapshot(20).map(func(l: Dictionary) -> String: return l["text"])})
	return _png_result(target, max_w)


# ================================================================== input / export

func _set_input_map(a: Dictionary) -> Dictionary:
	var actions: Dictionary = a["actions"]
	for k in actions.keys():
		if not (actions[k] is Array):
			return err("action '%s' must map to a list of key names" % k, ERR_PARAMS)
	history.record("res://project.godot")
	var res: Dictionary = InputMapper.new().apply(actions, true)
	var rcp: Variant = _read_json("res://amerika_recipe.json")
	if rcp is Dictionary:
		var inp: Dictionary = rcp.get("input", {})
		for k in actions.keys():
			inp[k] = actions[k]
		rcp["input"] = inp
		_write_text("res://amerika_recipe.json", _json_pretty(rcp))
	if res["error"] != "":
		return err("could not save project settings: " + str(res["error"]))
	return {"ok": true, "applied": res["applied"], "warnings": res["warnings"], "stored_in_recipe": rcp is Dictionary}


func _set_export_preset(a: Dictionary) -> Dictionary:
	var presets: Array = []
	var rcp: Variant = _read_json("res://amerika_recipe.json")
	var stored: Variant = rcp.get("export_presets") if rcp is Dictionary else _read_json("res://.amerika/export_presets.json")
	if stored is Array:
		presets = stored
	var name_ := str(a.get("name", a["platform"]))
	var kept: Array = []
	for p in presets:
		if str(p.get("name", p.get("platform"))) != name_:
			kept.append(p)
	if not bool(a.get("remove", false)):
		var p := {"name": name_, "platform": str(a["platform"])}
		if a.has("path"):
			var pr := resolve(str(a["path"]), true)
			if not pr["ok"]:
				return pr
			p["path"] = pr["rel"]
		if a.has("arch"):
			p["arch"] = str(a["arch"])
		kept.append(p)
	if rcp is Dictionary:
		rcp["export_presets"] = kept
		_write_text("res://amerika_recipe.json", _json_pretty(rcp))
	else:
		_write_text("res://.amerika/export_presets.json", _json_pretty(kept))
	var e := _write_text("res://export_presets.cfg", ExportPresets.new().render(kept))
	if e != OK:
		return err("could not write export_presets.cfg (%s)" % error_string(e))
	return {"ok": true, "presets": kept}
