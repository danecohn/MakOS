"""Tool implementations. Everything here runs on Blender's MAIN thread and imports bpy.

Each function takes the validated input dict and returns a JSON-able dict. Image-producing tools put PNG bytes
under the private key `_png` (list of bytes); the dispatcher turns them into base64 images.
"""
import base64
import colorsys
import math
import os
import random
import re
import tempfile
import time
from pathlib import Path

import bmesh
import bpy
import mathutils
from mathutils import Euler, Matrix, Vector

from . import config, safety, toolspecs
from .schema import ValidationError, validate


class ToolError(Exception):
    """A problem the model can fix; the message is returned to it."""
    code = -32000

    def __init__(self, message, code=-32000):
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------- helpers

def _r(v, n=4):
    if isinstance(v, (int, float)):
        return round(float(v), n)
    return [_r(x, n) for x in v]


def _srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def color4(value, default=None):
    """Hex string or 3/4 floats (linear) -> (r,g,b,a)."""
    if value is None:
        return default
    if isinstance(value, str):
        m = re.fullmatch(r'#?([0-9a-fA-F]{6})([0-9a-fA-F]{2})?', value.strip())
        if not m:
            raise ToolError(f'colour "{value}" is not a #rrggbb hex string')
        h = m.group(1)
        rgb = [_srgb_to_linear(int(h[i:i + 2], 16) / 255) for i in (0, 2, 4)]
        a = int(m.group(2), 16) / 255 if m.group(2) else 1.0
        return (*rgb, a)
    vals = [float(x) for x in value]
    return (vals[0], vals[1], vals[2], vals[3] if len(vals) > 3 else 1.0)


def scene():
    return bpy.context.scene


def get_obj(name, types=None):
    obj = bpy.data.objects.get(name)
    if obj is None:
        near = [o.name for o in bpy.data.objects if name.lower() in o.name.lower() or o.name.lower() in name.lower()][:8]
        hint = f' Similar: {near}.' if near else f' Existing objects: {[o.name for o in bpy.data.objects][:30]}.'
        raise ToolError(f'object "{name}" does not exist.{hint}')
    if types and obj.type not in types:
        raise ToolError(f'object "{name}" is a {obj.type}, expected {"/".join(types)}')
    return obj


def get_objs(names, types=None):
    return [get_obj(n, types) for n in names]


def settle():
    bpy.context.view_layer.update()


def get_collection(name, create=True, parent=None):
    coll = bpy.data.collections.get(name)
    if coll is None:
        if not create:
            raise ToolError(f'collection "{name}" does not exist')
        coll = bpy.data.collections.new(name)
        par = bpy.data.collections.get(parent) if parent else None
        (par or scene().collection).children.link(coll)
    return coll


def link_obj(obj, collection=None):
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    target = get_collection(collection) if collection else scene().collection
    target.objects.link(obj)


def unique_name_note(requested, obj):
    return {} if obj.name == requested else {'note': f'name "{requested}" was taken; created "{obj.name}"'}


def mesh_counts(obj, evaluated=True):
    if obj.type != 'MESH':
        return {}
    if evaluated and obj.modifiers:
        dg = bpy.context.evaluated_depsgraph_get()
        ev = obj.evaluated_get(dg)
        me = ev.to_mesh()
        try:
            me.calc_loop_triangles()
            return {'vertices': len(me.vertices), 'faces': len(me.polygons), 'triangles': len(me.loop_triangles)}
        finally:
            ev.to_mesh_clear()
    me = obj.data
    me.calc_loop_triangles()
    return {'vertices': len(me.vertices), 'faces': len(me.polygons), 'triangles': len(me.loop_triangles)}


def world_bbox(obj):
    pts = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    mn = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    mx = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return mn, mx


def scene_bbox(objs):
    mn = Vector((1e18,) * 3)
    mx = Vector((-1e18,) * 3)
    found = False
    for o in objs:
        if o.type in {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META', 'ARMATURE'}:
            a, b = world_bbox(o)
            mn = Vector((min(mn.x, a.x), min(mn.y, a.y), min(mn.z, a.z)))
            mx = Vector((max(mx.x, b.x), max(mx.y, b.y), max(mx.z, b.z)))
            found = True
    return (mn, mx) if found else (Vector((-1, -1, 0)), Vector((1, 1, 2)))


def mode_object():
    try:
        if bpy.context.object and bpy.context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
    except Exception:
        pass


def select_only(objs):
    mode_object()
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in objs:
        o.select_set(True)
    if objs:
        bpy.context.view_layer.objects.active = objs[0]


def op_context(objs, active=None):
    """Context override for bpy.ops that need an active/selected object (works in background mode)."""
    active = active or objs[0]
    select_only(objs)
    return bpy.context.temp_override(object=active, active_object=active, selected_objects=list(objs),
                                     selected_editable_objects=list(objs), view_layer=bpy.context.view_layer,
                                     scene=bpy.context.scene)


def to_euler(deg):
    return Euler([math.radians(x) for x in deg], 'XYZ')


def apply_transform_args(obj, a):
    if 'location' in a:
        obj.location = a['location']
    if 'rotation_deg' in a:
        obj.rotation_euler = to_euler(a['rotation_deg'])
    if 'scale' in a:
        obj.scale = a['scale']


def describe(obj, detail='full'):
    mn, mx = world_bbox(obj) if obj.type != 'EMPTY' else (obj.location, obj.location)
    d = {
        'name': obj.name, 'type': obj.type,
        'collection': obj.users_collection[0].name if obj.users_collection else None,
        'parent': obj.parent.name if obj.parent else None,
        'location': _r(obj.location), 'rotation_deg': _r([math.degrees(x) for x in obj.rotation_euler]),
        'scale': _r(obj.scale), 'dimensions': _r(obj.dimensions),
        'bbox_min': _r(mn), 'bbox_max': _r(mx),
        'hidden': obj.hide_get() if obj.name in bpy.context.view_layer.objects else None,
    }
    if obj.type == 'MESH':
        d.update(mesh_counts(obj))
        d['materials'] = [s.material.name if s.material else None for s in obj.material_slots]
        d['modifiers'] = [{'name': m.name, 'type': m.type} for m in obj.modifiers]
        d['uv_layers'] = [u.name for u in obj.data.uv_layers]
        if obj.data.shape_keys:
            d['shape_keys'] = [k.name for k in obj.data.shape_keys.key_blocks]
        if obj.vertex_groups:
            d['vertex_groups'] = len(obj.vertex_groups)
    elif obj.type == 'LIGHT':
        d['light'] = {'type': obj.data.type, 'energy': _r(obj.data.energy), 'color': _r(list(obj.data.color))}
    elif obj.type == 'CAMERA':
        d['camera'] = {'lens': _r(obj.data.lens), 'ortho': obj.data.type == 'ORTHO'}
    elif obj.type == 'ARMATURE':
        d['bones'] = [b.name for b in obj.data.bones][:100]
        d['actions'] = [a.name for a in bpy.data.actions]
    return d


def collection_tree(coll):
    return {'name': coll.name, 'objects': [o.name for o in coll.objects], 'children': [collection_tree(c) for c in coll.children]}


# ---------------------------------------------------------------- tools

def scene_info(a):
    sc = scene()
    settle()
    objs = [get_obj(n) for n in a['names']] if a.get('names') else list(sc.objects)
    totals = {'objects': len(sc.objects), 'meshes': 0, 'vertices': 0, 'faces': 0, 'triangles': 0}
    for o in sc.objects:
        if o.type == 'MESH':
            c = mesh_counts(o)
            totals['meshes'] += 1
            for k in ('vertices', 'faces', 'triangles'):
                totals[k] += c.get(k, 0)
    mn, mx = scene_bbox([o for o in sc.objects if o.type == 'MESH'])
    summary = a.get('detail') == 'summary' and len(objs) > 40
    out = {
        'scene': sc.name, 'file': bpy.data.filepath or None, 'project_dir': str(config.project_dir()),
        'units': {'system': sc.unit_settings.system, 'scale_length': sc.unit_settings.scale_length, 'length_unit': sc.unit_settings.length_unit},
        'axes': 'Blender is Z-up, -Y forward; the glTF exporter converts to Y-up for Godot',
        'frame': {'start': sc.frame_start, 'end': sc.frame_end, 'current': sc.frame_current, 'fps': sc.render.fps},
        'active': bpy.context.view_layer.objects.active.name if bpy.context.view_layer.objects.active else None,
        'selected': [o.name for o in sc.objects if o.select_get()],
        'camera': sc.camera.name if sc.camera else None,
        'collections': collection_tree(sc.collection),
        'totals': totals, 'bbox_min': _r(mn), 'bbox_max': _r(mx),
        'materials': [m.name for m in bpy.data.materials if m.users],
        'actions': [x.name for x in bpy.data.actions],
        'render_engine': sc.render.engine,
    }
    if summary:
        out['objects'] = [{'name': o.name, 'type': o.type, 'location': _r(o.location)} for o in objs]
        out['note'] = 'summary only: pass names for detail'
    else:
        out['objects'] = [describe(o) for o in objs]
    return out


def _bm_primitive(bm, kind, a):
    size = a.get('size', 2.0)
    radius = a.get('radius', 1.0)
    depth = a.get('depth', 2.0)
    seg = a.get('segments')
    mat = Matrix.Identity(4)
    if kind == 'cube':
        bmesh.ops.create_cube(bm, size=size)
    elif kind == 'plane':
        bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=size / 2)
    elif kind == 'grid':
        n = seg or 10
        bmesh.ops.create_grid(bm, x_segments=n, y_segments=n, size=size / 2)
    elif kind == 'uv_sphere':
        bmesh.ops.create_uvsphere(bm, u_segments=seg or 16, v_segments=a.get('rings', 8), radius=radius)
    elif kind == 'ico_sphere':
        bmesh.ops.create_icosphere(bm, subdivisions=a.get('subdivisions', 2), radius=radius)
    elif kind in ('cylinder', 'cone'):
        r2 = a.get('radius2', radius if kind == 'cylinder' else 0.0)
        bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=seg or 12, radius1=radius, radius2=r2, depth=depth)
    elif kind == 'circle':
        bmesh.ops.create_circle(bm, cap_ends=True, cap_tris=False, segments=seg or 16, radius=radius)
    elif kind == 'monkey':
        bmesh.ops.create_monkey(bm)
        bmesh.ops.scale(bm, vec=(radius,) * 3, verts=bm.verts)
    elif kind == 'torus':
        major, minor = radius, a.get('minor_radius', radius * 0.25)
        ns, nr = seg or 24, a.get('rings', 12)
        verts = [[bm.verts.new((((major + minor * math.cos(2 * math.pi * j / nr)) * math.cos(2 * math.pi * i / ns)),
                                ((major + minor * math.cos(2 * math.pi * j / nr)) * math.sin(2 * math.pi * i / ns)),
                                minor * math.sin(2 * math.pi * j / nr))) for j in range(nr)] for i in range(ns)]
        for i in range(ns):
            for j in range(nr):
                bm.faces.new((verts[i][j], verts[(i + 1) % ns][j], verts[(i + 1) % ns][(j + 1) % nr], verts[i][(j + 1) % nr]))
    else:
        raise ToolError(f'unknown primitive type {kind}')


