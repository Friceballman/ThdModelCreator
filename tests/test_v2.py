"""Version 2 approval and immutable-input tests; never launches Blender."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from model_workbench.storage import Store, WorkflowError, find, read, record, write
from model_workbench.v2 import V2Workbench
from model_workbench.runtime import load_config, REPO, execute
from model_workbench.cli import parser, dispatch


class V2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'projects')
        self.config = load_config(REPO / 'experiments/config.example.json')
        self.wb = V2Workbench(self.store, self.config)
        self.pid = self.store.create('ver2', '試験')['id']
        from PIL import Image
        self.image = self.root / 'front.png'
        Image.new('RGB', (16, 16), (120, 40, 20)).save(self.image)
        self.ref = self.wb.reference_add(self.pid, self.image, 'design', '正面資料', 1, 'front')
        self.req = self.wb.requirement_add(self.pid, 'must_keep', '輪郭を維持')
        self.structure = self.wb.part_plan(self.pid, [{'name': '身体'}], '単一部品')
        self.part_id = self.structure['parts'][0]['id']

    def production(self, max_runs=2):
        scope = {'part_ids': [self.part_id], 'stages': ['image_prepare', 'geometry', 'assembly', 'surface'],
                 'geometry_engines': ['blender_authoring'], 'allowed_edits': ['part_shape'],
                 'max_reference_drafts_per_part': 2, 'max_geometry_runs_per_part': max_runs,
                 'max_assembly_runs': 2, 'max_surface_runs': 2,
                 'face_limits': {self.part_id: {'target_faces': 20, 'max_faces': 100}},
                 'must_preserve': [self.req['id']], 'excluded': ['triposr_legacy']}
        item = self.wb.production_plan(self.pid, {
            'part_plan_id': self.structure['id'], 'reference_ids': [self.ref['id']],
            'requirement_ids': [self.req['id']], 'scope': scope,
            'deliverables': ['editable_blend', 'four_view_previews'], 'reason': '小型試験'})
        self.assertEqual(find(self.store.load(self.pid)['part_plans'], self.structure['id'])['state'], 'draft')
        self.wb.production_transition(self.pid, item['id'], 'request-approval')
        self.wb.production_transition(self.pid, item['id'], 'approve', '利用者が制作計画を確認')
        self.assertEqual(find(self.store.load(self.pid)['part_plans'], self.structure['id'])['state'], 'approved')
        return item

    def pack(self, production):
        item = self.wb.reference_pack_create(self.pid, production['id'], {'parts': [{
            'part_id': self.part_id, 'source_reference_ids': [self.ref['id']],
            'dimensions': {'height_m': 1}, 'anchors': {}, 'color_zones': [],
            'consistency': '正面のみ。背面は未確定', 'uncertainties': ['背面'],
            'images': [{'file': self.ref['file'], 'source_reference_id': self.ref['id'],
                        'view': 'front', 'method': 'original', 'inferred': False,
                        'uncertainties': []}]}]})
        self.wb.reference_pack_transition(self.pid, item['id'], 'request-approval')
        self.wb.reference_pack_transition(self.pid, item['id'], 'approve', '利用者が資料を確認')
        return item

    def test_new_and_legacy_schema_are_read_only_on_load(self):
        new = self.store.load(self.pid)
        self.assertEqual(new['workflow_version'], 2)
        self.assertEqual(new['reference_packs'], [])
        path = self.store.directory(self.pid) / 'project.json'
        old = read(path)
        old.pop('workflow_version')
        old.pop('production_plans')
        old.pop('reference_packs')
        write(path, old)
        self.assertNotIn('workflow_version', self.store.load(self.pid))
        self.assertNotIn('production_plans', read(path))

    def test_scope_pack_run_reservation_and_limits(self):
        production = self.production(max_runs=1)
        pack = self.pack(production)
        script = self.root / 'author.py'
        script.write_text('def build(job):\n    pass\n', encoding='utf-8')
        plan = self.wb.geometry_plan(self.pid, production['id'], pack['id'], self.part_id,
                                     {'script': str(script), 'intent': '単純な試験形状'})
        self.assertEqual(plan['approval']['kind'], 'parent_scope')
        self.assertTrue(self.store.path(self.pid, plan['fixed']['script']).is_file())
        self.assertEqual(read(self.store.path(self.pid, plan['run'] + '/plan.json'))['plan_hash'], plan['plan_hash'])
        with self.assertRaises(WorkflowError):
            self.wb.geometry_plan(self.pid, production['id'], pack['id'], self.part_id,
                                  {'script': str(script), 'intent': '上限超過'})

    def test_tampered_pack_or_script_stops_before_blender(self):
        production = self.production()
        pack = self.pack(production)
        script = self.root / 'author.py'
        script.write_text('def build(job):\n    pass\n', encoding='utf-8')
        plan = self.wb.geometry_plan(self.pid, production['id'], pack['id'], self.part_id,
                                     {'script': str(script), 'intent': '試験'})
        self.store.path(self.pid, plan['fixed']['script']).write_text('changed', encoding='utf-8')
        with self.assertRaises(WorkflowError):
            execute(self.wb, self.pid, plan['id'], self.config)
        self.assertEqual(find(self.store.load(self.pid)['plans'], plan['id'])['state'], 'approved')

    def test_new_cli_id_only_commands_and_trace(self):
        production = self.production()
        pack = self.pack(production)
        def call(*arguments):
            return dispatch(parser().parse_args(['--root', str(self.store.root), *arguments]))
        self.assertEqual(call('production', 'show', production['id'])['id'], production['id'])
        self.assertEqual(call('reference-pack', 'show', pack['id'])['id'], pack['id'])
        self.assertEqual(len(call('generate', 'list', self.pid, '--stage', 'geometry',
                                  '--production', production['id'])), 0)
        self.assertEqual(call('production', 'list', self.pid)[0]['id'], production['id'])

    def test_parent_scope_image_prepare_registers_into_run(self):
        production = self.production()
        plan = self.wb.plan(self.pid, 'image_prepare', '外部画像処理の登録',
                            reference_ids=[self.ref['id']], part_id=self.part_id,
                            production_id=production['id'])
        self.assertEqual(plan['state'], 'approved')
        image = self.wb.candidate_import(self.pid, self.image, 'prepared_image', self.part_id,
                                         '試験画像', plan['id'], 'external')
        self.assertTrue(image['files'][0]['file'].startswith('runs/' + plan['fixed']['run_id'] + '/outputs/'))
        self.assertEqual(find(self.store.load(self.pid)['plans'], plan['id'])['state'], 'succeeded')

    def test_modified_approved_pack_is_rejected(self):
        production = self.production()
        pack = self.pack(production)
        path = self.store.path(self.pid, f'reference-packs/{pack["id"]}/manifest.json')
        manifest = read(path)
        manifest['parts'][0]['consistency'] = '変更済み'
        write(path, manifest)
        script = self.root / 'author.py'
        script.write_text('def build(job):\n    pass\n', encoding='utf-8')
        with self.assertRaises(WorkflowError):
            self.wb.geometry_plan(self.pid, production['id'], pack['id'], self.part_id,
                                  {'script': str(script), 'intent': '試験'})

    def test_v2_shape_gate_requires_codex_review(self):
        production = self.production()
        candidate = record(kind='character', status='pending', production_plan_id=production['id'],
                           files=[{'file': self.ref['file'], 'sha256': self.ref['sha256']}],
                           history=[], shape_confirmed=False, composition=[], materials=[])
        with self.store.update(self.pid, 'fixture') as doc:
            doc['candidates'].append(candidate)
        with self.assertRaises(WorkflowError):
            self.wb.candidate_state(self.pid, candidate['id'], 'confirm-shape', '未評価')
        self.wb.review(self.pid, candidate['id'], [{
            'requirement_id': self.req['id'], 'result': 'uncertain', 'reason': '画像未確認',
            'impact': '見た目の確証なし', 'directions': ['front'],
            'image_files': [self.ref['file']]}], '自己点検', actor='codex')
        self.assertTrue(self.wb.candidate_state(self.pid, candidate['id'], 'confirm-shape', '仮固定')['shape_confirmed'])


if __name__ == '__main__':
    unittest.main()
