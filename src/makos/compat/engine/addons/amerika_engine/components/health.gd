extends "res://addons/amerika_engine/components/component.gd"
## @component health
## @dims 2d,3d
## @summary Hit points with brief invulnerability. The player dying loses the game; other entities score and disappear.

signal health_changed(current: int, maximum: int)
signal died

@export var max_health: int = 3 ## Hit points at start
@export var invulnerable_time: float = 0.8 ## Seconds of immunity after being hurt
@export var score_value: int = 0 ## Score awarded when this entity dies
@export var remove_on_death: bool = true ## Free the host when it dies (the player is never freed)
@export var death_sfx: String = "hit" ## Sound effect name to play on death

var current: int = 3
var _invulnerable: float = 0.0


func _ready() -> void:
	current = max_health
	host.add_to_group("damageable")
	if host.is_in_group("player"):
		_report()


func _process(delta: float) -> void:
	if _invulnerable > 0.0:
		_invulnerable -= delta
		var item := host as CanvasItem
		if item != null:
			item.modulate.a = 0.45 if int(_invulnerable * 12.0) % 2 == 0 else 1.0
			if _invulnerable <= 0.0:
				item.modulate.a = 1.0


func damage(amount: int = 1, source: Node = null) -> void:
	if current <= 0 or _invulnerable > 0.0 or game_frozen():
		return
	current = maxi(0, current - amount)
	_invulnerable = invulnerable_time
	health_changed.emit(current, max_health)
	_report()
	if current == 0:
		_die()
	else:
		play_sfx("hurt")


func heal(amount: int = 1) -> void:
	current = mini(max_health, current + amount)
	health_changed.emit(current, max_health)
	_report()


func _report() -> void:
	var g := game()
	if g != null and host.is_in_group("player"):
		g.call("set_player_health", current, max_health)


func _die() -> void:
	died.emit()
	var g := game()
	if host.is_in_group("player"):
		if g != null:
			g.call("lose", "You died")
		return
	play_sfx(death_sfx)
	if g != null:
		if score_value != 0:
			g.call("add_score", score_value)
		g.call("entity_died", host)
	if remove_on_death:
		host.queue_free()
