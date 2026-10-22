extends "res://addons/amerika_engine/components/component.gd"
## @component door_trigger
## @dims 2d,3d
## @summary Trigger zone: finish the level (goal), go to another level, or show a message. Can require a flag such as a key.

@export_enum("goal", "level", "message") var kind: String = "goal" ## What entering does
@export var next_level: String = "" ## Level name for kind=level
@export var requires_flag: String = "" ## Flag the player must hold (a collected key)
@export var message: String = "" ## Text shown for kind=message (or when the door is locked)
@export var locked_message: String = "It is locked." ## Shown when requires_flag is missing
@export var target_group: String = "player" ## Who triggers it
@export var radius: float = 0.0 ## Trigger radius (0 = automatic: 20 px in 2D, 1.2 m in 3D)
@export var once: bool = false ## Only fire once

var _area: Node
var _fired: bool = false


func _ready() -> void:
	_area = make_area(auto_value(radius, 20.0, 1.2))
	_area.connect("body_entered", _on_body)


func _on_body(body: Node) -> void:
	if not matches(body, target_group) or game_frozen() or (once and _fired):
		return
	var g := game()
	if g == null:
		return
	if requires_flag != "" and not bool(g.call("has_flag", requires_flag)):
		g.call("say", "", locked_message)
		return
	_fired = true
	match kind:
		"goal":
			play_sfx("win")
			g.call("win", message)
		"level":
			g.call("goto_level", next_level)
		"message":
			g.call("say", "", message)
