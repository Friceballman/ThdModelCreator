"""Version 2 production scope, reference packs, and Blender authoring plans."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import shutil
import math
import subprocess

from .storage import WorkflowError, find, fingerprint, no_links, read, record, sha, uid, write
from .workflow import Workbench, image_info, require_text

REPO = Path(__file__).resolve().parents[2]

STAGES = {'image_prepare', 'geometry', 'assembly', 'surface', 'inspect', 'source_export'}
ENGINES = {'blender_authoring', 'supplied_asset', 'triposr_legacy'}
METHODS = {'original', 'crop', 'background_removal', 'image_generation', 'drawing', 'external'}


def _positive(value, label):
    if type(value) is not int or value < 1:
        raise WorkflowError(f'{label}は正整数が必要です')
    return value


def _file(store, project_id, entry):
    path = store.path(project_id, entry['file'])
    if not path.is_file() or sha(path) != entry['sha256']:
        raise WorkflowError(f'資料ファイルのhashが一致しません: {entry["file"]}')
    return path


class V2Workbench(Workbench):
    def material_recipe_create(self, project_id, source_id, recipe):
        if not isinstance(recipe, dict):
            raise WorkflowError('材質レシピはJSONオブジェクトが必要です')
        shader = recipe.get('shader')
        if not isinstance(shader, dict):
            raise WorkflowError('shaderが必要です')
        color = shader.get('base_color')
        values = [*(color if isinstance(color, list) else []), shader.get('roughness'), shader.get('metallic')]
        if len(values) != 5 or any(type(x) not in (float, int) or not math.isfinite(x) or not 0 <= x <= 1 for x in values):
            raise WorkflowError('base_color、roughness、metallicは0〜1の有限数です')
        def validate_pattern(item):
            pattern = item.get('pattern')
            if pattern is None:
                return
            if not isinstance(pattern, dict) or pattern.get('type') != 'noise':
                raise WorkflowError('現在のプロシージャル模様はnoiseのみ対応します')
            scale = pattern.get('scale')
            strength = pattern.get('bump_strength', 0)
            if (type(scale) not in (int, float) or not math.isfinite(scale) or scale <= 0 or
                    type(strength) not in (int, float) or not math.isfinite(strength) or not 0 <= strength <= 1):
                raise WorkflowError('noise模様のscaleまたはbump_strengthが不正です')
            second = pattern.get('secondary_color')
            if second is not None and (not isinstance(second, list) or len(second) != 3 or
                    any(type(x) not in (int, float) or not math.isfinite(x) or not 0 <= x <= 1 for x in second)):
                raise WorkflowError('noise模様のsecondary_colorが不正です')
        validate_pattern(shader)
        for key in ('intent', 'reference_regions', 'zones', 'uncertainties'):
            if key not in recipe:
                raise WorkflowError(f'材質レシピに{key}が必要です')
        if not isinstance(recipe['reference_regions'], list) or not isinstance(recipe['zones'], list) or not isinstance(recipe['uncertainties'], list):
            raise WorkflowError('材質領域と不確実性は配列が必要です')
        for zone in recipe['zones']:
            if not isinstance(zone, dict) or not isinstance(zone.get('name'), str) or not zone['name']:
                raise WorkflowError('材質領域には名前が必要です')
            if not isinstance(zone.get('object_role'), str) or not zone['object_role']:
                raise WorkflowError('現在の領域割当条件はobject_roleの完全一致です')
            if 'shader' in zone:
                local = zone['shader']
                numbers = [*(local.get('base_color', []) if isinstance(local.get('base_color'), list) else []),
                           local.get('roughness'), local.get('metallic')]
                if len(numbers) != 5 or any(type(x) not in (float, int) or not math.isfinite(x) or not 0 <= x <= 1 for x in numbers):
                    raise WorkflowError('領域shaderの値が不正です')
                validate_pattern(local)
        with self.store.update(project_id, 'material_recipe_created') as doc:
            source = find(doc['candidates'], source_id)
            if source['kind'] != 'part' or source['status'] == 'rejected':
                raise WorkflowError('材質の対象は有効な部品形状候補です')
            item = record(project_id=project_id, part_id=source['part_id'], source_id=source_id,
                          source_shape_candidate_id=source_id, name=require_text(recipe.get('name')),
                          intent=require_text(recipe['intent']), reference_regions=copy.deepcopy(recipe['reference_regions']),
                          shader=copy.deepcopy(shader), zones=copy.deepcopy(recipe['zones']),
                          uncertainties=copy.deepcopy(recipe['uncertainties']),
                          provenance='recipe', color=color, roughness=shader['roughness'],
                          metallic=shader['metallic'], method='principled_parameters',
                          uv_verified=False, textures=[])
            doc['materials'].append(item)
        return item

    def candidate_trace(self, project_id, candidate_id):
        doc = self.store.load(project_id)
        candidate = find(doc['candidates'], candidate_id)
        plan_id = candidate.get('generation_id')
        plan = find(doc['plans'], plan_id) if plan_id else None
        production_id = candidate.get('production_plan_id') or (plan or {}).get('production_plan_id')
        pack_id = candidate.get('reference_pack_id') or (plan or {}).get('reference_pack_id')
        return {'candidate': candidate, 'plan': plan,
                'production_plan': find(doc.get('production_plans', []), production_id) if production_id else None,
                'reference_pack': find(doc.get('reference_packs', []), pack_id) if pack_id else None,
                'parent_candidate': find(doc['candidates'], candidate['parent_id']) if candidate.get('parent_id') else None,
                'parts': [{'binding': b, 'candidate': find(doc['candidates'], b['candidate_id'])}
                          for b in candidate.get('composition', [])],
                'materials': [find(doc['materials'], m['id']) for m in candidate.get('materials', [])],
                'reviews': [r for r in doc['reviews'] if r['candidate_id'] == candidate_id],
                'exports': [e for e in doc['exports'] if any(c.get('candidate_id') == candidate_id
                            for c in (read(self.store.path(project_id, e['file'])).get('candidates', [])))],
                'run': candidate.get('run_id'),
                'inspection_run_ids': candidate.get('inspection_run_ids', [])}

    def revision_run(self, project_id, source_id, production_id, edit=None, incoming=None):
        """Inspect a candidate or import a single declared .blend revision."""
        from .runtime import process
        mode = 'manual_import' if edit is not None else 'inspect'
        if edit is not None:
            if not isinstance(edit, dict) or not isinstance(edit.get('target_part_ids'), list):
                raise WorkflowError('手修正manifestにtarget_part_idsが必要です')
            require_text(edit.get('changed_by'))
            require_text(edit.get('reason'))
            if edit.get('mode') not in ('part_shape', 'part_transform', 'material_parameters'):
                raise WorkflowError('手修正の種類が不正です')
            external = no_links(incoming)
            if not external.is_file() or external.suffix.lower() != '.blend':
                raise WorkflowError('手修正入力は既存の.blendファイルが必要です')
        else:
            external = None
        failure = None
        outcome = None
        with self.store.update(project_id, 'candidate_' + mode) as doc:
            production = self.verify_production(doc, production_id)
            source = find(doc['candidates'], source_id)
            if source.get('production_plan_id') != production_id or source['kind'] not in ('part', 'character'):
                raise WorkflowError('対象候補は同じ親計画の部品または全身が必要です')
            if source['status'] == 'rejected':
                raise WorkflowError('却下済み候補は編集・点検できません')
            blend_entry = next((f for f in source['files'] if f['file'].endswith('.blend')), None)
            if not blend_entry:
                raise WorkflowError('対象候補に編集可能な.blendがありません')
            original = self.verify_file(project_id, blend_entry)
            if edit is None:
                stage = 'inspect'
                if stage not in production['fixed']['scope']['stages']:
                    raise WorkflowError('親計画でinspectが許可されていません')
            else:
                stage = {'part_shape': 'geometry', 'part_transform': 'assembly',
                         'material_parameters': 'surface'}[edit['mode']]
                if stage not in production['fixed']['scope']['stages'] or edit['mode'] not in production['fixed']['scope'].get('allowed_edits', []):
                    raise WorkflowError('手修正が親計画の範囲外です')
                expected_parts = {source['part_id']} if source['kind'] == 'part' else {b['part_id'] for b in source['composition']}
                if not edit['target_part_ids'] or not set(edit['target_part_ids']) <= expected_parts:
                    raise WorkflowError('変更対象部品が候補構成にありません')
                if source['kind'] == 'part' and edit['mode'] != 'part_shape':
                    raise WorkflowError('部品単体の手修正は形状変更として登録します')
                if source['kind'] == 'character' and edit['mode'] == 'part_shape':
                    raise WorkflowError('全身.blendの形状変更は部品候補で取り込んでください')
                scope = production['fixed']['scope']
                limit = (scope['max_geometry_runs_per_part'] if stage == 'geometry' else
                         scope['max_assembly_runs'] if stage == 'assembly' else scope['max_surface_runs'])
                consumed = sum(p.get('production_plan_id') == production_id and
                               p['fixed']['stage'] == stage and p['state'] != 'cancelled' and
                               (stage != 'geometry' or p.get('part_id') in edit['target_part_ids'])
                               for p in doc['plans'])
                if consumed >= limit:
                    raise WorkflowError('手修正の試行上限に達しています')
            run_id = uid()
            folder = self.store.path(project_id, f'runs/{run_id}')
            folder.mkdir(parents=True, exist_ok=False)
            fixed = {'stage': stage, 'engine': 'manual_blend' if edit else 'blender_inspect',
                     'project_id': project_id, 'production_plan_id': production_id,
                     'production_hash': production['content_hash'], 'source_id': source_id,
                     'source_blend': blend_entry, 'run_id': run_id, 'edit': copy.deepcopy(edit),
                     'adapter_config': copy.deepcopy(self.adapter_config),
                     'adapter_hash': sha(REPO / 'scripts' / 'blender_revision.py')}
            if external:
                input_file = folder / 'input.blend'
                shutil.copyfile(external, input_file)
                fixed['input_blend'] = {'file': f'runs/{run_id}/input.blend', 'sha256': sha(input_file)}
                if sha(external) != fixed['input_blend']['sha256']:
                    raise WorkflowError('手修正ファイルがコピー中に変わりました')
                write(folder / 'manual-edit.json', edit)
            plan = record(project_id=project_id, production_plan_id=production_id,
                          part_id=source.get('part_id'), fixed=fixed, plan_hash=fingerprint(fixed),
                          state='approved', approval=record(kind='parent_scope',
                                                             production_plan_id=production_id,
                                                             production_hash=production['content_hash']),
                          candidates=[], error=None, run=f'runs/{run_id}')
            doc['plans'].append(plan)
            write(folder / 'plan.json', plan)
            lock = REPO / 'experiments/runs/.execution.lock'
            lock.parent.mkdir(parents=True, exist_ok=True)
            no_links(lock)
            try:
                with lock.open('x', encoding='utf-8') as stream:
                    json.dump({'pid': os.getpid(), 'project_id': project_id, 'plan_id': plan['id']}, stream)
            except FileExistsError as exc:
                raise WorkflowError('他の外部処理または残存ロックがあります') from exc
            try:
                plan['state'] = 'running'
                self.store.save(doc)
                pending = folder / 'outputs.pending'
                material_ids = ({part_id: uid() for part_id in edit['target_part_ids']}
                                if edit and edit['mode'] == 'material_parameters' else {})
                job = {'mode': mode, 'source': str(original), 'output': str(pending),
                       'edit': edit, 'incoming': str(folder / 'input.blend') if external else None,
                       'material_ids': material_ids,
                       'composition': source.get('composition', [])}
                command = [self.adapter_config['blender'], '--background', '--factory-startup',
                           '--disable-autoexec', '--python-exit-code', '1', '--python',
                           str(REPO / 'scripts' / 'blender_revision.py'), '--', str(folder / 'job.json')]
                job['command'] = command
                write(folder / 'job.json', job)
                metrics = process(command, folder / 'blender.log',
                                  dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8'), REPO)
                checks = read(pending / 'checks.json')
                if checks.get('success') is not True or checks.get('mode') != mode:
                    raise WorkflowError('Blenderによる差分検査が不合格です')
                required = ['model.blend', 'model.obj', 'checks.json', 'previews/front.png',
                            'previews/side.png', 'previews/back.png', 'previews/oblique.png']
                for name in required:
                    path = pending / name
                    if not path.is_file() or not path.stat().st_size:
                        raise WorkflowError(f'点検成果物がありません: {name}')
                    if name.endswith('.png'):
                        image_info(path)
                pending.rename(folder / 'outputs')
                files = [{'file': f'runs/{run_id}/outputs/{name}',
                          'sha256': sha(folder / 'outputs' / name)} for name in required]
                if edit:
                    composition = copy.deepcopy(source.get('composition', []))
                    for binding in composition:
                        binding.update(checks.get('composition_updates', {}).get(binding['part_id'], {}))
                    material_snapshots = copy.deepcopy(source.get('materials', []))
                    if material_ids:
                        material_snapshots = [m for m in material_snapshots if m['part_id'] not in material_ids]
                        bindings = {b['part_id']: b['candidate_id'] for b in source['composition']}
                        for part_id, material_id in material_ids.items():
                            objects = checks['after'][part_id]['objects']
                            by_role = {}
                            for obj in objects:
                                values = obj['materials']
                                if len(values) != 1 or values[0]['id'] != material_id:
                                    raise WorkflowError('手修正材質の割当が不明です')
                                shader = {'base_color': values[0]['base_color'][:3],
                                          'roughness': values[0]['roughness'],
                                          'metallic': values[0]['metallic']}
                                if values[0].get('pattern'):
                                    shader['pattern'] = json.loads(values[0]['pattern'])
                                if obj['role'] in by_role and by_role[obj['role']] != shader:
                                    raise WorkflowError('同じ役割の材質が一致しません')
                                by_role[obj['role']] = shader
                            base_role = 'geometry' if 'geometry' in by_role else next(iter(by_role))
                            base = by_role[base_role]
                            zones = [{'name': role, 'object_role': role, 'shader': shader}
                                     for role, shader in by_role.items() if role != base_role and shader != base]
                            material = record(project_id=project_id, part_id=part_id,
                                              source_id=bindings[part_id],
                                              source_shape_candidate_id=bindings[part_id],
                                              name='手修正材質_' + part_id[:8], intent=edit['reason'],
                                              reference_regions=copy.deepcopy(edit.get('reference_regions', [])),
                                              shader=base, zones=zones,
                                              uncertainties=copy.deepcopy(edit.get('uncertainties', [])),
                                              provenance='manual_blend', color=base['base_color'],
                                              roughness=base['roughness'], metallic=base['metallic'],
                                              method='manual_blend', uv_verified=False, textures=[])
                            material['id'] = material_id
                            doc['materials'].append(material)
                            material_snapshots.append(copy.deepcopy(material))
                    candidate = record(project_id=project_id, kind=source['kind'], part_id=source.get('part_id'),
                                       description=edit['reason'], parent_id=source_id,
                                       generation_id=plan['id'], stage=stage, provenance='manual_blend',
                                       status='pending', history=[], files=files,
                                       composition=composition,
                                       materials=material_snapshots,
                                       shape_confirmed=False if stage != 'surface' else source.get('shape_confirmed', False),
                                       ue_verified=False, production_plan_id=production_id,
                                       reference_pack_id=source.get('reference_pack_id'), run_id=run_id,
                                       checks=checks)
                    doc['candidates'].append(candidate)
                    plan['candidates'] = [candidate['id']]
                    outcome = candidate
                else:
                    source.setdefault('inspection_run_ids', []).append(run_id)
                    outcome = {'candidate_id': source_id, 'inspection_run_id': run_id, 'files': files,
                               'checks': checks}
                plan.update(state='succeeded', metrics=metrics)
            except BaseException as exc:
                plan.update(state='result_unknown' if isinstance(exc, (KeyboardInterrupt, subprocess.TimeoutExpired)) else 'failed',
                            error=str(exc))
                failure = exc
            finally:
                lock.unlink()
        if failure:
            raise failure
        return outcome

    def plan(self, project_id, stage, prompt, reference_ids=(), part_id=None,
             input_id=None, source_id=None, bindings=None, materials=None, edit=None,
             production_id=None):
        if not production_id:
            return super().plan(project_id, stage, prompt, reference_ids, part_id,
                                input_id, source_id, bindings, materials, edit)
        if stage not in ('image_prepare', 'assembly', 'surface'):
            raise WorkflowError('この工程の親計画継承経路は未対応です')
        doc = self.store.load(project_id)
        production = self.verify_production(doc, production_id)
        approved_structures = [p for p in doc['part_plans'] if p['state'] == 'approved']
        if not approved_structures or approved_structures[-1]['id'] != production['fixed']['part_plan_id']:
            raise WorkflowError('現在の承認済み部品構成が親計画の固定版と異なります')
        if stage not in production['fixed']['scope']['stages']:
            raise WorkflowError('親計画で工程が許可されていません')
        scope = production['fixed']['scope']
        limit = (scope['max_reference_drafts_per_part'] if stage == 'image_prepare' else
                 scope['max_assembly_runs'] if stage == 'assembly' else scope['max_surface_runs'])
        if sum(p.get('production_plan_id') == production_id and p['fixed']['stage'] == stage
               and p['state'] != 'cancelled' and
               (stage != 'image_prepare' or p.get('part_id') == part_id)
               for p in doc['plans']) >= limit:
            raise WorkflowError('工程の試行上限に達しています')
        pack_id = None
        if stage == 'image_prepare':
            if part_id not in scope['part_ids']:
                raise WorkflowError('画像準備対象が親計画の部品ではありません')
            if not reference_ids or not set(reference_ids) <= {r['id'] for r in production['fixed']['references']}:
                raise WorkflowError('画像準備の資料が親計画の範囲外です')
        if stage == 'assembly':
            pack_ids = set()
            for binding in bindings or []:
                candidate = find(doc['candidates'], binding['candidate_id'])
                if candidate.get('production_plan_id') != production_id or candidate['status'] == 'rejected':
                    raise WorkflowError('仮組みには同じ親計画の有効な部品候補が必要です')
                pack_ids.add(candidate.get('reference_pack_id'))
            if len(pack_ids) != 1 or None in pack_ids:
                raise WorkflowError('仮組み部品の承認済み資料パックが一致しません')
            pack_id = next(iter(pack_ids))
            self.verify_pack(doc, pack_id)
        if stage == 'surface':
            source = find(doc['candidates'], source_id)
            if source.get('production_plan_id') != production_id:
                raise WorkflowError('材質適用には同じ親計画の全身候補が必要です')
            pack_id = source.get('reference_pack_id')
            if not pack_id:
                raise WorkflowError('全身候補に資料パックIDがありません')
            self.verify_pack(doc, pack_id)
        item = super().plan(project_id, stage, prompt, reference_ids, part_id,
                            input_id, source_id, bindings, materials, edit)
        with self.store.update(project_id, 'plan_parent_scope_inherited') as doc:
            plan = find(doc['plans'], item['id'])
            production = self.verify_production(doc, production_id)
            run_id = uid()
            folder = self.store.path(project_id, f'runs/{run_id}')
            folder.mkdir(parents=True, exist_ok=False)
            plan['fixed']['production_plan_id'] = production_id
            plan['fixed']['production_hash'] = production['content_hash']
            if pack_id:
                plan['fixed']['reference_pack_id'] = pack_id
                plan['fixed']['reference_pack_hash'] = self.verify_pack(doc, pack_id)['content_hash']
            plan['fixed']['run_id'] = run_id
            plan['plan_hash'] = fingerprint(plan['fixed'])
            plan.update(production_plan_id=production_id, part_id=part_id, run=f'runs/{run_id}', state='approved',
                        reference_pack_id=pack_id,
                        approval=record(kind='parent_scope', production_plan_id=production_id,
                                        production_hash=production['content_hash'],
                                        reference_pack_id=pack_id,
                                        reference_pack_hash=plan['fixed'].get('reference_pack_hash')))
            write(folder / 'plan.json', plan)
            item = copy.deepcopy(plan)
        return item

    def production_plan(self, project_id, manifest):
        if not isinstance(manifest, dict):
            raise WorkflowError('親計画はJSONオブジェクトが必要です')
        with self.store.update(project_id, 'production_plan_created') as doc:
            structure = find(doc['part_plans'], manifest['part_plan_id'])
            if structure['state'] not in ('draft', 'approved') or fingerprint(structure['parts']) != structure['content_hash']:
                raise WorkflowError('部品構成案が変更済みか使用できない状態です')
            refs = [copy.deepcopy(find(doc['references'], rid)) for rid in manifest['reference_ids']]
            reqs = [copy.deepcopy(find(doc['requirements'], rid)) for rid in manifest['requirement_ids']]
            if not refs or not reqs or len({r['id'] for r in refs}) != len(refs) or len({r['id'] for r in reqs}) != len(reqs):
                raise WorkflowError('資料と要件は重複のない空でない集合が必要です')
            for ref in refs:
                self.verify_file(project_id, ref)
            if any(not r['active'] for r in reqs):
                raise WorkflowError('廃止済み要件は親計画に含められません')
            scope = copy.deepcopy(manifest['scope'])
            part_ids = {p['id'] for p in structure['parts']}
            if not scope.get('part_ids') or set(scope['part_ids']) != part_ids or len(scope['part_ids']) != len(part_ids):
                raise WorkflowError('親計画は承認対象の全ての部品を一度ずつ含めます')
            if not set(scope.get('stages', ())) <= STAGES or not {'geometry', 'assembly', 'surface'} <= set(scope['stages']):
                raise WorkflowError('工程が不正または必須工程が不足しています')
            if not set(scope.get('geometry_engines', ())) <= ENGINES or not scope['geometry_engines']:
                raise WorkflowError('造形方式が不正です')
            for key in ('max_reference_drafts_per_part', 'max_geometry_runs_per_part',
                        'max_assembly_runs', 'max_surface_runs'):
                _positive(scope.get(key), key)
            limits = scope.get('face_limits', {})
            if set(limits) != part_ids:
                raise WorkflowError('全部品の面数目標・上限を指定してください')
            for limit in limits.values():
                target = _positive(limit.get('target_faces'), 'target_faces')
                maximum = _positive(limit.get('max_faces'), 'max_faces')
                if target > maximum:
                    raise WorkflowError('target_facesはmax_faces以下が必要です')
            if not isinstance(scope.get('must_preserve', []), list) or not set(scope.get('must_preserve', [])) <= {r['id'] for r in reqs}:
                raise WorkflowError('保持条件の要件IDが親計画に含まれていません')
            fixed = {'project_id': project_id, 'part_plan_id': structure['id'],
                     'part_plan_hash': structure['content_hash'], 'references': refs,
                     'requirements': reqs, 'scope': scope,
                     'deliverables': copy.deepcopy(manifest['deliverables']),
                     'reason': require_text(manifest['reason'])}
            item = record(project_id=project_id, fixed=fixed, content_hash=fingerprint(fixed),
                          state='draft', approval=None)
            doc.setdefault('production_plans', []).append(item)
        return item

    def production_transition(self, project_id, plan_id, action, evidence=None):
        with self.store.update(project_id, 'production_' + action) as doc:
            plan = find(doc.get('production_plans', []), plan_id)
            if fingerprint(plan['fixed']) != plan['content_hash']:
                raise WorkflowError('親計画の固定内容が変更されています')
            if action == 'request-approval' and plan['state'] == 'draft':
                plan['state'] = 'awaiting_approval'
            elif action == 'approve' and plan['state'] == 'awaiting_approval':
                structure = find(doc['part_plans'], plan['fixed']['part_plan_id'])
                if fingerprint(structure['parts']) != plan['fixed']['part_plan_hash']:
                    raise WorkflowError('部品構成案が変更されています')
                for ref in plan['fixed']['references']:
                    self.verify_file(project_id, ref)
                if structure['state'] == 'draft':
                    structure.update(state='approved', approval=record(evidence=require_text(evidence),
                                                                        production_plan_id=plan_id))
                elif structure['state'] != 'approved':
                    raise WorkflowError('部品構成案の状態が不正です')
                plan.update(state='approved', approval=record(evidence=require_text(evidence),
                                                             content_hash=plan['content_hash']))
            elif action == 'cancel' and plan['state'] in ('draft', 'awaiting_approval', 'approved'):
                if any(p.get('production_plan_id') == plan_id and p['state'] in ('running', 'result_unknown') for p in doc['plans']):
                    raise WorkflowError('実行中・結果不明の子計画があります')
                plan.update(state='cancelled', cancellation=record(reason=require_text(evidence)))
            else:
                raise WorkflowError('この状態では操作できません')
        return plan

    def verify_production(self, doc, production_id):
        plan = find(doc.get('production_plans', []), production_id)
        if plan['state'] != 'approved' or fingerprint(plan['fixed']) != plan['content_hash']:
            raise WorkflowError('承認済み・内容固定済みの親計画が必要です')
        fixed = plan['fixed']
        structure = find(doc['part_plans'], fixed['part_plan_id'])
        if structure['state'] != 'approved' or structure['content_hash'] != fixed['part_plan_hash'] or fingerprint(structure['parts']) != fixed['part_plan_hash']:
            raise WorkflowError('部品構成案の版が一致しません')
        for ref in fixed['references']:
            self.verify_file(doc['id'], ref)
        return plan

    def reference_pack_create(self, project_id, production_id, manifest):
        if not isinstance(manifest, dict) or not isinstance(manifest.get('parts'), list):
            raise WorkflowError('資料パックにparts配列が必要です')
        with self.store.update(project_id, 'reference_pack_created') as doc:
            production = self.verify_production(doc, production_id)
            part_ids = set(production['fixed']['scope']['part_ids'])
            ref_ids = {r['id'] for r in production['fixed']['references']}
            if len(manifest['parts']) != len(part_ids) or {p.get('part_id') for p in manifest['parts']} != part_ids:
                raise WorkflowError('資料パックには親計画の全部品が必要です')
            pack_id = uid()
            normalized, files = [], []
            for part in manifest['parts']:
                part = copy.deepcopy(part)
                part_id = part['part_id']
                if not part.get('source_reference_ids') or not set(part['source_reference_ids']) <= ref_ids:
                    raise WorkflowError('部品の元資料IDが親計画と一致しません')
                for key in ('dimensions', 'anchors', 'color_zones', 'consistency', 'uncertainties'):
                    if key not in part:
                        raise WorkflowError(f'資料パックの{key}がありません')
                images = part.get('images', [])
                if not images and not part.get('construction'):
                    raise WorkflowError('方向別画像または寸法付き構築図が必要です')
                for image in images:
                    if image.get('method') not in METHODS or 'inferred' not in image or 'uncertainties' not in image:
                        raise WorkflowError('画像の方法・推定・不確実性が必要です')
                    if image.get('source_reference_id') not in part['source_reference_ids']:
                        raise WorkflowError('画像の由来資料が不正です')
                    supplied = no_links(image['file']) if Path(image['file']).is_absolute() else self.store.path(project_id, image['file'])
                    image_info(supplied)
                    digest = sha(supplied)
                    if image.get('sha256') and image['sha256'] != digest:
                        raise WorkflowError('画像の申告hashと実体が異なります')
                    if supplied.is_relative_to(self.store.directory(project_id)):
                        relative = supplied.relative_to(self.store.directory(project_id)).as_posix()
                    else:
                        relative = f'reference-packs/{pack_id}/parts/{part_id}/{uid()}{image_info(supplied)["extension"]}'
                        dest = self.store.path(project_id, relative)
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(supplied, dest)
                        if sha(dest) != digest:
                            raise WorkflowError('画像コピー中に入力が変化しました')
                    image.update(file=relative, sha256=digest)
                    files.append({'file': relative, 'sha256': digest})
                normalized.append(part)
            parent_id = manifest.get('parent_pack_id')
            if parent_id:
                parent = find(doc.get('reference_packs', []), parent_id)
                if parent['production_plan_id'] != production_id:
                    raise WorkflowError('親資料パックの制作計画が異なります')
            fixed = {'production_plan_id': production_id, 'production_hash': production['content_hash'],
                     'part_plan_id': production['fixed']['part_plan_id'],
                     'parent_pack_id': parent_id, 'parts': normalized, 'files': files}
            item = record(project_id=project_id, **fixed, content_hash=fingerprint(fixed),
                          state='draft', approval=None)
            item['id'] = pack_id
            doc.setdefault('reference_packs', []).append(item)
            write(self.store.path(project_id, f'reference-packs/{pack_id}/manifest.json'), item)
        return item

    def verify_pack(self, doc, pack_id):
        pack = find(doc.get('reference_packs', []), pack_id)
        fixed = {key: pack[key] for key in ('production_plan_id', 'production_hash', 'part_plan_id',
                                             'parent_pack_id', 'parts', 'files')}
        if pack['state'] != 'approved' or fingerprint(fixed) != pack['content_hash']:
            raise WorkflowError('承認済み・固定済みの資料パックが必要です')
        production = self.verify_production(doc, pack['production_plan_id'])
        if production['content_hash'] != pack['production_hash']:
            raise WorkflowError('資料パックの親計画hashが不一致です')
        for entry in pack['files']:
            _file(self.store, doc['id'], entry)
        manifest = read(self.store.path(doc['id'], f'reference-packs/{pack_id}/manifest.json'))
        if manifest.get('id') != pack_id or manifest.get('state') != 'approved' or any(
                manifest.get(key) != pack.get(key) for key in ('content_hash', 'parts', 'files', 'approval')):
            raise WorkflowError('承認済み資料パックのmanifestが一致しません')
        return pack

    def reference_pack_transition(self, project_id, pack_id, action, evidence=None):
        with self.store.update(project_id, 'reference_pack_' + action) as doc:
            pack = find(doc.get('reference_packs', []), pack_id)
            fixed = {key: pack[key] for key in ('production_plan_id', 'production_hash', 'part_plan_id',
                                                 'parent_pack_id', 'parts', 'files')}
            if fingerprint(fixed) != pack['content_hash']:
                raise WorkflowError('資料パックが変更されています')
            for entry in pack['files']:
                _file(self.store, project_id, entry)
            if action == 'request-approval' and pack['state'] == 'draft':
                pack['state'] = 'awaiting_approval'
            elif action == 'approve' and pack['state'] == 'awaiting_approval':
                production = self.verify_production(doc, pack['production_plan_id'])
                if production['content_hash'] != pack['production_hash']:
                    raise WorkflowError('親計画が変更されています')
                pack.update(state='approved', approval=record(evidence=require_text(evidence),
                                                              content_hash=pack['content_hash']))
                write(self.store.path(project_id, f'reference-packs/{pack_id}/manifest.json'), pack)
            else:
                raise WorkflowError('この状態では操作できません')
        return pack

    def geometry_plan(self, project_id, production_id, pack_id, part_id, recipe):
        if not isinstance(recipe, dict) or not recipe.get('script') or not recipe.get('intent'):
            raise WorkflowError('造形レシピにはscriptとintentが必要です')
        script = no_links(recipe['script'])
        if not script.is_file() or script.suffix.lower() != '.py':
            raise WorkflowError('造形スクリプトは実在する.pyファイルが必要です')
        with self.store.update(project_id, 'geometry_plan_created') as doc:
            production = self.verify_production(doc, production_id)
            pack = self.verify_pack(doc, pack_id)
            scope = production['fixed']['scope']
            if pack['production_plan_id'] != production_id or part_id not in scope['part_ids']:
                raise WorkflowError('親計画・資料パック・部品の範囲が一致しません')
            if 'geometry' not in scope['stages'] or 'blender_authoring' not in scope['geometry_engines']:
                raise WorkflowError('Blender直接造形が親計画で許可されていません')
            consumed = sum(p.get('production_plan_id') == production_id and p.get('part_id') == part_id
                           and p.get('fixed', {}).get('stage') == 'geometry' for p in doc['plans'])
            if consumed >= scope['max_geometry_runs_per_part']:
                raise WorkflowError('部品の造形試行上限に達しています')
            run_id = uid()
            folder = self.store.path(project_id, f'runs/{run_id}')
            folder.mkdir(parents=True, exist_ok=False)
            action = folder / 'action.py'
            shutil.copyfile(script, action)
            script_hash = sha(action)
            if script_hash != sha(script):
                raise WorkflowError('造形スクリプトがコピー中に変わりました')
            input_manifest = folder / 'input-manifest.json'
            write(input_manifest, {'files': pack['files'], 'production_plan_id': production_id,
                                   'reference_pack_id': pack_id})
            job_file = folder / 'job.json'
            command = [self.adapter_config['blender'], '--background', '--factory-startup',
                       '--disable-autoexec', '--python-exit-code', '1', '--python',
                       str(REPO / 'scripts' / 'blender_authoring.py'), '--', str(job_file)]
            write(job_file, {'script': str(action), 'output': str(folder / 'outputs.pending'),
                             'part_id': part_id, 'intent': recipe['intent'],
                             'face_limit': scope['face_limits'][part_id],
                             'recipe': {k: copy.deepcopy(v) for k, v in recipe.items() if k != 'script'},
                             'command': command})
            fixed = {'stage': 'geometry', 'engine': 'blender_authoring', 'project_id': project_id,
                     'production_plan_id': production_id, 'production_hash': production['content_hash'],
                     'reference_pack_id': pack_id, 'reference_pack_hash': pack['content_hash'],
                     'part_id': part_id, 'part_plan_id': pack['part_plan_id'],
                     'run_id': run_id, 'script': f'runs/{run_id}/action.py', 'script_hash': script_hash,
                     'adapter_hash': sha(REPO / 'scripts' / 'blender_authoring.py'),
                     'job_hash': sha(job_file), 'input_manifest_hash': sha(input_manifest),
                     'recipe': {k: copy.deepcopy(v) for k, v in recipe.items() if k != 'script'},
                     'face_limit': copy.deepcopy(scope['face_limits'][part_id]),
                     'adapter_config': copy.deepcopy(self.adapter_config)}
            item = record(project_id=project_id, production_plan_id=production_id,
                          reference_pack_id=pack_id, part_id=part_id, fixed=fixed,
                          plan_hash=fingerprint(fixed), state='approved',
                          approval=record(kind='parent_scope', production_plan_id=production_id,
                                          production_hash=production['content_hash'],
                                          reference_pack_id=pack_id, reference_pack_hash=pack['content_hash']),
                          candidates=[], error=None, run=f'runs/{run_id}')
            doc['plans'].append(item)
            write(folder / 'plan.json', item)
        return item
