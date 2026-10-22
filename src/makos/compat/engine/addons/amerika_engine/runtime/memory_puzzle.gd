extends Control
## Memory-match card puzzle. Reads `puzzle` from res://amerika_game.json:
##   {"columns": 4, "pairs": 8, "symbols": ["A", "B", ...], "flip_back": 0.8, "time_limit": 0}

var columns: int = 4
var pairs: int = 8
var flip_back: float = 0.8
var time_limit: float = 0.0
var moves: int = 0
var matched: int = 0
var cards: Array[Dictionary] = [] ## {symbol, button, face_up, done}

var _first: int = -1
var _second: int = -1
var _lock: float = 0.0
var _info: Label
var _time: float = 0.0
var _accent := Color("ff3d6e")
var _txt := Color("fff0cf")
var _panel := Color("0e0810")
var _done: bool = false


func _ready() -> void:
	var g := get_node_or_null("/root/AmerikaGame")
	var symbols: Array = []
	if g != null:
		var cfg: Dictionary = g.call("cfg", "puzzle", {})
		columns = int(cfg.get("columns", columns))
		pairs = int(cfg.get("pairs", pairs))
		flip_back = float(cfg.get("flip_back", flip_back))
		time_limit = float(cfg.get("time_limit", 0))
		symbols = cfg.get("symbols", [])
		_accent = Color(str(g.call("cfg", "theme.accent", "ff3d6e")))
		_txt = Color(str(g.call("cfg", "theme.text", "fff0cf")))
		_panel = Color(str(g.call("cfg", "theme.panel", "0e0810")))
		g.set("level", self)
		g.set("state", "playing")
	set_anchors_preset(Control.PRESET_FULL_RECT)
	var bg := ColorRect.new()
	bg.color = _panel
	bg.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(bg)
	var rng := RandomNumberGenerator.new()
	rng.seed = 7 + pairs
	var deck: Array = []
	for i in range(pairs):
		var s: String = str(symbols[i]) if i < symbols.size() else char(65 + i % 26)
		deck.append(s)
		deck.append(s)
	for i in range(deck.size() - 1, 0, -1):
		var j := rng.randi_range(0, i)
		var t = deck[i]
		deck[i] = deck[j]
		deck[j] = t
	var center := CenterContainer.new()
	center.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(center)
	var col := VBoxContainer.new()
	center.add_child(col)
	_info = Label.new()
	_info.add_theme_font_size_override("font_size", 24)
	_info.add_theme_color_override("font_color", _txt)
	_info.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	col.add_child(_info)
	var grid := GridContainer.new()
	grid.columns = columns
	grid.add_theme_constant_override("h_separation", 10)
	grid.add_theme_constant_override("v_separation", 10)
	col.add_child(grid)
	for i in range(deck.size()):
		var b := Button.new()
		b.custom_minimum_size = Vector2(96, 112)
		b.add_theme_font_size_override("font_size", 40)
		b.text = "?"
		b.pressed.connect(flip.bind(i))
		grid.add_child(b)
		cards.append({"symbol": deck[i], "button": b, "face_up": false, "done": false})
	_update_info()


func _update_info() -> void:
	var left := "" if time_limit <= 0.0 else "   TIME %d" % maxi(0, int(ceil(time_limit - _time)))
	_info.text = "MOVES %d   PAIRS %d/%d%s" % [moves, matched, pairs, left]


## Turn card `index` face up (what the buttons call).
func flip(index: int) -> void:
	if _done or _lock > 0.0 or index < 0 or index >= cards.size():
		return
	var c := cards[index]
	if c["face_up"] or c["done"]:
		return
	_show(index, true)
	if _first < 0:
		_first = index
		return
	_second = index
	moves += 1
	if cards[_first]["symbol"] == cards[_second]["symbol"]:
		for k in [_first, _second]:
			cards[k]["done"] = true
			(cards[k]["button"] as Button).modulate = Color(_accent, 0.55)
		matched += 1
		_first = -1
		_second = -1
		var g := get_node_or_null("/root/AmerikaGame")
		if g != null:
			g.call("add_score", 10)
			g.call("play_sfx", "pickup")
		if matched >= pairs:
			_done = true
			if g != null:
				g.call("win", "All pairs found in %d moves!" % moves)
	else:
		_lock = flip_back
	_update_info()


func _show(index: int, up: bool) -> void:
	cards[index]["face_up"] = up
	(cards[index]["button"] as Button).text = str(cards[index]["symbol"]) if up else "?"


func _process(delta: float) -> void:
	if _done:
		return
	_time += delta
	if time_limit > 0.0:
		_update_info()
		if _time >= time_limit:
			_done = true
			var g := get_node_or_null("/root/AmerikaGame")
			if g != null:
				g.call("lose", "Time is up")
	if _lock > 0.0:
		_lock -= delta
		if _lock <= 0.0:
			_show(_first, false)
			_show(_second, false)
			_first = -1
			_second = -1
