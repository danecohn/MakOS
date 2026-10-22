extends "res://addons/amerika_engine/components/component.gd"
## @component contact_damage
## @dims 2d,3d
## @summary Hurts bodies of the target group while they overlap the host (spikes, enemies). Optional stomp for platformers.

@export var damage: int = 1 ## Hit points removed per hit
@export var target_group: String = "player" ## Group of bodies that get hurt
@export var radius: float = 0.0 ## Hit radius (0 = automatic: 16 px in 2D, 0.9 m in 3D)
@export var interval: float = 0.6 ## Seconds between hits on the same overlap
@export var stomp: bool = false ## 2D only: landing on top hurts the host instead and bounces the player
@export var knockback: float = 0.0 ## Push the victim away at this speed

var _area: Node
var _cooldown: float = 0.0


func _ready() -> void:
	_area = make_area(auto_value(radius, 16.0, 0.9))


func _physics_process(delta: float) -> void:
	_cooldown -= delta
	if _cooldown > 0.0 or game_frozen():
		return
	if not _area.is_inside_tree():
		return
	var bodies: Array = _area.call("get_overlapping_bodies")
	for body in bodies:
		if not matches(body, target_group):
			continue
		if stomp and host2d != null and body is CharacterBody2D:
			var cb := body as CharacterBody2D
			if cb.velocity.y > 40.0 and cb.global_position.y < host2d.global_position.y - 2.0:
				damage_node(host, 1, body)
				cb.velocity.y = -320.0
				_cooldown = 0.2
				play_sfx("stomp")
				return
		if damage_node(body, damage, host):
			_cooldown = interval
			if knockback > 0.0:
				_push(body)
			return


func _push(body: Node) -> void:
	if body is CharacterBody2D and host2d != null:
		var dir := ((body as CharacterBody2D).global_position - host2d.global_position).normalized()
		(body as CharacterBody2D).velocity += dir * knockback
	elif body is CharacterBody3D and host3d != null:
		var dir3 := ((body as CharacterBody3D).global_position - host3d.global_position)
		dir3.y = 0.2
		(body as CharacterBody3D).velocity += dir3.normalized() * knockback
