"""Tool definitions (names, descriptions, JSON schemas, risk) for the Render assistant. No bpy here."""

V3 = {'type': 'array', 'items': {'type': 'number'}, 'minItems': 3, 'maxItems': 3}
COLOR = {'type': ['array', 'string'], 'items': {'type': 'number'}, 'minItems': 3, 'maxItems': 4,
         'description': 'Linear RGB(A) 0..1 as [r,g,b] / [r,g,b,a], or a hex string like "#3a7d2c" (sRGB hex, converted).'}
NAME = {'type': 'string', 'minLength': 1, 'maxLength': 63}
NAMES = {'type': 'array', 'items': NAME, 'minItems': 1, 'maxItems': 200}
SEL = {
    'type': 'object',
    'description': ('Selection descriptor, all given conditions must hold (AND). Omit or {"all":true} for everything. '
                    '"indices": explicit element indices. "axis_range": {"axis":"x|y|z","min":n,"max":n,"space":"local|world"} '
                    'on element centres (faces/edges) or vertices. "normal": {"direction":[x,y,z],"min_dot":0.7} for faces '
                    '(e.g. top faces: direction [0,0,1], min_dot 0.9). "facing": "top|bottom|front|back|left|right" shortcut '
                    '(front = -Y, back = +Y, right = +X, left = -X, top = +Z). "area": {"min":n,"max":n} face area in local units. '
                    '"material_index": int. "box": {"min":[x,y,z],"max":[x,y,z]} local-space box containing centres. '
                    '"invert": true inverts the final result.'),
    'properties': {
        'mode': {'type': 'string', 'enum': ['vert', 'edge', 'face'], 'description': 'Element type (default depends on the operation).'},
        'all': {'type': 'boolean'},
        'indices': {'type': 'array', 'items': {'type': 'integer', 'minimum': 0}, 'maxItems': 100000},
        'axis_range': {'type': 'object'},
        'normal': {'type': 'object'},
        'facing': {'type': 'string', 'enum': ['top', 'bottom', 'front', 'back', 'left', 'right']},
        'area': {'type': 'object'},
        'material_index': {'type': 'integer', 'minimum': 0},
        'box': {'type': 'object'},
        'invert': {'type': 'boolean'},
    },
}

PRIMITIVES = ['cube', 'uv_sphere', 'ico_sphere', 'cylinder', 'cone', 'torus', 'plane', 'circle', 'grid', 'monkey', 'empty']
MODIFIERS = ['BEVEL', 'SUBSURF', 'MIRROR', 'ARRAY', 'BOOLEAN', 'SOLIDIFY', 'DISPLACE', 'DECIMATE', 'WEIGHTED_NORMAL',
             'EDGE_SPLIT', 'TRIANGULATE', 'SMOOTH', 'REMESH', 'WIREFRAME', 'SCREW', 'SIMPLE_DEFORM', 'SHRINKWRAP',
             'CURVE', 'LATTICE', 'WAVE', 'SKIN', 'MASK']


def _obj(props, required=None):
    return {'type': 'object', 'properties': props, 'required': required or [], 'additionalProperties': False}


