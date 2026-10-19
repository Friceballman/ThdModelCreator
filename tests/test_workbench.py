"""Workflow invariants. These tests do not launch Blender or a GPU workload."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from model_workbench.storage import Store, WorkflowError, find, read, record, write, fingerprint
from model_workbench.recovery import resume
from model_workbench.workflow import Workbench
from model_workbench.runtime import execute, load_config, REPO


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'projects')
        self.config = load_config(REPO / 'experiments/config.example.json')
        self.wb = Workbench(self.store, self.config)
        self.project = self.store.create('日本語の案件', '試験用。制作品質の評価ではない')
        self.pid = self.project['id']
        self.mesh = self.root / 'part.obj'
        self.mesh.write_text('v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n')
        from PIL import Image
        self.image = self.root / 'input.png'
        Image.new('RGB', (8, 8), (128, 128, 128)).save(self.image)

    def structure(self):
        proposal = self.wb.part_plan(self.pid, [{'name': '身体'}, {'name': '帽子'}], '試験構成')
        self.wb.part_approve(self.pid, proposal['id'], proposal['content_hash'], '試験の構成を確認')
        self.parts = [p['id'] for p in proposal['parts']]
        return proposal

    def assets(self):
        self.structure()
        self.candidates = [self.wb.candidate_import(self.pid, self.mesh, 'part', pid, '試験OBJ') for pid in self.parts]
        self.bindings = [{'part_id': pid, 'candidate_id': candidate['id'],
                          'location': [i * 2, 0, 0]} for i, (pid, candidate) in enumerate(zip(self.parts, self.candidates))]

    def approved_plan(self):
        self.assets()
        plan = self.wb.plan(self.pid, 'assembly', '試験の仮組み', bindings=self.bindings)
        self.wb.transition(self.pid, plan['id'], 'request-approval')
        self.wb.transition(self.pid, plan['id'], 'approve', plan['plan_hash'], '試験実行の承認')
        return plan

    def fake_character(self):
        self.assets()
        item = record(kind='character', status='pending', shape_confirmed=False,
                      files=copy.deepcopy(self.candidates[0]['files']), composition=[
                          dict(b, rotation_degrees=[0, 0, 0], scale=[1, 1, 1]) for b in self.bindings],
                      materials=[], history=[], generation_id=None, parent_id=None)
        with self.store.update(self.pid, 'fixture') as doc:
            doc['candidates'].append(item)
        return item

    def test_reference_copy_and_revision_dont_change_fixed_plan(self):
        self.structure()
        ref = self.wb.reference_add(self.pid, self.image, 'design', '形のみ', 1, 'front')
        requirement = self.wb.requirement_add(self.pid, 'must_keep', '頭身を維持')
        plan = self.wb.plan(self.pid, 'image_prepare', '帽子を準備', [ref['id']], self.parts[1])
        original = copy.deepcopy(plan['fixed'])
        self.wb.reference_update(self.pid, ref['id'], '範囲を修正', description='配色も使う')
        self.wb.requirement_update(self.pid, requirement['id'], '明確化', '頭身と輪郭を維持')
        saved = find(self.store.load(self.pid)['plans'], plan['id'])
        self.assertEqual(saved['fixed'], original)
        self.image.unlink()
        self.assertTrue(self.wb.verify_file(self.pid, ref).is_file())

    def test_unapproved_structure_rejected_and_ids_survive_revision(self):
        proposal = self.wb.part_plan(self.pid, [{'name': '身体'}], '初版')
        with self.assertRaises(WorkflowError):
            self.wb.plan(self.pid, 'image_prepare', '試験', part_id=proposal['parts'][0]['id'])
        revised = self.wb.part_plan(self.pid, [dict(proposal['parts'][0], name='体')], '名前を修正')
        self.assertEqual(proposal['parts'][0]['id'], revised['parts'][0]['id'])
        self.assertEqual(len(self.store.load(self.pid)['part_plans']), 2)

    def test_complete_binding_and_same_project_are_required(self):
        self.assets()
        with self.assertRaises(WorkflowError):
            self.wb.plan(self.pid, 'assembly', '組み立て', bindings=self.bindings[:1])
        with self.assertRaises(WorkflowError):
            self.wb.plan(self.pid, 'assembly', '組み立て', bindings=[self.bindings[0]] * 2)
        other = self.store.create('別案件', '分離を確認')
        with self.assertRaises(WorkflowError):
            self.wb.candidate_import(other['id'], self.mesh, 'part', self.parts[0], '別案件の部品')

    def test_approval_and_start_are_separate_and_hash_is_checked(self):
        self.assets()
        with patch('subprocess.Popen', side_effect=AssertionError('must not launch')):
            plan = self.wb.plan(self.pid, 'assembly', '組み立て', bindings=self.bindings)
            with self.assertRaises(WorkflowError):
                execute(self.wb, self.pid, plan['id'], self.config)
            self.wb.transition(self.pid, plan['id'], 'request-approval')
            with self.assertRaises(WorkflowError):
                self.wb.transition(self.pid, plan['id'], 'approve', 'wrong', '確認')
            self.wb.transition(self.pid, plan['id'], 'approve', plan['plan_hash'], '確認')
        self.assertEqual(find(self.store.load(self.pid)['plans'], plan['id'])['state'], 'approved')

    def test_tampered_input_stops_before_process(self):
        plan = self.approved_plan()
        path = self.store.path(self.pid, self.candidates[0]['files'][0]['file'])
        path.write_text('tampered')
        with patch('subprocess.Popen', side_effect=AssertionError('must not launch')):
            with self.assertRaises(WorkflowError):
                execute(self.wb, self.pid, plan['id'], self.config)
        self.assertEqual(find(self.store.load(self.pid)['plans'], plan['id'])['state'], 'approved')

    def test_external_failure_is_durable_and_not_retried(self):
        plan = self.approved_plan()
        with patch('model_workbench.runtime.process', side_effect=WorkflowError('fixture failure')) as mock:
            with self.assertRaises(WorkflowError):
                execute(self.wb, self.pid, plan['id'], self.config)
            with self.assertRaises(WorkflowError):
                execute(self.wb, self.pid, plan['id'], self.config)
        self.assertEqual(mock.call_count, 1)
        self.assertEqual(find(self.store.load(self.pid)['plans'], plan['id'])['state'], 'failed')
        self.assertEqual(self.store.load(self.pid)['candidates'], self.candidates)

    def test_surface_requires_shape_confirmation_and_matching_shape_revision(self):
        character = self.fake_character()
        materials = [self.wb.material_create(self.pid, pid, c['id'], '布', [0.2, 0.3, 0.4], 0.8, 0)
                     for pid, c in zip(self.parts, self.candidates)]
        mapping = {m['part_id']: m['id'] for m in materials}
        with self.assertRaises(WorkflowError):
            self.wb.plan(self.pid, 'surface', '材質適用', source_id=character['id'], materials=mapping)
        self.wb.candidate_state(self.pid, character['id'], 'confirm-shape', '試験の形状確認')
        plan = self.wb.plan(self.pid, 'surface', '材質適用', source_id=character['id'], materials=mapping)
        self.assertEqual(len(plan['fixed']['materials']), 2)
        wrong = self.wb.candidate_import(self.pid, self.mesh, 'part', self.parts[0], '新形状版')
        new_mat = self.wb.material_create(self.pid, self.parts[0], wrong['id'], '別版', [1, 0, 0], 0.5, 0)
        mapping[self.parts[0]] = new_mat['id']
        with self.assertRaises(WorkflowError):
            self.wb.plan(self.pid, 'surface', '誤った形状版', source_id=character['id'], materials=mapping)

    def test_export_only_selected_characters_and_keeps_history(self):
        character = self.fake_character()
        self.wb.candidate_state(self.pid, self.candidates[0]['id'], 'select', '部品も選択')
        self.wb.candidate_state(self.pid, character['id'], 'select', '全身を選択')
        first = self.wb.export(self.pid, '青い旅人', '出力を依頼')
        second = self.wb.export(self.pid, '青い旅人', '再出力を依頼')
        self.assertNotEqual(first['export_id'], second['export_id'])
        manifest = read(self.store.path(self.pid, first['file']))
        self.assertEqual([x['candidate_id'] for x in manifest['candidates']], [character['id']])
        self.assertEqual(manifest['candidates'][0]['name'], '青い旅人')
        self.assertIsNone(self.store.load(self.pid)['approved_candidate_id'])
        with self.assertRaises(WorkflowError):
            self.wb.export(self.pid, '../outside', '不正')
        with self.assertRaises(WorkflowError):
            self.wb.export(self.pid, 'NUL', '不正')

    def test_archive_and_unknown_schema_are_read_only(self):
        with self.store.update(self.pid, 'archive') as doc:
            doc['state'] = 'archived'
        with self.assertRaises(WorkflowError):
            self.wb.requirement_add(self.pid, 'must_keep', '変更禁止')
        path = self.store.directory(self.pid) / 'project.json'
        data = read(path)
        data['schema_version'] = 999
        write(path, data)
        with self.assertRaises(WorkflowError):
            self.store.load(self.pid)
        self.assertEqual(read(path)['schema_version'], 999)

    def test_path_traversal_and_remaining_lock_are_rejected(self):
        with self.assertRaises(WorkflowError):
            self.store.path(self.pid, '../outside')
        lock = self.store.directory(self.pid) / '.mwb.lock'
        lock.write_text('fixture lock')
        with self.assertRaises(WorkflowError):
            self.wb.requirement_add(self.pid, 'must_keep', '状態保全')
        self.assertTrue(lock.exists())

    def test_legacy_geometry_creation_is_rejected_without_writing(self):
        self.assets()
        image = self.wb.candidate_import(self.pid, self.image, 'prepared_image', self.parts[0], '生成用の試験画像')
        before = self.store.load(self.pid)
        with self.assertRaises(WorkflowError):
            self.wb.plan(self.pid, 'geometry', '旧方式', part_id=self.parts[0], input_id=image['id'])
        self.assertEqual(self.store.load(self.pid)['plans'], before['plans'])

    def test_existing_legacy_geometry_plan_cannot_execute(self):
        self.structure()
        legacy = record(fixed={'stage': 'geometry'}, state='approved', approval={'evidence': '旧計画'})
        with self.store.update(self.pid, 'legacy_fixture') as doc:
            doc['plans'].append(legacy)
        before = (self.store.directory(self.pid) / 'project.json').read_bytes()
        with patch('subprocess.Popen', side_effect=AssertionError('must not launch')):
            with self.assertRaisesRegex(WorkflowError, '旧式の造形計画'):
                execute(self.wb, self.pid, legacy['id'], self.config)
        self.assertEqual((self.store.directory(self.pid) / 'project.json').read_bytes(), before)

    def test_runtime_config_rejects_external_adapter_fields(self):
        path = self.root / 'config.json'
        write(path, {'blender': self.config['blender'], 'other_backend': 'outside'})
        with self.assertRaisesRegex(WorkflowError, 'blenderのパスだけ'):
            load_config(path)

    def test_image_preparation_is_parented_and_needs_separate_input_approval(self):
        self.structure()
        ref = self.wb.reference_add(self.pid, self.image, 'design', '元資料')
        first = self.wb.candidate_import(self.pid, self.image, 'prepared_image', self.parts[0], '初版')
        with self.assertRaises(WorkflowError):
            self.wb.plan(self.pid, 'geometry', '未確認', part_id=self.parts[0], input_id=first['id'])
        plan = self.wb.plan(self.pid, 'image_prepare', '初版から背景だけを除去', [ref['id']], self.parts[0], source_id=first['id'])
        with self.assertRaises(WorkflowError):
            self.wb.candidate_import(self.pid, self.image, 'prepared_image', self.parts[0], '未承認計画の結果', plan['id'])
        self.wb.transition(self.pid, plan['id'], 'request-approval')
        self.wb.transition(self.pid, plan['id'], 'approve', plan['plan_hash'], '画像準備を承認')
        result = self.wb.candidate_import(self.pid, self.image, 'prepared_image', self.parts[0], '外部処理の結果', plan['id'], 'background_removal')
        self.assertEqual(result['parent_id'], first['id'])
        self.assertEqual(find(self.store.load(self.pid)['plans'], plan['id'])['result_method'], 'external_result_import')
        with self.assertRaises(WorkflowError):
            self.wb.image_approve(self.pid, result['id'], 'wrong', '入力確認')
        self.wb.image_approve(self.pid, result['id'], fingerprint(result['files']), '元資料と一致する入力画像を確認')
        with self.assertRaises(WorkflowError):
            self.wb.plan(self.pid, 'geometry', '旧方式は不可', part_id=self.parts[0], input_id=result['id'])
        self.assertEqual(find(self.store.load(self.pid)['candidates'], first['id'])['files'], first['files'])

    def test_resume_checks_damage_without_repairing_or_unlocking(self):
        self.assets()
        target = self.store.path(self.pid, self.candidates[0]['files'][0]['file'])
        target.write_text('changed')
        lock = self.store.directory(self.pid) / '.mwb.lock'
        lock.write_text('{"pid": 123}')
        before = (self.store.directory(self.pid) / 'project.json').read_bytes()
        report = resume(self.wb, self.pid)
        self.assertEqual(len(report['file_issues']), 1)
        self.assertTrue(report['locks'])
        self.assertTrue(report['checkpoints'])
        self.assertTrue(lock.exists())
        self.assertEqual((self.store.directory(self.pid) / 'project.json').read_bytes(), before)

    def test_checkpoints_preserve_full_state_when_primary_is_corrupted(self):
        self.wb.requirement_add(self.pid, 'must_keep', '案件固有の合格基準')
        directory = self.store.directory(self.pid)
        (directory / 'project.json').write_text('{broken')
        saved = [read(p) for p in (directory / 'recovery').glob('*.json')]
        self.assertTrue(any(d['requirements'] and d['requirements'][0]['text'] == '案件固有の合格基準' for d in saved))
        with self.assertRaises(ValueError):
            self.store.load(self.pid)

    def test_surface_parameters_and_reference_files_cannot_be_mutated(self):
        self.assets()
        with self.assertRaises(WorkflowError):
            self.wb.material_create(self.pid, self.parts[0], self.candidates[0]['id'], '不正', [1, 0, 0], -0.1, 0)
        ref = self.wb.reference_add(self.pid, self.image, 'design', '参照')
        with self.assertRaises(WorkflowError):
            self.wb.reference_update(self.pid, ref['id'], '本体を上書きしない', file='other.png')

    def test_status_points_to_selection_and_export(self):
        character = self.fake_character()
        self.wb.reference_add(self.pid, self.image, 'design', '参照')
        self.wb.requirement_add(self.pid, 'must_keep', '構造を保持')
        self.wb.candidate_state(self.pid, character['id'], 'select', '出力対象')
        self.assertIn('名前付きで出力', self.wb.status(self.pid)['next'])


if __name__ == '__main__':
    unittest.main()
