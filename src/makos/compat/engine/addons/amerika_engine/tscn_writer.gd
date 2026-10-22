extends RefCounted
## Minimal deterministic writer for Godot 4 text scenes (.tscn, format 3).
## Values are serialized with var_to_str(); wrap pre-formatted text in Raw (see raw()).

class Raw:
	var text: String
	func _init(t: String) -> void:
		text = t

var _ext: Array = [] ## [type, path, id]
var _ext_ids: Dictionary = {} ## "type|path" -> id
var _subs: Array = [] ## [type, id, props]
var _nodes: Array = [] ## {name,type,parent,props,groups,instance}
var _next_sub: int = 1


func raw(text: String) -> Raw:
	return Raw.new(text)


func ext(type: String, path: String) -> String:
	var key := type + "|" + path
	if _ext_ids.has(key):
		return _ext_ids[key]
	var id := "%d_%s" % [_ext.size() + 1, str(abs(hash(path)) % 100000).pad_zeros(5)]
	_ext_ids[key] = id
	_ext.append([type, path, id])
	return id


func ext_ref(type: String, path: String) -> Raw:
	return Raw.new('ExtResource("%s")' % ext(type, path))


func sub(type: String, props: Dictionary = {}) -> Raw:
	var id := "%s_%d" % [type, _next_sub]
	_next_sub += 1
	_subs.append([type, id, props])
	return Raw.new('SubResource("%s")' % id)


## Add a node. parent: "" for the root, "." for a child of the root, else the path from the root.
func node(node_name: String, type: String, parent: String, props: Dictionary = {}, groups: Array = []) -> void:
	_nodes.append({"name": node_name, "type": type, "parent": parent, "props": props, "groups": groups, "instance": ""})


## Add an instance of another scene. `scene` is a res:// path.
func instance(node_name: String, scene: String, parent: String, props: Dictionary = {}, groups: Array = []) -> void:
	_nodes.append({"name": node_name, "type": "", "parent": parent, "props": props, "groups": groups,
		"instance": ext("PackedScene", scene)})


func _val(v: Variant) -> String:
	if v is Raw:
		return (v as Raw).text
	return var_to_str(v)


func _props(d: Dictionary) -> String:
	var out := ""
	for k in d.keys():
		out += "%s = %s\n" % [k, _val(d[k])]
	return out


func serialize() -> String:
	var steps := _ext.size() + _subs.size() + 1
	var s := "[gd_scene load_steps=%d format=3]\n\n" % steps
	for e in _ext:
		s += '[ext_resource type="%s" path="%s" id="%s"]\n' % [e[0], e[1], e[2]]
	if not _ext.is_empty():
		s += "\n"
	for sr in _subs:
		s += '[sub_resource type="%s" id="%s"]\n%s\n' % [sr[0], sr[1], _props(sr[2])]
	for n in _nodes:
		var head := '[node name="%s"' % n["name"]
		if n["type"] != "":
			head += ' type="%s"' % n["type"]
		if n["parent"] != "":
			head += ' parent="%s"' % n["parent"]
		if n["instance"] != "":
			head += ' instance=ExtResource("%s")' % n["instance"]
		if not (n["groups"] as Array).is_empty():
			var quoted: Array = []
			for g in n["groups"]:
				quoted.append('"%s"' % g)
			head += " groups=[%s]" % ", ".join(quoted)
		s += head + "]\n" + _props(n["props"]) + "\n"
	return s.rstrip("\n") + "\n"
