extends "res://addons/amerika_engine/components/component.gd"
## @component camera_follow
## @dims 2d,3d
## @summary Camera that follows the host: a smoothed Camera2D, or a third-person orbit camera (mouse or look_left/look_right keys).

@export var zoom: float = 1.0 ## 2D zoom factor
@export var smoothing: float = 6.0 ## 2D smoothing speed (0 = off)
@export var distance: float = 7.0 ## 3D orbit distance
@export var height: float = 1.4 ## 3D look-at height above the host
@export var pitch_degrees: float = -22.0 ## 3D camera pitch (negative looks down)
@export var mouse_sensitivity: float = 0.004 ## 3D orbit speed per mouse pixel
@export var key_orbit_speed: float = 2.0 ## 3D orbit speed in radians/s for look_left / look_right
@export var limit_to_level: bool = true ## 2D: keep the camera inside the level bounds when the level defines them

var camera2d: Camera2D
var camera3d: Camera3D
var yaw: float = 0.0
var _pitch: float


func _ready() -> void:
	if host3d != null:
		_pitch = deg_to_rad(pitch_degrees)
		camera3d = Camera3D.new()
		camera3d.name = "FollowCamera"
		camera3d.top_level = true
		camera3d.current = true
		host.add_child.call_deferred(camera3d)
		if DisplayServer.get_name() != "headless":
			Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
	else:
		camera2d = Camera2D.new()
		camera2d.name = "FollowCamera"
		camera2d.zoom = Vector2(zoom, zoom)
		if smoothing > 0.0:
			camera2d.position_smoothing_enabled = true
			camera2d.position_smoothing_speed = smoothing
		var g := game()
		if g != null and limit_to_level:
			var b: Variant = g.call("level_value", "bounds", null)
			if b is Array and (b as Array).size() == 4:
				camera2d.limit_left = int(b[0])
				camera2d.limit_top = int(b[1])
				camera2d.limit_right = int(b[2])
				camera2d.limit_bottom = int(b[3])
		host.add_child.call_deferred(camera2d)


func _unhandled_input(event: InputEvent) -> void:
	if camera3d == null:
		return
	if event is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		var m := event as InputEventMouseMotion
		yaw -= m.relative.x * mouse_sensitivity
		_pitch = clampf(_pitch - m.relative.y * mouse_sensitivity, -1.2, 0.3)
	elif event.is_action_pressed("ui_cancel"):
		Input.mouse_mode = Input.MOUSE_MODE_VISIBLE


func _process(delta: float) -> void:
	if camera3d == null or not camera3d.is_inside_tree():
		return
	yaw -= Input.get_axis("look_left", "look_right") * key_orbit_speed * delta
	var focus := host3d.global_position + Vector3(0.0, height, 0.0)
	var rot := Basis.from_euler(Vector3(_pitch, yaw, 0.0))
	camera3d.global_position = focus + rot * Vector3(0.0, 0.0, distance)
	camera3d.global_transform.basis = rot
