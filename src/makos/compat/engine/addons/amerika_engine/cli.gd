extends SceneTree
## Command line front end, used by the launcher, CI and the tests:
##   godot --headless --path <project> -s res://addons/amerika_engine/cli.gd -- assemble [--overwrite] [recipe.json]
##   godot --headless --path <project> -s res://addons/amerika_engine/cli.gd -- validate [recipe.json]
## Prints one line `AMERIKA_REPORT {json}` and exits non-zero on errors.

const Assembler := preload("res://addons/amerika_engine/recipe_assembler.gd")
const RecipeScript := preload("res://addons/amerika_engine/recipe.gd")


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	var cmd: String = args[0] if args.size() > 0 else "assemble"
	var path := "res://amerika_recipe.json"
	var overwrite := false
	for a in args.slice(1):
		if a == "--overwrite":
			overwrite = true
		elif not a.begins_with("--"):
			path = a if a.begins_with("res://") else "res://" + a
	if not FileAccess.file_exists(path):
		_done({"ok": false, "errors": ["recipe not found: " + path]}, 2)
		return
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if not (parsed is Dictionary):
		_done({"ok": false, "errors": ["recipe is not valid JSON: " + path]}, 2)
		return
	if cmd == "validate":
		var r := RecipeScript.new()
		var issues: Array = r.validate(parsed, "res://")
		var errs := r.errors_of(issues)
		_done({"ok": errs.is_empty(), "issues": issues}, 0 if errs.is_empty() else 1)
	else:
		var report: Dictionary = Assembler.new().assemble(parsed, {"overwrite": overwrite})
		_done(report, 0 if report["ok"] else 1)


func _done(report: Dictionary, code: int) -> void:
	print("AMERIKA_REPORT " + JSON.stringify(report))
	quit(code)
