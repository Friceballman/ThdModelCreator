"""V3.5 experiment facilities. Only requirement intake is a public CLI workflow.

Rig results live separately from static candidates: a successful Blender job is
never an accepted character or evidence of animation/UE quality.
"""
from __future__ import annotations

import copy
import math
import os
from pathlib import Path
import re
import shutil
import subprocess

from . import runtime
from .storage import WorkflowError, find, fingerprint, identifier, no_links, now, read, record, sha, uid, write
from .workflow import require_text

ADAPTER = runtime.REPO / 'scripts/blender_rigging.py'


def finite(value, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value) or (positive and value <= 0):
        raise WorkflowError('有限の数値が必要です')
    return value


def vector(value):
    if not isinstance(value, list) or len(value) != 3:
        raise WorkflowError('3要素の数値配列が必要です')
    return [finite(x) for x in value]


def label(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,63}', value):
        raise WorkflowError('骨・試験名は英字で始まる64文字以内の英数字・_.-です')
    return value


def lab(doc):
    value = doc.get('rigging_lab', {'version': 1, 'requirements': [], 'experiments': []})
    if (not isinstance(value, dict) or value.get('version') != 1 or
            any(not isinstance(value.get(k), list) for k in ('requirements', 'experiments'))):
        raise WorkflowError('未知または破損したrigging_labです')
    return value


