extends "res://addons/amerika_engine/components/component.gd"
## @component spawner
## @dims 2d,3d
## @summary Spawns copies of an entity scene around the host at an interval, up to a maximum alive.

@export var scene: String = "" ## res:// path of the entity scene (entities/<name>.tscn)
@export var interval: float = 3.0 ## Seconds between spawns
@export var max_alive: int = 5 ## Never exceed this many living spawns
@export var spread: float = 0.0 ## Random offset radius (0 = automatic: 120 px in 2D, 5 m in 3D)
@export var initial: int = 0 ## Spawn this many immediately
@export var active_group: String = "" ## Only spawn while a body of this group exists (empty = always)

var _timer: float = 0.0
var _packed: PackedScene
var _alive: Array[Node] = []
var _rng := RandomNumberGenerator.new()


func _ready() -> void:
	_rng.seed = hash(str(host.get_path()))
	if scene != "" and ResourceLoader.exists(scene):
		_packed = load(scene) as PackedScene
	_timer = interval
	for i in range(initial):
		_spawn.call_deferred()


func _process(delta: float) -> void:
	if _packed == null or game_frozen():
		return
	_timer -= delta
	if _timer > 0.0:
		return
	_timer = interval
	_alive = _alive.filter(func(n: Node) -> bool: return is_instance_valid(n) and not n.is_queued_for_deletion())
	if _alive.size() >= max_alive:
		return
	if active_group != "" and get_tree().get_nodes_in_group(active_group).is_empty():
		return
	_spawn()


func _spawn() -> void:
	if _packed == null:
		return
	var inst := _packed.instantiate()
	var r := auto_value(spread, 120.0, 5.0)
	host.get_parent().add_child(inst)
	if host3d != null and inst is Node3D:
		(inst as Node3D).global_position = host3d.global_position + Vector3(_rng.randf_range(-r, r), 0.5, _rng.randf_range(-r, r))
	elif host2d != null and inst is Node2D:
		(inst as Node2D).global_position = host2d.global_position + Vector2(_rng.randf_range(-r, r), _rng.randf_range(-r, r) * 0.25)
	_alive.append(inst)
