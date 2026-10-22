"""Small real-Blender smoke run, isolated from user projects and GUI scenes."""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from model_workbench.runtime import REPO, load_config, process
from model_workbench.storage import Store, record, read, write, sha, uid, find
from model_workbench.v3 import V3Workbench


def main():
    from PIL import Image
    root = REPO / '.local/v3-smoke' / uid()
    root.mkdir(parents=True)
    print('smoke_root=' + str(root), flush=True)
    config = load_config(REPO / 'experiments/config.example.json')
    store = Store(root / 'projects')
    wb = V3Workbench(store, config)
    pid = store.create('v3内部接続試験', '立方体2部品の制御確認。外観品質評価ではない', 3)['id']
    image = root / 'reference.png'
    Image.new('RGB', (64, 64), '#bbbbbb').save(image)
    ref = wb.reference_add(pid, image, 'design', '試験専用画像', 1, 'front')
    req = wb.requirement_add(pid, 'must_keep', '非対象部品を保持')
    structure = wb.part_plan(pid, [{'name': 'left'}, {'name': 'right'}], '2部品の試験')
    parts = [p['id'] for p in structure['parts']]
    scope = dict(part_ids=parts, stages=['geometry', 'assembly', 'surface', 'inspect'],
                 geometry_engines=['blender_authoring'], allowed_edits=['part_shape'],
                 max_reference_drafts_per_part=2, max_geometry_runs_per_part=3,
                 max_assembly_runs=3, max_surface_runs=3,
                 face_limits={p: {'target_faces': 12, 'max_faces': 100} for p in parts},
                 must_preserve=[req['id']])
    production = wb.production_plan(pid, dict(part_plan_id=structure['id'], reference_ids=[ref['id']],
        requirement_ids=[req['id']], scope=scope, deliverables=['editable_blend'], reason='内部試験'))
    wb.production_transition(pid, production['id'], 'request-approval')
    wb.production_transition(pid, production['id'], 'approve', '内部試験の承認')
    fixture = root / 'fixture.json'
    write(fixture, {'parts': parts, 'output': str(root)})
    script = root / 'fixture.py'
    script.write_text("""
import bpy, json, sys
from pathlib import Path
job=json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text(encoding='utf-8'))
bpy.ops.wm.read_factory_settings(use_empty=True)
for index, pid in enumerate(job['parts']):
    bpy.ops.mesh.primitive_cube_add(size=0.5, location=(index*0.8-0.4,0,0))
    obj=bpy.context.object
    obj['part_id']=obj['mwb_part_id']=pid
bpy.ops.wm.save_as_mainfile(filepath=str(Path(job['output'])/'whole.blend'))
for pid in job['parts']:
    bpy.ops.wm.open_mainfile(filepath=str(Path(job['output'])/'whole.blend'), use_scripts=False)
    for obj in list(bpy.context.scene.objects):
        if obj.get('part_id') != pid:
            bpy.data.objects.remove(obj, do_unlink=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(Path(job['output'])/(pid+'.blend')))
""", encoding='utf-8')

    def blender(script_path, argument, label):
        return process([config['blender'], '--background', '--factory-startup', '--disable-autoexec',
                        '--python-exit-code', '1', '--python', str(script_path), '--', str(argument)],
                       root / (label + '.log'), dict(os.environ, PYTHONDONTWRITEBYTECODE='1'), REPO)
    blender(script, fixture, 'fixture')
    candidates = []
    import shutil
    for part in parts:
        target = store.path(pid, f'fixtures/{part}.blend')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / (part + '.blend'), target)
        candidates.append(record(kind='part', part_id=part, status='pending', provenance='manual_blend',
            production_plan_id=production['id'], reference_pack_id=None, history=[],
            files=[{'file': f'fixtures/{part}.blend', 'sha256': sha(target)}]))
    target = store.path(pid, 'fixtures/whole.blend')
    shutil.copyfile(root / 'whole.blend', target)
    character = record(kind='character', status='pending', production_plan_id=production['id'],
        reference_pack_id=None, stage='geometry', materials=[], history=[],
        files=[{'file': 'fixtures/whole.blend', 'sha256': sha(target)}],
        composition=[dict(part_id=c['part_id'], candidate_id=c['id'],
                          location=[0,0,0], rotation_degrees=[0,0,0], scale=[1,1,1]) for c in candidates])
    with store.update(pid, 'synthetic_fixture') as doc:
        doc['candidates'].extend([*candidates, character])
    profile = dict(camera='auto',
        views={v: dict(reference_id=ref['id'], source_view=v) for v in ('front','side','top')})
    first = wb.comparison_run(pid, character['id'], profile)
    print('comparison_rendered', flush=True)
    session = wb.candidate_edit_session_start(pid, production['id'], character['id'])
    helper = str(REPO / 'scripts/blender_session.py')
    connect_script = root / 'connect.py'
    connect_script.write_text("import runpy\nns=runpy.run_path(" + repr(helper) + ")\n"
        "ns['connect'](" + repr(session['manifest_path']) + ", open_copy=True)\n", encoding='utf-8')
    blender(connect_script, fixture, 'connect')
    wb.candidate_edit_session_bind(pid, session['id'])
    edit_script = root / 'edit.py'
    edit_script.write_text(
        "import runpy,bpy\nns=runpy.run_path(" + repr(helper) + ")\n"
        "ns['connect'](" + repr(session['manifest_path']) + ", open_copy=True)\n"
        "obj=next(o for o in bpy.context.scene.objects if o.type=='MESH' and o.get('part_id')==" + repr(parts[0]) + ")\n"
        "obj.data.vertices[0].co.x+=0.05\n"
        "ns['capture'](" + repr(session['manifest_path']) + ", ['左部品の頂点を0.05移動'])\n", encoding='utf-8')
    blender(edit_script, fixture, 'edit')
    revised = wb.candidate_edit_session_finish(pid, session['id'],
        dict(mode='part_shape', target_part_ids=[parts[0]], changed_by='smoke', reason='全身内の局所形状修正'),
        session['working_path'])
    assert revised['parent_id'] == character['id']
    assert revised['composition'][0]['candidate_id'] != candidates[0]['id']
    assert revised['composition'][1]['candidate_id'] == candidates[1]['id']
    wb.verify_file(pid, character['files'][0])
    reassembled = root / 'reassembled'
    reassembled.mkdir()
    reassembly_job = root / 'reassembly.json'
    write(reassembly_job, dict(stage='assembly', source=None,
         parts=[dict(binding, blend=str(wb.verify_file(pid,
                 next(f for f in find(store.load(pid)['candidates'], binding['candidate_id'])['files']
                      if f['file'].endswith('.blend'))))) for binding in revised['composition']],
         composition=revised['composition'], materials=[], edit=None, output=str(reassembled)))
    blender(REPO / 'scripts/blender_workbench.py', reassembly_job, 'reassembly')
    reloaded_parts = read(reassembled / 'checks.json')['parts']
    for part_id in parts:
        original_meshes = sorted(o['mesh_hash'] for o in revised['checks']['after'][part_id]['objects'])
        loaded_meshes = sorted(o['mesh_hash'] for o in reloaded_parts[part_id]['objects'])
        assert original_meshes == loaded_meshes
    second = wb.comparison_run(pid, revised['id'], {'reuse': first['id']})
    assert first['profile_hash'] == second['profile_hash']
    issue = wb.quality_issue_add(pid, production['id'], dict(title='fixture差分', category='part_shape',
        affected_part_ids=[parts[0]], candidate_id=character['id'], evidence_reference_ids=[ref['id']],
        source_views=['front'], repair='頂点調整', mandatory=True))
    good = dict(result='pass', reason='内部制御試験の模擬判定。審美評価ではない')
    wb.comparison_review(pid, second['id'], dict(actor='user', whole=good, preservation=good,
        parts=[dict(good, part_id=p) for p in parts], requirements=[dict(good, requirement_id=req['id'])]))
    wb.quality_issue_evaluate(pid, issue['id'], revised['id'], 'resolved', '模擬判定', second['id'])
    completion = wb.completion_set(pid, production['id'], revised['id'], '内部試験の完了候補')
    assert wb.completion_status(pid, production['id'])['state'] == 'complete'
    report = dict(project_id=pid, session_id=session['id'], completion=completion,
                  comparison_ids=[first['id'], second['id']], source_preserved=True,
                  local_part_candidate_id=revised['composition'][0]['candidate_id'],
                  scope='real Blender transport and metadata only; no visual quality claim')
    write(root / 'report.json', report)
    print(json.dumps(dict(report=str(root / 'report.json'), **report), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
