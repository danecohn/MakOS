extends "res://addons/amerika_engine/components/component.gd"
## @component chase_ai
## @dims 2d,3d
## @mover true
## @summary Chase the nearest body of a group when it is within sight, otherwise stand still.

@export var target_group: String = "player" ## Whom to chase
@export var speed: float = 0.0 ## Speed (0 = automatic: 90 px/s in 2D, 3.5 m/s in 3D)
@export var sight: float = 0.0 ## Sight range (0 = automatic: 280 px / 14 m)
@export var stop_distance: float = 0.0 ## Stop this close to the target (0 = automatic: 6 px / 1 m)
@export var gravity: float = 0.0 ## 2D gravity in px/s^2 (top-down enemies keep 0; platformer chasers use ~1300). 3D always 20 m/s^2

var _body2d: CharacterBody2D
var _body3d: CharacterBody3D


func _ready() -> void:
	_body2d = host as CharacterBody2D
	_body3d = host as CharacterBody3D
	if _body2d == null and _body3d == null:
		push_error("chase_ai needs a CharacterBody2D/3D host (got %s)" % host)
		set_physics_process(false)
		return
	host.add_to_group("enemy")


func _nearest() -> Node:
	var best: Node = null
	var best_d := INF
	var here := global_pos()
	for n in get_tree().get_nodes_in_group(target_group):
		if n == host or not (n is Node2D or n is Node3D):
			continue
		var d := here.distance_to(Vector3((n as Node2D).global_position.x, (n as Node2D).global_position.y, 0.0) if n is Node2D else (n as Node3D).global_position)
		if d < best_d:
			best_d = d
			best = n
	return best


func _physics_process(delta: float) -> void:
	if game_frozen():
		return
	var spd := auto_value(speed, 90.0, 3.5)
	var range_ := auto_value(sight, 280.0, 14.0)
	var stop := auto_value(stop_distance, 6.0, 1.0)
	var target := _nearest()
	if _body2d != null:
		var vel := Vector2.ZERO
		if target != null:
			var to := (target as Node2D).global_position - _body2d.global_position
			if to.length() < range_ and to.length() > stop:
				vel = to.normalized() * spd
		if gravity > 0.0:
			vel = Vector2(vel.x, _body2d.velocity.y + gravity * delta)
		_body2d.velocity = vel
		_body2d.move_and_slide()
	else:
		var vel3 := Vector3(0.0, _body3d.velocity.y, 0.0)
		if not _body3d.is_on_floor():
			vel3.y -= 20.0 * delta
		if target != null:
			var to3 := (target as Node3D).global_position - _body3d.global_position
			to3.y = 0.0
			if to3.length() < range_ and to3.length() > stop:
				var d3 := to3.normalized()
				vel3.x = d3.x * spd
				vel3.z = d3.z * spd
				_body3d.rotation.y = atan2(-d3.x, -d3.z)
		_body3d.velocity = vel3
		_body3d.move_and_slide()