def create_primitive(a):
    mode_object()
    kind = a['type']
    if kind == 'empty':
        obj = bpy.data.objects.new(a['name'], None)
        obj.empty_display_type = 'PLAIN_AXES'
    else:
        bm = bmesh.new()
        _bm_primitive(bm, kind, a)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        me = bpy.data.meshes.new(a['name'])
        bm.to_mesh(me)
        bm.free()
        for p in me.polygons:
            p.use_smooth = bool(a.get('smooth'))
        me.update()
        obj = bpy.data.objects.new(a['name'], me)
    (get_collection(a['collection']) if a.get('collection') else scene().collection).objects.link(obj)
    apply_transform_args(obj, a)
    if a.get('material') and obj.type == 'MESH':
        mat = bpy.data.materials.get(a['material'])
        if mat is None:
            raise ToolError(f'material "{a["material"]}" does not exist; create it with set_material')
        obj.data.materials.append(mat)
    select_only([obj])
    settle()
    return {'name': obj.name, **unique_name_note(a['name'], obj), **describe(obj)}


def transform_object(a):
    obj = get_obj(a['name'])
    rel = a.get('relative')
    if 'dimensions' in a:
        dims = obj.dimensions
        sc_ = Vector(obj.scale)
        for i in range(3):
            if dims[i] > 1e-9:
                sc_[i] = obj.scale[i] * a['dimensions'][i] / dims[i]
        obj.scale = sc_
    if 'location' in a:
        obj.location = (Vector(obj.location) + Vector(a['location'])) if rel else a['location']
    if 'rotation_deg' in a:
        if rel:
            obj.rotation_euler = Euler([obj.rotation_euler[i] + math.radians(a['rotation_deg'][i]) for i in range(3)], 'XYZ')
        else:
            obj.rotation_euler = to_euler(a['rotation_deg'])
    if 'scale' in a:
        obj.scale = [obj.scale[i] * a['scale'][i] for i in range(3)] if rel else a['scale']
    if 'parent' in a:
        if a['parent'] is None:
            mw = obj.matrix_world.copy()
            obj.parent = None
            obj.matrix_world = mw
        else:
            par = get_obj(a['parent'])
            if par is obj:
                raise ToolError('cannot parent an object to itself')
            settle()
            mw = obj.matrix_world.copy()
            obj.parent = par
            obj.matrix_parent_inverse = par.matrix_world.inverted()
            obj.matrix_world = mw
    if a.get('apply'):
        _apply_transforms(obj, a['apply'])
    settle()
    return describe(obj)


def _apply_transforms(obj, which):
    if obj.type != 'MESH':
        raise ToolError('apply only works on mesh objects')
    if obj.data.users > 1:
        obj.data = obj.data.copy()
    loc, rot, scl = obj.matrix_basis.decompose()
    m = Matrix.Identity(4)
    new_loc, new_rot, new_scl = Vector(loc), rot.copy(), Vector(scl)
    if 'scale' in which:
        m = Matrix.Diagonal((*scl, 1.0)) @ m
        new_scl = Vector((1, 1, 1))
    if 'rotation' in which:
        m = rot.to_matrix().to_4x4() @ m
        new_rot = mathutils.Quaternion()
    if 'location' in which:
        m = Matrix.Translation(loc) @ m
        new_loc = Vector((0, 0, 0))
    for child in obj.children:
        child.matrix_parent_inverse = m @ child.matrix_parent_inverse
    obj.data.transform(m)
    if obj.rotation_mode == 'QUATERNION':
        obj.rotation_quaternion = new_rot
    else:
        obj.rotation_euler = new_rot.to_euler()
    obj.location, obj.scale = new_loc, new_scl
    obj.data.update()


MOD_ALIASES = {
    'BEVEL': 'BEVEL', 'SUBSURF': 'SUBSURF', 'MIRROR': 'MIRROR', 'ARRAY': 'ARRAY', 'BOOLEAN': 'BOOLEAN', 'SOLIDIFY': 'SOLIDIFY',
    'DISPLACE': 'DISPLACE', 'DECIMATE': 'DECIMATE', 'WEIGHTED_NORMAL': 'WEIGHTED_NORMAL', 'EDGE_SPLIT': 'EDGE_SPLIT',
    'TRIANGULATE': 'TRIANGULATE', 'SMOOTH': 'SMOOTH', 'REMESH': 'REMESH', 'WIREFRAME': 'WIREFRAME', 'SCREW': 'SCREW',
    'SIMPLE_DEFORM': 'SIMPLE_DEFORM', 'SHRINKWRAP': 'SHRINKWRAP', 'CURVE': 'CURVE', 'LATTICE': 'LATTICE', 'WAVE': 'WAVE',
    'SKIN': 'SKIN', 'MASK': 'MASK',
}


def _set_prop(owner, key, value, what):
    props = owner.bl_rna.properties
    if key not in props or key in ('rna_type', 'type', 'name'):
        valid = sorted(k for k in props.keys() if k not in ('rna_type', 'type', 'name'))
        raise ToolError(f'{what} has no property "{key}". Valid: {valid}')
    prop = props[key]
    try:
        if prop.type == 'POINTER':
            if value is None:
                setattr(owner, key, None)
            else:
                target = bpy.data.objects.get(value) if prop.fixed_type.identifier == 'Object' else \
                    getattr(bpy.data, 'textures').get(value) if prop.fixed_type.identifier == 'Texture' else None
                if target is None:
                    raise ToolError(f'{what}.{key} needs the name of an existing {prop.fixed_type.identifier}; "{value}" not found')
                setattr(owner, key, target)
        elif prop.type == 'ENUM' and prop.is_enum_flag:
            setattr(owner, key, set(value) if isinstance(value, (list, tuple)) else {value})
        elif prop.type in ('FLOAT', 'INT', 'BOOLEAN') and getattr(prop, 'array_length', 0):
            setattr(owner, key, value)
        else:
            setattr(owner, key, value)
    except ToolError:
        raise
    except (TypeError, ValueError, AttributeError) as e:
        extra = ''
        if prop.type == 'ENUM':
            extra = f' Valid: {[i.identifier for i in prop.enum_items]}'
        raise ToolError(f'{what}.{key} = {value!r} was rejected: {e}.{extra}') from None


def add_modifier(a):
    obj = get_obj(a['object'])
    action = a.get('action', 'add')
    mode_object()
    if action in ('apply', 'remove'):
        name = a.get('modifier_name')
        mod = obj.modifiers.get(name) if name else (obj.modifiers[-1] if obj.modifiers else None)
        if mod is None:
            raise ToolError(f'{obj.name} has no modifier {name or "(any)"}; modifiers: {[m.name for m in obj.modifiers]}')
        if action == 'remove':
            obj.modifiers.remove(mod)
        else:
            _apply_modifier(obj, mod)
        return {'object': obj.name, **mesh_counts(obj), 'modifiers': [m.name for m in obj.modifiers]}
    if obj.type not in ('MESH', 'CURVE', 'SURFACE', 'FONT', 'META', 'LATTICE'):
        raise ToolError(f'{obj.name} ({obj.type}) cannot take modifiers')
    if 'type' not in a:
        raise ToolError('add_modifier needs "type" when action is add')
    mod = obj.modifiers.new(a.get('modifier_name') or a['type'].title().replace('_', ''), MOD_ALIASES[a['type']])
    if a['type'] == 'DISPLACE' and not (a.get('params') or {}).get('texture'):
        tex = bpy.data.textures.new(f'{obj.name}_displace', 'CLOUDS')
        mod.texture = tex
    for k, v in (a.get('params') or {}).items():
        _set_prop(mod, k, v, f'{a["type"]} modifier')
    result = {'object': obj.name, 'modifier': mod.name}
    if a.get('apply'):
        _apply_modifier(obj, mod)
        result['applied'] = True
    settle()
    result.update(mesh_counts(obj))
    result['modifiers'] = [m.name for m in obj.modifiers]
    return result


def _apply_modifier(obj, mod):
    if obj.type != 'MESH':
        raise ToolError('only mesh modifiers can be applied here')
    if obj.data.users > 1:
        obj.data = obj.data.copy()
    # Make the target modifier the only enabled one on the stack so the evaluated mesh is exactly it
    # (applying a modifier that is not first still applies it at the current stack position in Blender, so we mimic that
    # by evaluating modifiers up to and including `mod`).
    mods = list(obj.modifiers)
    idx = mods.index(mod)
    saved = [(m, m.show_viewport) for m in mods]
    try:
        for i, m in enumerate(mods):
            m.show_viewport = i <= idx
        settle()
        dg = bpy.context.evaluated_depsgraph_get()
        ev = obj.evaluated_get(dg)
        new = bpy.data.meshes.new_from_object(ev, preserve_all_data_layers=True, depsgraph=dg)
    finally:
        for m, v in saved:
            m.show_viewport = v
    old = obj.data
    for i in range(idx + 1):
        obj.modifiers.remove(mods[i])
    obj.data = new
    new.name = old.name
    for m in old.materials:
        pass
    if not new.materials:
        for m in old.materials:
            new.materials.append(m)
    if old.users == 0:
        bpy.data.meshes.remove(old)
    settle()


# ---- edit_mesh

def _centre(elem, mode):
    if mode == 'vert':
        return elem.co
    if mode == 'edge':
        return (elem.verts[0].co + elem.verts[1].co) / 2
    return elem.calc_center_median()


FACING = {'top': (0, 0, 1), 'bottom': (0, 0, -1), 'front': (0, -1, 0), 'back': (0, 1, 0), 'right': (1, 0, 0), 'left': (-1, 0, 0)}
AXIS = {'x': 0, 'y': 1, 'z': 2}