class RiggingLab:
    def __init__(self, store, config):
        self.store, self.config = store, copy.deepcopy(config)

    def source(self, project_id, candidate_id):
        doc = self.store.load(project_id)
        candidate = find(doc['candidates'], candidate_id)
        if candidate.get('kind') != 'character' or candidate.get('status') == 'rejected':
            raise WorkflowError('却下されていない静止全身候補が必要です')
        blends = [f for f in candidate['files'] if f['file'].endswith('.blend')]
        if len(blends) != 1:
            raise WorkflowError('入力.blendを一意に特定できません')
        entry = blends[0]
        path = self.store.path(project_id, entry['file'])
        if sha(path) != entry['sha256']:
            raise WorkflowError('元静止モデルのhashが変更されています')
        return candidate, path, copy.deepcopy(entry)

    def requirements_input(self, project_id, candidate_id, text, details=None):
        require_text(text)
        candidate, _, source = self.source(project_id, candidate_id)
        details = copy.deepcopy(details or {})
        if not isinstance(details, dict):
            raise WorkflowError('detailsはオブジェクトです')
        if set(details) - {'motions', 'preserve', 'unknowns', 'parent_id'}:
            raise WorkflowError('未対応の要件項目があります')
        motions = details.get('motions', [])
        if not isinstance(motions, list):
            raise WorkflowError('motionsは配列です')
        ids = set()
        for motion in motions:
            if not isinstance(motion, dict) or set(motion) != {'id', 'text', 'evidence', 'state', 'acceptance'}:
                raise WorkflowError('動作要件にはid/text/evidence/state/acceptanceが必要です')
            identifier(motion['id'])
            if motion['id'] in ids or motion['state'] not in ('confirmed', 'proposed', 'unknown'):
                raise WorkflowError('動作要件IDの重複または状態が不正です')
            ids.add(motion['id'])
            for key in ('text', 'evidence', 'acceptance'):
                require_text(motion[key])
        for key in ('preserve', 'unknowns'):
            if not isinstance(details.get(key, []), list):
                raise WorkflowError(key + 'は文章の配列です')
            for text_value in details.get(key, []):
                require_text(text_value)
        item = record(candidate_id=candidate_id, source=source, text=text, details=details,
                      state='structured' if motions else 'needs_interpretation')
        item['content_hash'] = fingerprint({k: item[k] for k in ('candidate_id', 'source', 'text', 'details')})
        with self.store.update(project_id, 'animation_requirements_recorded') as doc:
            data = doc.setdefault('rigging_lab', lab(doc))
            if details.get('parent_id'):
                parent = find(data['requirements'], details['parent_id'])
                if parent['candidate_id'] != candidate_id:
                    raise WorkflowError('要件の親版と入力候補が異なります')
            data['requirements'].append(item)
        return item

    def requirements_show(self, project_id, candidate_id):
        self.source(project_id, candidate_id)
        return [r for r in lab(self.store.load(project_id))['requirements'] if r['candidate_id'] == candidate_id]

    def _requirement(self, doc, requirement_id):
        item = find(lab(doc)['requirements'], requirement_id)
        fixed = {k: item[k] for k in ('candidate_id', 'source', 'text', 'details')}
        if fingerprint(fixed) != item['content_hash']:
            raise WorkflowError('要件の固定内容が変更されています')
        latest = [r for r in lab(doc)['requirements'] if r['candidate_id'] == item['candidate_id']][-1]
        if latest['id'] != item['id']:
            raise WorkflowError('新しい要件版があります。新計画へ引き継いでください')
        return item

    def _files(self, project_id, folder):
        return [{'file': p.relative_to(self.store.directory(project_id)).as_posix(), 'sha256': sha(p)}
                for p in sorted(folder.rglob('*')) if p.is_file()]

    def _verified_output(self, project_id, experiment):
        if experiment['state'] != 'succeeded':
            raise WorkflowError('成功した検査・実験が必要です')
        for f in experiment['files']:
            if sha(self.store.path(project_id, f['file'])) != f['sha256']:
                raise WorkflowError('検証成果物のhashが変更されています')
        return read(self.store.path(project_id, experiment['run'] + '/outputs/checks.json'))

    def inspect(self, project_id, candidate_id):
        """Read-only preflight of a real registered model; never saves its blend."""
        _, _, source = self.source(project_id, candidate_id)
        item = record(kind='inspect', candidate_id=candidate_id, source=source,
                      state='approved', run='runs/' + uid(), files=[], reviews=[])
        with self.store.update(project_id, 'rig_inspection_reserved') as doc:
            doc.setdefault('rigging_lab', lab(doc))['experiments'].append(item)
        return self._execute(project_id, item['id'])

    def _definition(self, definition, inventory, requirement):
        definition = copy.deepcopy(definition)
        if set(definition) != {'bones', 'bindings', 'poses', 'rest_tolerance', 'scope', 'reason'}:
            raise WorkflowError('リグ定義の必須項目または未知項目があります')
        require_text(definition['reason'])
        if definition['scope'] not in ('partial_trial', 'whole_character'):
            raise WorkflowError('検証範囲を明示してください')
        finite(definition['rest_tolerance'], positive=True)
        bones = definition['bones']
        if not isinstance(bones, list) or not bones:
            raise WorkflowError('骨定義が必要です')
        names = set()
        for b in bones:
            if set(b) != {'name', 'parent', 'head', 'tail'}:
                raise WorkflowError('骨はname/parent/head/tailを指定します')
            label(b['name'])
            if b['name'] in names or b['parent'] is not None and b['parent'] not in names:
                raise WorkflowError('骨名の重複または親子順序が不正です')
            if vector(b['head']) == vector(b['tail']):
                raise WorkflowError('長さ0の骨は使用できません')
            names.add(b['name'])
        if sum(b['parent'] is None for b in bones) != 1:
            raise WorkflowError('骨格rootは1つです')
        objects = inventory['objects']
        bindings = definition['bindings']
        if not isinstance(bindings, dict) or set(bindings) != set(objects):
            raise WorkflowError('全部のメッシュに追従方式が必要です（未変更部品はstatic）')
        active = False
        for name, binding in bindings.items():
            mode = binding.get('mode')
            if mode == 'static' and set(binding) == {'mode'}:
                if definition['scope'] == 'whole_character':
                    raise WorkflowError('全身検証に未追従部品を残せません')
                continue
            active = True
            if mode == 'rigid' and set(binding) == {'mode', 'bone'} and binding['bone'] in names:
                continue
            if mode != 'weights' or set(binding) != {'mode', 'vertices'}:
                raise WorkflowError('追従はstatic/rigid/weightsを明示してください')
            vertices = binding['vertices']
            if not isinstance(vertices, list) or len(vertices) != objects[name]['vertices']:
                raise WorkflowError('全頂点の明示ウェイトが必要です')
            for weights in vertices:
                if not isinstance(weights, dict) or not weights or not set(weights) <= names:
                    raise WorkflowError('ウェイトの骨割当が不正です')
                for weight in weights.values():
                    finite(weight, positive=True)
                if abs(sum(weights.values()) - 1) > 1e-6:
                    raise WorkflowError('各頂点のウェイト合計は1です')
        if not active:
            raise WorkflowError('少なくとも1部品を骨に追従させてください')
        motions = {m['id'] for m in requirement['details'].get('motions', []) if m['state'] == 'confirmed'}
        if not motions or not requirement['details'].get('preserve'):
            raise WorkflowError('確認された動作要件と外観保持条件が必要です')
        if requirement['details'].get('unknowns'):
            raise WorkflowError('実行条件の未確定事項を解決した要件版が必要です')
        poses = definition['poses']
        if not isinstance(poses, list) or not poses:
            raise WorkflowError('要件に対応する試験ポーズが必要です')
        pose_names = set()
        for p in poses:
            if set(p) != {'name', 'requirement_id', 'rotations', 'samples'}:
                raise WorkflowError('試験はname/requirement_id/rotations/samplesを指定します')
            label(p['name'])
            if p['name'] in pose_names or p['requirement_id'] not in motions:
                raise WorkflowError('試験名の重複または未確定要件の試験です')
            pose_names.add(p['name'])
            if not isinstance(p['rotations'], dict) or not p['rotations'] or not set(p['rotations']) <= names:
                raise WorkflowError('試験対象の骨が不正です')
            for rotation in p['rotations'].values():
                vector(rotation)
            if not any(any(r) for r in p['rotations'].values()):
                raise WorkflowError('変形試験には0以外の回転が必要です')
            if type(p['samples']) is not int or not 3 <= p['samples'] <= 120:
                raise WorkflowError('試験は始点・中間・終点を含む3〜120サンプルです')
        if {p['requirement_id'] for p in poses} != motions:
            raise WorkflowError('確認済みの全動作要件を試験へ割り当ててください')
        return definition

    def plan(self, project_id, requirement_id, inspection_id, definition, parent_experiment_id=None):
        doc = self.store.load(project_id)
        requirement = self._requirement(doc, requirement_id)
        _, _, source = self.source(project_id, requirement['candidate_id'])
        inspection = find(lab(doc)['experiments'], inspection_id)
        inventory = self._verified_output(project_id, inspection)
        if (inspection['kind'] != 'inspect' or inspection['candidate_id'] != requirement['candidate_id'] or
                inspection['source'] != source or source != requirement['source'] or not inventory.get('ready')):
            raise WorkflowError('同じ静止基準の対応可能な診断が必要です')
        if parent_experiment_id:
            parent = find(lab(doc)['experiments'], parent_experiment_id)
            if parent['kind'] != 'rig' or parent['candidate_id'] != requirement['candidate_id']:
                raise WorkflowError('親実験の静止基準が異なります')
        fixed = dict(requirement_id=requirement_id, requirement_hash=requirement['content_hash'],
                     inspection_id=inspection_id, inspection_files=copy.deepcopy(inspection['files']),
                     source=source, definition=self._definition(definition, inventory, requirement),
                     adapter_hash=sha(ADAPTER), config=copy.deepcopy(self.config))
        item = record(kind='rig', candidate_id=requirement['candidate_id'], parent_experiment_id=parent_experiment_id,
                      source=source, fixed=fixed, plan_hash=fingerprint(fixed), state='draft',
                      approval=None, run='runs/' + uid(), files=[], reviews=[])
        with self.store.update(project_id, 'rig_experiment_planned') as doc:
            self._requirement(doc, requirement_id)
            doc.setdefault('rigging_lab', lab(doc))['experiments'].append(item)
        return item

    def approve(self, project_id, experiment_id, expected_hash, evidence):
        require_text(evidence)
        with self.store.update(project_id, 'rig_experiment_approved') as doc:
            item = find(lab(doc)['experiments'], experiment_id)
            if item['kind'] != 'rig' or item['state'] != 'draft' or expected_hash != item['plan_hash']:
                raise WorkflowError('未実行の固定計画と承認対象hashが必要です')
            self._verify_plan(project_id, doc, item)
            item.update(state='approved', approval=dict(plan_hash=expected_hash, evidence=evidence, at=now()))
        return item

    def _verify_plan(self, project_id, doc, item):
        fixed = item['fixed']
        requirement = self._requirement(doc, fixed['requirement_id'])
        _, _, source = self.source(project_id, item['candidate_id'])
        inspection = find(lab(doc)['experiments'], fixed['inspection_id'])
        inventory = self._verified_output(project_id, inspection)
        if (fingerprint(fixed) != item['plan_hash'] or requirement['content_hash'] != fixed['requirement_hash'] or
                fixed['config'] != self.config or fixed['adapter_hash'] != sha(ADAPTER) or
                fixed['inspection_files'] != inspection['files'] or fixed['source'] != requirement['source'] or
                source != fixed['source'] or requirement['candidate_id'] != item['candidate_id'] or
                inspection['candidate_id'] != item['candidate_id']):
            raise WorkflowError('計画・要件・診断・実行環境の固定内容が変更されています')
        self._definition(fixed['definition'], inventory, requirement)

    def execute(self, project_id, experiment_id):
        return self._execute(project_id, experiment_id)

    def _execute(self, project_id, experiment_id):
        error = None
        with self.store.update(project_id, 'rig_experiment_executed') as doc:
            item = find(lab(doc)['experiments'], experiment_id)
            if item['state'] != 'approved':
                raise WorkflowError('承認済みで未実行の実験が必要です。再試行は新計画を作成してください')
            _, original, source = self.source(project_id, item['candidate_id'])
            if source != item['source']:
                raise WorkflowError('実験の静止基準が一致しません')
            if item['kind'] == 'rig':
                self._verify_plan(project_id, doc, item)
                if not item['approval'] or item['approval']['plan_hash'] != item['plan_hash']:
                    raise WorkflowError('固定計画への明示承認が必要です')
            lock = no_links(runtime.REPO / 'experiments/runs/.execution.lock')
            lock.parent.mkdir(parents=True, exist_ok=True)
            try:
                with lock.open('x', encoding='utf-8') as stream:
                    stream.write(item['id'])
            except FileExistsError as exc:
                raise WorkflowError('他の外部処理または残存ロックがあります') from exc
            try:
                folder = self.store.path(project_id, item['run'])
                folder.mkdir(parents=True, exist_ok=False)
                shutil.copyfile(original, folder / 'input.blend')
                if sha(folder / 'input.blend') != source['sha256']:
                    raise WorkflowError('作業コピーのhashが一致しません')
                pending = folder / 'outputs.pending'
                pending.mkdir()
                job = dict(mode=item['kind'], source=str(folder / 'input.blend'), output=str(pending),
                           source_hash=source['sha256'], experiment_id=item['id'],
                           part_ids=sorted(b['part_id'] for b in find(doc['candidates'], item['candidate_id'])['composition']),
                           definition=item.get('fixed', {}).get('definition'))
                write(folder / 'job.json', job)
                item['job_hash'] = sha(folder / 'job.json')
                write(folder / 'plan.json', item)
                item.update(state='running', started_at=now())
                self.store.save(doc)
                command = [self.config['blender'], '--background', '--factory-startup', '--disable-autoexec',
                           '--python-exit-code', '1', '--python', str(ADAPTER), '--', str(folder / 'job.json')]
                item['metrics'] = runtime.process(command, folder / 'blender.log',
                                                  dict(os.environ, PYTHONDONTWRITEBYTECODE='1'), runtime.REPO)
                if sha(original) != source['sha256'] or sha(folder / 'input.blend') != source['sha256']:
                    raise WorkflowError('元モデルまたは固定入力が変更されています')
                if sha(folder / 'job.json') != item['job_hash']:
                    raise WorkflowError('実行中にjobが変更されています')
                if item['kind'] == 'rig':
                    self._verify_plan(project_id, doc, item)
                checks = read(pending / 'checks.json')
                if (checks.get('success') is not True or checks.get('source_hash') != source['sha256'] or
                        checks.get('experiment_id') != item['id']):
                    raise WorkflowError('検査結果または実験IDが一致しません')
                if item['kind'] == 'rig':
                    if checks.get('rest_geometry_preserved') is not True or not (pending / 'model.blend').is_file():
                        raise WorkflowError('リグ結果の保存または元ポーズの保持検査が不合格です')
                pending.rename(folder / 'outputs')
                item.update(state='succeeded', files=self._files(project_id, folder / 'outputs'),
                            verification=dict(appearance='not_run', motion='not_run', ue='not_run'), finished_at=now())
            except BaseException as exc:
                item.update(state='result_unknown' if isinstance(exc, (KeyboardInterrupt, subprocess.TimeoutExpired)) else 'failed',
                            error=str(exc), finished_at=now())
                error = exc
            finally:
                lock.unlink()
        if error:
            raise error
        return item

    def review(self, project_id, experiment_id, category, entries, actor='codex'):
        if category not in ('appearance', 'motion') or actor not in ('codex', 'user'):
            raise WorkflowError('レビュー種類・評価者が不正です')
        with self.store.update(project_id, 'rig_experiment_reviewed') as doc:
            item = find(lab(doc)['experiments'], experiment_id)
            if item['kind'] != 'rig':
                raise WorkflowError('リグ実験のレビューが必要です')
            self._verify_plan(project_id, doc, item)
            checks = self._verified_output(project_id, item)
            motions = {p['requirement_id'] for p in item['fixed']['definition']['poses']}
            expected = motions if category == 'motion' else {'preservation'}
            if not isinstance(entries, list) or len(entries) != len(expected) or {e.get('requirement_id') for e in entries} != expected:
                raise WorkflowError('全対象要件のレビューが必要です')
            allowed_files = {f['file'] for f in item['files']}
            for entry in entries:
                if entry.get('result') not in ('pass', 'fail', 'uncertain'):
                    raise WorkflowError('判定が不正です')
                require_text(entry.get('reason'))
                evidence = entry.get('evidence')
                if not isinstance(evidence, list) or not evidence or not set(evidence) <= allowed_files:
                    raise WorkflowError('同じ実験の証拠ファイルが必要です')
                if not all(f.endswith('.png') for f in evidence):
                    raise WorkflowError('見た目レビューには実画像を指定してください')
                needed = (checks['baseline_images'] + checks['rest_images'] if category == 'appearance' else
                          [name for sample in checks['samples']
                           if sample['requirement_id'] == entry['requirement_id'] for name in sample['images']])
                expected_evidence = {item['run'] + '/outputs/' + name for name in needed}
                if not expected_evidence or not expected_evidence <= set(evidence):
                    raise WorkflowError('基準と元ポーズの全方向、または該当動作の全サンプル画像が必要です')
            item['reviews'].append(record(category=category, actor=actor, entries=copy.deepcopy(entries),
                                           plan_hash=item['plan_hash'], files_hash=fingerprint(item['files'])))
            item['verification'][category] = ('pass' if all(e['result'] == 'pass' for e in entries) else
                                               'fail' if any(e['result'] == 'fail' for e in entries) else 'uncertain')
        return item

    def recover(self, project_id, experiment_id, process_stopped_evidence):
        """Register complete output after an interruption; never rerun or steal locks."""
        require_text(process_stopped_evidence)
        if (runtime.REPO / 'experiments/runs/.execution.lock').exists():
            raise WorkflowError('実行ロックが残っています。プロセスとロックを調査してから復元してください')
        with self.store.update(project_id, 'rig_experiment_recovered') as doc:
            item = find(lab(doc)['experiments'], experiment_id)
            if item['state'] == 'succeeded':
                self._verified_output(project_id, item)
                return item
            if item['state'] not in ('running', 'result_unknown'):
                raise WorkflowError('実行中または結果不明の記録だけを復元できます')
            _, _, source = self.source(project_id, item['candidate_id'])
            if source != item['source']:
                raise WorkflowError('元モデルが変更されています')
            folder = self.store.path(project_id, item['run'])
            if sha(folder / 'input.blend') != source['sha256']:
                raise WorkflowError('固定入力が変更されています')
            if item['kind'] == 'rig':
                self._verify_plan(project_id, doc, item)
            saved = read(folder / 'job.json')
            if sha(folder / 'job.json') != item.get('job_hash'):
                raise WorkflowError('固定jobのhashが一致しません')
            pending, final = folder / 'outputs.pending', folder / 'outputs'
            if pending.exists() and final.exists():
                raise WorkflowError('出力が二重に存在します。上書きしません')
            output = pending if pending.exists() else final
            checks = read(output / 'checks.json')
            if (saved.get('experiment_id') != item['id'] or checks.get('experiment_id') != item['id'] or
                    checks.get('source_hash') != source['sha256'] or checks.get('success') is not True):
                raise WorkflowError('完成した検査結果を確認できません')
            if item['kind'] == 'rig' and (checks.get('rest_geometry_preserved') is not True or
                                          not (output / 'model.blend').is_file()):
                raise WorkflowError('リグ出力が不完全です')
            if output == pending:
                pending.rename(final)
            item.update(state='succeeded', files=self._files(project_id, final),
                        verification=dict(appearance='not_run', motion='not_run', ue='not_run'),
                        recovered_at=now(), recovery_evidence=process_stopped_evidence)
        return item
