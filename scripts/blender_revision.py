"""Inspect or import a manually edited .blend without changing registered sources."""
from __future__ import annotations

import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Euler, Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from blender_workbench import snapshot


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def geometry(part):
    return [(obj['name'], obj['role'], obj['mesh_hash']) for obj in part['objects']]


def transforms(part):
    return {obj['name']: {'location': obj['location'], 'rotation': obj['rotation'],
                          'scale': obj['scale']} for obj in part['objects']}


def materials(part):
    return {obj['name']: obj['materials'] for obj in part['objects']}


def world_matrices():
    result = {}
    for obj in bpy.context.scene.objects:
        if obj.type == 'MESH':
            pid = obj.get('part_id') or obj.get('mwb_part_id')
            result.setdefault(pid, {})[obj.name] = obj.matrix_world.copy()
    return result


def composition_updates(before_world, after_world, edit, composition):
    updates = {}
    for part_id in edit['target_part_ids']:
        if set(before_world[part_id]) != set(after_world[part_id]):
            raise ValueError('配置変更で部品内のオブジェクトが増減しました')
        deltas = [after_world[part_id][name] @ before_world[part_id][name].inverted()
                  for name in before_world[part_id]]
        first = deltas[0]
        if any(abs(first[row][col] - delta[row][col]) > 1e-5
               for delta in deltas[1:] for row in range(4) for col in range(4)):
            raise ValueError('部品内で異なる配置変更があり、単一の部品変換に表せません')
        binding = next(item for item in composition if item['part_id'] == part_id)
        old = (Matrix.Translation(Vector(binding['location'])) @
               Euler([math.radians(x) for x in binding['rotation_degrees']]).to_matrix().to_4x4() @
               Matrix.Diagonal((*binding['scale'], 1)))
        location, rotation, scale = (first @ old).decompose()
        updates[part_id] = {'location': list(location),
                            'rotation_degrees': [math.degrees(x) for x in rotation.to_euler()],
                            'scale': list(scale)}
    return updates


def close_values(expected, actual):
    if isinstance(expected, dict) and isinstance(actual, dict):
        return set(expected) == set(actual) and all(close_values(expected[key], actual[key]) for key in expected)
    if isinstance(expected, list) and isinstance(actual, list):
        return len(expected) == len(actual) and all(close_values(a, b) for a, b in zip(expected, actual))
    if type(expected) in (int, float) and type(actual) in (int, float):
        return math.isclose(expected, actual, abs_tol=1e-5)
    return expected == actual


def compare(before, after, edit):
    if set(before) != set(after):
        raise ValueError('部品IDの追加・欠落がありました')
    target = set(edit['target_part_ids'])
    if not target or not target <= set(before):
        raise ValueError('変更対象の部品IDが不正です')
    mode = edit['mode']
    if mode not in ('part_shape', 'part_transform', 'material_parameters'):
        raise ValueError('手修正の種類が不明です')
    changed = []
    for part_id in before:
        if part_id not in target:
            if before[part_id] != after[part_id]:
                raise ValueError(f'申告していない部品が変更されました: {part_id}')
            continue
        old, new = before[part_id], after[part_id]
        if mode == 'part_shape':
            if transforms(old) != transforms(new) or materials(old) != materials(new):
                raise ValueError('形状変更の対象で変換・材質も変わっています')
        elif mode == 'part_transform':
            if geometry(old) != geometry(new) or materials(old) != materials(new):
                raise ValueError('配置変更の対象で形状・材質も変わっています')
        elif geometry(old) != geometry(new) or transforms(old) != transforms(new):
            raise ValueError('材質変更の対象で形状・変換も変わっています')
        if old != new:
            changed.append(part_id)
    if not changed:
        raise ValueError('対象に変更がありません')
    if mode == 'part_transform':
        declared_before = edit.get('before_transform')
        declared_after = edit.get('after_transform')
        actual_before = {pid: transforms(before[pid]) for pid in target}
        actual_after = {pid: transforms(after[pid]) for pid in target}
        if not close_values(declared_before, actual_before) or not close_values(declared_after, actual_after):
            raise ValueError('申告した変更前後の変換と実ファイルが一致しません')
    return changed


def render(output):
    scene = bpy.context.scene
    meshes = [obj for obj in scene.objects if obj.type == 'MESH']
    corners = [obj.matrix_world @ Vector(corner) for obj in meshes for corner in obj.bound_box]
    low = Vector([min(point[i] for point in corners) for i in range(3)])
    high = Vector([max(point[i] for point in corners) for i in range(3)])
    center = (low + high) * 0.5
    span = max(high - low)
    camera_data = bpy.data.cameras.new('mwb_revision_camera')
    camera = bpy.data.objects.new('mwb_revision_camera', camera_data)
    scene.collection.objects.link(camera)
    scene.camera = camera
    camera_data.type = 'ORTHO'
    camera_data.ortho_scale = max(span * 1.7, 0.1)
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.display.shading.color_type = 'MATERIAL'
    scene.render.resolution_x = scene.render.resolution_y = 384
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    previews = output / 'previews'
    previews.mkdir()
    for name, direction in {'front': (0, -1, 0), 'side': (1, 0, 0),
                            'back': (0, 1, 0), 'oblique': (1, -1, 0.5)}.items():
        camera.location = center + Vector(direction).normalized() * max(span * 2.5, 0.2)
        camera.rotation_euler = (center - camera.location).to_track_quat('-Z', 'Y').to_euler()
        scene.render.filepath = str(previews / f'{name}.png')
        bpy.ops.render.render(write_still=True)
    bpy.data.objects.remove(camera, do_unlink=True)


def main(job_path):
    job = json.loads(Path(job_path).read_text(encoding='utf-8'))
    output = Path(job['output'])
    output.mkdir(parents=True, exist_ok=False)
    bpy.ops.wm.open_mainfile(filepath=job['source'], use_scripts=False)
    before = snapshot()
    before_world = world_matrices()
    if job['mode'] == 'manual_import':
        bpy.ops.wm.open_mainfile(filepath=job['incoming'], use_scripts=False)
        after = snapshot()
        after_world = world_matrices()
        changed = compare(before, after, job['edit'])
        updates = (composition_updates(before_world, after_world, job['edit'], job['composition'])
                   if job['edit']['mode'] == 'part_transform' else {})
        for obj in bpy.context.scene.objects:
            if obj.type != 'MESH':
                continue
            part_id = obj.get('part_id') or obj.get('mwb_part_id')
            material_id = job.get('material_ids', {}).get(part_id)
            if material_id:
                for material in obj.data.materials:
                    if material:
                        material['material_id'] = material_id
        if job.get('material_ids'):
            after = snapshot()
    else:
        after, changed, updates = before, [], {}
    if job.get('render_previews', True):
        render(output)
    bpy.ops.wm.save_as_mainfile(filepath=str(output / 'model.blend'))
    bpy.ops.wm.obj_export(filepath=str(output / 'model.obj'))
    write(output / 'checks.json', {'success': True, 'mode': job['mode'],
                                   'blender_version': bpy.app.version_string,
                                   'changed_part_ids': changed, 'before': before, 'after': after,
                                   'composition_updates': updates,
                                   'visual_review': 'uncertain' if job.get('render_previews', True) else
                                                    'deferred_to_final_character'})


if __name__ == '__main__':
    main(sys.argv[sys.argv.index('--') + 1])
