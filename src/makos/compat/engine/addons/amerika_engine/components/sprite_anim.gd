extends "res://addons/amerika_engine/components/component.gd"
## @component sprite_anim
## @dims 2d
## @summary Frame animation for a sprite sheet (Sprite export): picks idle / run / jump rows from the host's motion.

@export var animations: Dictionary = {} ## Name -> [first_frame, last_frame], e.g. {"idle": [0, 1], "run": [2, 5], "jump": [6, 6]}
@export var fps: float = 8.0 ## Frames per second
@export var sprite_path: String = "Visual" ## Child Sprite2D of the host to animate
@export var face_motion: bool = true ## Flip the sprite to the direction of travel

var _sprite: Sprite2D
var _time: float = 0.0
var _current: String = ""


func _ready() -> void:
	_sprite = host.get_node_or_null(sprite_path) as Sprite2D


func _process(delta: float) -> void:
	if _sprite == null or animations.is_empty():
		return
	var vel := Vector2.ZERO
	var on_floor := true
	if host is CharacterBody2D:
		vel = (host as CharacterBody2D).velocity
		on_floor = (host as CharacterBody2D).is_on_floor() or not animations.has("jump")
	var want := "idle"
	if not on_floor:
		want = "jump"
	elif vel.length() > 12.0 and animations.has("run"):
		want = "run"
	if not animations.has(want):
		want = animations.keys()[0]
	if want != _current:
		_current = want
		_time = 0.0
	var range_: Array = animations[_current]
	var first := int(range_[0])
	var last := int(range_[1] if range_.size() > 1 else range_[0])
	_time += delta
	_sprite.frame = first + int(_time * fps) % (last - first + 1)
	if face_motion and absf(vel.x) > 12.0:
		_sprite.flip_h = vel.x < 0.0
