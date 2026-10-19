from __future__ import annotations

import copy
import math
from pathlib import Path
import re
import shutil

from .storage import WorkflowError, find, fingerprint, no_links, read, record, sha, uid, write

ROLES = ('pose', 'silhouette', 'design', 'face', 'color', 'orthographic', 'part', 'style', 'other')
VIEWS = ('front', 'side_left', 'side_right', 'back', 'perspective', 'multiple', 'unknown')
STAGES = ('image_prepare', 'geometry', 'assembly', 'surface')
STARTED_STATES = frozenset(('running', 'succeeded', 'failed', 'result_unknown'))


def started_runs(doc, production_id, stage, part_id=None):
    return sum(plan.get('production_plan_id') == production_id
               and plan.get('fixed', {}).get('stage') == stage
               and plan['state'] in STARTED_STATES
               and (part_id is None or plan.get('part_id') == part_id)
               for plan in doc['plans'])


def image_info(path):
    from PIL import Image
    path = no_links(path)
    with Image.open(path) as image:
        fmt, dimensions = image.format, image.size
        image.verify()
    extensions = {'PNG': '.png', 'JPEG': '.jpg', 'WEBP': '.webp'}
    if fmt not in extensions:
        raise WorkflowError('画像の実形式はPNG/JPEG/WebPが必要です')
    return dict(extension=extensions[fmt], format=fmt, width=dimensions[0], height=dimensions[1])


def obj_info(path):
    vertices = 0
    faces = []
    with no_links(path).open(encoding='utf-8-sig') as stream:
        for line in stream:
            words = line.split()
            if not words or words[0].startswith('#'):
                continue
            if words[0] in ('mtllib', 'usemtl', 'call', 'csh'):
                raise WorkflowError('初期OBJ取り込みは外部材質・外部命令を含まないものに限定します')
            if words[0] == 'v':
                if len(words) < 4 or not all(math.isfinite(float(x)) for x in words[1:]):
                    raise WorkflowError('不正な頂点')
                vertices += 1
            elif words[0] == 'f':
                indices = [int(x.split('/')[0]) for x in words[1:]]
                if len(indices) < 3 or 0 in indices:
                    raise WorkflowError('不正な面')
                faces.append([x if x > 0 else vertices + x + 1 for x in indices])
    if not vertices or not faces or any(x < 1 or x > vertices for face in faces for x in face):
        raise WorkflowError('空のOBJまたは面インデックス不正')
    return {'vertices': vertices, 'faces': len(faces)}


def priority(value):
    if type(value) is not int or not 1 <= value <= 5:
        raise WorkflowError('priorityは1〜5です')
    return value


def require_text(value):
    if not isinstance(value, str) or not value.strip():
        raise WorkflowError('説明・理由は空にできません')
    return value


