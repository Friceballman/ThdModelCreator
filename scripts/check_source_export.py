"""Read back a generated source bundle inside Blender; no rendering or generation."""
import json
from pathlib import Path
import sys
import bpy

manifest = Path(sys.argv[sys.argv.index('--') + 1]).resolve()
data = json.loads(manifest.read_text(encoding='utf-8'))
checks = []
for candidate in data['candidates']:
    files = [manifest.parent / f['file'] for f in candidate['files']]
    blend = next(f for f in files if f.suffix == '.blend')
    obj_path = next(f for f in files if f.suffix == '.obj')
    bpy.ops.wm.open_mainfile(filepath=str(blend), use_scripts=False)
    objects = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    before = sum(len(o.data.polygons) for o in objects)
    material_count = sum(len(o.data.materials) for o in objects)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.wm.obj_import(filepath=str(obj_path), forward_axis='NEGATIVE_Y', up_axis='Z')
    after_objects = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    after = sum(len(o.data.polygons) for o in after_objects)
    after_material_count = sum(len(o.data.materials) for o in after_objects)
    if before != after or material_count != after_material_count:
        raise RuntimeError('出力先でのモデル再読み込みが不一致です')
    checks.append({'candidate_id': candidate['candidate_id'], 'faces': after,
                   'material_slots': after_material_count})
print(json.dumps({'success': True, 'candidates': checks}))
