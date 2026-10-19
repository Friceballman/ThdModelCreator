"""Named-part import, transform edit, preserve checks, save/reload and previews."""
import hashlib
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector


def mesh_hash(obj):
    payload = {'vertices': [list(v.co) for v in obj.data.vertices],
               'faces': [list(p.vertices) for p in obj.data.polygons]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def snapshot():
    result = {}
    for obj in bpy.context.scene.objects:
        if obj.type != 'MESH':
            continue
        if not obj.data.vertices or not obj.data.polygons:
            raise RuntimeError('空メッシュ')
        coords = [list(v.co) for v in obj.data.vertices]
        if not all(math.isfinite(x) for v in coords for x in v):
            raise RuntimeError('非有限の座標')
        part_id = obj['part_id']
        if part_id in result:
            raise RuntimeError('部品ID重複')
        result[part_id] = {'mesh_hash': mesh_hash(obj), 'vertices': len(coords),
                           'faces': len(obj.data.polygons), 'location': list(obj.location),
                           'rotation': list(obj.rotation_euler), 'scale': list(obj.scale)}
    return result


def frame_camera():
    corners = [obj.matrix_world @ Vector(corner) for obj in bpy.context.scene.objects
               if obj.type == 'MESH' for corner in obj.bound_box]
    low = Vector([min(p[i] for p in corners) for i in range(3)])
    high = Vector([max(p[i] for p in corners) for i in range(3)])
    return (low + high) * 0.5, max(high - low)


def render_views(output, label, center, size, camera):
    scene = bpy.context.scene
    for view, direction in {'front': (0, -3, 0), 'side': (3, 0, 0),
                            'back': (0, 3, 0), 'perspective': (2, -3, 2)}.items():
        camera.location = center + Vector(direction) * size
        camera.rotation_euler = (center - camera.location).to_track_quat('-Z', 'Y').to_euler()
        scene.render.filepath = str(output / f'{label}-{view}.png')
        bpy.ops.render.render(write_still=True)


def main():
    job = json.loads(Path(sys.argv[sys.argv.index('--') + 1]).read_text(encoding='utf-8'))
    output = Path(job['output'])
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.unit_settings.system = 'METRIC'
    for part in job['parts']:
        bpy.ops.object.select_all(action='DESELECT')
        before = set(bpy.data.objects)
        bpy.ops.wm.obj_import(filepath=part['mesh'], forward_axis='NEGATIVE_Y', up_axis='Z')
        imported = [o for o in bpy.data.objects if o not in before and o.type == 'MESH']
        if len(imported) != 1:
            raise RuntimeError('初期検証はOBJごとに1メッシュを要求します')
        obj = imported[0]
        obj.name = part['id']
        obj['part_id'] = part['id']
        obj['source_sha256'] = part['source_sha256']
        obj.location = part['location']
        obj.rotation_euler = [math.radians(x) for x in part['rotation_degrees']]
        obj.scale = part['scale']
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.display.shading.light = 'STUDIO'
    scene.display.shading.color_type = 'SINGLE'
    scene.display.shading.single_color = (0.56, 0.65, 0.76)
    scene.display.shading.show_shadows = True
    scene.display.shading.show_cavity = True
    scene.render.resolution_x = scene.render.resolution_y = 512
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.world = bpy.data.worlds.new('World')
    scene.world.color = (0.15, 0.15, 0.15)
    bpy.context.view_layer.update()
    center, size = frame_camera()
    bpy.ops.object.camera_add()
    camera = bpy.context.object
    camera.data.type = 'ORTHO'
    camera.data.ortho_scale = size * 1.8
    scene.camera = camera
    camera.location = center + Vector((2, -3, 2)) * size
    camera.rotation_euler = (center - camera.location).to_track_quat('-Z', 'Y').to_euler()
    baseline = snapshot()
    baseline_path = output / 'baseline.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(baseline_path))
    render_views(output, 'baseline', center, size, camera)
    target_id = job['edit']['part_id']
    factor = job['edit']['scale_factor']
    target = next(obj for obj in scene.objects if obj.get('part_id') == target_id)
    target.scale = [x * factor for x in target.scale]
    bpy.context.view_layer.update()
    edited = snapshot()
    preserved = {part_id: baseline[part_id] == edited[part_id]
                 for part_id in baseline if part_id != target_id}
    target_before, target_after = baseline[target_id], edited[target_id]
    edit_ok = (target_before['mesh_hash'] == target_after['mesh_hash'] and
               target_before['location'] == target_after['location'] and
               target_before['rotation'] == target_after['rotation'] and
               all(math.isclose(a * factor, b, rel_tol=1e-6) for a, b in
                   zip(target_before['scale'], target_after['scale'])))
    edited_path = output / 'edited.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(edited_path))
    render_views(output, 'edited', center, size, camera)
    bpy.ops.wm.obj_export(filepath=str(output / 'edited.obj'),
                          forward_axis='NEGATIVE_Y', up_axis='Z', export_materials=False)
    bpy.ops.wm.open_mainfile(filepath=str(baseline_path), use_scripts=False)
    reload_baseline = snapshot() == baseline
    bpy.ops.wm.open_mainfile(filepath=str(edited_path), use_scripts=False)
    reload_edited = snapshot() == edited
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.wm.obj_import(filepath=str(output / 'edited.obj'),
                          forward_axis='NEGATIVE_Y', up_axis='Z')
    exported_objects = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
    export_reload = (sum(len(obj.data.vertices) for obj in exported_objects) ==
                     sum(part['vertices'] for part in edited.values()) and
                     sum(len(obj.data.polygons) for obj in exported_objects) ==
                     sum(part['faces'] for part in edited.values()))
    result = {'success': all(preserved.values()) and edit_ok and reload_baseline and reload_edited and export_reload,
              'blender': bpy.app.version_string, 'baseline': baseline, 'edited': edited,
              'preserved_parts': preserved, 'target_edit_correct': edit_ok,
              'baseline_reload': reload_baseline, 'edited_reload': reload_edited,
              'export_obj_reload': export_reload,
              'scope': 'object_scale_edit_only; no surface_join, rig, UV, PBR or UE verification'}
    (output / 'blender-check.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    if not result['success']:
        raise RuntimeError('保持・編集・再読み込み検査が不合格')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
