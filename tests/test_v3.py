"""V3 completion, comparison and session invariants with isolated temporary data."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import test_v2
from model_workbench.storage import record, sha, write, read, find, WorkflowError
from model_workbench.v3 import V3Workbench
from model_workbench.cli import parser, dispatch


class V3Tests(unittest.TestCase):
    def setUp(self):
        test_v2.V2Tests.setUp(self)
        self.wb = V3Workbench(self.store, self.config)
        self.production = test_v2.V2Tests.production(self)
        with self.store.update(self.pid, 'fixture') as doc:
            p = find(doc['production_plans'], self.production['id'])
            from model_workbench.storage import fingerprint
            p['fixed']['scope']['stages'].append('inspect')
            p['fixed']['scope']['quality_loop_version'] = 3
            p['content_hash'] = fingerprint(p['fixed'])
        self.blend = self.store.path(self.pid, 'fixtures/model.blend')
        self.blend.parent.mkdir()
        self.blend.write_bytes(b'BLENDER-test-fixture')
        self.character = record(kind='character', status='pending', history=[],
            production_plan_id=self.production['id'], parent_id=None,
            files=[{'file': 'fixtures/model.blend', 'sha256': sha(self.blend)}],
            composition=[{'part_id': self.part_id, 'candidate_id': record()['id']}])
        with self.store.update(self.pid, 'fixture') as doc:
            doc['candidates'].append(self.character)

    def profile(self):
        return {'camera': {'center': [0, 0, 0], 'ortho_scale': 2},
                'views': {v: {'reference_id': self.ref['id'], 'source_view': v}
                          for v in ('front', 'side', 'top')}}

    def fake_render(self, command, *_):
        from PIL import Image
        job = read(command[-1])
        output = Path(job['output'])
        for view in job['profile']['views']:
            for part in ['whole', *job['part_ids']]:
                Image.new('RGB', (16, 16)).save(output / f'{part}-{view}.png')
        write(output / 'checks.json', {'success': True, 'part_ids': job['part_ids']})
        return {'duration_seconds': 0}

    def comparison(self, candidate=None, profile=None):
        with patch('model_workbench.runtime.process', side_effect=self.fake_render):
            return self.wb.comparison_run(self.pid, (candidate or self.character)['id'], profile or self.profile())

    def review(self, comparison, result='pass'):
        good = {'result': result, 'reason': 'fixture only'}
        return self.wb.comparison_review(self.pid, comparison['id'],
            {'actor': 'user', 'whole': good, 'preservation': good,
             'parts': [dict(good, part_id=self.part_id)],
             'requirements': [dict(good, requirement_id=self.req['id'])]})

    def issue(self):
        return self.wb.quality_issue_add(self.pid, self.production['id'],
            {'title': '輪郭差', 'category': 'part_shape', 'affected_part_ids': [self.part_id],
             'candidate_id': self.character['id'], 'mandatory': True, 'source_views': ['front'],
             'evidence_reference_ids': [self.ref['id']], 'repair': '頭部の幅を修正'})

    def test_completion_needs_current_candidate_review_and_rejects_regression(self):
        issue = self.issue()
        with self.assertRaises(WorkflowError):
            self.wb.completion_set(self.pid, self.production['id'], self.character['id'], '未点検')
        comparison = self.comparison()
        self.review(comparison)
        self.wb.quality_issue_evaluate(self.pid, issue['id'], self.character['id'], 'resolved', '確認', comparison['id'])
        self.wb.completion_set(self.pid, self.production['id'], self.character['id'], '確認済み')
        self.assertEqual(self.wb.completion_status(self.pid, self.production['id'])['state'], 'complete')
        other = copy.deepcopy(self.character)
        other['id'] = record()['id']
        with self.store.update(self.pid, 'fixture') as doc:
            doc['candidates'].append(other)
        next_comparison = self.comparison(other, {'reuse': comparison['id']})
        self.review(next_comparison)
        with self.assertRaises(WorkflowError):
            self.wb.completion_set(self.pid, self.production['id'], other['id'], '課題未評価')
        self.review(comparison, 'fail')
        self.assertEqual(self.wb.completion_status(self.pid, self.production['id'])['state'], 'in_progress')

    def test_missing_views_and_modified_evidence_cannot_pass(self):
        profile = self.profile()
        profile['views']['top'] = {'missing_reason': '一次資料なし'}
        comparison = self.comparison(profile=profile)
        self.review(comparison)
        with self.assertRaises(WorkflowError):
            self.wb.completion_set(self.pid, self.production['id'], self.character['id'], '資料不足')
        self.store.path(self.pid, comparison['files'][0]['file']).write_bytes(b'changed')
        with self.assertRaises(WorkflowError):
            self.review(comparison)

    def test_failed_render_is_durable(self):
        with patch('model_workbench.runtime.process', side_effect=WorkflowError('render failed')):
            with self.assertRaises(WorkflowError):
                self.wb.comparison_run(self.pid, self.character['id'], self.profile())
        self.assertEqual(self.store.load(self.pid)['comparisons'][-1]['state'], 'failed')

    def test_session_binding_and_capture_hash(self):
        session = self.wb.candidate_edit_session_start(self.pid, self.production['id'], self.character['id'])
        folder = Path(session['working_path']).parent
        connection = {'session_id': session['id'], 'candidate_id': self.character['id'],
                      'filepath': session['working_path'], 'sha256': session['source_sha256'],
                      'objects': [{'part_id': self.part_id}]}
        write(folder / 'connection.json', dict(connection, candidate_id=record()['id']))
        with self.assertRaises(WorkflowError):
            self.wb.candidate_edit_session_bind(self.pid, session['id'])
        write(folder / 'connection.json', connection)
        self.wb.candidate_edit_session_bind(self.pid, session['id'])
        Path(session['working_path']).write_bytes(b'edited')
        write(folder / 'capture.json', dict(connection, operations=['shape edit']))
        with patch.object(self.wb, 'revision_run') as runner:
            with self.assertRaises(WorkflowError):
                self.wb.candidate_edit_session_finish(self.pid, session['id'], {}, session['working_path'])
            runner.assert_not_called()
        write(folder / 'capture.json', dict(connection, sha256=sha(session['working_path']), operations=['shape edit']))
        derived = dict(self.character, id=record()['id'], parent_id=self.character['id'])
        def imported(*args):
            with self.store.update(self.pid, 'fixture_import') as doc:
                doc['candidates'].append(derived)
            return derived
        with patch.object(self.wb, 'revision_run', side_effect=imported) as runner:
            self.wb.candidate_edit_session_finish(self.pid, session['id'], {}, session['working_path'])
            again = self.wb.candidate_edit_session_finish(self.pid, session['id'], {}, session['working_path'])
            self.assertEqual(again['id'], derived['id'])
            self.assertEqual(runner.call_count, 1)
        saved = find(self.store.load(self.pid)['edit_sessions'], session['id'])
        self.assertTrue(saved['closed_at'])
        self.assertEqual(self.blend.read_bytes(), b'BLENDER-test-fixture')

    def test_cli_id_resolution_and_brief(self):
        def call(*args):
            return dispatch(parser().parse_args(['--root', str(self.store.root), *args]))
        brief = call('reference-pack', 'brief', self.production['id'])
        self.assertEqual(brief['tasks'][0]['part_id'], self.part_id)
        self.assertEqual(call('completion', 'show', '--production', self.production['id'])['state'], 'in_progress')
        session = call('candidate', 'edit-start', self.character['id'], '--production', self.production['id'])
        self.assertEqual(call('candidate', 'edit-show', session['id'])['state'], 'open')
        call('candidate', 'edit-abandon', session['id'], '--reason', 'fixture終了')
        self.assertTrue(Path(session['working_path']).is_file())

    def test_rejected_candidate_and_unfinished_session_block_completion(self):
        comparison = self.comparison()
        self.review(comparison)
        session = self.wb.candidate_edit_session_start(self.pid, self.production['id'], self.character['id'])
        with self.assertRaises(WorkflowError):
            self.wb.completion_set(self.pid, self.production['id'], self.character['id'], '編集中')
        self.wb.candidate_edit_session_abandon(self.pid, session['id'], '検討中止')
        with self.store.update(self.pid, 'fixture') as doc:
            find(doc['candidates'], self.character['id'])['status'] = 'rejected'
        with self.assertRaises(WorkflowError):
            self.wb.completion_set(self.pid, self.production['id'], self.character['id'], '却下候補')

    def test_v3_export_requires_completion_and_recovery_is_idempotent(self):
        with self.store.update(self.pid, 'fixture') as doc:
            find(doc['candidates'], self.character['id'])['status'] = 'selected'
        with self.assertRaises(WorkflowError):
            self.wb.export(self.pid, '未完成', 'fixture')
        session = self.wb.candidate_edit_session_start(self.pid, self.production['id'], self.character['id'])
        plan = record(state='succeeded', fixed={'edit': {'session_id': session['id']}})
        derived = dict(self.character, id=record()['id'], generation_id=plan['id'], parent_id=self.character['id'])
        with self.store.update(self.pid, 'simulated_crash_after_import') as doc:
            doc['plans'].append(plan)
            doc['candidates'].append(derived)
            find(doc['edit_sessions'], session['id'])['state'] = 'importing'
        for _ in range(2):
            recovered = self.wb.candidate_edit_session_recover(self.pid, session['id'])
            self.assertEqual(recovered['result_candidate_id'], derived['id'])

    def test_repair_queue_is_candidate_specific_and_retains_instruction(self):
        issue = self.issue()
        queue = self.wb.repair_queue(self.pid, self.production['id'], self.character['id'])
        self.assertEqual(queue[0]['repair'], '頭部の幅を修正')
        comparison = self.comparison()
        self.review(comparison)
        self.wb.quality_issue_evaluate(self.pid, issue['id'], self.character['id'], 'resolved', '確認', comparison['id'])
        self.assertEqual(self.wb.repair_queue(self.pid, self.production['id'], self.character['id']), [])

    def test_v3_pack_requires_low_poly_and_honest_provenance(self):
        manifest = {'parts': [{'part_id': self.part_id, 'source_reference_ids': [self.ref['id']],
                    'dimensions': {}, 'anchors': {}, 'color_zones': [], 'consistency': 'fixture',
                    'uncertainties': [], 'low_poly': {'retained_features': ['輪郭'], 'omitted_details': []},
                    'images': [{'file': self.ref['file'], 'view': v, 'source_reference_id': self.ref['id'],
                                'method': 'image_generation', 'inferred': True, 'uncertainties': ['推定']}
                               for v in ('front', 'side', 'top')]}],
                    'assembly_concept': {'file': self.ref['file'], 'source_reference_ids': [self.ref['id']],
                                         'method': 'image_generation', 'inferred': True, 'uncertainties': ['推定']}}
        bad = copy.deepcopy(manifest)
        bad['parts'][0]['images'][0]['inferred'] = False
        with self.assertRaises(WorkflowError):
            self.wb.reference_pack_create(self.pid, self.production['id'], bad)
        bad = copy.deepcopy(manifest)
        bad['parts'][0]['images'].pop()
        with self.assertRaises(WorkflowError):
            self.wb.reference_pack_create(self.pid, self.production['id'], bad)
        pack = self.wb.reference_pack_create(self.pid, self.production['id'], manifest)
        self.wb.reference_pack_transition(self.pid, pack['id'], 'request-approval')
        self.wb.reference_pack_transition(self.pid, pack['id'], 'approve', 'fixture')
        self.wb.verify_pack(self.store.load(self.pid), pack['id'])


if __name__ == '__main__':
    unittest.main()
