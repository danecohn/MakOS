extends "res://addons/amerika_engine/components/component.gd"
## @component dialogue
## @dims 2d,3d
## @summary Talk to an NPC: lines appear in the HUD when the player walks up (enter) or presses interact.

@export var speaker: String = "" ## Name shown with the line
@export var lines: Array[String] = [] ## What is said, in order
@export_enum("enter", "interact") var trigger: String = "interact" ## Walk up, or press the interact key nearby
@export var radius: float = 0.0 ## Talk radius (0 = automatic: 48 px in 2D, 2.5 m in 3D)
@export var line_time: float = 3.0 ## Seconds each line stays when trigger=enter
@export var loop: bool = true ## Start over after the last line

var _area: Node
var _index: int = 0
var _inside: bool = false
var _timer: float = 0.0
var _playing: bool = false


func _ready() -> void:
	_area = make_area(auto_value(radius, 48.0, 2.5))
	_area.connect("body_entered", _on_enter)
	_area.connect("body_exited", _on_exit)


func _on_enter(body: Node) -> void:
	if not matches(body, "player"):
		return
	_inside = true
	if trigger == "enter" and not lines.is_empty():
		_playing = true
		_index = 0
		_say_next()


func _on_exit(body: Node) -> void:
	if matches(body, "player"):
		_inside = false
		_playing = false


func _process(delta: float) -> void:
	if _inside and trigger == "interact" and Input.is_action_just_pressed("interact") and not lines.is_empty():
		_say_next()
	elif _playing:
		_timer -= delta
		if _timer <= 0.0:
			_say_next()


func _say_next() -> void:
	if _index >= lines.size():
		if not loop:
			_playing = false
			return
		_index = 0
	var g := game()
	if g != null:
		g.call("say", speaker, lines[_index])
	_index += 1
	_timer = line_time