SPECS = [
    {
        'name': 'scene_info', 'risk': 'read',
        'description': (
            'Inspect the Blender scene. ALWAYS call this first in a new request and again after big changes. Returns units and scale, '
            'frame range, the active/selected objects, the collection tree, and for each object: type, parent, collection, location, '
            'rotation (degrees), scale, dimensions (metres, world-space bounding box size), world-space bounding box min/max, vertex/face/'
            'triangle counts, material names, modifiers, and shape-key/armature info. Also whole-scene totals and the project directory. '
            'Use `names` to inspect only some objects at full detail; use `detail: "summary"` for big scenes.'),
        'input_schema': _obj({
            'names': {'type': 'array', 'items': NAME, 'maxItems': 200, 'description': 'Limit to these objects.'},
            'detail': {'type': 'string', 'enum': ['summary', 'full'], 'default': 'full'},
        }),
    },
    {
        'name': 'create_primitive', 'risk': 'act',
        'description': (
            'Create a mesh primitive (or an empty) with a meaningful `name`. Types: cube, uv_sphere, ico_sphere, cylinder, cone, torus, plane, circle, '
            'grid, monkey, empty. Sizes are in metres: `size` is the edge length for cube/plane/grid; `radius` and `depth` (height) for sphere/'
            'cylinder/cone/circle; `radius2` is the top radius of a cone/cylinder (0 = point); torus uses `radius` (major) and `minor_radius`. '
            'Cylinders and cones are centred on their middle, so a 2 m tall cylinder at z=1 stands on the ground. Pick LOW segment counts for '
            'game assets (cylinder 8-12, uv_sphere 12 x 8, ico_sphere subdivisions 1-2). `location` is the object centre. Created objects get '
            'smooth shading only if `smooth` is true (default false = flat, best for low-poly).'),
        'input_schema': _obj({
            'type': {'type': 'string', 'enum': PRIMITIVES},
            'name': NAME,
            'location': V3, 'rotation_deg': V3, 'scale': V3,
            'size': {'type': 'number', 'minimum': 0.0001, 'maximum': 10000},
            'radius': {'type': 'number', 'minimum': 0.0001, 'maximum': 10000},
            'radius2': {'type': 'number', 'minimum': 0, 'maximum': 10000},
            'minor_radius': {'type': 'number', 'minimum': 0.0001, 'maximum': 10000},
            'depth': {'type': 'number', 'minimum': 0.0001, 'maximum': 10000},
            'segments': {'type': 'integer', 'minimum': 3, 'maximum': 256},
            'rings': {'type': 'integer', 'minimum': 2, 'maximum': 128},
            'subdivisions': {'type': 'integer', 'minimum': 1, 'maximum': 5},
            'smooth': {'type': 'boolean', 'default': False},
            'collection': NAME,
            'material': NAME,
        }, ['type', 'name']),
    },
    {
        'name': 'transform_object', 'risk': 'act',
        'description': (
            'Move, rotate, scale or resize an existing object, optionally re-parent it. Values are ABSOLUTE unless `relative` is true (then '
            'location/rotation are added and scale is multiplied). `rotation_deg` is XYZ Euler in degrees. `dimensions` sets the final world-space size '
            'in metres (it rescales the object; use it to hit exact sizes, e.g. a 1.8 m tall character). `apply` bakes transforms into the mesh '
            '(list any of location, rotation, scale) - ALWAYS apply scale before export so exported scale is 1. `parent` attaches to another object '
            'keeping its world position. Y-up is handled by the glTF exporter; model with Z up in Blender.'),
        'input_schema': _obj({
            'name': NAME, 'location': V3, 'rotation_deg': V3, 'scale': V3, 'dimensions': V3,
            'relative': {'type': 'boolean', 'default': False},
            'apply': {'type': 'array', 'items': {'type': 'string', 'enum': ['location', 'rotation', 'scale']}},
            'parent': {'type': ['string', 'null']},
        }, ['name']),
    },
    {
        'name': 'add_modifier', 'risk': 'act',
        'description': (
            'Add, apply or remove a modifier. `action` add (default) | apply | remove. `type` one of ' + ', '.join(MODIFIERS) + '. `params` sets modifier '
            'properties by their Blender RNA names (snake_case), e.g. BEVEL {width:0.02, segments:2, limit_method:"ANGLE"}; SUBSURF {levels:1, render_levels:2}; '
            'MIRROR {use_axis:[true,false,false], use_clip:true, use_mirror_merge:true, mirror_object:"Empty"}; ARRAY {count:5, relative_offset_displace:[1.1,0,0]} or '
            '{use_relative_offset:false, use_constant_offset:true, constant_offset_displace:[0,0,0.5]}; BOOLEAN {operation:"DIFFERENCE", object:"Cutter", solver:"EXACT"} '
            '(hide the cutter afterwards with transform/run_python display_type or delete it after applying); SOLIDIFY {thickness:0.05, offset:-1}; DECIMATE '
            '{ratio:0.5} or {decimate_type:"DISSOLVE", angle_limit:0.1}; DISPLACE {strength:0.3, texture_type:"CLOUDS"} (creates a texture automatically); '
            'WEIGHTED_NORMAL {keep_sharp:true}; TRIANGULATE {quad_method:"BEAUTY"}. Unknown property names return the list of valid ones. Objects can be referenced '
            'by name. Modifiers are non-destructive: set `apply: true` (or action apply) before export unless the exporter applies them (export_file has `apply_modifiers`). '
            'Keep modifier stacks short and name them via `modifier_name`.'),
        'input_schema': _obj({
            'object': NAME,
            'action': {'type': 'string', 'enum': ['add', 'apply', 'remove'], 'default': 'add'},
            'type': {'type': 'string', 'enum': MODIFIERS},
            'modifier_name': NAME,
            'params': {'type': 'object'},
            'apply': {'type': 'boolean', 'default': False},
        }, ['object']),
    },
    {
        'name': 'edit_mesh', 'risk': 'act',
        'description': (
            'Edit mesh topology with bmesh using selection DESCRIPTORS (no UI selection needed). `operations` run in order on one object. Each operation: '
            '{"op": ..., "select": <selection descriptor>, ...params}. Ops: extrude_faces {offset} (along face normals, metres; negative = inwards); '
            'inset_faces {thickness, depth}; bevel {offset, segments, mode:"edge|vert"} (selects edges); loop_cut {axis:"x|y|z", cuts:n, position:optional local coordinate} '
            '(slices the whole mesh with evenly spaced planes: a loop cut for boxy shapes); subdivide {cuts, smooth:0..1}; merge_by_distance {distance}; '
            'delete {mode:"vert|edge|face"}; translate {offset:[x,y,z]} / scale {factor:[x,y,z] or number, center:"selection|origin"} / rotate {angle_deg, axis:"x|y|z"} '
            'on selected vertices; extrude_edges {offset:[x,y,z]}; bridge/fill: fill_hole; dissolve {mode:"limited", angle_deg}; flip_normals; recalc_normals; triangulate; '
            'smooth_shading {smooth:true|false}; set_material_index {index}; mark_sharp {angle_deg} (marks edges sharper than the angle). '
            'Typical low-poly recipes: tapered trunk = cylinder + scale top faces ({"op":"scale","select":{"mode":"vert","facing"..} }) - or simply use cone/cylinder radius2; '
            'windows = inset_faces on a wall face then extrude_faces with a negative offset; roof = cube, translate top verts. The result reports vertex/face/triangle counts before and after '
            'and selection sizes, so check that `selected` is not zero (an empty selection is an error unless `allow_empty`).'),
        'input_schema': _obj({
            'object': NAME,
            'operations': {'type': 'array', 'minItems': 1, 'maxItems': 40, 'items': {
                'type': 'object',
                'properties': {'op': {'type': 'string'}, 'select': SEL},
                'required': ['op'],
            }},
            'allow_empty': {'type': 'boolean', 'default': False},
        }, ['object', 'operations']),
    },
    {
        'name': 'create_mesh_from_data', 'risk': 'act',
        'description': (
            'Create a mesh object from raw geometry: `vertices` [[x,y,z],...] (metres, Z up), `faces` [[i,j,k,...],...] (vertex indices, counter-clockwise when seen from '
            'outside so normals point outward; triangles, quads and n-gons OK), optional `uvs` (one [u,v] per face corner in face order). Use for shapes the primitives cannot '
            'make (leaves, blades, custom hulls, lathe profiles, terrain patches, you compute the numbers). Up to 200k vertices. Normals are recalculated outward by default.'),
        'input_schema': _obj({
            'name': NAME,
            'vertices': {'type': 'array', 'minItems': 1, 'maxItems': 200000, 'items': V3},
            'faces': {'type': 'array', 'maxItems': 400000, 'items': {'type': 'array', 'items': {'type': 'integer', 'minimum': 0}, 'minItems': 3, 'maxItems': 64}},
            'edges': {'type': 'array', 'maxItems': 400000, 'items': {'type': 'array', 'items': {'type': 'integer', 'minimum': 0}, 'minItems': 2, 'maxItems': 2}},
            'uvs': {'type': 'array', 'maxItems': 1600000, 'items': {'type': 'array', 'items': {'type': 'number'}, 'minItems': 2, 'maxItems': 2}},
            'location': V3, 'rotation_deg': V3, 'scale': V3,
            'smooth': {'type': 'boolean', 'default': False},
            'recalc_normals': {'type': 'boolean', 'default': True},
            'collection': NAME,
            'material': NAME,
        }, ['name', 'vertices']),
    },
    {
        'name': 'set_material', 'risk': 'act',
        'description': (
            'Create or update a PBR material (Principled BSDF) and assign it to one or more objects. `base_color` linear RGB or hex; `metallic` 0..1 (0 for wood/'
            'plastic/skin/foliage, 1 for bare metal); `roughness` 0..1; `alpha` (<1 enables blending); `emission` {color, strength}; `ior`; `transmission` for glass; `coat`; `normal_strength`. '
            '`texture` adds a PROCEDURAL texture driving a channel: {type: noise|voronoi|wave|checker|brick|gradient|magic, target: base_color|roughness|bump|emission|metallic, '
            'scale, detail, distortion, color1, color2, strength}. For base_color/emission the texture blends color1->color2; for roughness/metallic it blends 0.3..0.9 style numbers via '
            'color1/color2 greyscale; for bump it perturbs normals. Procedural nodes DO NOT survive glTF export: for game assets prefer plain `base_color`/`roughness` (flat or '
            'vertex-coloured low-poly look) and say so. `slot` picks a material slot index (default: replace slot 0 or append). Re-using a `material` name edits that '
            'material, so identical looks share one material (game-ready: few materials). `double_sided` disables backface culling (leaves, planes).'),
        'input_schema': _obj({
            'objects': NAMES,
            'material': NAME,
            'base_color': COLOR,
            'metallic': {'type': 'number', 'minimum': 0, 'maximum': 1},
            'roughness': {'type': 'number', 'minimum': 0, 'maximum': 1},
            'alpha': {'type': 'number', 'minimum': 0, 'maximum': 1},
            'ior': {'type': 'number', 'minimum': 1, 'maximum': 3},
            'transmission': {'type': 'number', 'minimum': 0, 'maximum': 1},
            'coat': {'type': 'number', 'minimum': 0, 'maximum': 1},
            'emission': _obj({'color': COLOR, 'strength': {'type': 'number', 'minimum': 0, 'maximum': 1000}}),
            'normal_strength': {'type': 'number', 'minimum': 0, 'maximum': 10},
            'texture': _obj({
                'type': {'type': 'string', 'enum': ['noise', 'voronoi', 'wave', 'checker', 'brick', 'gradient', 'magic']},
                'target': {'type': 'string', 'enum': ['base_color', 'roughness', 'bump', 'emission', 'metallic']},
                'scale': {'type': 'number', 'minimum': 0.001, 'maximum': 10000},
                'detail': {'type': 'number', 'minimum': 0, 'maximum': 16},
                'distortion': {'type': 'number', 'minimum': 0, 'maximum': 100},
                'strength': {'type': 'number', 'minimum': 0, 'maximum': 10},
                'color1': COLOR, 'color2': COLOR,
            }, ['type']),
            'double_sided': {'type': 'boolean'},
            'slot': {'type': 'integer', 'minimum': 0, 'maximum': 31},
        }, ['objects', 'material']),
    },
    {
        'name': 'assign_collection', 'risk': 'act',
        'description': (
            'Move objects into a collection (created if missing) - the way to organise a scene and to choose what gets exported (e.g. a collection "Tree_LOD0"). '
            '`exclusive` (default true) unlinks them from their other collections. `parent_collection` nests a new collection. Use short PascalCase/snake_case names.'),
        'input_schema': _obj({
            'objects': NAMES, 'collection': NAME, 'parent_collection': NAME,
            'exclusive': {'type': 'boolean', 'default': True},
        }, ['objects', 'collection']),
    },
    {
        'name': 'set_origin', 'risk': 'act',
        'description': (
            'Move an object\'s pivot (origin) without moving the geometry in the world. `mode`: bottom_center (origin at the middle of the bottom of the bounding box: the '
            'convention for props, characters and trees that stand on the ground), center_bounds, center_mass, world_origin, location (use `location`, world space). '
            'Game convention: origin at the base, object placed at the world origin or its intended position, scale applied (1,1,1), +Y forward in Godot = -Y in Blender '
            '(the glTF exporter converts axes, do not rotate for that).'),
        'input_schema': _obj({
            'name': NAME,
            'mode': {'type': 'string', 'enum': ['bottom_center', 'center_bounds', 'center_mass', 'world_origin', 'location']},
            'location': V3,
        }, ['name', 'mode']),
    },
    {
        'name': 'uv_unwrap', 'risk': 'act',
        'description': (
            'Generate UV coordinates for mesh objects. `method`: smart_project (default, good for hard-surface/low-poly; `angle_limit_deg` ~66), angle_based (conformal, organic, needs '
            'seams), cube_project, cylinder_project, sphere_project. `island_margin` 0.001..0.05 prevents bleeding in small textures. Run before export if the asset uses textures; flat-colour '
            'low-poly assets need no UVs. Reports islands/overlap-free status as vertex counts only.'),
        'input_schema': _obj({
            'objects': NAMES,
            'method': {'type': 'string', 'enum': ['smart_project', 'angle_based', 'cube_project', 'cylinder_project', 'sphere_project'], 'default': 'smart_project'},
            'angle_limit_deg': {'type': 'number', 'minimum': 1, 'maximum': 89, 'default': 66},
            'island_margin': {'type': 'number', 'minimum': 0, 'maximum': 0.2, 'default': 0.01},
        }, ['objects']),
    },
    {
        'name': 'import_file', 'risk': 'act',
        'description': 'Import a glb/gltf/obj/fbx/stl/blend(append objects) file located INSIDE the project directory (relative path or absolute path under it). Imported objects are returned by name. `collection` puts them in a collection; `scale` multiplies size.',
        'input_schema': _obj({
            'path': {'type': 'string', 'minLength': 1, 'maxLength': 400},
            'collection': NAME,
            'scale': {'type': 'number', 'minimum': 0.0001, 'maximum': 10000, 'default': 1},
        }, ['path']),
    },
    {
        'name': 'export_file', 'risk': 'act',
        'description': (
            'Export to glb/gltf/obj/fbx/stl or save a .blend, ONLY inside the project directory (relative paths; "../" and absolute paths outside are refused). '
            '`format` glb (default; best for Godot: single binary file), gltf, obj, fbx, stl, blend. `objects` limits what is exported (default: everything visible, or the `collection`). '
            'glTF export applies Y-up conversion for you, keeps materials (Principled BSDF factors, image textures; procedural nodes are not exported), uses `apply_modifiers` (default true), '
            'optional `animations`. Run `check_game_ready` first, apply scale, and name the file after the asset (e.g. "models/tree_pine.glb").'),
        'input_schema': _obj({
            'path': {'type': 'string', 'minLength': 1, 'maxLength': 400},
            'format': {'type': 'string', 'enum': ['glb', 'gltf', 'obj', 'fbx', 'stl', 'blend']},
            'objects': {'type': 'array', 'items': NAME, 'maxItems': 500},
            'collection': NAME,
            'apply_modifiers': {'type': 'boolean', 'default': True},
            'animations': {'type': 'boolean', 'default': True},
            'selection_only': {'type': 'boolean', 'default': False},
        }, ['path']),
    },
    {
        'name': 'set_camera', 'risk': 'act',
        'description': (
            'Create or update a camera and (by default) make it the scene camera. Give `location` and either `look_at` (a world point; recommended) or `rotation_deg`. `lens` focal length in mm '
            '(35-50 natural; 85 for portraits), `ortho` true with `ortho_scale` for isometric/game-style views (isometric: rotation [60,0,45], ortho). For a good product-style shot, place the camera '
            'about 2.5x the object size away, 20-35 degrees above, looking at the object centre.'),
        'input_schema': _obj({
            'name': {**NAME, 'default': 'Camera'},
            'location': V3, 'look_at': V3, 'rotation_deg': V3,
            'lens': {'type': 'number', 'minimum': 5, 'maximum': 500},
            'ortho': {'type': 'boolean'},
            'ortho_scale': {'type': 'number', 'minimum': 0.01, 'maximum': 10000},
            'clip_start': {'type': 'number', 'minimum': 0.0001}, 'clip_end': {'type': 'number', 'maximum': 100000},
            'make_active': {'type': 'boolean', 'default': True},
        }),
    },
    {
        'name': 'set_light', 'risk': 'act',
        'description': (
            'Create or update a light. `type`: SUN (direction via `rotation_deg` or `look_at`; energy ~2-5 W/m2), POINT, SPOT (`spot_size_deg`), AREA (`size`; soft key lights). `energy` is in watts '
            '(point/area/spot hundreds-1000 W for room-scale scenes; a sun is strength 1-6). Classic 3-point setup: key (area, 45 degrees to the side/above), fill (weaker, opposite), rim (behind). '
            '`color` linear RGB or hex.'),
        'input_schema': _obj({
            'name': NAME,
            'type': {'type': 'string', 'enum': ['SUN', 'POINT', 'SPOT', 'AREA'], 'default': 'POINT'},
            'energy': {'type': 'number', 'minimum': 0, 'maximum': 1000000},
            'color': COLOR,
            'location': V3, 'rotation_deg': V3, 'look_at': V3,
            'size': {'type': 'number', 'minimum': 0, 'maximum': 1000},
            'spot_size_deg': {'type': 'number', 'minimum': 1, 'maximum': 180},
            'shadow': {'type': 'boolean'},
        }, ['name']),
    },
    {
        'name': 'set_world', 'risk': 'act',
        'description': (
            'Set the world (background/ambient light): `color` flat colour, or `sky_gradient` {horizon, zenith} colours (a quick studio/sky look), with `strength` (0.3-1.5 usual). '
            '`transparent` makes renders have a transparent background (useful for sprites/icons). `unit_system`/`unit_scale` set scene units (default metric, scale 1.0 = 1 unit is 1 m: keep 1.0 for game export).'),
        'input_schema': _obj({
            'color': COLOR,
            'sky_gradient': _obj({'horizon': COLOR, 'zenith': COLOR}, ['horizon', 'zenith']),
            'strength': {'type': 'number', 'minimum': 0, 'maximum': 100},
            'transparent': {'type': 'boolean'},
            'unit_system': {'type': 'string', 'enum': ['METRIC', 'IMPERIAL', 'NONE']},
            'unit_scale': {'type': 'number', 'minimum': 0.0001, 'maximum': 1000},
        }),
    },
    {
        'name': 'viewport_screenshot', 'risk': 'read',
        'description': (
            'LOOK at the scene. Returns a PNG image you can see. Use it after every meaningful change and critique silhouette, proportions, floating/intersecting parts, flipped normals (dark faces) '
            'and colour. `view`: perspective (default 3/4 view), front (looks along +Y), back, right, left, top, bottom, camera (the scene camera). `focus`: all (default), selected, or an object name list in '
            '`objects`. `shading`: solid (default, with matcap-style lighting), wireframe (shows topology: use to check poly density), material (colours/materials). Max 1024 px, default 640. '
            'This renders offscreen so it works without a visible 3D view.'),
        'input_schema': _obj({
            'view': {'type': 'string', 'enum': ['perspective', 'front', 'back', 'right', 'left', 'top', 'bottom', 'camera'], 'default': 'perspective'},
            'shading': {'type': 'string', 'enum': ['solid', 'wireframe', 'material'], 'default': 'solid'},
            'focus': {'type': 'string', 'enum': ['all', 'selected'], 'default': 'all'},
            'objects': {'type': 'array', 'items': NAME, 'maxItems': 200},
            'width': {'type': 'integer', 'minimum': 64, 'maximum': 1024, 'default': 640},
            'height': {'type': 'integer', 'minimum': 64, 'maximum': 1024, 'default': 480},
        }),
    },
    {
        'name': 'render_preview', 'risk': 'read',
        'description': (
            'Render the scene camera to a PNG you can see (lit, with materials, shadows and the world). Capped at 1280 px and low samples so it is fast. `engine`: auto (Cycles on the CPU: reliable everywhere, a few seconds), '
            'eevee (GPU), cycles, workbench (GPU). If there is no camera one is created and framed on the scene. `save_to` optionally writes the PNG inside the project directory. Use it for final beauty checks; '
            'use viewport_screenshot for fast iteration.'),
        'input_schema': _obj({
            'engine': {'type': 'string', 'enum': ['auto', 'eevee', 'cycles', 'workbench'], 'default': 'auto'},
            'samples': {'type': 'integer', 'minimum': 1, 'maximum': 256, 'default': 24},
            'width': {'type': 'integer', 'minimum': 64, 'maximum': 1280, 'default': 640},
            'height': {'type': 'integer', 'minimum': 64, 'maximum': 1280, 'default': 480},
            'camera': NAME,
            'save_to': {'type': 'string', 'maxLength': 400},
        }),
    },
    {
        'name': 'delete_object', 'risk': 'act',
        'description': 'Delete objects by name (optionally with children). Their orphaned mesh data and unused materials are purged. Deleting is undoable with the `undo` tool.',
        'input_schema': _obj({'names': NAMES, 'with_children': {'type': 'boolean', 'default': False}}, ['names']),
    },
    {
        'name': 'undo', 'risk': 'act',
        'description': 'Undo. `steps` (default 1) undo steps, or `checkpoint: "request_start"` to return to the state saved at the start of the user\'s current request (the safe way to abandon a failed approach).',
        'input_schema': _obj({
            'steps': {'type': 'integer', 'minimum': 1, 'maximum': 50, 'default': 1},
            'checkpoint': {'type': 'string', 'enum': ['request_start']},
        }),
    },
    {
        'name': 'duplicate_object', 'risk': 'act',
        'description': 'Duplicate an object (`linked: true` shares mesh data: cheaper and keeps edits in sync, good for repeated props). Returns the new name. Optionally offset it.',
        'input_schema': _obj({
            'name': NAME, 'new_name': NAME, 'offset': V3, 'location': V3,
            'linked': {'type': 'boolean', 'default': False}, 'collection': NAME,
        }, ['name']),
    },
    {
        'name': 'set_shading', 'risk': 'act',
        'description': 'Set flat or smooth shading on mesh objects. `mode`: flat (faceted low-poly), smooth, auto (smooth but keeps edges sharper than `angle_deg` crisp; best for most hard-surface and stylised assets).',
        'input_schema': _obj({
            'objects': NAMES, 'mode': {'type': 'string', 'enum': ['flat', 'smooth', 'auto']},
            'angle_deg': {'type': 'number', 'minimum': 1, 'maximum': 180, 'default': 40},
        }, ['objects', 'mode']),
    },
    {
        'name': 'check_game_ready', 'risk': 'read',
        'description': (
            'Audit objects against the game-ready checklist and return concrete problems: unapplied scale/rotation, negative scale, triangle budget (`budget_tris`), n-gons, loose geometry, '
            'non-manifold edges, missing/duplicate UVs when textured, too many materials, default names ("Cube.003"), origin far from the base, unapplied modifiers, tiny/huge size. '
            'Fix what it lists, then call it again until `ok` is true, then export_file.'),
        'input_schema': _obj({
            'objects': {'type': 'array', 'items': NAME, 'maxItems': 500},
            'budget_tris': {'type': 'integer', 'minimum': 10, 'maximum': 10000000, 'default': 5000},
        }),
    },
    {
        'name': 'create_armature', 'risk': 'act',
        'description': (
            'Create an armature from a bone list for simple rigs. `bones`: [{name, head:[x,y,z], tail:[x,y,z], parent:name?, connect?:bool}] in world metres. Optionally bind meshes '
            '(`bind` names) with automatic weights. Typical humanoid: Hips, Spine, Chest, Neck, Head, Upper/Lower arm and leg L/R with `.L`/`.R` suffixes (Godot-friendly names). Keep bone counts low.'),
        'input_schema': _obj({
            'name': NAME,
            'bones': {'type': 'array', 'minItems': 1, 'maxItems': 200, 'items': _obj({
                'name': NAME, 'head': V3, 'tail': V3, 'parent': NAME, 'connect': {'type': 'boolean'}, 'roll_deg': {'type': 'number'},
            }, ['name', 'head', 'tail'])},
            'bind': {'type': 'array', 'items': NAME, 'maxItems': 100},
            'bind_method': {'type': 'string', 'enum': ['auto_weights', 'envelope', 'empty_groups', 'rigid'], 'default': 'auto_weights'},
        }, ['name', 'bones']),
    },
    {
        'name': 'pose_keyframes', 'risk': 'act',
        'description': (
            'Create an animation clip (an Action) by keyframing bone rotations/locations: {armature, action: "walk", frame_start, frame_end, loop, keyframes:[{frame, bones:{BoneName:{rotation_deg:[x,y,z], location:[x,y,z]}}}]}. '
            'Rotations are local Euler XYZ degrees relative to the rest pose. For a 24 fps walk cycle: 25 frames, contact/passing/contact poses, last frame = first frame when `loop`. Name clips idle, walk, run, attack '
            'so Godot imports them as named animations. Use `preset` (idle|walk|attack) to auto-generate a simple clip for armatures that follow the humanoid naming of create_armature; you can still pass keyframes to refine.'),
        'input_schema': _obj({
            'armature': NAME,
            'action': {'type': 'string', 'minLength': 1, 'maxLength': 63},
            'preset': {'type': 'string', 'enum': ['idle', 'walk', 'attack']},
            'frame_start': {'type': 'integer', 'minimum': 0, 'maximum': 100000, 'default': 1},
            'frame_end': {'type': 'integer', 'minimum': 1, 'maximum': 100000},
            'loop': {'type': 'boolean', 'default': True},
            'keyframes': {'type': 'array', 'maxItems': 500, 'items': _obj({
                'frame': {'type': 'integer', 'minimum': 0, 'maximum': 100000},
                'bones': {'type': 'object'},
            }, ['frame', 'bones'])},
        }, ['armature', 'action']),
    },
    {
        'name': 'run_python', 'risk': 'critical',
        'description': (
            'LAST RESORT: run generated Blender Python (bpy/bmesh/mathutils/math/random/colorsys/itertools/collections only) when no structured tool can do the job, e.g. procedural geometry, '
            'many-object scatter, curves, lattice-like loops. The code is statically checked (no os/sys/subprocess/socket/ctypes, no open/eval/exec/__import__, no dunder or escape attributes, no bpy.ops.wm/script/'
            'import_/export_, no bpy.app/utils/path), shown to the user for approval when review mode is on, time-limited (20 s) and its print() output is returned. Do NOT try to read/write files or open the network. '
            'Prefer bmesh over bpy.ops for geometry (ops need UI context). Name every object you create, put results in variables and print() the names/counts so you can verify. `bpy`, `bmesh`, `mathutils`, `math`, `random`, `C` (context) and `D` (data) are pre-imported.'),
        'input_schema': _obj({
            'code': {'type': 'string', 'minLength': 1, 'maxLength': 100000},
            'description': {'type': 'string', 'maxLength': 300},
        }, ['code']),
    },
]

BY_NAME = {s['name']: s for s in SPECS}
REVIEW_ALWAYS = {'run_python'}


def api_tools():
    """Tool list in the Anthropic Messages API format."""
    return [{'name': s['name'], 'description': s['description'], 'input_schema': s['input_schema']} for s in SPECS]
