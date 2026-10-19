"""Limited production operations. No arbitrary user-provided Python is executed."""
import hashlib
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Euler, Matrix, Vector


def snapshot():
    result = {}
    for obj in bpy.context.scene.objects:
        if obj.type != 'MESH':
            continue
        pid = obj.get('part_id') or obj.get('mwb_part_id')
        if not pid:
            raise RuntimeError('部品IDが欠落しています')
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
                              'metallic': node.inputs['Metallic'].default_value if node else mat.metallic,
                              'pattern': mat.get('mwb_pattern')})
        entry = {'name': obj.name, 'role': obj.get('mwb_object_role', 'geometry'),
                 'mesh_hash': hashlib.sha256(json.dumps([vertices, faces]).encode()).hexdigest(),
                 'vertices': len(vertices), 'faces': len(faces), 'location': list(obj.location),
                 'rotation': list(obj.rotation_euler), 'scale': list(obj.scale), 'materials': materials}
        result.setdefault(pid, {'objects': [], 'materials': materials})['objects'].append(entry)
        if result[pid]['materials'] != materials:
            result[pid]['materials'] = []
    for item in result.values():
        item['objects'].sort(key=lambda obj: obj['name'])
    return result


def without_materials(part):
    return {'objects': [{k: v for k, v in obj.items() if k != 'materials'}
                        for obj in part['objects']]}


