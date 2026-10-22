extends "res://addons/amerika_engine/components/component.gd"
## @component pickup
## @dims 2d,3d
## @summary Collectable: coins/score, healing, keys (flags). Removes the host when the target touches it.

@export_enum("score", "heal", "flag", "ammo") var kind: String = "score" ## What collecting does
@export var value: int = 1 ## Score or hit points to award
@export var flag: String = "" ## Flag to set for kind=flag (e.g. "red_key")
@export var sfx: String = "pickup" ## Sound effect name
@export var target_group: String = "player" ## Who can collect it
@export var radius: float = 0.0 ## Pickup radius (0 = automatic: 14 px in 2D, 0.8 m in 3D)
@export var counts_for_win: bool = true ## Counts toward the collect_all win rule

var _area: Node


func _ready() -> void:
	_area = make_area(auto_value(radius, 14.0, 0.8))
	_area.connect("body_entered", _on_body)
	if counts_for_win:
		host.add_to_group("collectible")


func _on_body(body: Node) -> void:
	if not matches(body, target_group) or game_frozen():
		return
	_area.disconnect("body_entered", _on_body)
	var g := game()
	if g != null:
		g.call("collect", kind, value, flag, host)
	play_sfx(sfx)
	host.queue_free()
