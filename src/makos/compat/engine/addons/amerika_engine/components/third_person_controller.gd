extends "res://addons/amerika_engine/components/component.gd"
## @component third_person_controller
## @dims 3d
## @mover true
## @summary Camera-relative third-person movement for a CharacterBody3D with jump and gravity; pairs with camera_follow (orbit mode).

@export var speed: float = 6.0 ## Move speed in m/s
@export var acceleration: float = 40.0 ## Acceleration in m/s^2
@export var jump_speed: float = 7.0 ## Jump velocity
@export var gravity: float = 20.0 ## Gravity in m/s^2
@export var turn_speed: float = 12.0 ## How fast the body turns to face movement
@export var kill_y: float = -30.0 ## Falling below this y counts as death

var body: CharacterBody3D
var facing: Vector3 = Vector3.FORWARD


func _ready() -> void:
	body = host as CharacterBody3D
	if body == null:
		push_error("third_person_controller needs a CharacterBody3D host (got %s)" % host)
		set_physics_process(false)
		return
	var g := game()
	if g != null:
		g.set("player", body)
		kill_y = float(g.call("level_value", "kill_y", kill_y))


func _physics_process(delta: float) -> void:
	var input := Vector2.ZERO
	if not game_frozen():
		input = Input.get_vector("move_left", "move_right", "move_up", "move_down")
	var cam := body.get_viewport().get_camera_3d()
	var basis := cam.global_transform.basis if cam != null else Basis.IDENTITY
	var fwd := -basis.z
	fwd.y = 0.0
	fwd = fwd.normalized() if fwd.length() > 0.001 else Vector3.FORWARD
	var right := basis.x
	right.y = 0.0
	right = right.normalized() if right.length() > 0.001 else Vector3.RIGHT
	var dir := (right * input.x + fwd * -input.y).normalized() if input != Vector2.ZERO else Vector3.ZERO
	var target := dir * speed
	body.velocity.x = move_toward(body.velocity.x, target.x, acceleration * delta)
	body.velocity.z = move_toward(body.velocity.z, target.z, acceleration * delta)
	if body.is_on_floor():
		if Input.is_action_just_pressed("jump") and not game_frozen():
			body.velocity.y = jump_speed
			play_sfx("jump")
	else:
		body.velocity.y -= gravity * delta
	body.move_and_slide()
	if dir != Vector3.ZERO:
		facing = dir
		var target_yaw := atan2(-dir.x, -dir.z)
		body.rotation.y = lerp_angle(body.rotation.y, target_yaw, clampf(turn_speed * delta, 0.0, 1.0))
	if body.global_position.y < kill_y:
		var g := game()
		if g != null:
			g.call("lose", "You fell out of the world")
