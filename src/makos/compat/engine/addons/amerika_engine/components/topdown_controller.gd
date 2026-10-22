extends "res://addons/amerika_engine/components/component.gd"
## @component topdown_controller
## @dims 2d
## @mover true
## @summary Eight-way top-down movement for a CharacterBody2D; the facing vector follows movement (or the mouse when aim_with_mouse is set).

@export var speed: float = 200.0 ## Move speed in px/s
@export var acceleration: float = 2200.0 ## Acceleration in px/s^2
@export var aim_with_mouse: bool = false ## Face the mouse cursor instead of the move direction
@export var rotate_host: bool = false ## Rotate the host to face the aim direction

var body: CharacterBody2D
var facing: Vector2 = Vector2.RIGHT


func _ready() -> void:
	body = host as CharacterBody2D
	if body == null:
		push_error("topdown_controller needs a CharacterBody2D host (got %s)" % host)
		set_physics_process(false)
		return
	var g := game()
	if g != null:
		g.set("player", body)


func _physics_process(delta: float) -> void:
	var dir := Vector2.ZERO
	if not game_frozen():
		dir = Input.get_vector("move_left", "move_right", "move_up", "move_down")
	body.velocity = body.velocity.move_toward(dir * speed, acceleration * delta)
	body.move_and_slide()
	if aim_with_mouse and DisplayServer.get_name() != "headless":
		var to_mouse := body.get_global_mouse_position() - body.global_position
		if to_mouse.length() > 4.0:
			facing = to_mouse.normalized()
	elif dir != Vector2.ZERO:
		facing = dir.normalized()
	if rotate_host:
		body.rotation = facing.angle()
