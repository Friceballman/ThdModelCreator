"""Approval and evidence boundaries for the v3.5 experiment, without Blender."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from model_workbench.storage import Store, WorkflowError, find, read, record, sha, uid, write
from model_workbench.rigging import RiggingLab, lab
from model_workbench.runtime import load_config, REPO
from model_workbench.cli import parser, dispatch


class RiggingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = Store(Path(temp.name) / 'projects')
        self.pid = self.store.create('fixture', 'rig experiment', 3)['id']
        self.config = load_config(REPO / 'experiments/config.example.json')
        self.lab = RiggingLab(self.store, self.config)
        self.part = uid()
        self.source = self.store.path(self.pid, 'fixtures/model.blend')
        self.source.parent.mkdir()
        self.source.write_bytes(b'BLENDER-fixture-only')
        self.candidate = record(kind='character', status='pending', composition=[{'part_id': self.part}],
                                files=[{'file': 'fixtures/model.blend', 'sha256': sha(self.source)}])
        with self.store.update(self.pid, 'fixture') as doc:
            doc['candidates'].append(self.candidate)
        self.motion = uid()

    def requirement(self):
        return self.lab.requirements_input(self.pid, self.candidate['id'], 'fixture movement only',
                    dict(motions=[dict(id=self.motion, text='fixture rotation', evidence='synthetic fixture',
                                       state='confirmed', acceptance='inspect all synthetic samples')],
                         preserve=['fixture appearance'], unknowns=[]))

    def fake_blender(self, command, *_):
        from PIL import Image
        job = read(command[-1])
        output = Path(job['output'])
        checks = dict(success=True, ready=True, experiment_id=job['experiment_id'], source_hash=job['source_hash'],
                      objects={'mesh': {'vertices': 3}}, rest_geometry_preserved=True,
                      baseline_images=['baseline-front.png'], rest_images=['rest-front.png'], samples=[])
        if job['mode'] == 'rig':
            (output / 'model.blend').write_bytes(b'BLENDER-rig-fixture')
            for pose in job['definition']['poses']:
                checks['samples'].append(dict(requirement_id=pose['requirement_id'], images=['pose-front.png']))
            for image_name in ('baseline-front.png', 'rest-front.png', 'pose-front.png'):
                Image.new('RGB', (16, 16)).save(output / image_name)
        write(output / 'checks.json', checks)
        return {'seconds': 0, 'scope': 'mock only'}

    def inspection(self):
        with patch('model_workbench.runtime.process', side_effect=self.fake_blender):
            return self.lab.inspect(self.pid, self.candidate['id'])

    def definition(self):
        return dict(bones=[dict(name='root', parent=None, head=[0, 0, 0], tail=[0, 0, 1])],
                    bindings={'mesh': {'mode': 'rigid', 'bone': 'root'}},
                    poses=[dict(name='turn', requirement_id=self.motion, rotations={'root': [30, 0, 0]}, samples=3)],
                    rest_tolerance=1e-6, scope='partial_trial', reason='fixture only')

    def planned(self):
        return self.lab.plan(self.pid, self.requirement()['id'], self.inspection()['id'], self.definition())

    def execute_fixture(self):
        plan = self.planned()
        self.lab.approve(self.pid, plan['id'], plan['plan_hash'], 'synthetic test authorization')
        with patch('model_workbench.runtime.process', side_effect=self.fake_blender):
            return self.lab.execute(self.pid, plan['id'])

    def test_input_cli_keeps_history_without_launching_blender_or_promoting_candidate(self):
        def call(*args):
            return dispatch(parser().parse_args(['--root', str(self.store.root), *args]))
        with patch('model_workbench.runtime.process') as runner:
            first = call('animation', 'input', self.candidate['id'], '--text', '腕を下ろしたい')
            second = call('animation', 'input', self.candidate['id'], '--text', '元の外形を保ちたい')
            self.assertEqual(len(call('animation', 'show', self.candidate['id'])), 2)
            self.assertEqual(first['state'], 'needs_interpretation')
            self.assertNotEqual(first['id'], second['id'])
            runner.assert_not_called()
        self.assertEqual(self.source.read_bytes(), b'BLENDER-fixture-only')
        doc = self.store.load(self.pid)
        self.assertEqual(doc['workflow_version'], 3)
        self.assertIsNone(doc['approved_candidate_id'])

    def test_unapproved_or_changed_plan_never_launches_blender(self):
        plan = self.planned()
        with patch('model_workbench.runtime.process') as runner:
            with self.assertRaises(WorkflowError):
                self.lab.execute(self.pid, plan['id'])
            self.lab.approve(self.pid, plan['id'], plan['plan_hash'], 'fixture')
            with self.store.update(self.pid, 'tamper') as doc:
                find(lab(doc)['experiments'], plan['id'])['fixed']['definition']['rest_tolerance'] = 10
            with self.assertRaises(WorkflowError):
                self.lab.execute(self.pid, plan['id'])
            runner.assert_not_called()

    def test_new_requirements_invalidate_execution_and_reviews(self):
        result = self.execute_fixture()
        self.lab.requirements_input(self.pid, self.candidate['id'], 'new requirement')
        with self.assertRaises(WorkflowError):
            self.lab.review(self.pid, result['id'], 'appearance', [])

    def test_definition_rejects_unassigned_bones_bad_weights_and_unconfirmed_motion(self):
        req, inspect = self.requirement(), self.inspection()
        mutations = []
        missing = self.definition()
        missing['bindings'] = {}
        mutations.append(missing)
        weight = self.definition()
        weight['bindings']['mesh'] = {'mode': 'weights', 'vertices': [{'root': 0.5}] * 3}
        mutations.append(weight)
        parent = self.definition()
        parent['bones'][0]['parent'] = 'root'
        mutations.append(parent)
        unknown = self.definition()
        unknown['poses'][0]['requirement_id'] = uid()
        mutations.append(unknown)
        few_samples = self.definition()
        few_samples['poses'][0]['samples'] = 2
        mutations.append(few_samples)
        for value in mutations:
            with self.assertRaises(WorkflowError):
                self.lab.plan(self.pid, req['id'], inspect['id'], value)

    def test_failure_keeps_source_and_pending_output_but_consumes_execution(self):
        plan = self.planned()
        self.lab.approve(self.pid, plan['id'], plan['plan_hash'], 'fixture')
        with patch('model_workbench.runtime.process', side_effect=WorkflowError('fixture failure')):
            with self.assertRaises(WorkflowError):
                self.lab.execute(self.pid, plan['id'])
        saved = find(lab(self.store.load(self.pid))['experiments'], plan['id'])
        self.assertEqual(saved['state'], 'failed')
        self.assertTrue(self.store.path(self.pid, plan['run'] + '/outputs.pending').is_dir())
        self.assertEqual(self.source.read_bytes(), b'BLENDER-fixture-only')
        with self.assertRaises(WorkflowError):
            self.lab.execute(self.pid, plan['id'])

    def test_success_does_not_equal_quality_or_ue_verification(self):
        result = self.execute_fixture()
        self.assertEqual(result['verification'], dict(appearance='not_run', motion='not_run', ue='not_run'))
        self.assertEqual(len(self.store.load(self.pid)['candidates']), 1)
        prefix = result['run'] + '/outputs/'
        with self.assertRaises(WorkflowError):
            self.lab.review(self.pid, result['id'], 'appearance', [dict(requirement_id='preservation',
                            result='pass', reason='fixture', evidence=[prefix + 'rest-front.png'])])
        result = self.lab.review(self.pid, result['id'], 'appearance', [dict(requirement_id='preservation',
                    result='pass', reason='synthetic fixture only',
                    evidence=[prefix + 'baseline-front.png', prefix + 'rest-front.png'])])
        self.assertEqual(result['verification']['appearance'], 'pass')
        self.assertEqual(result['verification']['motion'], 'not_run')
        self.assertEqual(result['verification']['ue'], 'not_run')
        self.store.path(self.pid, prefix + 'rest-front.png').write_bytes(b'tampered')
        with self.assertRaises(WorkflowError):
            self.lab.review(self.pid, result['id'], 'appearance', [])

    def test_complete_output_can_be_recovered_once_without_reexecution(self):
        result = self.execute_fixture()
        with self.store.update(self.pid, 'simulate_interruption') as doc:
            find(lab(doc)['experiments'], result['id'])['state'] = 'result_unknown'
        with patch('model_workbench.runtime.process') as runner:
            recovered = self.lab.recover(self.pid, result['id'], 'fixture process already exited')
            again = self.lab.recover(self.pid, result['id'], 'fixture process already exited')
            self.assertEqual(recovered['id'], again['id'])
            runner.assert_not_called()

    def test_changed_source_and_diagnostic_evidence_are_rejected(self):
        req, inspected = self.requirement(), self.inspection()
        self.store.path(self.pid, inspected['files'][0]['file']).write_bytes(b'changed')
        with self.assertRaises(WorkflowError):
            self.lab.plan(self.pid, req['id'], inspected['id'], self.definition())
        self.source.write_bytes(b'changed')
        with self.assertRaises(WorkflowError):
            self.lab.requirements_input(self.pid, self.candidate['id'], 'should fail')


if __name__ == '__main__':
    unittest.main()
