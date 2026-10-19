"""Blender: preserve upstream, derive only body faces, Z-up/feet-zero/1.7m."""
import hashlib
import json
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'assets/body-bases/makehuman-hm08'
OUTPUT = SOURCE / 'derived'


def main():
    if OUTPUT.exists():
        raise RuntimeError('Derived files already exist. Do not overwrite.')
    manifest = json.loads((SOURCE / 'manifest.json').read_text(encoding='utf-8'))
    for f in manifest['files']:
        assert hashlib.sha256((SOURCE / f['file']).read_bytes()).hexdigest() == f['sha256']
    # Preserve UV indexing. Only the officially named body group is exported;
    # fitting helpers and joint marker cubes are not body geometry.
    vertices, texcoords, faces, uv_faces = [], [], [], []
    group = None
    for line in (SOURCE / 'base.obj').read_text(encoding='utf-8').splitlines():
        words = line.split()
        if not words:
            continue
        if words[0] == 'v':
            vertices.append(tuple(map(float, words[1:4])))
        elif words[0] == 'vt':
            texcoords.append(tuple(map(float, words[1:3])))
        elif words[0] == 'g':
            group = words[1:]
        elif words[0] == 'f' and group == ['body']:
            tokens = [w.split('/') for w in words[1:]]
            faces.append([int(w[0]) - 1 for w in tokens])
            uv_faces.append([int(w[1]) - 1 for w in tokens])
    assert faces
    used = sorted({v for face in faces for v in face})
    index = {v: i for i, v in enumerate(used)}
    # HM08 faces source -Z. Rotate to our front camera at -Y, preserving handedness.
    points = [Vector((-vertices[v][0], vertices[v][2], vertices[v][1])) for v in used]
    low = Vector(tuple(min(p[i] for p in points) for i in range(3)))
    high = Vector(tuple(max(p[i] for p in points) for i in range(3)))
    factor = 1.7 / (high.z - low.z)
    offset = Vector(((low.x + high.x) / 2, (low.y + high.y) / 2, low.z))
    points = [(p - offset) * factor for p in points]
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    mesh = bpy.data.meshes.new('MakeHuman HM08 body only')
    mesh.from_pydata(points, [], [[index[v] for v in face] for face in faces])
    mesh.update()
    obj = bpy.data.objects.new('body_base_candidate', mesh)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    uv = mesh.uv_layers.new(name='upstream_uv')
    for polygon, face_uv in zip(mesh.polygons, uv_faces):
        for loop, tid in zip(polygon.loop_indices, face_uv):
            uv.data[loop].uv = texcoords[tid]
    obj['upstream_commit'] = manifest['commit']
    obj['license'] = 'CC0-1.0'
    obj['adopted'] = False
    bpy.context.scene.unit_settings.system = 'METRIC'
    bpy.context.scene.unit_settings.scale_length = 1.0
    for area in bpy.context.screen.areas:
        if area.type == 'VIEW_3D':
            area.spaces.active.region_3d.view_distance = 3.4
            area.spaces.active.region_3d.view_location = Vector((0, 0, 0.85))
            area.spaces.active.clip_end = 100
    OUTPUT.mkdir()
    blend = OUTPUT / 'body-base.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    bpy.ops.wm.obj_export(filepath=str(OUTPUT / 'body-base.obj'), export_selected_objects=True,
                          forward_axis='NEGATIVE_Y', up_axis='Z', export_materials=False)
    before = (len(mesh.vertices), len(mesh.polygons))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.wm.obj_import(filepath=str(OUTPUT / 'body-base.obj'), forward_axis='NEGATIVE_Y', up_axis='Z')
    imported = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    assert len(imported) == 1
    assert (len(imported[0].data.vertices), len(imported[0].data.polygons)) == before
    assert abs(imported[0].dimensions.z - 1.7) < 0.0001
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    assert len([o for o in bpy.context.scene.objects if o.type == 'MESH']) == 1
    result = {'source_commit': manifest['commit'], 'source_sha256': manifest['files'][0]['sha256'],
              'operation': 'Keep body group only, remove unused vertices, (x,y,z)->(-x,z,y), front=-Y, center XY, feet Z=0, height=1.7m',
              'scale_factor': factor, 'original_axis_offset': list(offset),
              'height_m': 1.7, 'height_is_design_assumption': True,
              'vertices': before[0], 'faces': before[1], 'uv': 'copied from upstream, appearance unreviewed',
              'rigged': False, 'textures': False, 'ue_verified': False,
              'obj_reloaded': True, 'blend_reloaded': True, 'adopted': False,
              'files': [{'file': p.name, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                        for p in sorted(OUTPUT.iterdir()) if p.is_file()]}
    (OUTPUT / 'derivation.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
