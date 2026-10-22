extends RefCounted
## Game Recipe validation. Mirrors amerika_engine/recipe.py (same error codes): JSON Schema subset + semantic checks.
## Usage: var issues: Array = Recipe.new().validate(recipe_dict)  -> [{code, path, message, severity}, ...]

const SCHEMA_PATH := "res://addons/amerika_engine/recipe.schema.json"
const COMPONENTS_PATH := "res://addons/amerika_engine/components/components.json"
const GAMEPLAY := ["platformer_2d", "topdown_2d", "third_person_3d", "first_person_3d"]
const DIMS := {"platformer_2d": "2d", "topdown_2d": "2d", "third_person_3d": "3d", "first_person_3d": "3d"}

var _schema: Dictionary = {}
var _components: Dictionary = {}


func _init() -> void:
	_schema = _load_json(SCHEMA_PATH)
	_components = _load_json(COMPONENTS_PATH).get("components", {})


func _load_json(path: String) -> Dictionary:
	if not FileAccess.file_exists(path):
		return {}
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	return parsed if parsed is Dictionary else {}


func components() -> Dictionary:
	return _components


func _issue(code: String, path: String, message: String, severity: String = "error") -> Dictionary:
	return {"code": code, "path": path, "message": message, "severity": severity}


func errors_of(issues: Array) -> Array:
	return issues.filter(func(i: Dictionary) -> bool: return i["severity"] == "error")


func format_issue(i: Dictionary) -> String:
	return "%s %s: %s" % [i["code"], i["path"], i["message"]]


# ------------------------------------------------------------------ JSON Schema subset

func _is_int(v: Variant) -> bool:
	return (typeof(v) == TYPE_INT) or (typeof(v) == TYPE_FLOAT and is_equal_approx(v, roundf(v)))


func _type_ok(v: Variant, t: String) -> bool:
	match t:
		"object":
			return v is Dictionary
		"array":
			return v is Array
		"string":
			return v is String
		"boolean":
			return typeof(v) == TYPE_BOOL
		"integer":
			return _is_int(v)
		"number":
			return typeof(v) == TYPE_INT or typeof(v) == TYPE_FLOAT
		"null":
			return v == null
	return false


func schema_errors(value: Variant, schema: Dictionary, path: String = "$") -> Array:
	var errs: Array = []
	if schema.has("$ref"):
		var node: Variant = _schema
		for part in String(schema["$ref"]).lstrip("#/").split("/"):
			node = node[part]
		return schema_errors(value, node, path)
	if schema.has("const") and value != schema["const"]:
		errs.append("%s: must be %s" % [path, str(schema["const"])])
	if schema.has("enum") and not (schema["enum"] as Array).has(value):
		errs.append("%s: must be one of %s" % [path, str(schema["enum"])])
	if schema.has("type"):
		if not _type_ok(value, schema["type"]):
			errs.append("%s: expected %s" % [path, schema["type"]])
			return errs
	if value is String:
		var s: String = value
		if schema.has("minLength") and s.length() < int(schema["minLength"]):
			errs.append("%s: shorter than %d" % [path, int(schema["minLength"])])
		if schema.has("maxLength") and s.length() > int(schema["maxLength"]):
			errs.append("%s: longer than %d" % [path, int(schema["maxLength"])])
		if schema.has("pattern"):
			var re := RegEx.new()
			re.compile(schema["pattern"])
			if re.search(s) == null:
				errs.append("%s: does not match %s" % [path, schema["pattern"]])
	if (typeof(value) == TYPE_INT or typeof(value) == TYPE_FLOAT):
		var f := float(value)
		if schema.has("minimum") and f < float(schema["minimum"]):
			errs.append("%s: below minimum %s" % [path, str(schema["minimum"])])
		if schema.has("maximum") and f > float(schema["maximum"]):
			errs.append("%s: above maximum %s" % [path, str(schema["maximum"])])
		if schema.has("exclusiveMinimum") and f <= float(schema["exclusiveMinimum"]):
			errs.append("%s: must be greater than %s" % [path, str(schema["exclusiveMinimum"])])
	if value is Array:
		var a: Array = value
		if schema.has("minItems") and a.size() < int(schema["minItems"]):
			errs.append("%s: needs at least %d items" % [path, int(schema["minItems"])])
		if schema.has("maxItems") and a.size() > int(schema["maxItems"]):
			errs.append("%s: more than %d items" % [path, int(schema["maxItems"])])
		if schema.get("uniqueItems", false):
			var seen := {}
			for item in a:
				var k := JSON.stringify(item)
				if seen.has(k):
					errs.append("%s: items must be unique" % path)
					break
				seen[k] = true
		if schema.has("items"):
			for i in range(a.size()):
				errs.append_array(schema_errors(a[i], schema["items"], "%s[%d]" % [path, i]))
	if value is Dictionary:
		var d: Dictionary = value
		for req in schema.get("required", []):
			if not d.has(req):
				errs.append('%s: missing "%s"' % [path, req])
		if schema.has("minProperties") and d.size() < int(schema["minProperties"]):
			errs.append("%s: needs at least %d properties" % [path, int(schema["minProperties"])])
		var props: Dictionary = schema.get("properties", {})
		for key in d.keys():
			if schema.has("propertyNames"):
				for e in schema_errors(String(key), schema["propertyNames"], path):
					errs.append(String(e).replace(path, "%s.%s (key)" % [path, key]))
			if props.has(key):
				errs.append_array(schema_errors(d[key], props[key], "%s.%s" % [path, key]))
			else:
				var ap: Variant = schema.get("additionalProperties", true)
				if typeof(ap) == TYPE_BOOL and not ap:
					errs.append('%s: unknown property "%s"' % [path, key])
				elif ap is Dictionary:
					errs.append_array(schema_errors(d[key], ap, "%s.%s" % [path, key]))
	return errs