def select_elements(bm, obj, sel, default_mode='face'):
    sel = sel or {}
    mode = sel.get('mode', default_mode)
    seq = {'vert': bm.verts, 'edge': bm.edges, 'face': bm.faces}[mode]
    seq.ensure_lookup_table()
    chosen = []
    mw = obj.matrix_world
    nm = mw.to_3x3().inverted_safe().transposed()
    for el in seq:
        ok = True
        if sel.get('indices') is not None and el.index not in sel['indices']:
            ok = False
        if ok and sel.get('axis_range'):
            r = sel['axis_range']
            ax = AXIS.get(str(r.get('axis', 'z')).lower())
            if ax is None:
                raise ToolError('axis_range.axis must be x, y or z')
            p = _centre(el, mode)
            if r.get('space', 'local') == 'world':
                p = mw @ p
            v = p[ax]
            if 'min' in r and v < r['min'] - 1e-6:
                ok = False
            if 'max' in r and v > r['max'] + 1e-6:
                ok = False
        if ok and sel.get('box'):
            b = sel['box']
            p = _centre(el, mode)
            for i in range(3):
                if p[i] < b['min'][i] - 1e-6 or p[i] > b['max'][i] + 1e-6:
                    ok = False
        if ok and (sel.get('normal') or sel.get('facing')):
            if mode != 'face':
                raise ToolError('"normal"/"facing" selections need mode "face"')
            if sel.get('facing'):
                d, md = Vector(FACING[sel['facing']]), 0.7
            else:
                d, md = Vector(sel['normal']['direction']).normalized(), sel['normal'].get('min_dot', 0.7)
            if el.normal.dot(d) < md:
                ok = False
        if ok and sel.get('area'):
            if mode != 'face':
                raise ToolError('"area" selections need mode "face"')
            ar = el.calc_area()
            if ('min' in sel['area'] and ar < sel['area']['min']) or ('max' in sel['area'] and ar > sel['area']['max']):
                ok = False
        if ok and 'material_index' in sel and mode == 'face' and el.material_index != sel['material_index']:
            ok = False
        if sel.get('invert'):
            ok = not ok
        if ok:
            chosen.append(el)
    return mode, chosen


def _verts_of(elems, mode):
    vs = set()
    for e in elems:
        if mode == 'vert':
            vs.add(e)
        else:
            vs.update(e.verts)
    return list(vs)


def edit_mesh(a):
    obj = get_obj(a['object'], ['MESH'])
    mode_object()
    if obj.data.users > 1:
        obj.data = obj.data.copy()
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    before = (len(bm.verts), len(bm.faces))
    log = []
    try:
        for n, spec in enumerate(a['operations']):
            op = spec['op']
            sel = spec.get('select')
            default = {'extrude_faces': 'face', 'inset_faces': 'face', 'bevel': 'edge', 'delete': 'face', 'flip_normals': 'face',
                       'set_material_index': 'face', 'extrude_edges': 'edge', 'mark_sharp': 'edge', 'subdivide': 'edge'}.get(op, 'vert')
            if op in ('merge_by_distance', 'loop_cut', 'recalc_normals', 'triangulate', 'fill_hole', 'smooth_shading', 'dissolve') and not sel:
                sel = {'all': True, 'mode': default}
            if op == 'bevel' and spec.get('mode') == 'vert':
                default = 'vert'
            if op == 'delete' and spec.get('mode'):
                default = spec['mode']
            mode, elems = select_elements(bm, obj, sel, default)
            ctx = f'operation {n} ({op})'
            if not elems and op not in ('loop_cut',) and not a.get('allow_empty'):
                raise ToolError(f'{ctx}: the selection matched 0 {mode}s of {obj.name} (mesh has {len(bm.verts)} verts/{len(bm.faces)} faces). '
                                'Check the descriptor (axes are LOCAL by default; use scene_info bbox) or pass allow_empty.')
            info = {'op': op, 'selected': len(elems), 'mode': mode}
            if op == 'extrude_faces':
                off = float(spec.get('offset', 0.1))
                res = bmesh.ops.extrude_face_region(bm, geom=elems)
                newv = [g for g in res['geom'] if isinstance(g, bmesh.types.BMVert)]
                newf = [g for g in res['geom'] if isinstance(g, bmesh.types.BMFace)]
                # move along averaged face normal per face group
                if newf:
                    nrm = sum((f.normal for f in newf), Vector()).normalized() if len(newf) > 0 else Vector((0, 0, 1))
                    for f in newf:
                        for v in f.verts:
                            pass
                    # per-vertex: use its own face normal(s) average so curved regions extrude outward
                    vn = {}
                    for f in newf:
                        for v in f.verts:
                            vn.setdefault(v, Vector())
                            vn[v] += f.normal
                    for v, n_ in vn.items():
                        if n_.length > 1e-9:
                            v.co += n_.normalized() * off
            elif op == 'inset_faces':
                bmesh.ops.inset_region(bm, faces=elems, thickness=float(spec.get('thickness', 0.05)), depth=float(spec.get('depth', 0.0)),
                                       use_even_offset=True, use_boundary=True)
            elif op == 'bevel':
                geom = elems
                bmesh.ops.bevel(bm, geom=geom, offset=float(spec.get('offset', 0.05)), segments=int(spec.get('segments', 1)),
                                affect='VERTICES' if mode == 'vert' else 'EDGES', profile=float(spec.get('profile', 0.5)))
            elif op == 'loop_cut':
                axis = AXIS[str(spec.get('axis', 'z')).lower()]
                cuts = int(spec.get('cuts', 1))
                coords = [v.co[axis] for v in bm.verts]
                lo, hi = min(coords), max(coords)
                if spec.get('position') is not None:
                    positions = [float(spec['position'])]
                else:
                    positions = [lo + (hi - lo) * (i + 1) / (cuts + 1) for i in range(cuts)]
                no = Vector((1 if axis == 0 else 0, 1 if axis == 1 else 0, 1 if axis == 2 else 0))
                for p in positions:
                    co = Vector((0, 0, 0)); co[axis] = p
                    bmesh.ops.bisect_plane(bm, geom=list(bm.verts) + list(bm.edges) + list(bm.faces), plane_co=co, plane_no=no, dist=1e-6)
            elif op == 'subdivide':
                edges = elems if mode == 'edge' else list({e for el in elems for e in (el.edges if mode == 'face' else [])})
                if mode == 'vert':
                    edges = list({e for v in elems for e in v.link_edges})
                bmesh.ops.subdivide_edges(bm, edges=edges, cuts=int(spec.get('cuts', 1)), smooth=float(spec.get('smooth', 0.0)),
                                          use_grid_fill=True)
            elif op == 'merge_by_distance':
                verts = _verts_of(elems, mode)
                bmesh.ops.remove_doubles(bm, verts=verts, dist=float(spec.get('distance', 0.0001)))
            elif op == 'delete':
                ctxmap = {'vert': 'VERTS', 'edge': 'EDGES', 'face': 'FACES'}
                bmesh.ops.delete(bm, geom=elems, context=ctxmap[mode])
            elif op in ('translate', 'scale', 'rotate'):
                verts = _verts_of(elems, mode)
                if op == 'translate':
                    off = Vector(spec.get('offset', (0, 0, 0)))
                    for v in verts:
                        v.co += off
                elif op == 'scale':
                    f = spec.get('factor', 1.0)
                    f = Vector((f, f, f)) if isinstance(f, (int, float)) else Vector(f)
                    c = Vector((0, 0, 0)) if spec.get('center') == 'origin' else sum((v.co for v in verts), Vector()) / len(verts)
                    for v in verts:
                        d = v.co - c
                        v.co = c + Vector((d.x * f.x, d.y * f.y, d.z * f.z))
                else:
                    ax = str(spec.get('axis', 'z')).upper()
                    m = Matrix.Rotation(math.radians(float(spec.get('angle_deg', 0))), 3, ax)
                    c = sum((v.co for v in verts), Vector()) / len(verts)
                    for v in verts:
                        v.co = c + m @ (v.co - c)
            elif op == 'extrude_edges':
                res = bmesh.ops.extrude_edge_only(bm, edges=elems)
                off = Vector(spec.get('offset', (0, 0, 0.1)))
                for g in res['geom']:
                    if isinstance(g, bmesh.types.BMVert):
                        g.co += off
            elif op == 'fill_hole':
                bmesh.ops.holes_fill(bm, edges=[e for e in bm.edges if e.is_boundary], sides=int(spec.get('sides', 0)))
            elif op == 'dissolve':
                bmesh.ops.dissolve_limit(bm, angle_limit=math.radians(float(spec.get('angle_deg', 5))), verts=list(bm.verts), edges=list(bm.edges))
            elif op == 'flip_normals':
                bmesh.ops.reverse_faces(bm, faces=elems)
            elif op == 'recalc_normals':
                bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
            elif op == 'triangulate':
                bmesh.ops.triangulate(bm, faces=list(bm.faces))
            elif op == 'smooth_shading':
                for f in (elems if mode == 'face' else bm.faces):
                    f.smooth = bool(spec.get('smooth', True))
            elif op == 'set_material_index':
                for f in elems:
                    f.material_index = int(spec.get('index', 0))
            elif op == 'mark_sharp':
                ang = math.radians(float(spec.get('angle_deg', 30)))
                for e in bm.edges:
                    if len(e.link_faces) == 2:
                        e.smooth = e.calc_face_angle(0) <= ang
            else:
                raise ToolError(f'{ctx}: unknown op "{op}". Ops: extrude_faces, inset_faces, bevel, loop_cut, subdivide, merge_by_distance, delete, translate, scale, rotate, '
                                'extrude_edges, fill_hole, dissolve, flip_normals, recalc_normals, triangulate, smooth_shading, set_material_index, mark_sharp')
            bm.verts.ensure_lookup_table(); bm.edges.ensure_lookup_table(); bm.faces.ensure_lookup_table()
            log.append(info)
        bm.normal_update()
        bm.to_mesh(obj.data)
        obj.data.update()
    finally:
        bm.free()
    settle()
    me = obj.data
    me.calc_loop_triangles()
    return {'object': obj.name, 'before': {'vertices': before[0], 'faces': before[1]},
            'after': {'vertices': len(me.vertices), 'faces': len(me.polygons), 'triangles': len(me.loop_triangles)}, 'operations': log}


