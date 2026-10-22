extends RefCounted
## Where the plugin talks to: the local Studio bridge. There is no API key anywhere in the plugin; the bridge adds it.
## The per-user token is read from $XDG_RUNTIME_DIR/amerika/studio-token (or AMERIKA_STUDIO_TOKEN_FILE for tests).
## Also writes the control-endpoint descriptor $XDG_RUNTIME_DIR/amerika/studio-engine.json (mode 0600).

const DEFAULT_URL := "http://127.0.0.1:18890"
const APP := "engine"


func base_url() -> String:
	var env := OS.get_environment("AMERIKA_STUDIO_URL")
	if env != "" and (env.begins_with("http://127.0.0.1:") or env.begins_with("http://localhost:") or env.begins_with("http://[::1]:")):
		return env.rstrip("/")
	var port := OS.get_environment("AMERIKA_STUDIO_PORT")
	if port.is_valid_int():
		return "http://127.0.0.1:" + port
	return DEFAULT_URL


func runtime_dir() -> String:
	var d := OS.get_environment("XDG_RUNTIME_DIR")
	return d.path_join("amerika") if d != "" else ""


func token_path() -> String:
	var env := OS.get_environment("AMERIKA_STUDIO_TOKEN_FILE")
	if env != "":
		return env
	var d := runtime_dir()
	return d.path_join("studio-token") if d != "" else ""


func read_token() -> String:
	var p := token_path()
	if p == "" or not FileAccess.file_exists(p):
		return ""
	return FileAccess.get_file_as_string(p).strip_edges()


func headers() -> PackedStringArray:
	return PackedStringArray([
		"Content-Type: application/json",
		"Authorization: Bearer " + read_token(),
		"X-Amerika-App: " + APP,
		"anthropic-version: 2023-06-01",
	])


func descriptor_path() -> String:
	var d := runtime_dir()
	return d.path_join("studio-engine.json") if d != "" else ""


## Write the descriptor with owner-only permissions (the file is created empty and chmod'ed before the token goes in).
func write_descriptor(port: int, token: String, version: String) -> bool:
	var path := descriptor_path()
	if path == "":
		return false
	DirAccess.make_dir_recursive_absolute(path.get_base_dir())
	var f := FileAccess.open(path, FileAccess.WRITE)
	if f == null:
		return false
	f.close()
	FileAccess.set_unix_permissions(path, FileAccess.UNIX_READ_OWNER | FileAccess.UNIX_WRITE_OWNER)
	f = FileAccess.open(path, FileAccess.WRITE)
	if f == null:
		return false
	f.store_string(JSON.stringify({"app": APP, "url": "http://127.0.0.1:%d" % port, "token": token, "pid": OS.get_process_id(), "version": version}))
	f.close()
	return true


func remove_descriptor() -> void:
	var path := descriptor_path()
	if path != "" and FileAccess.file_exists(path):
		DirAccess.remove_absolute(path)