# ------------------------------------------------------------------ semantic checks

func _param_ok(spec: Dictionary, v: Variant) -> bool:
	match str(spec["type"]):
		"number":
			return typeof(v) == TYPE_INT or typeof(v) == TYPE_FLOAT
		"integer":
			return _is_int(v)
		"boolean":
			return typeof(v) == TYPE_BOOL
		"string", "color":
			return v is String
		"object":
			return v is Dictionary
		"string_array":
			if not (v is Array):
				return false
			for item in v:
				if not (item is String):
					return false
			return true
	return true


func validate(recipe: Dictionary, project_root: String = "") -> Array:
	var issues: Array = []
	for e in schema_errors(recipe, _schema):
		var path := String(e).get_slice(": ", 0)
		var msg := String(e).substr(path.length() + 2)
		issues.append(_issue("E_SCHEMA", path, msg))
	if not issues.is_empty():
		return issues
	var genre: String = recipe["genre"]
	var dims: String = DIMS.get(genre, "")
	var entities: Dictionary = recipe.get("entities", {})
	var music: Dictionary = recipe.get("audio", {}).get("music", {})
	for key in entities.keys():
		var ent: Dictionary = entities[key]
		var comps: Array = ent.get("components", [])
		for i in range(comps.size()):
			var c: Dictionary = comps[i]
			var base := "entities.%s.components[%d]" % [key, i]
			var spec: Dictionary = _components.get(c["type"], {})
			if spec.is_empty() or spec.get("internal", false):
				issues.append(_issue("E_COMPONENT_UNKNOWN", base, 'unknown component "%s"' % c["type"]))
				continue
			if dims != "" and not (spec["dims"] as Array).has(dims):
				issues.append(_issue("E_COMPONENT_DIMS", base, "%s does not support %s games" % [c["type"], dims.to_upper()]))
			for pk in c.keys():
				if pk == "type":
					continue
				var pspec: Dictionary = spec["params"].get(pk, {})
				if pspec.is_empty():
					issues.append(_issue("E_PARAM_UNKNOWN", "%s.%s" % [base, pk], '%s has no parameter "%s" (has: %s)' % [c["type"], pk, ", ".join(spec["params"].keys())]))
				elif not _param_ok(pspec, c[pk]):
					issues.append(_issue("E_PARAM_TYPE", "%s.%s" % [base, pk], "expected %s" % pspec["type"]))
				elif pspec.has("enum") and not (pspec["enum"] as Array).has(c[pk]):
					issues.append(_issue("E_PARAM_ENUM", "%s.%s" % [base, pk], "must be one of %s" % str(pspec["enum"])))
				if c["type"] == "spawner" and pk == "scene" and c[pk] is String and not String(c[pk]).begins_with("res://") and not entities.has(c[pk]):
					issues.append(_issue("E_ENTITY_UNKNOWN", base + ".scene", 'spawner scene "%s" is not an entity' % c[pk]))
		if ent.has("model") and project_root != "":
			if not FileAccess.file_exists(String(ent["model"])):
				issues.append(_issue("W_MODEL_MISSING", "entities.%s.model" % key, "%s not found; a placeholder is used" % ent["model"], "warning"))
	if GAMEPLAY.has(genre):
		var levels: Array = recipe.get("levels", [])
		if levels.is_empty():
			issues.append(_issue("E_LEVELS_REQUIRED", "levels", "%s games need at least one level" % genre))
		var player_keys: Array = []
		for k in entities.keys():
			if entities[k]["role"] == "player":
				player_keys.append(k)
		if player_keys.is_empty():
			issues.append(_issue("E_NO_PLAYER", "entities", 'no entity with role "player"'))
		var placed := {}
		for li in range(levels.size()):
			var level: Dictionary = levels[li]
			var base := "levels[%d]" % li
			if not level.has("rows") and not level.has("objects"):
				issues.append(_issue("E_LEVEL_KIND", base, 'a level needs "rows" (grid) or "objects"'))
			var legend: Dictionary = level.get("legend", {})
			for ch in legend.keys():
				if legend[ch] != "block" and not entities.has(legend[ch]):
					issues.append(_issue("E_ENTITY_UNKNOWN", "%s.legend.%s" % [base, ch], 'unknown entity "%s"' % legend[ch]))
			var rows: Array = level.get("rows", [])
			for ri in range(rows.size()):
				var seen := {}
				for ch in String(rows[ri]):
					if seen.has(ch):
						continue
					seen[ch] = true
					if not legend.has(ch) and not "#. ".contains(ch):
						issues.append(_issue("E_LEGEND_CHAR", "%s.rows[%d]" % [base, ri], 'character "%s" is not in the legend' % ch))
					elif li == 0 and legend.has(ch):
						placed[legend[ch]] = true
			var objs: Array = level.get("objects", [])
			for oi in range(objs.size()):
				var ek: String = objs[oi]["entity"]
				if ek != "block" and not entities.has(ek):
					issues.append(_issue("E_ENTITY_UNKNOWN", "%s.objects[%d]" % [base, oi], 'unknown entity "%s"' % ek))
				elif li == 0:
					placed[ek] = true
			if level.has("music") and not music.has(level["music"]):
				issues.append(_issue("E_AUDIO_KEY", base + ".music", 'no audio.music entry "%s"' % level["music"]))
		if not player_keys.is_empty() and not levels.is_empty():
			var any_placed := false
			for pk in player_keys:
				if placed.has(pk):
					any_placed = true
			if not any_placed:
				issues.append(_issue("E_PLAYER_NOT_PLACED", "levels[0]", "the first level never places the player entity"))
	if genre == "visual_novel":
		if not recipe.has("story"):
			issues.append(_issue("E_STORY_REQUIRED", "story", "visual_novel games need a story"))
		else:
			var nodes: Dictionary = recipe["story"]["nodes"]
			if not nodes.has(recipe["story"]["start"]):
				issues.append(_issue("E_STORY_NODE", "story.start", 'unknown node "%s"' % recipe["story"]["start"]))
			for nid in nodes.keys():
				var n: Dictionary = nodes[nid]
				if n.has("next") and not nodes.has(n["next"]):
					issues.append(_issue("E_STORY_NODE", "story.nodes.%s.next" % nid, 'unknown node "%s"' % n["next"]))
				var chs: Array = n.get("choices", [])
				for ci in range(chs.size()):
					if not nodes.has(chs[ci]["goto"]):
						issues.append(_issue("E_STORY_NODE", "story.nodes.%s.choices[%d]" % [nid, ci], 'unknown node "%s"' % chs[ci]["goto"]))
	return issues