def create_mesh_from_data(a):
    mode_object()
    verts = [tuple(v) for v in a['vertices']]
    faces = [tuple(f) for f in a.get('faces', [])]
    edges = [tuple(e) for e in a.get('edges', [])]
    n = len(verts)
    for f in faces:
        if max(f) >= n:
            raise ToolError(f'face {list(f)} refers to vertex {max(f)} but only {n} vertices were given')
        if len(set(f)) != len(f):
            raise ToolError(f'face {list(f)} repeats a vertex')
    for e in edges:
        if max(e) >= n:
            raise ToolError(f'edge {list(e)} refers to a missing vertex')
    me = bpy.data.meshes.new(a['name'])
    me.from_pydata(verts, edges, faces)
    me.validate(clean_customdata=False)
    if a.get('uvs'):
        corners = sum(len(p.vertices) for p in me.polygons)
        if len(a['uvs']) != corners:
            raise ToolError(f'uvs has {len(a["uvs"])} entries but the faces have {corners} corners (one [u,v] per face corner, in face order)')
        layer = me.uv_layers.new(name='UVMap')
        for i, uv in enumerate(a['uvs']):
            layer.data[i].uv = uv
    for p in me.polygons:
        p.use_smooth = bool(a.get('smooth'))
    if a.get('recalc_normals', True) and faces:
        bm = bmesh.new(); bm.from_mesh(me)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(me); bm.free()
    me.update()
    obj = bpy.data.objects.new(a['name'], me)
    (get_collection(a['collection']) if a.get('collection') else scene().collection).objects.link(obj)
    apply_transform_args(obj, a)
    if a.get('material'):
        mat = bpy.data.materials.get(a['material'])
        if mat is None:
            raise ToolError(f'material "{a["material"]}" does not exist')
        me.materials.append(mat)
    select_only([obj])
    settle()
    return {'name': obj.name, **unique_name_note(a['name'], obj), **describe(obj)}


# ---- materials

