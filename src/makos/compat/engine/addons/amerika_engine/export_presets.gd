extends RefCounted
## Renders export_presets.cfg for the platforms listed in a recipe (or set through the set_export_preset tool).
## Godot fills every option that is not written with its default, so only the essentials are emitted.

const PLATFORMS := {
	"linux": {"platform": "Linux", "ext": "x86_64", "options": {"binary_format/architecture": "x86_64", "binary_format/embed_pck": true}},
	"windows": {"platform": "Windows Desktop", "ext": "exe", "options": {"binary_format/architecture": "x86_64", "binary_format/embed_pck": true}},
	"macos": {"platform": "macOS", "ext": "zip", "options": {}},
	"web": {"platform": "Web", "ext": "html", "options": {}},
}


func render(presets: Array) -> String:
	var out := ""
	for i in range(presets.size()):
		var p: Dictionary = presets[i]
		var plat: Dictionary = PLATFORMS[p["platform"]].duplicate(true)
		var arch: String = str(p.get("arch", "x86_64"))
		if plat["options"].has("binary_format/architecture"):
			plat["options"]["binary_format/architecture"] = arch
		var nm: String = str(p.get("name", plat["platform"]))
		var path: String = str(p.get("path", "build/%s.%s" % [p["platform"], plat["ext"]]))
		out += "[preset.%d]\n\nname=%s\nplatform=%s\nrunnable=true\nadvanced_options=false\ndedicated_server=false\ncustom_features=\"\"\nexport_filter=\"all_resources\"\ninclude_filter=\"\"\nexclude_filter=\"\"\nexport_path=%s\n\n" % [
			i, JSON.stringify(nm), JSON.stringify(plat["platform"]), JSON.stringify(path)]
		out += "[preset.%d.options]\n\n" % i
		for k in plat["options"].keys():
			out += "%s=%s\n" % [k, var_to_str(plat["options"][k])]
		out += "\n"
	return out