def new_material(specification, suffix, shader):
    mat = bpy.data.materials.new(specification['name'] + '_' + specification['id'] + suffix)
    mat['material_id'] = specification['id']
    mat['zone'] = suffix or 'base'
    mat.use_nodes = True
    node = mat.node_tree.nodes.get('Principled BSDF')
    color = [*shader['base_color'], 1]
    node.inputs['Base Color'].default_value = color
    node.inputs['Roughness'].default_value = shader['roughness']
    node.inputs['Metallic'].default_value = shader['metallic']
    mat.diffuse_color = color
    mat.roughness = shader['roughness']
    mat.metallic = shader['metallic']
    pattern = shader.get('pattern')
    if pattern:
        noise = mat.node_tree.nodes.new('ShaderNodeTexNoise')
        noise.inputs['Scale'].default_value = pattern['scale']
        if pattern.get('secondary_color') is not None:
            ramp = mat.node_tree.nodes.new('ShaderNodeValToRGB')
            ramp.color_ramp.elements[0].color = (*shader['base_color'], 1)
            ramp.color_ramp.elements[1].color = (*pattern['secondary_color'], 1)
            mat.node_tree.links.new(noise.outputs['Fac'], ramp.inputs['Fac'])
            mat.node_tree.links.new(ramp.outputs['Color'], node.inputs['Base Color'])
        if pattern.get('bump_strength', 0):
            bump = mat.node_tree.nodes.new('ShaderNodeBump')
            bump.inputs['Strength'].default_value = pattern['bump_strength']
            mat.node_tree.links.new(noise.outputs['Fac'], bump.inputs['Height'])
            mat.node_tree.links.new(bump.outputs['Normal'], node.inputs['Normal'])
        mat['mwb_pattern'] = json.dumps(pattern, sort_keys=True)
    return mat


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
            if part.get('blend'):
                with bpy.data.libraries.load(part['blend'], link=False) as (source, target):
                    target.objects = list(source.objects)
                imported = [o for o in target.objects if o and o.type == 'MESH']
                for obj in imported:
                    bpy.context.scene.collection.objects.link(obj)
            else:
                before = set(bpy.data.objects)
                bpy.ops.wm.obj_import(filepath=part['mesh'], forward_axis='NEGATIVE_Y', up_axis='Z')
                imported = [o for o in bpy.data.objects if o not in before and o.type == 'MESH']
            if not imported:
                raise RuntimeError('部品候補にメッシュがありません')
            for index, obj in enumerate(imported):
                obj['part_id'] = part['part_id']
                obj['mwb_part_id'] = part['part_id']
                obj['mwb_source_candidate_id'] = part['candidate_id']
                obj['mwb_object_role'] = obj.get('mwb_object_role', 'geometry')
                obj.name = 'part_' + part['part_id'] + '_' + str(index) + '_' + obj.name
    before = snapshot()
    mapping = {}
    for obj in bpy.context.scene.objects:
        if obj.type == 'MESH':
            mapping.setdefault(obj.get('part_id') or obj.get('mwb_part_id'), []).append(obj)
    if set(mapping) != {p['part_id'] for p in job['composition']}:
        raise RuntimeError('構成とBlender内の部品が一致しません')
    if job['stage'] == 'assembly':
        for part in job['composition']:
            transform = (Matrix.Translation(Vector(part['location'])) @
                         Euler([math.radians(x) for x in part['rotation_degrees']]).to_matrix().to_4x4() @
                         Matrix.Diagonal((*part['scale'], 1)))
            for obj in mapping[part['part_id']]:
                obj.matrix_world = transform @ obj.matrix_world
    elif job['stage'] == 'surface':
        for specification in job['materials']:
            base_shader = {'base_color': specification['color'],
                           'roughness': specification['roughness'],
                           'metallic': specification['metallic']}
            if specification.get('shader', {}).get('pattern'):
                base_shader['pattern'] = specification['shader']['pattern']
            base = new_material(specification, '', base_shader)
            zones = specification.get('zones', [])
            used_zones = set()
            for obj in mapping[specification['part_id']]:
                matching = [z for z in zones if z['object_role'] == obj.get('mwb_object_role', 'geometry')]
                if len(matching) > 1:
                    raise RuntimeError('材質領域の割当が重複しています')
                if matching:
                    zone = matching[0]
                    used_zones.add(zone['name'])
                    mat = new_material(specification, '_' + zone['name'], zone.get('shader', base_shader))
                else:
                    mat = base
                obj.data.materials.clear()
                obj.data.materials.append(mat)
            if used_zones != {z['name'] for z in zones}:
                raise RuntimeError('割当先のない材質領域があります')
    else:
        raise RuntimeError('未対応のBlender工程')
    after = snapshot()
    unchanged = {}
    for pid in before:
        if job['stage'] == 'surface':
            unchanged[pid] = without_materials(before[pid]) == without_materials(after[pid])
        elif job['edit'] and pid != job['edit']['part_id']:
            unchanged[pid] = before[pid] == after[pid]
    if not all(unchanged.values()):
        raise RuntimeError('保持対象が変更されています')
    if job['stage'] == 'surface':
        for specification in job['materials']:
            for obj in after[specification['part_id']]['objects']:
                actual = obj['materials']
                if len(actual) != 1 or actual[0]['id'] != specification['id']:
                    raise RuntimeError('材質割当不一致')
                zone = next((z for z in specification.get('zones', []) if z['object_role'] == obj['role']), None)
                expected = zone.get('shader') if zone else None
                expected = expected or {'base_color': specification['color'],
                                        'roughness': specification['roughness'],
                                        'metallic': specification['metallic']}
                if zone is None and specification.get('shader', {}).get('pattern'):
                    expected['pattern'] = specification['shader']['pattern']
                for key in ('roughness', 'metallic'):
                    if not math.isclose(actual[0][key], expected[key], abs_tol=1e-6):
                        raise RuntimeError('材質パラメータ不一致')
                if any(not math.isclose(a, b, abs_tol=1e-6) for a, b in zip(actual[0]['base_color'][:3], expected['base_color'])):
                    raise RuntimeError('材質色不一致')
                if actual[0]['pattern'] != (json.dumps(expected['pattern'], sort_keys=True) if expected.get('pattern') else None):
                    raise RuntimeError('プロシージャル模様の設定不一致')
    scene = bpy.context.scene
    scene.unit_settings.system = 'METRIC'
    bpy.context.view_layer.update()
    corners = [obj.matrix_world @ Vector(v) for objects in mapping.values() for obj in objects for v in obj.bound_box]
    low = Vector([min(p[i] for p in corners) for i in range(3)])
    high = Vector([max(p[i] for p in corners) for i in range(3)])
    center, size = (low + high) * 0.5, max(high - low)
    if job['source'] and 'preview_center' in scene and 'preview_size' in scene:
        center, size = Vector(scene['preview_center']), scene['preview_size']
    scene['preview_center'] = list(center)
    scene['preview_size'] = size
    if job['stage'] == 'surface':
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
              'preview': ('Workbench material-color preview; not a PBR lighting evaluation'
                          if job['stage'] == 'surface' else 'deferred_to_final_character'),
              'ue_verified': False, 'uv_verified': False}
    (output / 'checks.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    if not success:
        raise RuntimeError('保存後の再読み込み検査が不合格です')


if __name__ == '__main__':
    main()