def _principled(mat):
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next((n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if bsdf is None:
        bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled')
        out = next((n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL'), None) or nt.nodes.new('ShaderNodeOutputMaterial')
        nt.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
    return nt, bsdf


def _in(bsdf, *names):
    for n in names:
        if n in bsdf.inputs:
            return bsdf.inputs[n]
    raise ToolError(f'Principled BSDF has none of the inputs {names}')


def _tex_node(nt, kind, t):
    kinds = {'noise': 'ShaderNodeTexNoise', 'voronoi': 'ShaderNodeTexVoronoi', 'wave': 'ShaderNodeTexWave', 'checker': 'ShaderNodeTexChecker',
             'brick': 'ShaderNodeTexBrick', 'gradient': 'ShaderNodeTexGradient', 'magic': 'ShaderNodeTexMagic'}
    node = nt.nodes.new(kinds[kind])
    for key, names in (('scale', ('Scale',)), ('detail', ('Detail',)), ('distortion', ('Distortion',))):
        if key in t:
            for nme in names:
                if nme in node.inputs:
                    node.inputs[nme].default_value = t[key]
    out = next((node.outputs[n] for n in ('Fac', 'Distance', 'Color') if n in node.outputs), node.outputs[0])
    return node, out


def _apply_texture(nt, bsdf, t):
    target = t.get('target', 'base_color')
    node, fac = _tex_node(nt, t['type'], t)
    coord = nt.nodes.new('ShaderNodeTexCoord')
    if 'Vector' in node.inputs:
        nt.links.new(coord.outputs['Object'], node.inputs['Vector'])
    c1 = color4(t.get('color1'), (0.05, 0.05, 0.05, 1))
    c2 = color4(t.get('color2'), (0.9, 0.9, 0.9, 1))
    if target == 'bump':
        bump = nt.nodes.new('ShaderNodeBump')
        bump.inputs['Strength'].default_value = t.get('strength', 0.5)
        nt.links.new(fac, bump.inputs['Height'])
        nt.links.new(bump.outputs['Normal'], _in(bsdf, 'Normal'))
        return
    ramp = nt.nodes.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].color = c1
    ramp.color_ramp.elements[1].color = c2
    nt.links.new(fac, ramp.inputs['Fac'])
    socket = {'base_color': ('Base Color',), 'emission': ('Emission Color', 'Emission'), 'roughness': ('Roughness',), 'metallic': ('Metallic',)}[target]
    if target in ('roughness', 'metallic'):
        sep = nt.nodes.new('ShaderNodeRGBToBW')
        nt.links.new(ramp.outputs['Color'], sep.inputs['Color'])
        nt.links.new(sep.outputs['Val'], _in(bsdf, *socket))
    else:
        nt.links.new(ramp.outputs['Color'], _in(bsdf, *socket))
        if target == 'emission':
            _in(bsdf, 'Emission Strength').default_value = max(_in(bsdf, 'Emission Strength').default_value, t.get('strength', 1.0))


def set_material(a):
    objs = get_objs(a['objects'], ['MESH', 'CURVE', 'SURFACE', 'FONT', 'META'])
    mat = bpy.data.materials.get(a['material']) or bpy.data.materials.new(a['material'])
    nt, bsdf = _principled(mat)
    if 'base_color' in a:
        _in(bsdf, 'Base Color').default_value = color4(a['base_color'])
        mat.diffuse_color = color4(a['base_color'])
    for key, sock in (('metallic', ('Metallic',)), ('roughness', ('Roughness',)), ('ior', ('IOR',)),
                      ('transmission', ('Transmission Weight', 'Transmission')), ('coat', ('Coat Weight', 'Clearcoat'))):
        if key in a:
            _in(bsdf, *sock).default_value = a[key]
    if 'alpha' in a:
        _in(bsdf, 'Alpha').default_value = a['alpha']
        try:
            mat.surface_render_method = 'BLENDED' if a['alpha'] < 1 else 'DITHERED'
        except (AttributeError, TypeError):
            pass
    if 'emission' in a:
        e = a['emission']
        if 'color' in e:
            _in(bsdf, 'Emission Color', 'Emission').default_value = color4(e['color'])
        _in(bsdf, 'Emission Strength').default_value = e.get('strength', 1.0)
    if 'normal_strength' in a and a['normal_strength'] != 1:
        pass
    if 'double_sided' in a:
        mat.use_backface_culling = not a['double_sided']
    if 'texture' in a:
        _apply_texture(nt, bsdf, a['texture'])
    for o in objs:
        if o.data.users > 1 and o.type == 'MESH':
            pass
        mats = o.data.materials
        if 'slot' in a:
            while len(mats) <= a['slot']:
                mats.append(None)
            mats[a['slot']] = mat
        elif len(mats) == 0:
            mats.append(mat)
        elif mat.name not in [m.name for m in mats if m]:
            mats[0] = mat
    return {'material': mat.name, 'objects': [o.name for o in objs], 'base_color': _r(_in(bsdf, 'Base Color').default_value),
            'roughness': _r(_in(bsdf, 'Roughness').default_value), 'metallic': _r(_in(bsdf, 'Metallic').default_value),
            'total_materials': len([m for m in bpy.data.materials if m.users])}


def assign_collection(a):
    objs = get_objs(a['objects'])
    coll = get_collection(a['collection'], True, a.get('parent_collection'))
    for o in objs:
        if a.get('exclusive', True):
            for c in list(o.users_collection):
                if c is not coll:
                    c.objects.unlink(o)
        if o.name not in coll.objects:
            coll.objects.link(o)
    return {'collection': coll.name, 'objects': [o.name for o in objs]}


def set_origin(a):
    obj = get_obj(a['name'])
    if obj.type != 'MESH':
        raise ToolError('set_origin supports mesh objects')
    if obj.data.users > 1:
        obj.data = obj.data.copy()
    settle()
    mode = a['mode']
    mn, mx = world_bbox(obj)
    if mode == 'bottom_center':
        new_world = Vector(((mn.x + mx.x) / 2, (mn.y + mx.y) / 2, mn.z))
    elif mode == 'center_bounds':
        new_world = (mn + mx) / 2
    elif mode == 'center_mass':
        verts = obj.data.vertices
        local = sum((v.co for v in verts), Vector()) / max(1, len(verts))
        new_world = obj.matrix_world @ local
    elif mode == 'world_origin':
        new_world = Vector((0, 0, 0))
    else:
        if 'location' not in a:
            raise ToolError('mode "location" needs `location`')
        new_world = Vector(a['location'])
    delta_local = obj.matrix_world.inverted() @ new_world
    obj.data.transform(Matrix.Translation(-delta_local))
    obj.matrix_world.translation = new_world
    for ch in obj.children:
        ch.matrix_parent_inverse = Matrix.Translation(-delta_local) @ ch.matrix_parent_inverse
    obj.data.update()
    settle()
    return describe(obj)


def uv_unwrap(a):
    objs = get_objs(a['objects'], ['MESH'])
    method = a.get('method', 'smart_project')
    done = []
    for o in objs:
        if o.data.users > 1:
            o.data = o.data.copy()
        if not o.data.uv_layers:
            o.data.uv_layers.new(name='UVMap')
        with op_context([o]):
            bpy.ops.object.mode_set(mode='EDIT')
            try:
                bpy.ops.mesh.select_all(action='SELECT')
                if method == 'smart_project':
                    bpy.ops.uv.smart_project(angle_limit=math.radians(a.get('angle_limit_deg', 66)), island_margin=a.get('island_margin', 0.01))
                elif method == 'angle_based':
                    bpy.ops.uv.unwrap(method='ANGLE_BASED', margin=a.get('island_margin', 0.01))
                elif method == 'cube_project':
                    bpy.ops.uv.cube_project(cube_size=1.0)
                elif method == 'cylinder_project':
                    bpy.ops.uv.cylinder_project()
                else:
                    bpy.ops.uv.sphere_project()
            finally:
                bpy.ops.object.mode_set(mode='OBJECT')
        done.append({'object': o.name, 'uv_layers': [u.name for u in o.data.uv_layers]})
    return {'unwrapped': done, 'method': method}


# ---- import / export

def import_file(a):
    path = _confine(a['path'], must_exist=True)
    ext = path.suffix.lower()
    before = set(bpy.data.objects.keys())
    mode_object()
    _enable_addons()
    if ext in ('.glb', '.gltf'):
        bpy.ops.import_scene.gltf(filepath=str(path))
    elif ext == '.obj':
        bpy.ops.wm.obj_import(filepath=str(path))
    elif ext == '.fbx':
        if hasattr(bpy.ops.wm, 'fbx_import'):
            bpy.ops.wm.fbx_import(filepath=str(path))
        else:
            bpy.ops.import_scene.fbx(filepath=str(path))
    elif ext == '.stl':
        bpy.ops.wm.stl_import(filepath=str(path))
    elif ext == '.blend':
        with bpy.data.libraries.load(str(path), link=False) as (src, dst):
            dst.objects = list(src.objects)
        for o in dst.objects:
            if o is not None:
                scene().collection.objects.link(o)
    else:
        raise ToolError(f'unsupported import format {ext}; use glb, gltf, obj, fbx, stl or blend')
    new = [bpy.data.objects[n] for n in bpy.data.objects.keys() if n not in before]
    if a.get('collection'):
        for o in new:
            link_obj(o, a['collection'])
    if a.get('scale', 1) != 1:
        for o in new:
            if o.parent is None:
                o.scale = [x * a['scale'] for x in o.scale]
    settle()
    return {'imported': [o.name for o in new], 'path': str(path.relative_to(config.project_dir()))}


_addons_done = False


def _enable_addons():
    global _addons_done
    if _addons_done:
        return
    import addon_utils
    for m in ('io_scene_gltf2', 'io_scene_fbx'):
        try:
            addon_utils.enable(m, default_set=False, persistent=False)
        except Exception:
            pass
    _addons_done = True


def _confine(rel, must_exist=False):
    try:
        return config.confine(rel, must_exist=must_exist)
    except config.PathError as e:
        raise ToolError(str(e), -32003) from None


def export_file(a):
    fmt = a.get('format') or Path(a['path']).suffix.lstrip('.').lower() or 'glb'
    path = _confine(a['path'])
    if path.suffix.lower() != '.' + fmt:
        path = path.with_suffix('.' + fmt)
        path = _confine(str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == 'blend':
        bpy.ops.wm.save_as_mainfile(filepath=str(path), copy=True)
        return {'path': str(path.relative_to(config.project_dir())), 'bytes': path.stat().st_size}
    if a.get('objects'):
        objs = get_objs(a['objects'])
    elif a.get('collection'):
        objs = list(get_collection(a['collection'], False).all_objects)
    elif a.get('selection_only'):
        objs = [o for o in scene().objects if o.select_get()]
    else:
        objs = [o for o in scene().objects if o.type in ('MESH', 'ARMATURE', 'CURVE', 'EMPTY') and not o.hide_get()]
    if not objs:
        raise ToolError('nothing to export: no matching objects')
    # include children/armatures needed
    extra = set()
    for o in objs:
        for m in o.modifiers:
            if m.type == 'ARMATURE' and m.object:
                extra.add(m.object)
    objs = list({o.name: o for o in list(objs) + list(extra)}.values())
    _enable_addons()
    mode_object()
    select_only(objs)
    for o in objs:
        o.select_set(True)
    settle()
    try:
        with bpy.context.temp_override(selected_objects=objs, active_object=objs[0], object=objs[0]):
            if fmt in ('glb', 'gltf'):
                bpy.ops.export_scene.gltf(filepath=str(path), export_format='GLB' if fmt == 'glb' else 'GLTF_SEPARATE', use_selection=True,
                                          export_apply=a.get('apply_modifiers', True), export_animations=a.get('animations', True), export_yup=True)
            elif fmt == 'obj':
                bpy.ops.wm.obj_export(filepath=str(path), export_selected_objects=True, apply_modifiers=a.get('apply_modifiers', True))
            elif fmt == 'fbx':
                if 'use_selection' not in bpy.ops.export_scene.fbx.get_rna_type().properties:
                    raise ToolError('this Blender build has no FBX exporter; export glb (recommended for Godot) or obj instead')
                bpy.ops.export_scene.fbx(filepath=str(path), use_selection=True, apply_scale_options='FBX_SCALE_ALL',
                                         use_mesh_modifiers=a.get('apply_modifiers', True), bake_anim=a.get('animations', True))
            elif fmt == 'stl':
                bpy.ops.wm.stl_export(filepath=str(path), export_selected_objects=True, apply_modifiers=a.get('apply_modifiers', True))
            else:
                raise ToolError(f'unsupported export format {fmt}')
    except RuntimeError as e:
        raise ToolError(f'export failed: {e}') from None
    if not path.exists():
        raise ToolError('exporter produced no file')
    return {'path': str(path.relative_to(config.project_dir())), 'format': fmt, 'bytes': path.stat().st_size, 'objects': [o.name for o in objs]}


# ---- camera / light / world

def look_rotation(src, target):
    d = Vector(target) - Vector(src)
    if d.length < 1e-9:
        d = Vector((0, 1, 0))
    return d.to_track_quat('-Z', 'Y').to_euler()


def set_camera(a):
    name = a.get('name', 'Camera')
    obj = bpy.data.objects.get(name)
    if obj is None or obj.type != 'CAMERA':
        cam = bpy.data.cameras.new(name)
        obj = bpy.data.objects.new(name, cam)
        scene().collection.objects.link(obj)
    cam = obj.data
    if 'location' in a:
        obj.location = a['location']
    if 'look_at' in a:
        obj.rotation_euler = look_rotation(obj.location, a['look_at'])
    elif 'rotation_deg' in a:
        obj.rotation_euler = to_euler(a['rotation_deg'])
    if 'lens' in a:
        cam.lens = a['lens']
    if 'ortho' in a:
        cam.type = 'ORTHO' if a['ortho'] else 'PERSP'
    if 'ortho_scale' in a:
        cam.ortho_scale = a['ortho_scale']
    if 'clip_start' in a:
        cam.clip_start = a['clip_start']
    if 'clip_end' in a:
        cam.clip_end = a['clip_end']
    if a.get('make_active', True):
        scene().camera = obj
    settle()
    return describe(obj)


def set_light(a):
    name = a['name']
    obj = bpy.data.objects.get(name)
    kind = a.get('type', 'POINT')
    if obj is None or obj.type != 'LIGHT':
        light = bpy.data.lights.new(name, kind)
        obj = bpy.data.objects.new(name, light)
        scene().collection.objects.link(obj)
    light = obj.data
    if light.type != kind and 'type' in a:
        light.type = kind
    if 'energy' in a:
        light.energy = a['energy']
    elif light.users and obj.data.energy == 10 and kind == 'SUN':
        light.energy = 3.0
    if 'color' in a:
        light.color = color4(a['color'])[:3]
    if 'size' in a and hasattr(light, 'size'):
        light.size = a['size']
    if 'spot_size_deg' in a and light.type == 'SPOT':
        light.spot_size = math.radians(a['spot_size_deg'])
    if 'shadow' in a:
        light.use_shadow = a['shadow']
    if 'location' in a:
        obj.location = a['location']
    if 'look_at' in a:
        obj.rotation_euler = look_rotation(obj.location, a['look_at'])
    elif 'rotation_deg' in a:
        obj.rotation_euler = to_euler(a['rotation_deg'])
    settle()
    return describe(obj)


def set_world(a):
    sc = scene()
    world = sc.world or bpy.data.worlds.new('World')
    sc.world = world
    world.use_nodes = True
    nt = world.node_tree
    bg = next((n for n in nt.nodes if n.type == 'BACKGROUND'), None)
    if bg is None:
        bg = nt.nodes.new('ShaderNodeBackground')
        out = next((n for n in nt.nodes if n.type == 'OUTPUT_WORLD'), None) or nt.nodes.new('ShaderNodeOutputWorld')
        nt.links.new(bg.outputs[0], out.inputs[0])
    if 'color' in a:
        for l in list(bg.inputs['Color'].links):
            nt.links.remove(l)
        bg.inputs['Color'].default_value = color4(a['color'])
    if 'sky_gradient' in a:
        g = a['sky_gradient']
        coord = nt.nodes.new('ShaderNodeTexCoord')
        sep = nt.nodes.new('ShaderNodeSeparateXYZ')
        rng = nt.nodes.new('ShaderNodeMapRange')
        ramp = nt.nodes.new('ShaderNodeValToRGB')
        nt.links.new(coord.outputs['Generated'], sep.inputs['Vector'])
        nt.links.new(sep.outputs['Z'], rng.inputs['Value'])
        rng.inputs['From Min'].default_value = 0.35
        rng.inputs['From Max'].default_value = 0.85
        ramp.color_ramp.elements[0].color = color4(g['horizon'])
        ramp.color_ramp.elements[1].color = color4(g['zenith'])
        nt.links.new(rng.outputs['Result'], ramp.inputs['Fac'])
        nt.links.new(ramp.outputs['Color'], bg.inputs['Color'])
    if 'strength' in a:
        bg.inputs['Strength'].default_value = a['strength']
    if 'transparent' in a:
        sc.render.film_transparent = a['transparent']
    if 'unit_system' in a:
        sc.unit_settings.system = a['unit_system']
    if 'unit_scale' in a:
        sc.unit_settings.scale_length = a['unit_scale']
    return {'world': world.name, 'transparent': sc.render.film_transparent, 'units': sc.unit_settings.system, 'unit_scale': sc.unit_settings.scale_length}


# ---- rendering

def _png_bytes(path):
    data = Path(path).read_bytes()
    return data


def _frame_objects(a_objs=None, selected=False):
    sc = scene()
    if a_objs:
        objs = get_objs(a_objs)
    elif selected:
        objs = [o for o in sc.objects if o.select_get()]
    else:
        objs = list(sc.objects)
    meshes = [o for o in objs if o.type in ('MESH', 'CURVE', 'SURFACE', 'FONT', 'META', 'ARMATURE') and not o.hide_get()]
    return scene_bbox(meshes or [o for o in sc.objects if o.type == 'MESH'])


# The GPU engines (Workbench/EEVEE) dropped objects in headless renders on the Adreno/freedreno driver we test on, so
# CPU Cycles is the default for screenshots and previews. AMERIKA_RENDER_GPU=1 prefers the GPU engines again.
PREFER_GPU = os.environ.get('AMERIKA_RENDER_GPU') == '1'

VIEW_DIRS = {
    'perspective': (0.75, -1.0, 0.65), 'front': (0, -1, 0), 'back': (0, 1, 0), 'right': (1, 0, 0), 'left': (-1, 0, 0),
    'top': (0, 0.0001, 1), 'bottom': (0, 0.0001, -1),
}


def _render_tmp_scene(setup, width, height, samples=None):
    """Render through a throw-away scene that shares the real scene's collection tree, so the user's scene is untouched."""
    orig = scene()
    tmp = bpy.data.scenes.new('_amerika_tmp')
    tmp.collection.children.link(orig.collection)
    tmp.render.resolution_x, tmp.render.resolution_y, tmp.render.resolution_percentage = width, height, 100
    tmp.render.image_settings.file_format = 'PNG'
    tmp.render.film_transparent = False
    tmp.unit_settings.system = orig.unit_settings.system
    tmp_cam_data = tmp_cam = None
    fd, fname = tempfile.mkstemp(suffix='.png', prefix='amerika_render_')
    os.close(fd)
    window = bpy.context.window
    old_scene = window.scene if window else None
    try:
        tmp_cam, tmp_cam_data = setup(tmp)
        tmp.render.filepath = fname
        errors = []
        for engine in setup.engines:
            tmp.render.engine = engine
            if engine == 'CYCLES':
                tmp.cycles.device = 'CPU'
                tmp.cycles.samples = samples or 16
                try:
                    tmp.cycles.use_denoising = True
                except Exception:
                    pass
            try:
                if window:
                    window.scene = tmp
                bpy.ops.render.render(write_still=True, scene=tmp.name)
                break
            except RuntimeError as e:
                errors.append(f'{engine}: {e}')
                continue
        else:
            raise ToolError('rendering failed with all engines: ' + '; '.join(errors))
        png = _png_bytes(fname)
        return png
    finally:
        if window and old_scene:
            window.scene = old_scene
        try:
            bpy.data.scenes.remove(tmp)
        except Exception:
            pass
        for coll in (bpy.data.worlds, bpy.data.lights, bpy.data.materials):
            for item in list(coll):
                if item.name.startswith('_amerika_'):
                    coll.remove(item)
        for item in list(bpy.data.objects):
            if item.name.startswith('_amerika_'):
                bpy.data.objects.remove(item)
        for item in list(bpy.data.cameras):
            if item.name.startswith('_amerika_'):
                bpy.data.cameras.remove(item)
        try:
            os.unlink(fname)
        except OSError:
            pass


def _make_cam(tmp, mn, mx, direction, width, height, lens=50):
    centre = (mn + mx) / 2
    size = max((mx - mn).length, 0.1)
    cam_data = bpy.data.cameras.new('_amerika_cam')
    cam_data.lens = lens
    cam_data.sensor_width = 36
    cam_data.clip_start = max(size / 1000, 0.001)
    cam_data.clip_end = size * 100
    cam = bpy.data.objects.new('_amerika_cam', cam_data)
    tmp.collection.objects.link(cam)
    d = Vector(direction).normalized()
    # distance so the bounding sphere fits the narrow field of view
    fov = 2 * math.atan((cam_data.sensor_width / 2) / lens)
    aspect = width / height
    fov_eff = fov if aspect >= 1 else 2 * math.atan(math.tan(fov / 2) * aspect)
    if aspect >= 1:
        fov_eff = 2 * math.atan(math.tan(fov / 2) / aspect)
    dist = (size / 2) / math.tan(fov_eff / 2) * 0.85
    cam.location = centre + d * dist
    cam.rotation_euler = look_rotation(cam.location, centre)
    tmp.camera = cam
    return cam, cam_data


def _view_matrices(mn, mx, direction, width, height, lens=50.0, sensor=36.0):
    """View and projection matrices (4x4 nested lists via mathutils) framing the bounding box from `direction`."""
    centre = (mn + mx) / 2
    size = max((mx - mn).length, 0.1)
    aspect = width / height
    fx = 2 * lens / sensor            # focal length in NDC units across the sensor-fit axis
    fy = fx * aspect if aspect >= 1 else fx
    fx_ = fx if aspect >= 1 else fx / aspect
    if aspect >= 1:
        fx_, fy = fx, fx * aspect
    else:
        fx_, fy = fx / aspect, fx
    tan_half = 1 / min(fx_, fy)
    dist = (size / 2) / tan_half * 0.85
    d = Vector(direction).normalized()
    loc = centre + d * dist
    rot = look_rotation(loc, centre).to_matrix().to_4x4()
    view = (Matrix.Translation(loc) @ rot).inverted()
    n, f = max(size / 1000, 0.001), size * 100 + dist
    proj = Matrix(((fx_, 0, 0, 0), (0, fy, 0, 0), (0, 0, -(f + n) / (f - n), -2 * f * n / (f - n)), (0, 0, -1, 0)))
    return view, proj


def _wireframe_png(objs, view, proj, width, height, bg=(0.93, 0.94, 0.96), fg=(0.10, 0.12, 0.2)):
    """Software wireframe (the Workbench render engine cannot draw wireframes): projects edges with numpy."""
    import numpy as np
    dg = bpy.context.evaluated_depsgraph_get()
    img = np.empty((height, width, 4), dtype=np.float32)
    img[:] = (*bg, 1.0)
    vp = np.array(proj @ view, dtype=np.float64)
    edges_drawn = 0
    for o in objs:
        if o.type != 'MESH' or o.hide_get():
            continue
        ev = o.evaluated_get(dg)
        me = ev.to_mesh()
        try:
            nv, ne = len(me.vertices), len(me.edges)
            if not ne:
                continue
            co = np.empty(nv * 3, dtype=np.float32)
            me.vertices.foreach_get('co', co)
            co = co.reshape(nv, 3).astype(np.float64)
            mw = np.array(o.matrix_world, dtype=np.float64)
            hom = np.concatenate([co, np.ones((nv, 1))], axis=1) @ (vp @ mw).T
            w = hom[:, 3]
            ok = w > 1e-6
            ndc = np.zeros((nv, 2))
            ndc[ok] = hom[ok, :2] / w[ok, None]
            px = (ndc[:, 0] * 0.5 + 0.5) * (width - 1)
            py = (1 - (ndc[:, 1] * 0.5 + 0.5)) * (height - 1)
            ed = np.empty(ne * 2, dtype=np.int32)
            me.edges.foreach_get('vertices', ed)
            ed = ed.reshape(ne, 2)
            keep = ok[ed[:, 0]] & ok[ed[:, 1]]
            for a_, b_ in ed[keep]:
                x0, y0, x1, y1 = px[a_], py[a_], px[b_], py[b_]
                if max(abs(x0), abs(x1), abs(y0), abs(y1)) > 20000:
                    continue
                n = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
                t = np.linspace(0.0, 1.0, n)
                xs = np.rint(x0 + (x1 - x0) * t).astype(np.int64)
                ys = np.rint(y0 + (y1 - y0) * t).astype(np.int64)
                m = (xs >= 0) & (xs < width) & (ys >= 0) & (ys < height)
                img[ys[m], xs[m], :3] = fg
                edges_drawn += 1
        finally:
            ev.to_mesh_clear()
    image = bpy.data.images.new('_amerika_wire', width, height, alpha=False, float_buffer=False)
    fd, fname = tempfile.mkstemp(suffix='.png', prefix='amerika_wire_')
    os.close(fd)
    try:
        image.colorspace_settings.name = 'Non-Color'
        image.pixels.foreach_set(np.ascontiguousarray(img[::-1]).ravel())
        image.filepath_raw = fname
        image.file_format = 'PNG'
        image.save()
        return Path(fname).read_bytes(), edges_drawn
    finally:
        bpy.data.images.remove(image)
        try:
            os.unlink(fname)
        except OSError:
            pass


def viewport_screenshot(a):
    width, height = a.get('width', 640), a.get('height', 480)
    settle()
    mn, mx = _frame_objects(a.get('objects'), a.get('focus') == 'selected')
    shading = a.get('shading', 'solid')
    view = a.get('view', 'perspective')
    if shading == 'wireframe':
        if view == 'camera':
            cam = scene().camera
            if not cam:
                raise ToolError('the scene has no camera; use set_camera or another view')
            dg = bpy.context.evaluated_depsgraph_get()
            vm = cam.matrix_world.inverted()
            pm = cam.calc_matrix_camera(dg, x=width, y=height)
        else:
            vm, pm = _view_matrices(mn, mx, VIEW_DIRS[view], width, height)
        objs = get_objs(a['objects']) if a.get('objects') else list(scene().objects)
        png, n = _wireframe_png(objs, vm, pm, width, height)
        return {'view': view, 'shading': shading, 'size': [width, height], 'edges_drawn': n, '_png': [png]}

    def setup(tmp):
        if view == 'camera':
            if not scene().camera:
                raise ToolError('the scene has no camera; use set_camera or another view')
            tmp.camera = scene().camera
            cam = cam_data = None
        else:
            cam, cam_data = _make_cam(tmp, mn, mx, VIEW_DIRS[view], width, height)
        if setup.engines[0] == 'BLENDER_WORKBENCH':
            sh = tmp.display.shading
            sh.light = 'STUDIO'
            sh.show_shadows = True
            sh.show_cavity = False
            sh.type = 'SOLID'
            sh.color_type = 'MATERIAL' if shading == 'material' else 'SINGLE'
            if shading == 'solid':
                sh.single_color = (0.78, 0.78, 0.8)
            bg = (0.16, 0.17, 0.2)
            w = bpy.data.worlds.new('_amerika_w')
            w.color = bg
            tmp.world = w
        else:
            _cycles_fallback_setup(tmp, shading)
        return cam, cam_data

    setup.engines = ['BLENDER_WORKBENCH', 'CYCLES'] if PREFER_GPU else ['CYCLES']
    png = _render_tmp_scene(setup, width, height, samples=12)
    return {'view': view, 'shading': shading, 'size': [width, height], '_png': [png]}


def _cycles_fallback_setup(tmp, shading):
    """When Workbench cannot run (no GPU), approximate it with a CPU Cycles clay render."""
    w = bpy.data.worlds.new('_amerika_w')
    w.use_nodes = True
    w.node_tree.nodes['Background'].inputs['Color'].default_value = (0.5, 0.52, 0.56, 1)
    w.node_tree.nodes['Background'].inputs['Strength'].default_value = 1.0
    tmp.world = w
    sun = bpy.data.lights.new('_amerika_sun', 'SUN')
    sun.energy = 3
    so = bpy.data.objects.new('_amerika_sun', sun)
    so.rotation_euler = (math.radians(50), 0, math.radians(30))
    tmp.collection.objects.link(so)
    if shading != 'material':
        mat = bpy.data.materials.new('_amerika_clay')
        mat.use_nodes = True
        mat.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (0.75, 0.75, 0.78, 1)
        tmp.view_layers[0].material_override = mat


def render_preview(a):
    width, height = a.get('width', 640), a.get('height', 480)
    sc = scene()
    settle()
    created = None
    cam = a.get('camera')
    cam_obj = get_obj(cam, ['CAMERA']) if cam else sc.camera
    mn, mx = _frame_objects()
    engines = {'auto': ['BLENDER_EEVEE', 'CYCLES'] if PREFER_GPU else ['CYCLES'], 'eevee': ['BLENDER_EEVEE', 'CYCLES'], 'cycles': ['CYCLES'],
               'workbench': ['BLENDER_WORKBENCH', 'CYCLES']}[a.get('engine', 'auto')]
    samples = a.get('samples', 24)

    def setup(tmp):
        # Share the real scene's world/camera/settings.
        tmp.world = sc.world
        tmp.render.film_transparent = sc.render.film_transparent
        tmp.view_settings.view_transform = sc.view_settings.view_transform
        cam_d = cam_data = None
        if cam_obj is None:
            c, cam_data = _make_cam(tmp, mn, mx, VIEW_DIRS['perspective'], width, height)
            if not tmp.world:
                w = bpy.data.worlds.new('_amerika_w'); w.use_nodes = True
                w.node_tree.nodes['Background'].inputs['Color'].default_value = (0.55, 0.57, 0.62, 1)
                tmp.world = w
            if not any(o.type == 'LIGHT' for o in sc.objects):
                sun = bpy.data.lights.new('_amerika_sun', 'SUN'); sun.energy = 3.5
                so = bpy.data.objects.new('_amerika_sun', sun)
                so.rotation_euler = (math.radians(50), 0, math.radians(35))
                tmp.collection.objects.link(so)
            cam_d = c
        else:
            tmp.camera = cam_obj
        if tmp.render.engine == 'BLENDER_EEVEE':
            pass
        return cam_d, cam_data

    setup.engines = engines
    # EEVEE samples are set on the tmp scene after engine selection; handled by defaults (taa_render_samples)

    png = _render_with_samples(setup, width, height, samples)
    out = {'engine': a.get('engine', 'auto'), 'size': [width, height], 'camera': cam_obj.name if cam_obj else '(auto framed)', '_png': [png]}
    if a.get('save_to'):
        p = _confine(a['save_to'])
        if p.suffix.lower() != '.png':
            p = p.with_suffix('.png')
            p = _confine(str(p))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(png)
        out['saved'] = str(p.relative_to(config.project_dir()))
    return out


def _render_with_samples(setup, width, height, samples):
    inner = setup

    def wrapped(tmp):
        res = inner(tmp)
        try:
            tmp.eevee.taa_render_samples = samples
        except AttributeError:
            pass
        return res

    wrapped.engines = inner.engines
    return _render_tmp_scene(wrapped, width, height, samples=samples)


def delete_object(a):
    objs = get_objs(a['names'])
    mode_object()
    if a.get('with_children'):
        todo = []
        for o in objs:
            todo.extend(o.children_recursive)
        objs = list({o.name: o for o in objs + todo}.values())
    removed = []
    mats = set()
    for o in objs:
        data = o.data if o.type in ('MESH', 'CURVE', 'CAMERA', 'LIGHT', 'ARMATURE') else None
        if o.type == 'MESH':
            mats.update(s.material for s in o.material_slots if s.material)
        removed.append(o.name)
        bpy.data.objects.remove(o, do_unlink=True)
        if data is not None and data.users == 0:
            coll = {'MESH': bpy.data.meshes, 'CURVE': bpy.data.curves, 'CAMERA': bpy.data.cameras, 'LIGHT': bpy.data.lights,
                    'ARMATURE': bpy.data.armatures}.get(type(data).__name__.lower())
            try:
                {'Mesh': bpy.data.meshes, 'Curve': bpy.data.curves, 'Camera': bpy.data.cameras, 'Light': bpy.data.lights,
                 'SunLight': bpy.data.lights, 'PointLight': bpy.data.lights, 'SpotLight': bpy.data.lights, 'AreaLight': bpy.data.lights,
                 'Armature': bpy.data.armatures}[type(data).__name__].remove(data)
            except KeyError:
                pass
    for m in mats:
        if m.users == 0:
            bpy.data.materials.remove(m)
    settle()
    return {'deleted': removed, 'remaining_objects': len(scene().objects)}


def duplicate_object(a):
    src = get_obj(a['name'])
    new = src.copy()
    if src.data is not None and not a.get('linked'):
        new.data = src.data.copy()
    new.name = a.get('new_name') or src.name + '_copy'
    if a.get('collection'):
        get_collection(a['collection']).objects.link(new)
    else:
        (src.users_collection[0] if src.users_collection else scene().collection).objects.link(new)
    if 'location' in a:
        new.location = a['location']
    elif 'offset' in a:
        new.location = Vector(src.location) + Vector(a['offset'])
    settle()
    return describe(new)


def set_shading(a):
    objs = get_objs(a['objects'], ['MESH'])
    for o in objs:
        if o.data.users > 1:
            o.data = o.data.copy()
        me = o.data
        if a['mode'] == 'flat':
            for p in me.polygons:
                p.use_smooth = False
        else:
            for p in me.polygons:
                p.use_smooth = True
            if a['mode'] == 'auto':
                bm = bmesh.new(); bm.from_mesh(me)
                ang = math.radians(a.get('angle_deg', 40))
                for e in bm.edges:
                    if len(e.link_faces) == 2:
                        e.smooth = e.calc_face_angle(0.0) <= ang
                bm.to_mesh(me); bm.free()
        me.update()
    return {'objects': [o.name for o in objs], 'mode': a['mode']}


DEFAULT_NAME = re.compile(r'^(Cube|Sphere|Cylinder|Cone|Plane|Circle|Torus|Icosphere|Suzanne|Mesh|Empty|Object|Grid)(\.\d+)?$')


def check_game_ready(a):
    objs = get_objs(a['objects']) if a.get('objects') else [o for o in scene().objects if o.type == 'MESH']
    budget = a.get('budget_tris', 5000)
    settle()
    problems, notes = [], []
    tris = 0
    mats = set()
    for o in objs:
        if o.type != 'MESH':
            continue
        me = o.data
        c = mesh_counts(o)
        tris += c.get('triangles', 0)
        if any(abs(s - 1) > 1e-4 for s in o.scale):
            problems.append(f'{o.name}: scale {_r(o.scale)} is not applied (use transform_object apply ["scale"])')
        if any(s < 0 for s in o.scale):
            problems.append(f'{o.name}: negative scale flips normals; apply scale')
        if any(abs(r) > 1e-4 for r in o.rotation_euler) and not o.parent:
            notes.append(f'{o.name}: has rotation {_r([math.degrees(r) for r in o.rotation_euler])} (fine for placed parts; apply for the root asset)')
        if o.modifiers:
            problems.append(f'{o.name}: unapplied modifiers {[m.name for m in o.modifiers]} (export_file applies them by default; apply to be safe)')
        if DEFAULT_NAME.match(o.name):
            problems.append(f'{o.name}: default name; use a descriptive snake_case/PascalCase name')
        bm = bmesh.new(); bm.from_mesh(me)
        ngons = sum(1 for f in bm.faces if len(f.verts) > 4)
        loose = sum(1 for v in bm.verts if not v.link_edges)
        nonman = sum(1 for e in bm.edges if not e.is_manifold and not e.is_boundary) + 0
        boundary = sum(1 for e in bm.edges if e.is_boundary)
        bm.free()
        if ngons:
            problems.append(f'{o.name}: {ngons} n-gons (>4 sides); triangulate or fix topology')
        if loose:
            problems.append(f'{o.name}: {loose} loose vertices; delete them')
        if nonman:
            problems.append(f'{o.name}: {nonman} non-manifold edges')
        if boundary and not o.name.lower().startswith(('plane', 'ground', 'leaf', 'foliage', 'card')):
            notes.append(f'{o.name}: {boundary} open boundary edges (fine for planes/cards, check otherwise)')
        mats.update(s.material.name for s in o.material_slots if s.material)
        if any(s.material is None for s in o.material_slots):
            problems.append(f'{o.name}: has an empty material slot')
        if not o.material_slots:
            notes.append(f'{o.name}: no material (exports with a default grey)')
        if me.uv_layers and len(me.uv_layers) > 2:
            problems.append(f'{o.name}: {len(me.uv_layers)} UV layers; keep 1-2')
        if any(m.node_tree and any(n.type.startswith('TEX_') and n.type != 'TEX_IMAGE' for n in m.node_tree.nodes) for m in (s.material for s in o.material_slots if s.material)):
            notes.append(f'{o.name}: uses procedural texture nodes that glTF cannot export; bake to an image or use plain colours')
        dims = o.dimensions
        if max(dims) > 1000 or (max(dims) < 0.001 and max(dims) > 0):
            problems.append(f'{o.name}: size {_r(dims)} m looks wrong for a game asset')
        mn, mx = world_bbox(o)
        if not o.parent and mn.z > max(dims.z * 0.5, 0.05):
            notes.append(f'{o.name}: floats {mn.z:.2f} m above z=0; check pivot/ground placement')
    if tris > budget:
        problems.append(f'total {tris} triangles exceeds the budget {budget}; use a Decimate modifier or remove detail')
    if len(mats) > 8:
        problems.append(f'{len(mats)} materials; merge to fewer for fewer draw calls')
    return {'ok': not problems, 'problems': problems, 'notes': notes, 'triangles': tris, 'budget_tris': budget, 'materials': sorted(mats),
            'objects_checked': [o.name for o in objs if o.type == 'MESH']}


# ---- rigging

def create_armature(a):
    mode_object()
    arm = bpy.data.armatures.new(a['name'])
    obj = bpy.data.objects.new(a['name'], arm)
    scene().collection.objects.link(obj)
    select_only([obj])
    settle()
    with bpy.context.temp_override(object=obj, active_object=obj):
        bpy.ops.object.mode_set(mode='EDIT')
        try:
            names = {b['name'] for b in a['bones']}
            for b in a['bones']:
                eb = arm.edit_bones.new(b['name'])
                eb.head, eb.tail = b['head'], b['tail']
                if (Vector(b['tail']) - Vector(b['head'])).length < 1e-5:
                    raise ToolError(f'bone {b["name"]} has zero length')
                eb.roll = math.radians(b.get('roll_deg', 0))
            for b in a['bones']:
                if b.get('parent'):
                    if b['parent'] not in names:
                        raise ToolError(f'bone {b["name"]} has unknown parent {b["parent"]}')
                    eb = arm.edit_bones[b['name']]
                    eb.parent = arm.edit_bones[b['parent']]
                    eb.use_connect = bool(b.get('connect'))
        finally:
            bpy.ops.object.mode_set(mode='OBJECT')
    bound = []
    if a.get('bind'):
        meshes = get_objs(a['bind'], ['MESH'])
        method = a.get('bind_method', 'auto_weights')
        for m in meshes:
            select_only([m, obj])
            bpy.context.view_layer.objects.active = obj
            with bpy.context.temp_override(object=obj, active_object=obj, selected_objects=[m, obj], selected_editable_objects=[m, obj]):
                typ = {'auto_weights': 'ARMATURE_AUTO', 'envelope': 'ARMATURE_ENVELOPE', 'empty_groups': 'ARMATURE_NAME', 'rigid': 'ARMATURE'}[method]
                bpy.ops.object.parent_set(type=typ)
            bound.append(m.name)
    settle()
    return {'armature': obj.name, 'bones': [b.name for b in arm.bones], 'bound': bound}


PRESETS = {
    'idle': {'frames': 49, 'keys': lambda B: [
        (1, {B('Spine'): {'rotation_deg': [0, 0, 0]}, B('Chest'): {'rotation_deg': [0, 0, 0]}}),
        (25, {B('Spine'): {'rotation_deg': [3, 0, 0]}, B('Chest'): {'rotation_deg': [2, 0, 0]}}),
        (49, {B('Spine'): {'rotation_deg': [0, 0, 0]}, B('Chest'): {'rotation_deg': [0, 0, 0]}})]},
    'walk': {'frames': 25, 'keys': lambda B: [
        (1, {B('UpperLeg.L'): {'rotation_deg': [30, 0, 0]}, B('UpperLeg.R'): {'rotation_deg': [-30, 0, 0]}, B('UpperArm.L'): {'rotation_deg': [-25, 0, 0]}, B('UpperArm.R'): {'rotation_deg': [25, 0, 0]}}),
        (13, {B('UpperLeg.L'): {'rotation_deg': [-30, 0, 0]}, B('UpperLeg.R'): {'rotation_deg': [30, 0, 0]}, B('UpperArm.L'): {'rotation_deg': [25, 0, 0]}, B('UpperArm.R'): {'rotation_deg': [-25, 0, 0]}}),
        (25, {B('UpperLeg.L'): {'rotation_deg': [30, 0, 0]}, B('UpperLeg.R'): {'rotation_deg': [-30, 0, 0]}, B('UpperArm.L'): {'rotation_deg': [-25, 0, 0]}, B('UpperArm.R'): {'rotation_deg': [25, 0, 0]}})]},
    'attack': {'frames': 20, 'keys': lambda B: [
        (1, {B('UpperArm.R'): {'rotation_deg': [0, 0, 0]}, B('Spine'): {'rotation_deg': [0, 0, 0]}}),
        (6, {B('UpperArm.R'): {'rotation_deg': [-120, 0, 0]}, B('Spine'): {'rotation_deg': [0, 0, 20]}}),
        (10, {B('UpperArm.R'): {'rotation_deg': [40, 0, 0]}, B('Spine'): {'rotation_deg': [10, 0, -25]}}),
        (20, {B('UpperArm.R'): {'rotation_deg': [0, 0, 0]}, B('Spine'): {'rotation_deg': [0, 0, 0]}})]},
}


def pose_keyframes(a):
    arm = get_obj(a['armature'], ['ARMATURE'])
    mode_object()
    names = {b.name.lower().replace('_', '').replace('.', '').replace('-', ''): b.name for b in arm.data.bones}

    def B(n):
        k = n.lower().replace('_', '').replace('.', '').replace('-', '')
        alt = {'upperleg': 'thigh', 'upperarm': 'arm'}
        if k in names:
            return names[k]
        for s, d in alt.items():
            if s in k and k.replace(s, d) in names:
                return names[k.replace(s, d)]
        return None

    keys = [(k['frame'], k['bones']) for k in a.get('keyframes', [])]
    start = a.get('frame_start', 1)
    end = a.get('frame_end')
    if not keys:
        if 'preset' not in a:
            raise ToolError('give keyframes or a preset')
        p = PRESETS[a['preset']]
        raw = p['keys'](B)
        keys = [(start + f - 1, {n: v for n, v in b.items() if n}) for f, b in raw]
        end = end or start + p['frames'] - 1
    end = end or max(f for f, _ in keys)
    action = bpy.data.actions.new(a['action'])
    if not arm.animation_data:
        arm.animation_data_create()
    arm.animation_data.action = action
    count = 0
    for frame, bones in keys:
        for bname, vals in bones.items():
            pb = arm.pose.bones.get(bname)
            if pb is None:
                raise ToolError(f'bone "{bname}" not found; bones: {[b.name for b in arm.data.bones]}')
            pb.rotation_mode = 'XYZ'
            if 'rotation_deg' in vals:
                pb.rotation_euler = [math.radians(x) for x in vals['rotation_deg']]
                pb.keyframe_insert('rotation_euler', frame=frame)
                count += 1
            if 'location' in vals:
                pb.location = vals['location']
                pb.keyframe_insert('location', frame=frame)
                count += 1
    action.use_fake_user = True
    if a.get('loop', True):
        try:
            action.use_cyclic = True
        except AttributeError:
            pass
    action.frame_range = (start, end) if hasattr(action, 'frame_range') else None
    try:
        action.use_frame_range = True
    except AttributeError:
        pass
    scene().frame_start, scene().frame_end = start, end
    return {'action': action.name, 'frames': [start, end], 'keyframes': count}


# ---- undo / python

CHECKPOINT = {'path': None}


def undo(a):
    if a.get('checkpoint') == 'request_start':
        path = CHECKPOINT.get('path')
        if not path or not Path(path).exists():
            raise ToolError('no checkpoint saved for this request')
        restore_checkpoint(path)
        return {'restored': 'request_start'}
    done = 0
    for _ in range(a.get('steps', 1)):
        try:
            bpy.ops.ed.undo()
            done += 1
        except RuntimeError:
            break
    settle()
    return {'undone_steps': done, 'objects': len(scene().objects)}


def save_checkpoint(project_dir=None, label='request'):
    d = Path(project_dir or config.project_dir()) / '.amerika-render' / 'checkpoints'
    d.mkdir(parents=True, exist_ok=True)
    path = d / f'{int(time.time())}-{label}.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(path), copy=True, compress=True)
    # keep the 10 most recent
    for old in sorted(d.glob('*.blend'))[:-10]:
        try:
            old.unlink()
        except OSError:
            pass
    CHECKPOINT['path'] = str(path)
    try:
        bpy.ops.ed.undo_push(message=f'Amerika: {label}')
    except Exception:
        pass
    return str(path)


def restore_checkpoint(path):
    bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False)


def run_python(a):
    mode_object()
    env = {'bpy': bpy, 'bmesh': bmesh, 'mathutils': mathutils, 'math': math, 'random': random, 'colorsys': colorsys,
           'C': bpy.context, 'D': bpy.data, 'Vector': Vector, 'Matrix': Matrix, 'Euler': Euler}
    before = set(bpy.data.objects.keys())
    try:
        res = safety.run(a['code'], env, timeout=20.0)
    except safety.UnsafeCode as e:
        raise ToolError('run_python rejected by the safety check: ' + '; '.join(e.problems[:10])) from None
    except safety.Timeout as e:
        raise ToolError(str(e)) from None
    except Exception as e:  # the model's code failed: report it
        import traceback
        tb = traceback.format_exc().splitlines()
        raise ToolError(f'run_python raised {type(e).__name__}: {e}\n' + '\n'.join(tb[-6:])) from None
    settle()
    now = set(bpy.data.objects.keys())
    res['created'] = sorted(now - before)
    res['removed'] = sorted(before - now)
    res['objects'] = len(now)
    return res


IMPL = {
    'scene_info': scene_info, 'create_primitive': create_primitive, 'transform_object': transform_object, 'add_modifier': add_modifier,
    'edit_mesh': edit_mesh, 'create_mesh_from_data': create_mesh_from_data, 'set_material': set_material,
    'assign_collection': assign_collection, 'set_origin': set_origin, 'uv_unwrap': uv_unwrap, 'import_file': import_file,
    'export_file': export_file, 'set_camera': set_camera, 'set_light': set_light, 'set_world': set_world,
    'viewport_screenshot': viewport_screenshot, 'render_preview': render_preview, 'delete_object': delete_object, 'undo': undo,
    'duplicate_object': duplicate_object, 'set_shading': set_shading, 'check_game_ready': check_game_ready,
    'create_armature': create_armature, 'pose_keyframes': pose_keyframes, 'run_python': run_python,
}
assert set(IMPL) == set(toolspecs.BY_NAME), set(IMPL) ^ set(toolspecs.BY_NAME)


def call(name, raw_input):
    """Validate and run one tool. Returns {"ok":bool, "result":dict|None, "error":str|None, "images":[bytes]}. Never raises."""
    spec = toolspecs.BY_NAME.get(name)
    if spec is None:
        return {'ok': False, 'error': f'unknown tool "{name}". Tools: {sorted(toolspecs.BY_NAME)}', 'code': -32601, 'images': []}
    try:
        args = validate(raw_input if raw_input is not None else {}, spec['input_schema'], name)
    except ValidationError as e:
        return {'ok': False, 'error': f'invalid input: {e}', 'code': -32602, 'images': []}
    t0 = time.monotonic()
    try:
        res = IMPL[name](args)
    except ToolError as e:
        return {'ok': False, 'error': str(e), 'code': e.code, 'images': []}
    except Exception as e:
        import traceback
        return {'ok': False, 'error': f'{name} failed: {type(e).__name__}: {e}', 'code': -32000, 'detail': traceback.format_exc()[-1500:], 'images': []}
    if spec['risk'] != 'read' and name != 'undo':
        try:
            bpy.ops.ed.undo_push(message=f'Amerika: {name}')
        except Exception:
            pass
    images = res.pop('_png', []) if isinstance(res, dict) else []
    if isinstance(res, dict):
        res['elapsed_s'] = round(time.monotonic() - t0, 3)
    return {'ok': True, 'result': res, 'images': images}
