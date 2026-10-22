extends "res://addons/amerika_engine/components/component.gd"
## @component patrol_ai
## @dims 2d,3d
## @mover true
## @summary Walk back and forth around the start position; turns at walls and (in platformers) at ledges.

@export_enum("x", "y", "z") var axis: String = "x" ## Patrol axis (use y for vertical top-down patrols, z for 3D depth)
@export var speed: float = 0.0 ## Speed (0 = automatic: 60 px/s in 2D, 2.5 m/s in 3D)
@export var distance: float = 0.0 ## How far to each side of the start (0 = automatic: 96 px / 4 m)
@export var gravity: float = 1300.0 ## 2D gravity in px/s^2 (set 0 for top-down enemies); 3D uses 20 m/s^2
@export var turn_at_ledges: bool = true ## 2D platformers: turn instead of walking off a ledge
@export var ledge_probe: float = 18.0 ## Distance ahead of the body checked for ground

var _origin: Vector3
var _dir: float = 1.0
var _speed: float
var _distance: float
var _body2d: CharacterBody2D
var _body3d: CharacterBody3D


func _ready() -> void:
	_body2d = host as CharacterBody2D
	_body3d = host as CharacterBody3D
	if _body2d == null and _body3d == null:
		push_error("patrol_ai needs a CharacterBody2D/3D host (got %s)" % host)
		set_physics_process(false)
		return
	_speed = auto_value(speed, 60.0, 2.5)
	_distance = auto_value(distance, 96.0, 4.0)
	_origin = global_pos()
	host.set_meta("amerika_enemy", true)
	host.add_to_group("enemy")


func _physics_process(delta: float) -> void:
	if game_frozen():
		return
	if _body2d != null:
		_step_2d(delta)
	else:
		_step_3d(delta)


func _step_2d(delta: float) -> void:
	var vertical := axis == "y"
	if vertical:
		_body2d.velocity = Vector2(0.0, _dir * _speed)
	else:
		_body2d.velocity.x = _dir * _speed
		if gravity > 0.0:
			_body2d.velocity.y += gravity * delta
	_body2d.move_and_slide()
	var offset := (_body2d.global_position.y - _origin.y) if vertical else (_body2d.global_position.x - _origin.x)
	if _body2d.is_on_wall() or absf(offset) > _distance and signf(offset) == _dir:
		_dir = -_dir
	elif turn_at_ledges and not vertical and gravity > 0.0 and _body2d.is_on_floor() and not _ground_ahead():
		_dir = -_dir
	_face(_dir)


func _ground_ahead() -> bool:
	var from := _body2d.global_position + Vector2(_dir * ledge_probe, 0.0)
	var query := PhysicsRayQueryParameters2D.create(from, from + Vector2(0.0, ledge_probe * 2.5), 1)
	return not _body2d.get_world_2d().direct_space_state.intersect_ray(query).is_empty()


func _step_3d(delta: float) -> void:
	var along := Vector3.BACK if axis == "z" else Vector3.RIGHT
	_body3d.velocity.x = along.x * _dir * _speed
	_body3d.velocity.z = along.z * _dir * _speed
	if not _body3d.is_on_floor():
		_body3d.velocity.y -= 20.0 * delta
	_body3d.move_and_slide()
	var offset := (_body3d.global_position - _origin).dot(along)
	if _body3d.is_on_wall() or absf(offset) > _distance and signf(offset) == _dir:
		_dir = -_dir
	if _body3d.velocity.length() > 0.1:
		_body3d.rotation.y = atan2(-along.x * _dir, -along.z * _dir)


func _face(direction: float) -> void:
	if axis != "y":
		face_visual(direction)
