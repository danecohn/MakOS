extends "res://addons/amerika_engine/components/component.gd"
## @component projectile
## @dims 2d,3d
## @internal true
## @summary Created by the shooter component; flies straight, damages the target group, disappears on walls.

var velocity: Vector3 = Vector3.ZERO
var damage: int = 1
var lifetime: float = 1.5
var target_group: String = "enemy"
var owner_host: Node
var _area: Node


func _ready() -> void:
	_area = make_area(auto_value(0.0, 6.0, 0.3))
	_area.connect("body_entered", _on_body)


func _physics_process(delta: float) -> void:
	lifetime -= delta
	if lifetime <= 0.0:
		host.queue_free()
		return
	if host3d != null:
		host3d.global_position += velocity * delta
	else:
		host2d.global_position += Vector2(velocity.x, velocity.y) * delta


func _on_body(body: Node) -> void:
	if body == owner_host or body == host:
		return
	if body.is_in_group(target_group):
		damage_node(body, damage, owner_host)
		host.queue_free()
	elif body is StaticBody2D or body is StaticBody3D:
		host.queue_free()
