"""Short CLI workflows, ownership, confirmation and compatibility; no GPU/Blender."""
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from model_workbench.cli import main
from model_workbench.storage import Store, find, record, fingerprint, WorkflowError
from model_workbench.workflow import Workbench
from model_workbench.runtime import REPO, load_config


class ShortCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'projects')
        self.config = load_config(REPO / 'experiments/config.example.json')
        self.wb = Workbench(self.store, self.config)
        self.pid = self.store.create('短いCLIの試験', '試験用')['id']
        self.mesh = self.root / 'part.obj'
        self.mesh.write_text('v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n')
        from PIL import Image
        self.image = self.root / 'image.png'
        Image.new('RGB', (8, 8)).save(self.image)

    def run_cli(self, *args, code=0):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result = main(['--root', str(self.store.root), '--json', *map(str, args)])
        self.assertEqual(result, code, err.getvalue())
        return json.loads(out.getvalue()) if result == 0 else err.getvalue()

    def structure(self):
        p = self.run_cli('part', 'plan', self.pid, '--name', '身体', '--name', '帽子', '--prompt', '2部品')
        self.run_cli('part', 'approve', p['id'], '--evidence', '試験構成の承認')
        self.parts = [x['id'] for x in p['parts']]
        return p

    def assets(self):
        self.structure()
        return [self.run_cli('asset', 'add', self.pid, self.mesh, '--part', p, '--prompt', '試験形状') for p in self.parts]

    def test_id_only_and_legacy_form_resolve_same_resource(self):
        assets = self.assets()
        self.assertEqual(self.run_cli('candidate', 'show', assets[0]['id']),
                         self.run_cli('candidate', 'show', self.pid, assets[0]['id']))
        self.assertEqual(len(self.run_cli('candidate', 'compare', assets[0]['id'], assets[1]['id'])), 2)
        self.assertEqual(len(self.run_cli('candidate', 'compare', self.pid, assets[0]['id'], assets[1]['id'])), 2)
        other = self.store.create('別案件', '分離確認')['id']
        self.run_cli('candidate', 'show', other, assets[0]['id'], code=3)

    def test_image_register_does_not_enable_legacy_geometry(self):
        self.structure()
        plan = self.run_cli('generate', 'plan', self.pid, '--part', self.parts[1], '--prompt', '帽子画像の準備')
        self.run_cli('generate', 'request-approval', plan['id'])
        self.run_cli('generate', 'approve', plan['id'], '--evidence', '試験計画の承認')
        image = self.run_cli('generate', 'register', plan['id'], self.image, '--method', 'external')
        self.run_cli('generate', 'plan', self.pid, '--input', image['id'], '--prompt', '未承認画像は不可', code=3)
        self.run_cli('image', 'approve', image['id'], '--evidence', '試験画像の確認')
        with patch('subprocess.Popen', side_effect=AssertionError('must not execute')):
            self.run_cli('generate', 'plan', self.pid, '--input', image['id'], '--prompt', '旧方式', code=3)
        self.assertEqual(len(self.run_cli('candidate', 'list', self.pid, '--generation', plan['id'])), 1)

    def test_approval_needs_confirmation_and_rechecks_displayed_hash(self):
        p = self.structure()
        plan = self.run_cli('generate', 'plan', self.pid, '--part', self.parts[0], '--prompt', '準備')
        self.run_cli('generate', 'request-approval', plan['id'])
        with patch('sys.stdin.isatty', return_value=False):
            self.run_cli('generate', 'approve', plan['id'], code=3)
        with patch('sys.stdin.isatty', return_value=True), patch('builtins.input', return_value='n'):
            self.run_cli('generate', 'approve', plan['id'], code=3)
        self.assertEqual(find(self.store.load(self.pid)['plans'], plan['id'])['state'], 'awaiting_approval')
        def tamper():
            with self.store.update(self.pid, 'test_change') as doc:
                changed = find(doc['plans'], plan['id'])
                changed['fixed']['prompt'] = '確認後の変更'
                changed['plan_hash'] = fingerprint(changed['fixed'])
            return 'y'
        with patch('sys.stdin.isatty', return_value=True), patch('builtins.input', side_effect=tamper):
            self.run_cli('generate', 'approve', plan['id'], code=3)

    def test_bind_material_edit_and_review_without_json_recipes(self):
        assets = self.assets()
        plan = self.run_cli('generate', 'plan', self.pid, '--bind', assets[0]['id'], '--bind', assets[1]['id'],
                            '--part', self.parts[1], '--location', '0,0,1.65', '--scale', '0.25,0.25,0.25', '--prompt', '仮組み')
        self.assertEqual(plan['fixed']['composition'][1]['location'], [0., 0., 1.65])
        char = record(kind='character', part_id=None, status='pending', shape_confirmed=True,
                      files=copy.deepcopy(assets[0]['files']), composition=plan['fixed']['composition'],
                      materials=[], history=[], generation_id=None, parent_id=None)
        with self.store.update(self.pid, 'fixture') as doc:
            doc['candidates'].append(char)
        edit = self.run_cli('edit', 'plan', self.pid, '--source', char['id'], '--part', self.parts[1], '--scale', '1.1', '--prompt', '帽子の拡大')
        self.run_cli('edit', 'show', edit['id'])
        self.assertEqual(edit['fixed']['edit']['scale_factor'], 1.1)
        mats = [self.run_cli('material', 'create', self.pid, '--source', a['id'], '--name', '青', '--color', '0.1,0.2,0.8') for a in assets]
        surface = self.run_cli('generate', 'plan', self.pid, '--source', char['id'], '--material', mats[0]['id'], '--material', mats[1]['id'], '--prompt', '材質')
        self.assertEqual(surface['fixed']['stage'], 'surface')
        req = self.run_cli('requirement', 'add', self.pid, '--category', 'must_keep', '--prompt', '身体保持')
        self.run_cli('review', char['id'], '--requirement', req['id'], '--result', 'uncertain', '--prompt', '未確認')
        with patch('sys.stdin.isatty', return_value=True), patch('builtins.input', return_value='y'):
            self.run_cli('candidate', 'select', char['id'])
        self.assertEqual(find(self.store.load(self.pid)['candidates'], char['id'])['status'], 'selected')
        selection = sorted([c for c in self.store.load(self.pid)['candidates'] if c['status'] == 'selected'], key=lambda c: c['id'])
        with self.store.update(self.pid, 'test_change') as doc:
            find(doc['candidates'], char['id'])['description'] = '確認後の変更'
        with self.assertRaises(WorkflowError):
            self.wb.export(self.pid, '試験出力', '試験', expected_selection=fingerprint(selection))
        self.assertFalse((self.store.directory(self.pid) / 'exports').exists())

    def test_duplicate_id_across_projects_and_wrong_placement_are_rejected(self):
        assets = self.assets()
        other = self.store.create('重複データ', '誤特定の拒否')['id']
        with self.store.update(other, 'fixture') as doc:
            doc['candidates'].append(copy.deepcopy(assets[0]))
        self.run_cli('candidate', 'show', assets[0]['id'], code=3)
        self.run_cli('generate', 'plan', self.pid, '--input', assets[0]['id'], '--location', '0,0,1', '--prompt', '誤指定', code=3)


if __name__ == '__main__':
    unittest.main()
