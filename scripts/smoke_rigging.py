"""Isolated Blender test; optionally diagnose a copy of a real static candidate.

No requirements, skeletons or motion approvals are invented for the real model.
The real project index and all registered files are left unchanged.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from model_workbench.rigging import RiggingLab, lab
from model_workbench.runtime import REPO, load_config, process
from model_workbench.storage import Store, find, record, sha, uid, write


def register(store, project_id, blend, parts, origin=None):
    destination = store.path(project_id, 'fixtures/model.blend')
    destination.parent.mkdir()
    shutil.copyfile(blend, destination)
    candidate = record(kind='character', status='pending', composition=parts,
                       origin=origin, files=[{'file': 'fixtures/model.blend', 'sha256': sha(destination)}])
    with store.update(project_id, 'smoke_fixture') as doc:
        doc['candidates'].append(candidate)
    return candidate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=str(REPO / 'experiments/config.example.json'))
    parser.add_argument('--real-project')
    parser.add_argument('--candidate')
    args = parser.parse_args()
    if bool(args.real_project) != bool(args.candidate):
        parser.error('--real-projectと--candidateを同時に指定してください')
    config = load_config(args.config)
    if (REPO / 'experiments/runs/.execution.lock').exists():
        raise RuntimeError('別のBlender実行または残存ロックがあります')
    folder = REPO / '.local/v35-smoke' / uid()
    folder.mkdir(parents=True)
    store = Store(folder / 'projects')
    project = store.create('v3.5 synthetic fixture', 'synthetic rig evidence only', 3)
    part_id = uid()
    fixture_script = folder / 'fixture.py'
    fixture_script.write_text('''import bpy
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
vertices = [(x, y, z) for z in (0, 1, 2) for x, y in ((-.2,-.2),(.2,-.2),(.2,.2),(-.2,.2))]
faces = [(3,2,1,0),(8,9,10,11)]
for ring in range(2):
    for i in range(4):
        faces.append((ring*4+i, ring*4+(i+1)%4, (ring+1)*4+(i+1)%4, (ring+1)*4+i))
mesh = bpy.data.meshes.new('fixture')
mesh.from_pydata(vertices, [], faces)
obj = bpy.data.objects.new('fixture', mesh)
bpy.context.scene.collection.objects.link(obj)
obj['mwb_part_id'] = PART_ID
bpy.ops.wm.save_as_mainfile(filepath=DESTINATION)
'''.replace('PART_ID', repr(part_id)).replace('DESTINATION', repr(str(folder / 'source.blend'))), encoding='utf-8')
    process([config['blender'], '--background', '--factory-startup', '--disable-autoexec',
             '--python-exit-code', '1', '--python', str(fixture_script)], folder / 'fixture.log', dict(os.environ), REPO)
    candidate = register(store, project['id'], folder / 'source.blend', [{'part_id': part_id}])
    rigging = RiggingLab(store, config)
    inspection = rigging.inspect(project['id'], candidate['id'])
    motion_id = uid()
    req = rigging.requirements_input(project['id'], candidate['id'], 'synthetic fixture bend only',
                dict(motions=[dict(id=motion_id, text='bend synthetic tip 45 degrees',
                                   evidence='smoke fixture, not user character requirements',
                                   state='confirmed', acceptance='finite displacement and review samples')],
                     preserve=['synthetic mesh, material and source pose'], unknowns=[]))
    definition = dict(bones=[dict(name='root', parent=None, head=[0, 0, 0], tail=[0, 0, 1]),
                             dict(name='tip', parent='root', head=[0, 0, 1], tail=[0, 0, 2])],
                      bindings={'fixture': {'mode': 'weights', 'vertices': [
                          {'root': 1} if i < 4 else {'root': .5, 'tip': .5} if i < 8 else {'tip': 1}
                          for i in range(12)]}},
                      poses=[dict(name='bend', requirement_id=motion_id, rotations={'tip': [45, 0, 0]}, samples=3)],
                      rest_tolerance=1e-6, scope='whole_character', reason='synthetic fixture, not a character quality test')
    experiment = rigging.plan(project['id'], req['id'], inspection['id'], definition)
    rigging.approve(project['id'], experiment['id'], experiment['plan_hash'], 'isolated synthetic smoke test')
    result = rigging.execute(project['id'], experiment['id'])
    checks = rigging._verified_output(project['id'], result)
    assert checks['rest_geometry_preserved']
    assert len(checks['saved_rig']['bones']) == 2
    assert checks['samples'][-1]['maximum_displacement_by_object']['fixture'] > .1
    assert all(v == 'not_run' for v in result['verification'].values())
    assert sha(folder / 'source.blend') == candidate['files'][0]['sha256']
    report = dict(synthetic_experiment=result['id'], synthetic_checks=str(
                  store.path(project['id'], result['run'] + '/outputs/checks.json')),
                  synthetic_blend=str(store.path(project['id'], result['run'] + '/outputs/model.blend')),
                  synthetic_deformation_observed=True, visual_review='not_run', ue_verified=False)
    if args.real_project:
        original_store = Store(REPO / 'projects')
        original = original_store.load(args.real_project)
        original_index = sha(original_store.directory(args.real_project) / 'project.json')
        original_candidate, original_blend, original_entry = RiggingLab(original_store, config).source(
            args.real_project, args.candidate)
        real_project = store.create('real static model preflight', 'read-only source diagnosis, no rig trial', 3)
        real_candidate = register(store, real_project['id'], original_blend, original_candidate['composition'],
                                  dict(project_id=args.real_project, candidate_id=args.candidate, source=original_entry))
        real_result = rigging.inspect(real_project['id'], real_candidate['id'])
        real_checks = rigging._verified_output(real_project['id'], real_result)
        assert sha(original_blend) == original_entry['sha256']
        assert sha(original_store.directory(args.real_project) / 'project.json') == original_index
        report['real_preflight'] = dict(ready=real_checks['ready'], reasons=real_checks['unsupported'],
                                        mesh_objects=len(real_checks['objects']), vertices=real_checks['vertices'],
                                        faces=real_checks['faces'], source=original_entry,
                                        checks=str(store.path(real_project['id'], real_result['run'] + '/outputs/checks.json')),
                                        rig_applied=False, original_project_unchanged=True)
    write(folder / 'summary.json', report)
    print(json.dumps(dict(report, summary=str(folder / 'summary.json')), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
