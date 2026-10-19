"""Explicit Blender v2 smoke test. Uses an isolated temporary project."""
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from model_workbench.storage import Store
from model_workbench.v2 import V2Workbench
from model_workbench.runtime import execute, load_config, REPO


def main():
    from PIL import Image
    with tempfile.TemporaryDirectory(prefix='mwb-v2-smoke-') as temporary:
        root = Path(temporary)
        config = load_config(REPO / 'experiments/config.example.json')
        store = Store(root / 'projects')
        wb = V2Workbench(store, config)
        project = store.create('Blender造形の接続試験', '単純立方体。制作品質の保証ではない')
        pid = project['id']
        image = root / 'reference.png'
        Image.new('RGB', (32, 32), (180, 180, 180)).save(image)
        reference = wb.reference_add(pid, image, 'design', '試験用の灰色面', 1, 'front')
        requirement = wb.requirement_add(pid, 'must_keep', '単純形状を保持')
        structure = wb.part_plan(pid, [{'name': '立方体'}], '接続試験')
        part_id = structure['parts'][0]['id']
        scope = {'part_ids': [part_id], 'stages': ['geometry', 'assembly', 'surface', 'inspect', 'source_export'],
                 'geometry_engines': ['blender_authoring'], 'allowed_edits': ['part_shape', 'part_transform', 'material_parameters'],
                 'max_reference_drafts_per_part': 1, 'max_geometry_runs_per_part': 2,
                 'max_assembly_runs': 2, 'max_surface_runs': 2,
                 'face_limits': {part_id: {'target_faces': 12, 'max_faces': 20}},
                 'must_preserve': [requirement['id']], 'excluded': ['ue_export']}
        production = wb.production_plan(pid, {'part_plan_id': structure['id'],
            'reference_ids': [reference['id']], 'requirement_ids': [requirement['id']],
            'scope': scope, 'deliverables': ['editable_blend', 'obj', 'four_view_previews'],
            'reason': '造形アダプタ接続試験'})
        wb.production_transition(pid, production['id'], 'request-approval')
        wb.production_transition(pid, production['id'], 'approve', '試験用の固定計画')
        pack = wb.reference_pack_create(pid, production['id'], {'parts': [{
            'part_id': part_id, 'source_reference_ids': [reference['id']],
            'dimensions': {'side_m': 1}, 'anchors': {}, 'color_zones': [],
            'consistency': '灰色面のみ', 'uncertainties': ['背面は同形と仮定'],
            'images': [{'file': reference['file'], 'source_reference_id': reference['id'],
                        'view': 'front', 'method': 'original', 'inferred': False,
                        'uncertainties': []}]}]})
        wb.reference_pack_transition(pid, pack['id'], 'request-approval')
        wb.reference_pack_transition(pid, pack['id'], 'approve', '試験用資料パック')
        script = root / 'cube.py'
        script.write_text('def build(job):\n    import bpy\n    bpy.ops.mesh.primitive_cube_add(size=1, location=(-0.7, 0, 0))\n    bpy.context.object["mwb_object_role"] = "base"\n    bpy.ops.mesh.primitive_cube_add(size=1, location=(0.7, 0, 0))\n    bpy.context.object["mwb_object_role"] = "accent"\n', encoding='utf-8')
        plan = wb.geometry_plan(pid, production['id'], pack['id'], part_id,
                                {'script': str(script), 'intent': '1mの立方体を作る'})
        candidate = execute(wb, pid, plan['id'], config)
        for file in candidate['files']:
            wb.verify_file(pid, file)
        source_blend = next(wb.verify_file(pid, f) for f in candidate['files'] if f['file'].endswith('.blend'))
        edited_blend = root / 'edited.blend'
        edit_script = root / 'edit_fixture.py'
        edit_script.write_text('import bpy, sys\na = sys.argv[sys.argv.index("--") + 1:]\nbpy.ops.wm.open_mainfile(filepath=a[0], use_scripts=False)\nmesh = next(o for o in bpy.context.scene.objects if o.type == "MESH")\nmesh.data.vertices[0].co.x += 0.1\nbpy.ops.wm.save_as_mainfile(filepath=a[1])\n', encoding='utf-8')
        subprocess.run([config['blender'], '--background', '--factory-startup', '--disable-autoexec',
                        '--python-exit-code', '1', '--python', str(edit_script), '--',
                        str(source_blend), str(edited_blend)], check=True, capture_output=True)
        edited = wb.revision_run(pid, candidate['id'], production['id'],
                                 {'mode': 'part_shape', 'target_part_ids': [part_id],
                                  'changed_by': 'test', 'reason': '頂点を0.1m修正'}, edited_blend)
        binding = {'part_id': part_id, 'candidate_id': edited['id'],
                   'location': [0, 0, 0], 'rotation_degrees': [0, 0, 0], 'scale': [1, 1, 1]}
        assembly = wb.plan(pid, 'assembly', '2オブジェクトを仮組み', bindings=[binding],
                           production_id=production['id'])
        character = execute(wb, pid, assembly['id'], config)
        before_inspection = wb.revision_run(pid, character['id'], production['id'])
        before_transform = {obj['name']: {key: obj[key] for key in ('location', 'rotation', 'scale')}
                            for obj in before_inspection['checks']['after'][part_id]['objects']}
        after_transform = {name: {'location': [values['location'][0] + 0.2, *values['location'][1:]],
                                  'rotation': values['rotation'], 'scale': values['scale']}
                           for name, values in before_transform.items()}
        character_blend = next(wb.verify_file(pid, f) for f in character['files'] if f['file'].endswith('.blend'))
        move_script = root / 'move_fixture.py'
        moved_blend = root / 'moved.blend'
        move_script.write_text('import bpy, sys\na = sys.argv[sys.argv.index("--") + 1:]\nbpy.ops.wm.open_mainfile(filepath=a[0], use_scripts=False)\nfor obj in bpy.context.scene.objects:\n    if obj.type == "MESH":\n        obj.location.x += 0.2\nbpy.ops.wm.save_as_mainfile(filepath=a[1])\n', encoding='utf-8')
        subprocess.run([config['blender'], '--background', '--factory-startup', '--disable-autoexec',
                        '--python-exit-code', '1', '--python', str(move_script), '--',
                        str(character_blend), str(moved_blend)], check=True, capture_output=True)
        try:
            placed = wb.revision_run(pid, character['id'], production['id'],
                                     {'mode': 'part_transform', 'target_part_ids': [part_id],
                                      'changed_by': 'test', 'reason': '位置を0.2m移動',
                                      'before_transform': {part_id: before_transform},
                                      'after_transform': {part_id: after_transform}}, moved_blend)
        except Exception:
            plan = store.load(pid)['plans'][-1]
            log = store.path(pid, plan['run'] + '/blender.log')
            if log.exists():
                print(log.read_text(encoding='utf-8', errors='replace'))
            raise
        previews = [f['file'] for f in placed['files'] if f['file'].endswith('.png')]
        wb.review(pid, placed['id'], [{'requirement_id': requirement['id'], 'result': 'uncertain',
                                       'reason': '機械的な接続試験のみで審美評価はしていない',
                                       'impact': '実案件の輪郭一致は別途確認が必要',
                                       'directions': ['front', 'side', 'back', 'oblique'],
                                       'image_files': previews}], '試験の形状自己点検', actor='codex')
        wb.candidate_state(pid, placed['id'], 'confirm-shape', '試験で形状を確認')
        material = wb.material_recipe_create(pid, edited['id'], {
            'name': '灰色', 'intent': '資料の無彩色を再現', 'reference_regions': [],
            'shader': {'base_color': [0.5, 0.5, 0.5], 'roughness': 0.5, 'metallic': 0},
            'zones': [{'name': 'アクセント', 'object_role': 'accent',
                       'shader': {'base_color': [0.8, 0.1, 0.1], 'roughness': 0.4, 'metallic': 0,
                                  'pattern': {'type': 'noise', 'scale': 8,
                                              'bump_strength': 0.1,
                                              'secondary_color': [0.6, 0.05, 0.05]}}}],
            'uncertainties': []})
        surface = wb.plan(pid, 'surface', '灰色材質を適用', source_id=placed['id'],
                          materials={part_id: material['id']}, production_id=production['id'])
        try:
            finished = execute(wb, pid, surface['id'], config)
        except Exception:
            log = store.path(pid, surface['run'] + '/blender.log')
            if log.exists():
                print(log.read_text(encoding='utf-8', errors='replace'))
            raise
        try:
            inspection = wb.revision_run(pid, finished['id'], production['id'])
        except Exception:
            plan = store.load(pid)['plans'][-1]
            log = store.path(pid, plan['run'] + '/blender.log')
            if log.exists():
                print(log.read_text(encoding='utf-8', errors='replace'))
            raise
        finished_blend = next(wb.verify_file(pid, f) for f in finished['files'] if f['file'].endswith('.blend'))
        material_edit = root / 'material_edit.blend'
        material_script = root / 'material_edit_fixture.py'
        material_script.write_text('import bpy, sys\na = sys.argv[sys.argv.index("--") + 1:]\nbpy.ops.wm.open_mainfile(filepath=a[0], use_scripts=False)\nmesh = next(o for o in bpy.context.scene.objects if o.type == "MESH")\nmat = mesh.data.materials[0]\nmat.node_tree.nodes.get("Principled BSDF").inputs["Base Color"].default_value = (0.2, 0.6, 0.3, 1)\nbpy.ops.wm.save_as_mainfile(filepath=a[1])\n', encoding='utf-8')
        subprocess.run([config['blender'], '--background', '--factory-startup', '--disable-autoexec',
                        '--python-exit-code', '1', '--python', str(material_script), '--',
                        str(finished_blend), str(material_edit)], check=True, capture_output=True)
        revised = wb.revision_run(pid, finished['id'], production['id'],
                                  {'mode': 'material_parameters', 'target_part_ids': [part_id],
                                   'changed_by': 'test', 'reason': '色を変更'}, material_edit)
        wb.candidate_state(pid, revised['id'], 'select', '試験候補を選択')
        exported = wb.export(pid, 'smoke-v2', '試験出力')
        print({'candidate_id': revised['id'], 'faces': candidate['checks']['faces'],
               'geometry_files': len(candidate['files']), 'stages': [p['state'] for p in store.load(pid)['plans']],
               'inspection_run_id': inspection['inspection_run_id'], 'export': exported['file']})


if __name__ == '__main__':
    main()
