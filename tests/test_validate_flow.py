"""Safety and provenance tests; never start TripoSR, Blender, or a GPU job."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('validate_flow',
    Path(__file__).resolve().parents[1] / 'scripts/validate_flow.py')
flow = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(flow)


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'cache').mkdir()
        for name in ('python.exe', 'blender.exe', 'run.py'):
            (self.root / name).write_text('test only', encoding='utf-8')
        self.mesh = self.root / 'mesh.obj'
        self.mesh.write_text('v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n')
        self.config = self.root / 'config.json'
        self.config.write_text(json.dumps({
            'triposr_root': str(self.root), 'triposr_python': str(self.root / 'python.exe'),
            'blender': str(self.root / 'blender.exe'), 'hf_home': str(self.root / 'cache'),
            'u2net_home': str(self.root / 'cache')}))
        self.recipe = self.root / 'recipe.json'
        self.data = {'parts': [{'id': 'body', 'mesh': str(self.mesh)}],
                     'edit': {'part_id': 'body', 'scale_factor': 1.1}}

    def plan(self):
        self.recipe.write_text(json.dumps(self.data))
        return flow.build_plan(self.config, self.recipe)

    def test_plan_is_non_executing_and_hash_bound(self):
        with patch.object(flow.subprocess, 'Popen', side_effect=AssertionError('must not start')):
            plan = self.plan()
            self.assertEqual(plan['payload']['new_generations'], 0)
            flow.verify_plan(plan, plan['plan_hash'])
        with self.assertRaises(ValueError):
            flow.verify_plan(plan, 'not approved')
        altered = copy.deepcopy(plan)
        altered['payload']['recipe']['edit']['scale_factor'] = 2
        with self.assertRaises(ValueError):
            flow.verify_plan(altered, plan['plan_hash'])

    def test_changed_source_stops_before_process(self):
        plan = self.plan()
        self.mesh.write_text('changed')
        with patch.object(flow.subprocess, 'Popen', side_effect=AssertionError('must not start')):
            with self.assertRaises(ValueError):
                flow.verify_plan(plan, plan['plan_hash'])

    def test_duplicate_and_invalid_part_ids(self):
        self.data['parts'].append(dict(self.data['parts'][0]))
        with self.assertRaises(ValueError):
            self.plan()
        self.data['parts'] = [{'id': '../outside', 'mesh': str(self.mesh)}]
        with self.assertRaises(ValueError):
            self.plan()

    def test_material_dependency_and_bad_indices_are_rejected(self):
        self.mesh.write_text('mtllib outside.mtl\nv 0 0 0\nf 1 1 1\n')
        with self.assertRaises(ValueError):
            self.plan()
        self.mesh.write_text('v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 99\n')
        with self.assertRaises(ValueError):
            self.plan()

    def test_each_plan_has_distinct_identity(self):
        a, b = self.plan(), self.plan()
        self.assertNotEqual(a['plan_hash'], b['plan_hash'])

    def test_gpu_settings_cannot_silently_exceed_probe_budget(self):
        self.data['mc_resolution'] = 256
        with self.assertRaises(ValueError):
            self.plan()

    def test_completed_plan_is_not_executed_twice(self):
        plan = self.plan()
        plan_path = self.root / 'plan.json'
        flow.save_json(plan_path, plan)
        runs = self.root / 'runs'
        previous = runs / 'previous'
        previous.mkdir(parents=True)
        flow.save_json(previous / 'plan.json', plan)
        with patch.object(flow, 'RUN_DIR', runs.resolve()), \
             patch.object(flow, 'PLAN_DIR', self.root.resolve()), \
             patch.object(flow.subprocess, 'Popen', side_effect=AssertionError('must not start')):
            with self.assertRaisesRegex(ValueError, '既に実行済み'):
                flow.execute(plan_path, plan['plan_hash'])
        self.assertTrue((previous / 'plan.json').is_file())
        self.assertFalse((runs / '.execution.lock').exists())


if __name__ == '__main__':
    unittest.main()
