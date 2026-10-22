extends "res://addons/amerika_engine/components/component.gd"
## @component first_person_controller
## @dims 3d
## @mover true
## @summary First-person movement for a CharacterBody3D: WASD, jump, mouse look (or look_left/right keys), creates its own Camera3D at eye height.

@export var speed: float = 6.0 ## Move speed in m/s
@export var acceleration: float = 50.0 ## Acceleration in m/s^2
@export var jump_speed: float = 6.5 ## Jump velocity
@export var gravity: float = 20.0 ## Gravity in m/s^2
@export var eye_height: float = 1.6 ## Camera height above the host origin
@export var mouse_sensitivity: float = 0.0025 ## Radians per mouse pixel
@export var key_look_speed: float = 2.0 ## Radians per second for look_left / look_right
@export var kill_y: float = -30.0 ## Falling below this y counts as death

var body: CharacterBody3D
var camera: Camera3D
var _pitch: float = 0.0


func _ready() -> void:
	body = host as CharacterBody3D
	if body == null:
		push_error("first_person_controller needs a CharacterBody3D host (got %s)" % host)
		set_physics_process(false)
		return
	camera = Camera3D.new()
	camera.name = "EyeCamera"
	camera.position = Vector3(0.0, eye_height, 0.0)
	camera.current = true
	body.add_child.call_deferred(camera)
	if DisplayServer.get_name() != "headless":
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
	var g := game()
	if g != null:
		g.set("player", body)
		kill_y = float(g.call("level_value", "kill_y", kill_y))


func _unhandled_input(event: InputEvent) -> void:
	if body == null or game_frozen():
		return
	if event is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		var motion := event as InputEventMouseMotion
		body.rotate_y(-motion.relative.x * mouse_sensitivity)
		_pitch = clampf(_pitch - motion.relative.y * mouse_sensitivity, -1.4, 1.4)
		camera.rotation.x = _pitch
	elif event.is_action_pressed("ui_cancel"):
		Input.mouse_mode = Input.MOUSE_MODE_VISIBLE


func _physics_process(delta: float) -> void:
	var input := Vector2.ZERO
	if not game_frozen():
		input = Input.get_vector("move_left", "move_right", "move_up", "move_down")
		body.rotate_y(-Input.get_axis("look_left", "look_right") * key_look_speed * delta)
	var dir := (body.global_transform.basis * Vector3(input.x, 0.0, input.y)).normalized()
	body.velocity.x = move_toward(body.velocity.x, dir.x * speed, acceleration * delta)
	body.velocity.z = move_toward(body.velocity.z, dir.z * speed, acceleration * delta)
	if body.is_on_floor():
		if Input.is_action_just_pressed("jump") and not game_frozen():
			body.velocity.y = jump_speed
	else:
		body.velocity.y -= gravity * delta
	body.move_and_slide()
	if body.global_position.y < kill_y:
		var g := game()
		if g != null:
			g.call("lose", "You fell out of the world")
