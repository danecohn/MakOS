extends Node
## Base class for Engine behaviour components.
##
## A component is a plain Node attached as a child of an entity root (a Node2D/Node3D,
## CharacterBody or StaticBody). It finds its `host` through get_parent(), so the same
## script works in 2D and 3D wherever the host type allows it. Components never use
## class_name, so they run in a fresh project before the editor has built its class cache.

var host: Node
var host2d: Node2D
var host3d: Node3D


func _enter_tree() -> void:
	host = get_parent()
	host2d = host as Node2D
	host3d = host as Node3D


func is_3d() -> bool:
	return host3d != null


## The AmerikaGame autoload (score, flags, win/lose), or null when running a bare scene.
func game() -> Node:
	return get_node_or_null("/root/AmerikaGame")


func game_frozen() -> bool:
	var g := game()
	return g != null and bool(g.get("frozen"))


func global_pos() -> Vector3:
	if host3d != null:
		return host3d.global_position
	if host2d != null:
		return Vector3(host2d.global_position.x, host2d.global_position.y, 0.0)
	return Vector3.ZERO


## Create an Area2D/Area3D child of host (no layer, sees every layer) with a round shape.
func make_area(radius: float) -> Node:
	var area: Node
	if host3d != null:
		var a3 := Area3D.new()
		var cs3 := CollisionShape3D.new()
		var sp := SphereShape3D.new()
		sp.radius = radius
		cs3.shape = sp
		a3.add_child(cs3)
		a3.collision_layer = 0
		a3.collision_mask = 0xFFFFF
		area = a3
	else:
		var a2 := Area2D.new()
		var cs2 := CollisionShape2D.new()
		var ci := CircleShape2D.new()
		ci.radius = radius
		cs2.shape = ci
		a2.add_child(cs2)
		a2.collision_layer = 0
		a2.collision_mask = 0xFFFFF
		area = a2
	area.name = "%sArea" % name
	host.add_child.call_deferred(area) # the host is still setting up its children
	return area


## True when `body` belongs to `group` (empty group matches everything but the host).
func matches(body: Node, group: String) -> bool:
	if body == host:
		return false
	return group == "" or body.is_in_group(group)


func play_sfx(sfx_name: String) -> void:
	var g := game()
	if g != null and sfx_name != "":
		g.call("play_sfx", sfx_name)


## Apply damage to the first Health component on `node` (returns true if it had one).
func damage_node(node: Node, amount: int, source: Node = null) -> bool:
	for child in node.get_children():
		if child.has_method("damage"):
			child.call("damage", amount, source)
			return true
	return false


## Convenience: radius, falling back to a 2D or 3D default when `value` is 0 or less.
func auto_value(value: float, default_2d: float, default_3d: float) -> float:
	if value > 0.0:
		return value
	return default_3d if host3d != null else default_2d


## Mirror a polygon placeholder ("Visual") towards `dir_x`. Sprite sheets flip themselves (sprite_anim).
func face_visual(dir_x: float) -> void:
	if host2d == null or dir_x == 0.0:
		return
	var visual := host.get_node_or_null("Visual") as Polygon2D
	if visual != null:
		visual.scale.x = absf(visual.scale.x) * signf(dir_x)
