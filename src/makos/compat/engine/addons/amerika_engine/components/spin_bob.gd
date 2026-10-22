extends "res://addons/amerika_engine/components/component.gd"
## @component spin_bob
## @dims 2d,3d
## @summary Decoration: spin around the up axis and/or float up and down (nice for coins and gems).

@export var spin_degrees: float = 0.0 ## Degrees per second around the vertical axis (3D) or in the plane (2D)
@export var bob_height: float = 0.0 ## Bob amplitude (0 = none; ~4 px in 2D, ~0.15 m in 3D)
@export var bob_speed: float = 3.0 ## Bobs per second times 2*pi

var _t: float = 0.0
var _base: Vector3


func _ready() -> void:
	_base = host3d.position if host3d != null else (Vector3(host2d.position.x, host2d.position.y, 0.0) if host2d != null else Vector3.ZERO)
	_t = float(hash(str(host.get_path())) % 628) / 100.0


func _process(delta: float) -> void:
	_t += delta * bob_speed
	var off := sin(_t) * bob_height
	if host3d != null:
		host3d.rotate_y(deg_to_rad(spin_degrees) * delta)
		host3d.position.y = _base.y + off
	elif host2d != null:
		host2d.rotation += deg_to_rad(spin_degrees) * delta
		host2d.position.y = _base.y + off
