"""Render a reproducible whole/part comparison in a separate Blender process."""
import json
from pathlib import Path
import sys

import bpy
from mathutils import Vector


def main(job_path):
    job = json.loads(Path(job_path).read_text(encoding='utf-8'))
    bpy.ops.wm.open_mainfile(filepath=job['source'], use_scripts=False)
    scene = bpy.context.scene
    bpy.context.view_layer.update()
    meshes = [obj for obj in scene.objects if obj.type == 'MESH']
    identities = {obj.name: obj.get('part_id') or obj.get('mwb_part_id') for obj in meshes}
    if set(identities.values()) != set(job['part_ids']):
        raise ValueError('比較シーンの部品IDに不足・未登録オブジェクトがあります')
    camera_data = bpy.data.cameras.new('mwb_compare_camera')
    camera = bpy.data.objects.new('mwb_compare_camera', camera_data)
    scene.collection.objects.link(camera)
    scene.camera = camera
    camera_data.type = 'ORTHO'
    if job['profile']['camera'] == 'auto':
        all_corners = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
        low = Vector([min(c[i] for c in all_corners) for i in range(3)])
        high = Vector([max(c[i] for c in all_corners) for i in range(3)])
        job['profile']['camera'] = dict(center=list((low + high) * 0.5),
                                       ortho_scale=max(max(high - low) * 1.5, 0.1))
    camera_data.ortho_scale = job['profile']['camera']['ortho_scale']
    camera_data.clip_end = max(camera_data.ortho_scale * 20, 100)
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.display.shading.color_type = 'MATERIAL'
    scene.display.shading.light = 'STUDIO'
    scene.display.shading.background_type = 'VIEWPORT'
    scene.display.shading.background_color = (0.8, 0.8, 0.8)
    # Keep individual images large enough to judge apertures, fingers and occlusion.
    # Contact sheets may downsample these, but the evidence PNGs retain the detail.
    scene.render.resolution_x = scene.render.resolution_y = 768
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.film_transparent = False
    center = Vector(job['profile']['camera']['center'])
    directions = {'front': (0, -1, 0), 'side': (1, 0, 0), 'top': (0, 0, 1),
                  'back': (0, 1, 0), 'oblique': (1, -1, 0.5)}
    part_cameras = job['profile'].setdefault('part_cameras', {})
    for part_id in job['part_ids']:
        if part_id not in part_cameras:
            corners = [o.matrix_world @ Vector(c) for o in meshes
                       if identities[o.name] == part_id for c in o.bound_box]
            low = Vector([min(c[i] for c in corners) for i in range(3)])
            high = Vector([max(c[i] for c in corners) for i in range(3)])
            part_cameras[part_id] = dict(center=list((low + high) * 0.5),
                                         ortho_scale=max(max(high - low) * 1.5, 0.01))
    for view in job['profile']['views']:
        scopes = [('whole', None), *[(pid, pid) for pid in job['part_ids']],
                  *[('detail-' + pid, pid) for pid in job['part_ids']]]
        for name, scope in scopes:
            framing = part_cameras[scope] if name.startswith('detail-') else job['profile']['camera']
            center = Vector(framing['center'])
            camera_data.ortho_scale = framing['ortho_scale']
            camera.location = center + Vector(directions[view]).normalized() * camera_data.ortho_scale * 3
            camera.rotation_euler = (center - camera.location).to_track_quat('-Z', 'Y').to_euler()
            for obj in meshes:
                obj.hide_render = scope is not None and identities[obj.name] != scope
            bpy.context.view_layer.update()
            scene.render.filepath = str(Path(job['output']) / f'{name}-{view}.png')
            bpy.ops.render.render(write_still=True)
    (Path(job['output']) / 'checks.json').write_text(json.dumps({
        'success': True, 'part_ids': job['part_ids'], 'profile': job['profile'],
        'blender_version': bpy.app.version_string}), encoding='utf-8')


if __name__ == '__main__':
    main(sys.argv[sys.argv.index('--') + 1])
