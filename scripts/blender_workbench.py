"""Limited production operations. No arbitrary user-provided Python is executed."""
import hashlib
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector


def snapshot():
    result = {}
    for obj in bpy.context.scene.objects:
        if obj.type != 'MESH':
            continue
        pid = obj.get('part_id')
        if not pid or pid in result:
            raise RuntimeError('部品IDが欠落または重複しています')
        vertices = [list(v.co) for v in obj.data.vertices]
        faces = [list(p.vertices) for p in obj.data.polygons]
        if not vertices or not faces or not all(math.isfinite(x) for v in vertices for x in v):
            raise RuntimeError('空メッシュまたは非有限座標')
        materials = []
        for mat in obj.data.materials:
            if not mat:
                continue
            node = mat.node_tree.nodes.get('Principled BSDF') if mat.use_nodes else None
            materials.append({'id': mat.get('material_id'), 'name': mat.name,
                              'base_color': list(node.inputs['Base Color'].default_value) if node else list(mat.diffuse_color),
                              'roughness': node.inputs['Roughness'].default_value if node else mat.roughness,
                              'metallic': node.inputs['Metallic'].default_value if node else mat.metallic})
        result[pid] = {'mesh_hash': hashlib.sha256(json.dumps([vertices, faces]).encode()).hexdigest(),
                       'vertices': len(vertices), 'faces': len(faces), 'location': list(obj.location),
                       'rotation': list(obj.rotation_euler), 'scale': list(obj.scale), 'materials': materials}
    return result


def main():
    job = json.loads(Path(sys.argv[sys.argv.index('--') + 1]).read_text(encoding='utf-8'))
    output = Path(job['output'])
    if job['source']:
        bpy.ops.wm.open_mainfile(filepath=job['source'], use_scripts=False)
        for obj in list(bpy.context.scene.objects):
            if obj.type != 'MESH':
                bpy.data.objects.remove(obj, do_unlink=True)
    else:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        for part in job['parts']:
            before = set(bpy.data.objects)
            bpy.ops.wm.obj_import(filepath=part['mesh'], forward_axis='NEGATIVE_Y', up_axis='Z')
            imported = [o for o in bpy.data.objects if o not in before and o.type == 'MESH']
            if len(imported) != 1:
                raise RuntimeError('部品OBJは1メッシュである必要があります')
            imported[0]['part_id'] = part['part_id']
            imported[0].name = 'part_' + part['part_id']
    before = snapshot()
    mapping = {obj.get('part_id'): obj for obj in bpy.context.scene.objects if obj.type == 'MESH'}
    if set(mapping) != {p['part_id'] for p in job['composition']}:
        raise RuntimeError('構成とBlender内の部品が一致しません')
    if job['stage'] == 'assembly':
        for part in job['composition']:
            obj = mapping[part['part_id']]
            obj.location = part['location']
            obj.rotation_euler = [math.radians(x) for x in part['rotation_degrees']]
            obj.scale = part['scale']
    elif job['stage'] == 'surface':
        for specification in job['materials']:
            obj = mapping[specification['part_id']]
            mat = bpy.data.materials.new(specification['name'] + '_' + specification['id'])
            mat['material_id'] = specification['id']
            mat.use_nodes = True
            node = mat.node_tree.nodes.get('Principled BSDF')
            color = [*specification['color'], 1]
            node.inputs['Base Color'].default_value = color
            node.inputs['Roughness'].default_value = specification['roughness']
            node.inputs['Metallic'].default_value = specification['metallic']
            mat.diffuse_color = color
            mat.roughness = specification['roughness']
            mat.metallic = specification['metallic']
            obj.data.materials.clear()
            obj.data.materials.append(mat)
    else:
        raise RuntimeError('未対応のBlender工程')
    after = snapshot()
    unchanged = {}
    for pid in before:
        if job['stage'] == 'surface':
            unchanged[pid] = {k: v for k, v in before[pid].items() if k != 'materials'} == {
                k: v for k, v in after[pid].items() if k != 'materials'}
        elif job['edit'] and pid != job['edit']['part_id']:
            unchanged[pid] = before[pid] == after[pid]
    if not all(unchanged.values()):
        raise RuntimeError('保持対象が変更されています')
    if job['stage'] == 'surface':
        for specification in job['materials']:
            actual = after[specification['part_id']]['materials']
            if len(actual) != 1 or actual[0]['id'] != specification['id']:
                raise RuntimeError('材質割当不一致')
            for key in ('roughness', 'metallic'):
                if not math.isclose(actual[0][key], specification[key], abs_tol=1e-6):
                    raise RuntimeError('材質パラメータ不一致')
    scene = bpy.context.scene
    scene.unit_settings.system = 'METRIC'
    bpy.context.view_layer.update()
    corners = [obj.matrix_world @ Vector(v) for obj in mapping.values() for v in obj.bound_box]
    low = Vector([min(p[i] for p in corners) for i in range(3)])
    high = Vector([max(p[i] for p in corners) for i in range(3)])
    center, size = (low + high) * 0.5, max(high - low)
    if job['source'] and 'preview_center' in scene and 'preview_size' in scene:
        center, size = Vector(scene['preview_center']), scene['preview_size']
    scene['preview_center'] = list(center)
    scene['preview_size'] = size
    bpy.ops.object.camera_add()
    camera = bpy.context.object
    camera.data.type = 'ORTHO'
    camera.data.ortho_scale = max(size * 1.7, 0.1)
    scene.camera = camera
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.display.shading.color_type = 'MATERIAL'
    scene.display.shading.light = 'STUDIO'
    scene.display.shading.show_cavity = True
    scene.render.resolution_x = scene.render.resolution_y = 384
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    for view, direction in {'front': (0, -3, 0), 'side': (3, 0, 0), 'back': (0, 3, 0), 'perspective': (2, -3, 2)}.items():
        camera.location = center + Vector(direction) * max(size, 0.1)
        camera.rotation_euler = (center - camera.location).to_track_quat('-Z', 'Y').to_euler()
        bpy.context.view_layer.update()
        scene.render.filepath = str(output / f'{view}.png')
        bpy.ops.render.render(write_still=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output / 'model.blend'))
    bpy.ops.wm.obj_export(filepath=str(output / 'model.obj'), forward_axis='NEGATIVE_Y', up_axis='Z',
                          export_materials=job['stage'] == 'surface')
    bpy.ops.wm.open_mainfile(filepath=str(output / 'model.blend'), use_scripts=False)
    reloaded = snapshot()
    success = reloaded == after
    result = {'success': success, 'blender': bpy.app.version_string, 'parts': reloaded,
              'preserved': unchanged, 'blend_reload': success,
              'preview': 'Workbench material-color preview; not a PBR lighting evaluation',
              'ue_verified': False, 'uv_verified': False}
    (output / 'checks.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    if not success:
        raise RuntimeError('保存後の再読み込み検査が不合格です')


if __name__ == '__main__':
    main()