class Workbench:
    def __init__(self, store, adapter_config=None):
        self.store = store
        self.adapter_config = copy.deepcopy(adapter_config)

    def copy_input(self, project_id, path, folder, filename):
        source = no_links(path)
        if not source.is_file():
            raise WorkflowError('入力は通常ファイルが必要です')
        before = sha(source)
        relative = f'{folder}/{uid()}/{filename}'
        target = self.store.path(project_id, relative)
        target.parent.mkdir(parents=True, exist_ok=False)
        shutil.copyfile(source, target)
        if sha(target) != before:
            raise WorkflowError('コピー中に入力が変化しました')
        return {'file': relative, 'sha256': before}

    def verify_file(self, project_id, item):
        path = self.store.path(project_id, item['file'])
        if not path.is_file() or sha(path) != item['sha256']:
            raise WorkflowError(f'入力・成果物のhash不一致: {path}')
        return path

    def reference_add(self, project_id, path, role, description, rank=3, view='unknown'):
        if role not in ROLES or view not in VIEWS:
            raise WorkflowError('資料のrole／viewが不正です')
        info = image_info(path)
        with self.store.update(project_id, 'reference_added') as doc:
            item = record(role=role, description=require_text(description), priority=priority(rank),
                          view=view, revision=1, history=[], **info,
                          **self.copy_input(project_id, path, 'references', 'image' + info['extension']))
            doc['references'].append(item)
        return item

    def reference_update(self, project_id, item_id, reason, **changes):
        require_text(reason)
        if set(changes) - {'role', 'view', 'description', 'priority'}:
            raise WorkflowError('画像本体・IDは更新できません')
        changes = {key: value for key, value in changes.items() if value is not None}
        with self.store.update(project_id, 'reference_updated') as doc:
            item = find(doc['references'], item_id)
            old = {k: copy.deepcopy(v) for k, v in item.items() if k != 'history'}
            if 'priority' in changes:
                priority(changes['priority'])
            if changes.get('role', item['role']) not in ROLES or changes.get('view', item['view']) not in VIEWS:
                raise WorkflowError('資料のrole／viewが不正です')
            if 'description' in changes:
                require_text(changes['description'])
            item['history'].append(record(reason=reason, before=old))
            item.update(changes, revision=item['revision'] + 1)
        return item

    def requirement_add(self, project_id, category, text, rank=3, part_id=None):
        if category not in ('must_keep', 'must_change', 'improve'):
            raise WorkflowError('要件カテゴリが不正です')
        with self.store.update(project_id, 'requirement_added') as doc:
            if part_id:
                self.part(doc, part_id)
            item = record(category=category, text=require_text(text), priority=priority(rank),
                          part_id=part_id, active=True, revision=1, history=[])
            doc['requirements'].append(item)
        return item

    def requirement_update(self, project_id, item_id, reason, text=None, retire=False):
        require_text(reason)
        with self.store.update(project_id, 'requirement_updated') as doc:
            item = find(doc['requirements'], item_id)
            if not item['active']:
                raise WorkflowError('廃止済み要件は変更できません')
            item['history'].append(record(reason=reason, before={k: copy.deepcopy(v) for k, v in item.items() if k != 'history'}))
            if text is not None:
                item['text'] = require_text(text)
            item.update(active=not retire, revision=item['revision'] + 1)
        return item

    @staticmethod
    def part(doc, part_id):
        for proposal in reversed(doc['part_plans']):
            for part in proposal['parts']:
                if part['id'] == part_id:
                    return part
        raise WorkflowError('案件内に対象部品がありません')

    def part_plan(self, project_id, parts, reason):
        require_text(reason)
        if not isinstance(parts, list) or not parts:
            raise WorkflowError('部品構成は空でない配列が必要です')
        with self.store.update(project_id, 'part_plan_created') as doc:
            normalized, seen = [], set()
            for part in parts:
                part = dict(part)
                if part.get('id'):
                    self.part(doc, part['id'])
                else:
                    part['id'] = uid()
                if part['id'] in seen:
                    raise WorkflowError('部品IDが重複しています')
                seen.add(part['id'])
                part['name'] = require_text(part.get('name'))
                part['description'] = require_text(part.get('description', part['name']))
                normalized.append(part)
            item = record(parts=normalized, reason=reason, state='draft', approval=None)
            item['content_hash'] = fingerprint(normalized)
            doc['part_plans'].append(item)
        return item

    def part_approve(self, project_id, proposal_id, expected_hash, evidence):
        with self.store.update(project_id, 'part_plan_approved') as doc:
            item = find(doc['part_plans'], proposal_id)
            if item['state'] != 'draft' or fingerprint(item['parts']) != expected_hash or item['content_hash'] != expected_hash:
                raise WorkflowError('部品構成の状態・hashが一致しません')
            item.update(state='approved', approval=record(evidence=require_text(evidence)))
        return item

    def candidate_import(self, project_id, path, kind, part_id, description, plan_id=None, method='external'):
        if kind not in ('prepared_image', 'part'):
            raise WorkflowError('取り込みは生成用画像またはOBJ部品が対象です')
        metadata = image_info(path) if kind == 'prepared_image' else obj_info(path)
        extension = metadata.get('extension', '.obj')
        with self.store.update(project_id, 'candidate_imported') as doc:
            self.part(doc, part_id)
            plan = find(doc['plans'], plan_id) if plan_id else None
            if plan and (kind != 'prepared_image' or plan['fixed']['stage'] != 'image_prepare'
                         or plan['fixed']['part_id'] != part_id or plan['state'] != 'approved'
                         or fingerprint(plan['fixed']) != plan['plan_hash']):
                raise WorkflowError('承認済みの対象部品の画像準備計画が必要です')
            if method not in ('crop', 'background_removal', 'image_generation', 'external'):
                raise WorkflowError('画像の準備方法が不正です')
            if plan:
                for ref in plan['fixed']['references']:
                    self.verify_file(project_id, ref)
                if plan['fixed']['source']:
                    for f in plan['fixed']['source']['files']:
                        self.verify_file(project_id, f)
            if plan and plan.get('production_plan_id') and kind == 'prepared_image':
                run_id = plan['fixed']['run_id']
                relative = f'runs/{run_id}/outputs/prepared{extension}'
                target = self.store.path(project_id, relative)
                target.parent.mkdir(parents=True, exist_ok=False)
                before = sha(no_links(path))
                shutil.copyfile(no_links(path), target)
                if sha(target) != before:
                    raise WorkflowError('画像の登録中に入力が変化しました')
                files = [{'file': relative, 'sha256': before}]
            else:
                files = [self.copy_input(project_id, path, 'artifacts', 'model' + extension)]
            item = record(kind=kind, part_id=part_id, description=require_text(description),
                          parent_id=plan['fixed']['source']['id'] if plan and plan['fixed']['source'] else None,
                          generation_id=plan_id, status='pending', shape_confirmed=False,
                          provenance='imported', history=[], metadata=metadata,
                          files=files, production_plan_id=plan.get('production_plan_id') if plan else None,
                          run_id=plan['fixed'].get('run_id') if plan else None)
            if kind == 'prepared_image':
                item.update(preparation_method=method, input_approval=None,
                            external_result=bool(plan), provenance='external_result' if plan else 'imported')
            if plan:
                plan.update(state='succeeded', result_method='external_result_import',
                            candidates=[item['id']], error=None)
            doc['candidates'].append(item)
        return item

    def image_approve(self, project_id, candidate_id, expected_hash, evidence):
        with self.store.update(project_id, 'image_input_approved') as doc:
            image = find(doc['candidates'], candidate_id)
            if image['kind'] != 'prepared_image' or image['status'] == 'rejected':
                raise WorkflowError('却下されていない生成用画像が必要です')
            for item in image['files']:
                self.verify_file(project_id, item)
            if fingerprint(image['files']) != expected_hash:
                raise WorkflowError('確認した画像のhashが一致しません')
            image['input_approval'] = record(content_hash=expected_hash, evidence=require_text(evidence))
            image['history'].append(record(action='approve-input', evidence=evidence))
        return image

    def material_create(self, project_id, part_id, source_id, name, color, roughness, metallic):
        if (len(color) != 3 or any(type(x) not in (float, int) or not math.isfinite(x) or not 0 <= x <= 1
                                  for x in [*color, roughness, metallic])):
            raise WorkflowError('色・粗さ・金属度は0〜1の有限数です')
        with self.store.update(project_id, 'material_created') as doc:
            source = find(doc['candidates'], source_id)
            if source['kind'] != 'part' or source['part_id'] != part_id:
                raise WorkflowError('材質の対象形状と部品が一致しません')
            item = record(part_id=part_id, source_id=source_id, name=require_text(name),
                          color=color, roughness=roughness, metallic=metallic,
                          method='principled_parameters', uv_verified=False, textures=[])
            doc['materials'].append(item)
        return item

    def plan(self, project_id, stage, prompt, reference_ids=(), part_id=None,
             input_id=None, source_id=None, bindings=None, materials=None, edit=None):
        if stage not in STAGES:
            raise WorkflowError('未対応工程です')
        if stage == 'geometry':
            raise WorkflowError('部品造形は承認済み資料パックを使うBlender直接造形計画から作成してください')
        with self.store.update(project_id, 'plan_created') as doc:
            approved = [p for p in doc['part_plans'] if p['state'] == 'approved']
            if not approved:
                raise WorkflowError('先に部品構成を確認・承認してください')
            structure = approved[-1]
            if part_id and part_id not in {p['id'] for p in structure['parts']}:
                raise WorkflowError('承認済み構成に対象部品がありません')
            refs = [copy.deepcopy(find(doc['references'], r)) for r in reference_ids]
            for ref in refs:
                self.verify_file(project_id, ref)
            inputs, composition, material_snapshots = [], [], []
            source = copy.deepcopy(find(doc['candidates'], source_id)) if source_id else None
            if stage == 'assembly':
                if source and not edit:
                    raise WorkflowError('親候補を使うassembly計画は限定編集にしてください')
                if not isinstance(bindings, list) or not bindings:
                    raise WorkflowError('組み立ての部品割当が必要です')
                bound = set()
                for binding in bindings:
                    candidate = copy.deepcopy(find(doc['candidates'], binding['candidate_id']))
                    pid = binding['part_id']
                    if pid in bound or pid not in {p['id'] for p in structure['parts']} or candidate['kind'] != 'part' or candidate['part_id'] != pid:
                        raise WorkflowError('部品割当の重複・種類・所属が不正です')
                    bound.add(pid)
                    transform = {}
                    for key, default in [('location', [0, 0, 0]), ('rotation_degrees', [0, 0, 0]), ('scale', [1, 1, 1])]:
                        values = binding.get(key, default)
                        if len(values) != 3 or any(type(x) not in (float, int) or not math.isfinite(x) or (key == 'scale' and x <= 0) for x in values):
                            raise WorkflowError('部品の変換値が不正です')
                        transform[key] = values
                    composition.append(dict(part_id=pid, candidate_id=candidate['id'], **transform))
                    inputs.append(candidate)
                if bound != {p['id'] for p in structure['parts']}:
                    raise WorkflowError('承認済み構成の全ての部品を割り当ててください')
            elif stage == 'surface':
                if not source or source['kind'] != 'character' or not source['shape_confirmed']:
                    raise WorkflowError('仮組みをレビューして形状を確定した全身候補が必要です')
                composition = copy.deepcopy(source['composition'])
                if not isinstance(materials, dict) or set(materials) != {p['part_id'] for p in composition}:
                    raise WorkflowError('全ての構成部品に材質を割り当ててください')
                for binding in composition:
                    material = copy.deepcopy(find(doc['materials'], materials[binding['part_id']]))
                    if material['part_id'] != binding['part_id'] or material['source_id'] != binding['candidate_id']:
                        raise WorkflowError('材質と対象の形状版が一致しません')
                    material_snapshots.append(material)
                inputs.append(source)
            elif stage == 'image_prepare':
                if not part_id:
                    raise WorkflowError('対象部品が必要です')
                if source and (source['kind'] != 'prepared_image' or source['part_id'] != part_id):
                    raise WorkflowError('画像編集の親は同じ部品の画像候補が必要です')
            if edit:
                if stage != 'assembly' or not source or source['kind'] != 'character':
                    raise WorkflowError('限定編集は全身のassembly計画から実行します')
                if edit.get('part_id') not in {p['part_id'] for p in composition}:
                    raise WorkflowError('編集対象が構成にありません')
                factor = edit.get('scale_factor')
                if type(factor) not in (int, float) or not math.isfinite(factor) or not 0.1 <= factor <= 10:
                    raise WorkflowError('拡大率は0.1〜10です')
                if composition != source['composition']:
                    raise WorkflowError('局所拡大の計画では親候補の構成・配置を維持してください')
                for binding in composition:
                    if binding['part_id'] == edit['part_id']:
                        binding['scale'] = [x * factor for x in binding['scale']]
            for candidate in inputs + ([source] if source else []):
                for item in candidate['files']:
                    self.verify_file(project_id, item)
            fixed = dict(stage=stage, prompt=require_text(prompt), part_id=part_id,
                         references=refs, requirements=copy.deepcopy([r for r in doc['requirements'] if r['active']]),
                         part_plan=copy.deepcopy(structure), inputs=inputs, source=source,
                         composition=composition, materials=material_snapshots, edit=edit,
                         adapter_config=copy.deepcopy(self.adapter_config))
            implementation = list(Path(__file__).parent.glob('*.py'))
            implementation += [Path(__file__).resolve().parents[2] / 'scripts' / 'blender_workbench.py']
            fixed['code'] = [{'path': str(p), 'sha256': sha(p)} for p in sorted(implementation) if p.is_file()]
            item = record(fixed=fixed, plan_hash=fingerprint(fixed), state='draft',
                          approval=None, candidates=[], error=None)
            doc['plans'].append(item)
        return item

    def transition(self, project_id, plan_id, action, expected_hash=None, evidence=None):
        with self.store.update(project_id, 'plan_' + action) as doc:
            item = find(doc['plans'], plan_id)
            if fingerprint(item['fixed']) != item['plan_hash']:
                raise WorkflowError('計画内容のhashが変わっています')
            if action == 'request-approval' and item['state'] == 'draft':
                item['state'] = 'awaiting_approval'
            elif action == 'approve' and item['state'] == 'awaiting_approval':
                if item['plan_hash'] != expected_hash:
                    raise WorkflowError('提示した計画hashと一致しません')
                item.update(state='approved', approval=record(evidence=require_text(evidence)))
            elif action == 'cancel' and item['state'] in ('draft', 'awaiting_approval', 'approved'):
                item.update(state='cancelled', error=require_text(evidence))
            else:
                raise WorkflowError('この状態では操作できません')
        return item

    def candidate_state(self, project_id, candidate_id, action, reason):
        require_text(reason)
        with self.store.update(project_id, 'candidate_' + action) as doc:
            item = find(doc['candidates'], candidate_id)
            if action == 'confirm-shape':
                if item['kind'] != 'character':
                    raise WorkflowError('形状確定は全身候補が対象です')
                if item.get('production_plan_id'):
                    checks_file = next((f for f in item['files'] if f['file'].endswith('/checks.json')), None)
                    if not checks_file or read(self.verify_file(project_id, checks_file)).get('success') is not True:
                        raise WorkflowError('形状確定には仮組みの構造検査成功が必要です')
                item['shape_confirmed'] = True
            else:
                item['status'] = {'select': 'selected', 'hold': 'on_hold', 'reject': 'rejected'}[action]
            item['history'].append(record(action=action, reason=reason))
        return item

    def review(self, project_id, candidate_id, entries, summary, actor='user'):
        with self.store.update(project_id, 'candidate_reviewed') as doc:
            candidate = find(doc['candidates'], candidate_id)
            if actor not in ('user', 'codex'):
                raise WorkflowError('レビューの主体が不正です')
            if not isinstance(entries, list):
                raise WorkflowError('レビューは要件別の配列が必要です')
            for entry in entries:
                find(doc['requirements'], entry['requirement_id'])
                if entry['result'] not in ('pass', 'fail', 'uncertain', 'not_applicable'):
                    raise WorkflowError('レビュー結果が不正です')
                require_text(entry['reason'])
                if actor == 'codex' and candidate.get('production_plan_id'):
                    if not entry.get('directions') or not entry.get('image_files'):
                        raise WorkflowError('Codex自己点検には確認方向と画像ファイルが必要です')
                    if entry['result'] == 'uncertain':
                        require_text(entry.get('impact'))
                    available = {f['file'] for f in candidate['files'] if f['file'].endswith('.png')}
                    if not set(entry['image_files']) <= available:
                        raise WorkflowError('自己点検の画像が候補に含まれていません')
            item = record(candidate_id=candidate['id'], actor=actor,
                          entries=copy.deepcopy(entries), summary=require_text(summary))
            doc['reviews'].append(item)
        return item

    def set_approved(self, project_id, candidate_id, reason):
        with self.store.update(project_id, 'project_approved') as doc:
            candidate = find(doc['candidates'], candidate_id)
            if candidate['kind'] != 'character' or candidate['status'] != 'selected':
                raise WorkflowError('正式採用は選択済み全身候補が対象です')
            if candidate.get('production_plan_id') and candidate.get('stage') != 'surface':
                raise WorkflowError('正式採用は材質適用後の全身候補が対象です')
            required_actor = 'user' if candidate.get('production_plan_id') else None
            reviews = [r for r in doc['reviews'] if r['candidate_id'] == candidate_id and
                       (required_actor is None or r.get('actor') == required_actor)]
            if not reviews:
                raise WorkflowError('正式採用の前にユーザーの最終レビューを保存してください' if required_actor else
                                    '正式採用の前にレビューを保存してください')
            if required_actor:
                production = find(doc['production_plans'], candidate['production_plan_id'])
                required = {item['id'] for item in production['fixed']['requirements']}
                reviewed = {entry['requirement_id'] for entry in reviews[-1]['entries']}
                if not required <= reviewed:
                    raise WorkflowError('正式採用には親計画の全要件に対する最終レビューが必要です')
            require_text(reason)
            doc['approved_candidate_id'] = candidate_id
        return {'approved_candidate_id': candidate_id}

    def export(self, project_id, name, evidence, expected_selection=None):
        require_text(evidence)
        if name is not None:
            if (not name.strip() or name[-1] in ' .' or re.search(r'[<>:"/\\|?*\x00-\x1f\x7f]', name)
                    or re.match(r'^(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)', name, re.I)):
                raise WorkflowError('出力名が不正です。パス・禁止文字・Windows予約名は使用できません')
        with self.store.update(project_id, 'source_exported') as doc:
            candidates = sorted([c for c in doc['candidates'] if c['kind'] == 'character' and c['status'] == 'selected'], key=lambda c: c['id'])
            if expected_selection is not None and fingerprint(candidates) != expected_selection:
                raise WorkflowError('確認後に出力候補が変わりました。一覧から確認し直してください')
            if not candidates:
                return {'count': 0, 'message': '選択済み全身候補は0件です'}
            for candidate in candidates:
                if candidate.get('production_plan_id'):
                    production = find(doc.get('production_plans', []), candidate['production_plan_id'])
                    if production['state'] != 'approved' or fingerprint(production['fixed']) != production['content_hash']:
                        raise WorkflowError('出力元の親計画が有効ではありません')
                    if 'source_export' not in production['fixed']['scope']['stages']:
                        raise WorkflowError('親計画でsource出力が許可されていません')
            export_id = uid()
            temporary = self.store.path(project_id, f'exports/.pending-{export_id}')
            temporary.mkdir(parents=True, exist_ok=False)
            manifest = record(project_id=project_id, profile='source', evidence=evidence,
                              ue_verified=False, rig_verified=False, animation_verified=False,
                              candidates=[])
            for index, candidate in enumerate(candidates, 1):
                base = candidate['id'] if name is None else name + (f'_{index:03}' if len(candidates) > 1 else '')
                if len((base + '.blend').encode('utf-16-le')) // 2 > 255:
                    raise WorkflowError('完成ファイル名が長すぎます')
                folder = temporary / base
                folder.mkdir()
                exported = []
                for file in candidate['files']:
                    source = self.verify_file(project_id, file)
                    target = folder / source.name
                    shutil.copyfile(source, target)
                    if sha(target) != file['sha256']:
                        raise WorkflowError('出力のhashが一致しません')
                    exported.append({'file': f'{base}/{source.name}', 'sha256': file['sha256']})
                if candidate.get('production_plan_id'):
                    dependency_records = []
                    for binding in candidate.get('composition', []):
                        part_candidate = find(doc['candidates'], binding['candidate_id'])
                        for dependency in part_candidate['files']:
                            source = self.verify_file(project_id, dependency)
                            suffix = dependency['file'].split('/outputs/', 1)[-1]
                            target = folder / 'dependencies' / 'parts' / part_candidate['id'] / suffix
                            target.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(source, target)
                            if sha(target) != dependency['sha256']:
                                raise WorkflowError('出力依存ファイルのhashが一致しません')
                            dependency_records.append({'candidate_id': part_candidate['id'],
                                                       'file': target.relative_to(temporary).as_posix(),
                                                       'sha256': dependency['sha256']})
                    if candidate.get('reference_pack_id'):
                        pack = find(doc.get('reference_packs', []), candidate['reference_pack_id'])
                        for dependency in pack['files']:
                            source = self.verify_file(project_id, dependency)
                            target = folder / 'dependencies' / 'reference-pack' / dependency['file']
                            target.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(source, target)
                            if sha(target) != dependency['sha256']:
                                raise WorkflowError('資料パック依存ファイルのhashが一致しません')
                            dependency_records.append({'reference_pack_id': pack['id'],
                                                       'file': target.relative_to(temporary).as_posix(),
                                                       'sha256': dependency['sha256']})
                    for material_snapshot in candidate.get('materials', []):
                        material = find(doc['materials'], material_snapshot['id'])
                        for dependency in material.get('files', []):
                            source = self.verify_file(project_id, dependency)
                            target = folder / 'dependencies' / 'materials' / material['id'] / source.name
                            target.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(source, target)
                            if sha(target) != dependency['sha256']:
                                raise WorkflowError('材質定義の出力hashが一致しません')
                            dependency_records.append({'material_id': material['id'],
                                                       'file': target.relative_to(temporary).as_posix(),
                                                       'sha256': dependency['sha256']})
                    lineage = {'candidate_id': candidate['id'],
                               'production_plan_id': candidate['production_plan_id'],
                               'reference_pack_id': candidate.get('reference_pack_id'),
                               'part_candidate_ids': [b['candidate_id'] for b in candidate.get('composition', [])],
                               'materials': candidate.get('materials', []),
                               'reviews': [r for r in doc['reviews'] if r['candidate_id'] == candidate['id']],
                               'dependencies': dependency_records,
                               'ue_verified': False, 'rig_verified': False, 'animation_verified': False}
                    write(folder / 'lineage.json', lineage)
                    exported.append({'file': f'{base}/lineage.json', 'sha256': sha(folder / 'lineage.json')})
                    exported.extend({'file': entry['file'], 'sha256': entry['sha256']}
                                    for entry in dependency_records)
                write(folder / 'composition.json', candidate)
                exported.append({'file': f'{base}/composition.json', 'sha256': sha(folder / 'composition.json')})
                manifest['candidates'].append({'candidate_id': candidate['id'], 'name': base, 'files': exported})
            write(temporary / 'manifest.json', manifest)
            final = self.store.path(project_id, f'exports/{export_id}')
            temporary.rename(final)
            summary = record(export_id=export_id, count=len(candidates), file=f'exports/{export_id}/manifest.json')
            doc['exports'].append(summary)
        return summary

    def status(self, project_id):
        doc = self.store.load(project_id)
        running = [p for p in doc['plans'] if p['state'] in ('running', 'result_unknown')]
        characters = [c for c in doc['candidates'] if c['kind'] == 'character']
        selected = [c for c in characters if c['status'] == 'selected']
        approvals = [p for p in doc['plans'] if p['state'] == 'awaiting_approval']
        ready = [p for p in doc['plans'] if p['state'] == 'approved']
        if doc['state'] == 'archived':
            next_step = 'アーカイブ済み。読み取りと履歴確認のみ利用できます。'
        elif running:
            next_step = '実行中／結果不明の計画を確認してください。重複実行しないでください。'
        elif approvals:
            next_step = '提示した生成・編集計画を確認し、対象の計画を明示承認してください。'
        elif ready:
            next_step = '承認済み計画を確認し、未実行の計画を実行できます。'
        elif not doc['references']:
            next_step = '資料をインポートし、役割・方向・優先度を確認してください。'
        elif not doc['requirements']:
            next_step = '維持・変更・改善条件を要件として整理してください。'
        elif not any(p['state'] == 'approved' for p in doc['part_plans']):
            next_step = '部品構成案を確認し、承認してください。'
        elif not characters:
            next_step = '部品候補を用意し、全身の仮組み計画を作成してください。'
        elif selected:
            next_step = '選択済みの全身候補を名前付きで出力できます。必要ならレビュー後に正式採用を記録してください。'
        elif not any(c['shape_confirmed'] for c in characters):
            next_step = '全身の形状・接続を確認して形状を確定してください。'
        elif not any(c.get('stage') == 'surface' for c in characters):
            next_step = '材質を作成・適用し、全身をレビュー・選択して出力してください。'
        else:
            next_step = '材質適用後の全身を比較・レビューし、出力する候補を選択してください。'
        return {'id': doc['id'], 'name': doc['name'], 'state': doc['state'],
                'counts': {key: len(doc[key]) for key in ('references', 'requirements', 'part_plans', 'plans', 'candidates', 'materials')},
                'approved_candidate_id': doc['approved_candidate_id'], 'next': next_step,
                'attention': [{'id': p['id'], 'state': p['state'], 'error': p.get('error')}
                              for p in doc['plans'] if p['state'] in ('blocked', 'failed', 'result_unknown')],
                'limitations': ['画像描き起こし・UV・ベイク・リグ・UE検証は未実装', '一覧は端末全文／JSON表示。VS Code表示は未実装']}
