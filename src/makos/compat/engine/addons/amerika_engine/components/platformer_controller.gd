extends "res://addons/amerika_engine/components/component.gd"
## @component platformer_controller
## @dims 2d
## @mover true
## @summary Side-scrolling movement for a CharacterBody2D: run, jump with coyote time, double jump, gravity, fall-death.

@export var speed: float = 220.0 ## Run speed in px/s
@export var acceleration: float = 1800.0 ## Ground acceleration in px/s^2
@export var jump_speed: float = 460.0 ## Initial upward speed of a jump
@export var gravity: float = 1300.0 ## Gravity in px/s^2
@export var coyote_time: float = 0.1 ## Seconds after leaving a ledge you can still jump
@export var max_jumps: int = 1 ## 2 enables double jump
@export var kill_y: float = 3000.0 ## Falling below this y counts as death (the level may override it)

var body: CharacterBody2D
var facing: float = 1.0
var _coyote: float = 0.0
var _jumps_left: int = 1


func _ready() -> void:
	body = host as CharacterBody2D
	if body == null:
		push_error("platformer_controller needs a CharacterBody2D host (got %s)" % host)
		set_physics_process(false)
		return
	var g := game()
	if g != null:
		g.set("player", body)
		kill_y = float(g.call("level_value", "kill_y", kill_y))


func _physics_process(delta: float) -> void:
	if game_frozen():
		body.velocity.x = move_toward(body.velocity.x, 0.0, acceleration * delta)
		body.velocity.y += gravity * delta
		body.move_and_slide()
		return
	var axis := Input.get_axis("move_left", "move_right")
	if axis != 0.0:
		facing = signf(axis)
		face_visual(facing)
	body.velocity.x = move_toward(body.velocity.x, axis * speed, acceleration * delta)
	if body.is_on_floor():
		_coyote = coyote_time
		_jumps_left = max_jumps
	else:
		_coyote -= delta
		if _coyote <= 0.0 and _jumps_left == max_jumps:
			_jumps_left = max_jumps - 1 # walked off a ledge: the ground jump is gone
		body.velocity.y += gravity * delta
	if Input.is_action_just_pressed("jump") and (_coyote > 0.0 or _jumps_left > 0):
		body.velocity.y = -jump_speed
		_jumps_left = max_jumps - 1 if _coyote > 0.0 else _jumps_left - 1
		_coyote = 0.0
		play_sfx("jump")
	if Input.is_action_just_released("jump") and body.velocity.y < -jump_speed * 0.4:
		body.velocity.y = -jump_speed * 0.4
	body.move_and_slide()
	if body.global_position.y > kill_y:
		var g := game()
		if g != null:
			g.call("lose", "You fell out of the world")
