extends RefCounted
## Git-free undo for everything the assistant writes. Each chat request (or each direct tool call) is a "session":
## before a file is first modified in a session its previous content is copied to
##   res://.amerika/history/<id>/before/<relative path>      (a marker file ".created" list says which files were new)
## and when the session ends the new content is copied to .../after/ so the whole request can be undone and redone.

const ROOT := "res://.amerika/history"
const KEEP := 40

var current_id: String = ""
var label: String = ""
var _touched: Dictionary = {} ## rel path -> existed_before (bool)
var _counter: int = 0
var on_restored: Callable = Callable() ## called with the list of res:// paths changed by undo/redo


func active() -> bool:
	return current_id != ""


func begin(session_label: String) -> String:
	if active():
		return current_id
	_counter += 1
	current_id = "%s_%03d" % [Time.get_datetime_string_from_system().replace(":", "").replace("-", "").replace("T", "-"), _counter]
	label = session_label
	_touched = {}
	DirAccess.make_dir_recursive_absolute("%s/%s/before" % [ROOT, current_id])
	return current_id


func _rel(path: String) -> String:
	return path.trim_prefix("res://")


## Call BEFORE modifying `path` (res://). Idempotent within a session.
func record(path: String) -> void:
	if not active():
		return
	var rel := _rel(path)
	if _touched.has(rel):
		return
	var existed := FileAccess.file_exists(path)
	_touched[rel] = existed
	if existed:
		var dest := "%s/%s/before/%s" % [ROOT, current_id, rel]
		DirAccess.make_dir_recursive_absolute(dest.get_base_dir())
		DirAccess.copy_absolute(path, dest)


## Finish the session. Returns {} when nothing changed, else the manifest.
func end() -> Dictionary:
	if not active():
		return {}
	var id := current_id
	current_id = ""
	if _touched.is_empty():
		_remove_dir("%s/%s" % [ROOT, id])
		return {}
	var files: Array = []
	for rel in _touched.keys():
		var existed: bool = _touched[rel]
		var now := FileAccess.file_exists("res://" + rel)
		if now:
			var dest := "%s/%s/after/%s" % [ROOT, id, rel]
			DirAccess.make_dir_recursive_absolute(dest.get_base_dir())
			DirAccess.copy_absolute("res://" + rel, dest)
		files.append({"path": "res://" + rel, "existed_before": existed, "exists_after": now})
	var manifest := {"id": id, "label": label, "time": Time.get_datetime_string_from_system(), "files": files}
	var f := FileAccess.open("%s/%s/manifest.json" % [ROOT, id], FileAccess.WRITE)
	if f != null:
		f.store_string(JSON.stringify(manifest, "\t"))
	_prune()
	return manifest


func list_sessions() -> Array:
	var out: Array = []
	var d := DirAccess.open(ROOT)
	if d == null:
		return out
	var names: Array = []
	for n in d.get_directories():
		names.append(n)
	names.sort()
	for n in names:
		var mf := "%s/%s/manifest.json" % [ROOT, n]
		if FileAccess.file_exists(mf):
			var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(mf))
			if parsed is Dictionary:
				out.append(parsed)
	return out


func last_session() -> Dictionary:
	var all := list_sessions()
	return all[all.size() - 1] if not all.is_empty() else {}


## Restore the files of a session to how they were before it (undo) or after it (redo).
func restore(id: String, redo: bool = false) -> Dictionary:
	var mf := "%s/%s/manifest.json" % [ROOT, id]
	if not FileAccess.file_exists(mf):
		return {"ok": false, "error": "unknown history entry " + id}
	var manifest: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(mf))
	var changed: Array = []
	for item in manifest["files"]:
		var path: String = item["path"]
		var rel := _rel(path)
		var want_exists: bool = item["exists_after"] if redo else item["existed_before"]
		if want_exists:
			var src := "%s/%s/%s/%s" % [ROOT, id, "after" if redo else "before", rel]
			if FileAccess.file_exists(src):
				DirAccess.make_dir_recursive_absolute(path.get_base_dir())
				DirAccess.copy_absolute(src, path)
				changed.append(path)
		elif FileAccess.file_exists(path):
			DirAccess.remove_absolute(path)
			changed.append(path)
	if on_restored.is_valid():
		on_restored.call(changed)
	return {"ok": true, "restored": changed, "label": manifest.get("label", "")}


## Editor undo/redo hooks (EditorUndoRedoManager calls these).
func undo_session(id: String) -> void:
	restore(id, false)


func redo_session(id: String) -> void:
	restore(id, true)


func _prune() -> void:
	var all := list_sessions()
	while all.size() > KEEP:
		var oldest: Dictionary = all.pop_front()
		_remove_dir("%s/%s" % [ROOT, oldest["id"]])


func _remove_dir(path: String) -> void:
	var d := DirAccess.open(path)
	if d == null:
		return
	d.include_hidden = true
	for f in d.get_files():
		d.remove(f)
	for sub in d.get_directories():
		_remove_dir(path + "/" + sub)
	DirAccess.remove_absolute(path)
