"""Blender-only, geometry-preserving rig experiments. No automatic acceptance."""
import hashlib
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Vector


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def coordinates(obj):
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        return [list(evaluated.matrix_world @ v.co) for v in mesh.vertices]
    finally:
        evaluated.to_mesh_clear()


def value_data(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    try:
        return list(value)
    except TypeError:
        return str(value)


def appearance_data(obj):
    mesh = obj.data
    materials = []
    for slot in obj.material_slots:
        mat = slot.material
        if mat is None:
            materials.append(None)
            continue
        materials.append(dict(name=mat.name, color=list(mat.diffuse_color),
                              nodes=[dict(name=n.name, type=n.bl_idname,
                                          inputs={s.identifier: value_data(s.default_value)
                                                  for s in n.inputs if hasattr(s, 'default_value')})
                                     for n in mat.node_tree.nodes] if mat.node_tree else [],
                              links=[(l.from_node.name, l.from_socket.identifier,
                                      l.to_node.name, l.to_socket.identifier)
                                     for l in mat.node_tree.links] if mat.node_tree else []))
    return dict(vertices=[list(v.co) for v in mesh.vertices],
                edges=[list(e.vertices) for e in mesh.edges],
                faces=[(list(p.vertices), p.material_index, p.use_smooth) for p in mesh.polygons],
                uv={layer.name: [list(item.uv) for item in layer.data] for layer in mesh.uv_layers},
                materials=materials, matrix=[list(row) for row in obj.matrix_world],
                hide_render=obj.hide_render)


def inspect_scene(job):
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
    reasons = []
    if not meshes:
        reasons.append('メッシュがありません')
    if any(o.type not in ('MESH', 'CAMERA', 'LIGHT') for o in bpy.context.scene.objects):
        reasons.append('既存の骨格または未対応オブジェクトがあります')
    objects = {}
    for obj in meshes:
        pid = obj.get('part_id') or obj.get('mwb_part_id')
        if not pid:
            reasons.append(obj.name + ': 部品IDがありません')
        if (obj.modifiers or obj.constraints or obj.parent or obj.data.shape_keys or
                obj.animation_data or obj.vertex_groups or obj.data.animation_data):
            reasons.append(obj.name + ': 既存の変形・ウェイト・アニメーションは未対応です')
        if not obj.data.vertices or not obj.data.polygons:
            reasons.append(obj.name + ': 空の形状です')
        world = coordinates(obj)
        if any(not math.isfinite(v) for point in world for v in point):
            reasons.append(obj.name + ': 非有限の座標です')
        objects[obj.name] = dict(part_id=pid, vertices=len(obj.data.vertices), faces=len(obj.data.polygons),
                                 positions=world, appearance_hash=digest(appearance_data(obj)))
    if {o['part_id'] for o in objects.values()} != set(job['part_ids']):
        reasons.append('候補構成と実メッシュの部品IDが一致しません')
    for image in bpy.data.images:
        if image.source == 'FILE' and not image.packed_file:
            reasons.append(image.name + ': 外部画像は先に元モデル側で由来とパックを確認してください')
    return dict(ready=not reasons, unsupported=reasons, objects=objects,
                units=dict(system=bpy.context.scene.unit_settings.system,
                           scale_length=bpy.context.scene.unit_settings.scale_length),
                vertices=sum(o['vertices'] for o in objects.values()),
                faces=sum(o['faces'] for o in objects.values()),
                part_count=len({o['part_id'] for o in objects.values()}))


def frame_profile(meshes):
    points = [Vector(p) for obj in meshes for p in coordinates(obj)]
    low = Vector([min(p[i] for p in points) for i in range(3)])
    high = Vector([max(p[i] for p in points) for i in range(3)])
    return dict(center=list((low + high) / 2), ortho_scale=max(max(high - low) * 1.8, 0.1))


def render_views(output, prefix, profile):
    scene = bpy.context.scene
    camera_data = bpy.data.cameras.new('mwb_rig_camera')
    camera = bpy.data.objects.new('mwb_rig_camera', camera_data)
    scene.collection.objects.link(camera)
    scene.camera = camera
    camera_data.type = 'ORTHO'
    camera_data.ortho_scale = profile['ortho_scale']
    camera_data.clip_end = max(camera_data.ortho_scale * 20, 100)
    center = Vector(profile['center'])
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.display.shading.color_type = 'MATERIAL'
    scene.display.shading.light = 'STUDIO'
    scene.display.shading.background_type = 'VIEWPORT'
    scene.display.shading.background_color = (0.8, 0.8, 0.8)
    scene.render.resolution_x = scene.render.resolution_y = 768
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.film_transparent = False
    images = []
    try:
        for view, direction in {'front': (0, -1, 0), 'side': (1, 0, 0),
                                'back': (0, 1, 0), 'oblique': (1, -1, 0.5)}.items():
            camera.location = center + Vector(direction).normalized() * camera_data.ortho_scale * 3
            camera.rotation_euler = (center - camera.location).to_track_quat('-Z', 'Y').to_euler()
            name = f'{prefix}-{view}.png'
            scene.render.filepath = str(output / name)
            bpy.ops.render.render(write_still=True)
            images.append(name)
    finally:
        bpy.data.objects.remove(camera, do_unlink=True)
        bpy.data.cameras.remove(camera_data)
    return images


def build(definition):
    scene = bpy.context.scene
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT')
    data = bpy.data.armatures.new('MWB_RIG')
    arm = bpy.data.objects.new('MWB_RIG', data)
    scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    for b in definition['bones']:
        bone = data.edit_bones.new(b['name'])
        bone.head, bone.tail = b['head'], b['tail']
        if b['parent'] is not None:
            bone.parent = data.edit_bones[b['parent']]
    bpy.ops.object.mode_set(mode='OBJECT')
    for name, binding in definition['bindings'].items():
        obj = bpy.data.objects[name]
        if binding['mode'] == 'static':
            continue
        if binding['mode'] == 'rigid':
            obj.vertex_groups.new(name=binding['bone']).add(list(range(len(obj.data.vertices))), 1, 'REPLACE')
        else:
            groups = {b['name']: obj.vertex_groups.new(name=b['name']) for b in definition['bones']}
            for index, weights in enumerate(binding['vertices']):
                for bone, weight in weights.items():
                    groups[bone].add([index], weight, 'REPLACE')
        modifier = obj.modifiers.new('MWB_DEFORM', 'ARMATURE')
        modifier.object = arm
        modifier.use_vertex_groups = True
        modifier.use_bone_envelopes = False
        # Explicit linear skinning keeps the test portable; other modes need their own validation.
        modifier.use_deform_preserve_volume = False
    bpy.context.view_layer.update()
    return arm


def rest_checks(before, objects, tolerance):
    rows = {}
    for name, baseline in before['objects'].items():
        obj = objects[name]
        current = coordinates(obj)
        maximum = max((Vector(a) - Vector(b)).length for a, b in zip(baseline['positions'], current))
        rows[name] = dict(appearance_unchanged=digest(appearance_data(obj)) == baseline['appearance_hash'],
                          vertex_count_unchanged=len(current) == baseline['vertices'],
                          maximum_position_error=maximum)
    return rows, all(r['appearance_unchanged'] and r['vertex_count_unchanged'] and
                     r['maximum_position_error'] <= tolerance for r in rows.values())


def rig_evidence(arm, meshes):
    return dict(bones=[dict(name=b.name, parent=b.parent.name if b.parent else None,
                           head=list(b.head_local), tail=list(b.tail_local)) for b in arm.data.bones],
                weights={o.name: [{o.vertex_groups[g.group].name: g.weight for g in v.groups}
                                   for v in o.data.vertices] for o in meshes})


def main(job_path):
    job = json.loads(Path(job_path).read_text(encoding='utf-8'))
    output = Path(job['output'])
    bpy.ops.wm.open_mainfile(filepath=job['source'], use_scripts=False)
    bpy.context.view_layer.update()
    inventory = inspect_scene(job)
    report = dict(success=True, source_hash=job['source_hash'], experiment_id=job['experiment_id'],
                  blender_version=bpy.app.version_string, mode=job['mode'], **inventory,
                  visual_review='not_run', motion_review='not_run', ue_verified=False,
                  memory_measurement='not_measured')
    if job['mode'] == 'inspect':
        write(output / 'checks.json', report)
        return
    if not inventory['ready']:
        raise ValueError('未対応の静止入力: ' + '; '.join(inventory['unsupported']))
    definition = job['definition']
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    objects = {o.name: o for o in meshes}
    if set(objects) != set(definition['bindings']):
        raise ValueError('追従対象オブジェクトが一致しません')
    profile = frame_profile(meshes)
    report['profile'] = profile
    report['baseline_images'] = render_views(output, 'baseline', profile)
    arm = build(definition)
    rows, preserved = rest_checks(inventory, objects, definition['rest_tolerance'])
    report.update(rest_checks=rows, rest_geometry_preserved=preserved)
    if not preserved:
        write(output / 'checks.json', dict(report, success=False))
        raise ValueError('リグ導入で元ポーズの形状・材質・変換が変わりました')
    report['rest_images'] = render_views(output, 'rest', profile)
    report['samples'] = []
    for test in definition['poses']:
        for index in range(test['samples']):
            fraction = index / (test['samples'] - 1)
            for bone in arm.pose.bones:
                bone.rotation_mode = 'XYZ'
                bone.rotation_euler = [math.radians(x) * fraction
                                       for x in test['rotations'].get(bone.name, [0, 0, 0])]
            bpy.context.view_layer.update()
            points = {name: coordinates(obj) for name, obj in objects.items()}
            if any(not math.isfinite(x) for vertices in points.values() for p in vertices for x in p):
                raise ValueError('試験ポーズに非有限の座標があります')
            displacements = {name: max((Vector(a) - Vector(b)).length
                                       for a, b in zip(inventory['objects'][name]['positions'], vertices))
                             for name, vertices in points.items()}
            report['samples'].append(dict(name=test['name'], requirement_id=test['requirement_id'],
                                           sample=index, fraction=fraction,
                                           maximum_displacement_by_object=displacements,
                                           images=render_views(output, f'pose-{test["name"]}-{index:03d}', profile)))
    for bone in arm.pose.bones:
        bone.matrix_basis = Matrix.Identity(4)
    bpy.context.view_layer.update()
    before_save = rig_evidence(arm, meshes)
    model = output / 'model.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(model))
    bpy.ops.wm.open_mainfile(filepath=str(model), use_scripts=False)
    bpy.context.view_layer.update()
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    arm = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
    if rig_evidence(arm, meshes) != before_save:
        raise ValueError('保存後に骨格・ウェイトが一致しません')
    rows, preserved = rest_checks(inventory, {o.name: o for o in meshes}, definition['rest_tolerance'])
    if not preserved:
        raise ValueError('保存・再読込後の元ポーズ保持が不合格です')
    report.update(rest_checks=rows, rest_geometry_preserved=True, saved_rig=before_save,
                  animation_coverage='discrete_samples_only', continuous_playback_verified=False,
                  collision_detection='not_run', scope=definition['scope'])
    write(output / 'checks.json', report)


if __name__ == '__main__':
    main(sys.argv[sys.argv.index('--') + 1])
