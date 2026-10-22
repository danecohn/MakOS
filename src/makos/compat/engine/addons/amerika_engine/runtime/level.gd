extends Node
## Level root script written by the recipe assembler. Registers the level with the AmerikaGame autoload.

@export var level_name: String = ""
@export var meta: Dictionary = {} ## kill_y, bounds [l, t, r, b], music, intro text


func _ready() -> void:
	var g := get_node_or_null("/root/AmerikaGame")
	if g != null:
		g.call("begin_level", self)
		var intro: String = str(meta.get("intro", ""))
		if intro != "":
			g.call("say", "", intro)
