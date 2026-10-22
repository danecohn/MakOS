extends "res://addons/amerika_engine/components/component.gd"
## @component shooter
## @dims 2d,3d
## @summary Fires projectiles. mode=player shoots on the shoot action (aim from movement, mouse or camera); mode=turret shoots automatically at the nearest body of aim_group.

const Projectile := preload("res://addons/amerika_engine/components/projectile.gd")

@export_enum("player", "turret") var mode: String = "player" ## Who pulls the trigger
@export var damage: int = 1 ## Damage per projectile
@export var projectile_speed: float = 0.0 ## Speed (0 = automatic: 520 px/s, 30 m/s)
@export var cooldown: float = 0.25 ## Seconds between shots
@export var lifetime: float = 1.6 ## Seconds before a projectile disappears
@export var target_group: String = "enemy" ## Group the projectile damages (player shots: enemy, enemy shots: player)
@export var aim_group: String = "player" ## turret mode: whom to aim at
@export var max_range: float = 0.0 ## turret mode: shoot only within this range (0 = automatic: 360 px / 18 m)
@export var color: Color = Color(1.0, 0.85, 0.2) ## Projectile colour
@export var sfx: String = "shoot" ## Sound effect name
@export var muzzle_offset: float = 0.0 ## Spawn this far in front of the host (0 = automatic: 18 px / 1 m)

var _cooldown: float = 0.0


func _process(delta: float) -> void:
	_cooldown -= delta
	if _cooldown > 0.0 or game_frozen():
		return
	if mode == "player":
		if Input.is_action_pressed("shoot"):
			fire(aim_direction())
	else:
		var t := _nearest_target()
		if t != Vector3.INF:
			var here := global_pos()
			var d := t - here
			if not is_3d():
				d.z = 0.0
			fire(d.normalized())


func _nearest_target() -> Vector3:
	var best := Vector3.INF
	var best_d := auto_value(max_range, 360.0, 18.0)
	var here := global_pos()
	for n in get_tree().get_nodes_in_group(aim_group):
		if n == host:
			continue
		var p := Vector3.INF
		if n is Node3D:
			p = (n as Node3D).global_position
		elif n is Node2D:
			p = Vector3((n as Node2D).global_position.x, (n as Node2D).global_position.y, 0.0)
		if p != Vector3.INF and here.distance_to(p) < best_d:
			best_d = here.distance_to(p)
			best = p
	return best


## Unit vector the player is aiming along (a Vector3 with z=0 in 2D).
func aim_direction() -> Vector3:
	if host3d != null:
		var cam := host.get_viewport().get_camera_3d()
		if cam != null:
			var f := -cam.global_transform.basis.z
			f.y = 0.0 if host.get_node_or_null("EyeCamera") == null else f.y
			return f.normalized()
		return -host3d.global_transform.basis.z
	for c in host.get_children():
		var f: Variant = c.get("facing")
		if f is Vector2:
			return Vector3((f as Vector2).x, (f as Vector2).y, 0.0)
		if f is float:
			return Vector3(f, 0.0, 0.0)
	return Vector3.RIGHT


func fire(dir: Vector3) -> void:
	if dir.length() < 0.001:
		return
	_cooldown = cooldown
	var spd := auto_value(projectile_speed, 520.0, 30.0)
	var off := auto_value(muzzle_offset, 18.0, 1.0)
	var root: Node
	if host3d != null:
		var n3 := Node3D.new()
		var mesh := MeshInstance3D.new()
		var sphere := SphereMesh.new()
		sphere.radius = 0.12
		sphere.height = 0.24
		var mat := StandardMaterial3D.new()
		mat.albedo_color = color
		mat.emission_enabled = true
		mat.emission = color
		sphere.material = mat
		mesh.mesh = sphere
		n3.add_child(mesh)
		root = n3
	else:
		var n2 := Node2D.new()
		var poly := Polygon2D.new()
		var pts := PackedVector2Array()
		for i in range(10):
			pts.append(Vector2.from_angle(TAU * i / 10.0) * 4.0)
		poly.polygon = pts
		poly.color = color
		n2.add_child(poly)
		root = n2
	var comp := Projectile.new()
	comp.name = "Projectile"
	comp.set("velocity", dir * spd)
	comp.set("damage", damage)
	comp.set("lifetime", lifetime)
	comp.set("target_group", target_group)
	comp.set("owner_host", host)
	root.add_child(comp)
	host.get_parent().add_child(root)
	if host3d != null:
		(root as Node3D).global_position = host3d.global_position + Vector3(0.0, 1.0, 0.0) + dir * off
	else:
		(root as Node2D).global_position = host2d.global_position + Vector2(dir.x, dir.y) * off
	play_sfx(sfx)
