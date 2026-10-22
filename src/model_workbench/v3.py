"""Interactive v3 workflow. Visual judgments remain explicit review records."""
from __future__ import annotations

import copy
import math
import os
import subprocess
from pathlib import Path

from .storage import WorkflowError, find, fingerprint, no_links, now, read, record, sha, write
from .v2 import V2Workbench, REPO
from .workflow import require_text, image_info

VIEWS = ('front', 'side', 'top', 'back', 'oblique')


class V3Workbench(V2Workbench):
    def comparison_brief(self, project_id, candidate_id):
        doc = self.store.load(project_id)
        candidate, production = self._candidate(doc, candidate_id)
        if candidate['kind'] != 'character':
            raise WorkflowError('比較条件の作成には全身候補が必要です')
        references = production['fixed']['references']
        views = {}
        for view in ('front', 'side', 'top'):
            matching = sorted((r for r in references if r.get('view') == view),
                              key=lambda r: (r.get('priority', 3), r['id']))
            views[view] = ({'reference_id': matching[0]['id'], 'source_view': view}
                           if matching else {'missing_reason': f'{view}方向の資料を親計画に追加してください'})
        return {'camera': 'auto', 'views': views}

    def reference_brief(self, project_id, production_id):
        """Expose image-generation work to Codex without assuming an image API."""
        doc = self.store.load(project_id)
        production = self.verify_production(doc, production_id)
        scope = production['fixed']['scope']
        parts = find(doc['part_plans'], production['fixed']['part_plan_id'])['parts']
        refs = [dict(r, path=str(self.verify_file(project_id, r)))
                for r in production['fixed']['references']]
        return {
            'production_plan_id': production_id, 'production_hash': production['content_hash'],
            'state': 'awaiting_images', 'references': refs,
            'tasks': [dict(part_id=p['id'], name=p['name'], views=list(VIEWS[:4]),
                           face_limit=scope['face_limits'][p['id']],
                           prompt=f"{p['name']}: 一次資料の輪郭・比率を保った低ポリ造形ガイド。"
                           "正面・側面・上面を同じ縮尺で作り、背面の推定を明記する。")
                      for p in parts],
            'assembly_concept': '全部品の低ポリガイドと一次資料を参照し、全身構成を再構築した画像を生成。',
            'next': 'Codexの画像生成で準備し、reference-pack createで由来・推定・low_polyと共に登録する。'}

    def reference_pack_create(self, project_id, production_id, manifest):
        doc = self.store.load(project_id)
        production = self.verify_production(doc, production_id)
        if production['fixed']['scope'].get('quality_loop_version', 2) >= 3:
            for part in manifest.get('parts', []):
                low_poly = part.get('low_poly', {})
                if not isinstance(low_poly, dict) or not low_poly.get('retained_features'):
                    raise WorkflowError('v3部品資料にlow_poly.retained_featuresが必要です')
                if not isinstance(low_poly.get('omitted_details'), list):
                    raise WorkflowError('low_poly.omitted_detailsは配列で指定してください')
                for image in part.get('images', []):
                    if image.get('view') not in VIEWS or type(image.get('inferred')) is not bool:
                        raise WorkflowError('画像のviewと真偽値inferredを指定してください')
                    if image.get('method') == 'image_generation' and image['inferred'] is not True:
                        raise WorkflowError('生成画像はinferred=trueで登録してください')
            concept = manifest.get('assembly_concept', {})
            if (not isinstance(concept, dict) or concept.get('inferred') is not True
                    or concept.get('method') not in ('image_generation', 'drawing', 'external')
                    or not isinstance(concept.get('uncertainties'), list)):
                raise WorkflowError('全身予想図にmethod/inferred=true/uncertaintiesが必要です')
        return super().reference_pack_create(project_id, production_id, manifest)

    def _candidate(self, doc, candidate_id):
        candidate = find(doc['candidates'], candidate_id)
        if candidate.get('status') == 'rejected' or candidate['kind'] not in ('character', 'part'):
            raise WorkflowError('有効な部品または全身候補が必要です')
        production = self.verify_production(doc, candidate['production_plan_id'])
        for entry in candidate['files']:
            self.verify_file(doc['id'], entry)
        return candidate, production

    def comparison_run(self, project_id, candidate_id, manifest):
        from .runtime import process
        from PIL import Image, ImageDraw, ImageOps
        with self.store.update(project_id, 'comparison_created') as doc:
            candidate, production = self._candidate(doc, candidate_id)
            if 'inspect' not in production['fixed']['scope']['stages']:
                raise WorkflowError('親計画にinspect工程が必要です')
            if candidate['kind'] != 'character':
                raise WorkflowError('全身候補を指定してください。部品画像も同時に作成します')
            source = next((f for f in candidate['files'] if f['file'].endswith('.blend')), None)
            if source is None:
                raise WorkflowError('候補に.blendがありません')
            # A previous comparison is the reproducible camera/reference contract.
            if manifest.get('reuse'):
                previous = find(doc.get('comparisons', []), manifest['reuse'])
                self._verify_comparison(doc, previous)
                if previous.get('renderer_hash') != sha(REPO / 'scripts/blender_compare.py'):
                    raise WorkflowError('比較レンダーの実装が変わりました。比較条件を新規作成してください')
                if previous['production_plan_id'] != production['id']:
                    raise WorkflowError('比較条件の親計画が異なります')
                profile = copy.deepcopy(previous['profile'])
            else:
                profile = copy.deepcopy(manifest)
                camera = profile.get('camera', {})
                center, scale = ((camera.get('center'), camera.get('ortho_scale'))
                                 if isinstance(camera, dict) else (None, None))
                if camera != 'auto' and (not isinstance(center, list) or len(center) != 3 or
                        any(type(x) not in (int, float) or not math.isfinite(x) for x in center) or
                        type(scale) not in (int, float) or not math.isfinite(scale) or scale <= 0):
                    raise WorkflowError('camera.center=[x,y,z]と正数ortho_scaleが必要です')
                if 'part_cameras' in profile:
                    raise WorkflowError('部品カメラは初回レンダーで固定します。以後はreuseを指定してください')
                views = profile.get('views', {})
                if not isinstance(views, dict) or not {'front', 'side', 'top'} <= set(views) or not set(views) <= set(VIEWS):
                    raise WorkflowError('比較にはfront/side/topを含むviewsが必要です')
                refs = {r['id']: r for r in production['fixed']['references']}
                for view, target in views.items():
                    if not isinstance(target, dict):
                        raise WorkflowError('方向ごとの参照指定はオブジェクトです')
                    ref = refs.get(target.get('reference_id'))
                    if ref is None:
                        # Missing primary views are explicit, never a false visual pass.
                        require_text(target.get('missing_reason'))
                        continue
                    self.verify_file(project_id, ref)
                    crop = target.get('crop')
                    if crop is not None and (not isinstance(crop, list) or len(crop) != 4 or
                            any(type(x) not in (int, float) or not math.isfinite(x) for x in crop)
                            or not 0 <= crop[0] < crop[2] <= 1 or not 0 <= crop[1] < crop[3] <= 1):
                        raise WorkflowError('cropは画像比率の[x0,y0,x1,y1]（0〜1）です')
                    if target.get('source_view') != view:
                        raise WorkflowError('参照画像内の方向をsource_viewで明示してください')
                    target['reference'] = copy.deepcopy(ref)
            item = record(candidate_id=candidate_id, production_plan_id=production['id'],
                          profile=profile, profile_hash=fingerprint(profile),
                          renderer_hash=sha(REPO / 'scripts/blender_compare.py'),
                          candidate_hash=fingerprint(candidate['files']), state='running',
                          files=[], reviews=[], error=None)
            folder = self.store.path(project_id, f'comparisons/{item["id"]}')
            folder.mkdir(parents=True, exist_ok=False)
            parts = [b['part_id'] for b in candidate.get('composition', [])]
            if set(parts) != set(production['fixed']['scope']['part_ids']):
                raise WorkflowError('全身候補の部品構成が親計画と一致しません')
            job = {'source': str(self.verify_file(project_id, source)), 'output': str(folder),
                   'profile': profile, 'part_ids': parts}
            write(folder / 'job.json', job)
            doc.setdefault('comparisons', []).append(item)
            self.store.save(doc)
            try:
                command = [self.adapter_config['blender'], '--background', '--factory-startup',
                           '--disable-autoexec', '--python-exit-code', '1', '--python',
                           str(REPO / 'scripts/blender_compare.py'), '--', str(folder / 'job.json')]
                lock = no_links(REPO / 'experiments/runs/.execution.lock')
                lock.parent.mkdir(parents=True, exist_ok=True)
                try:
                    with lock.open('x', encoding='utf-8') as stream:
                        stream.write(str(os.getpid()))
                except FileExistsError as exc:
                    raise WorkflowError('他のBlender処理または残存ロックがあります') from exc
                try:
                    item['metrics'] = process(command, folder / 'blender.log',
                                             dict(os.environ, PYTHONDONTWRITEBYTECODE='1'), REPO)
                finally:
                    lock.unlink()
                checks = read(folder / 'checks.json')
                if checks.get('success') is not True or checks.get('part_ids') != parts:
                    raise WorkflowError('比較レンダーの部品検査が一致しません')
                resolved = checks.get('profile', profile)
                initial = {k: v for k, v in profile.items() if k not in ('part_cameras', 'camera')}
                actual = {k: v for k, v in resolved.items() if k not in ('part_cameras', 'camera')}
                if initial != actual or (profile['camera'] != 'auto' and resolved['camera'] != profile['camera']):
                    raise WorkflowError('Blenderが比較条件を変更しました')
                if profile.get('part_cameras') and resolved.get('part_cameras') != profile['part_cameras']:
                    raise WorkflowError('固定済み部品カメラが変更されました')
                item['profile'] = profile = copy.deepcopy(resolved)
                item['profile_hash'] = fingerprint(profile)
                for view, target in profile['views'].items():
                    tiles = []
                    ref = target.get('reference')
                    if ref:
                        with Image.open(self.verify_file(project_id, ref)) as im:
                            tile = im.convert('RGB')
                        if target.get('crop'):
                            x0, y0, x1, y1 = target['crop']
                            tile = tile.crop((int(x0 * tile.width), int(y0 * tile.height),
                                              int(x1 * tile.width), int(y1 * tile.height)))
                        tile = ImageOps.contain(tile, (256, 256))
                        tiles.append(('SOURCE', tile))
                    else:
                        tiles.append(('SOURCE MISSING', Image.new('RGB', (256, 256), '#888888')))
                    for name in ['whole', *parts, *(['detail-' + p for p in parts] if profile.get('part_cameras') else [])]:
                        path = folder / f'{name}-{view}.png'
                        image_info(path)
                        with Image.open(path) as im:
                            tiles.append((name, im.convert('RGB').resize((256, 256))))
                    sheet = Image.new('RGB', (256 * len(tiles), 280), 'white')
                    draw = ImageDraw.Draw(sheet)
                    for index, (label, tile) in enumerate(tiles):
                        sheet.paste(tile, (index * 256 + (256 - tile.width) // 2,
                                           24 + (256 - tile.height) // 2))
                        draw.text((index * 256 + 4, 4), label, fill='black')
                    sheet.save(folder / f'sheet-{view}.png')
                item['files'] = [{'file': p.relative_to(self.store.directory(project_id)).as_posix(),
                                  'sha256': sha(p)}
                                 for p in sorted(folder.glob('*.png'))]
                item['state'] = 'succeeded'
            except BaseException as exc:
                item.update(state='result_unknown' if isinstance(exc, (KeyboardInterrupt, subprocess.TimeoutExpired))
                            else 'failed', error=str(exc))
                self.store.save(doc)
                raise
        return item

    def _verify_comparison(self, doc, comparison):
        if comparison['state'] != 'succeeded' or fingerprint(comparison['profile']) != comparison['profile_hash']:
            raise WorkflowError('比較画像が未完成または比較条件が変更されています')
        candidate, _ = self._candidate(doc, comparison['candidate_id'])
        if fingerprint(candidate['files']) != comparison['candidate_hash']:
            raise WorkflowError('比較後に候補ファイルが変更されています')
        if not comparison['files']:
            raise WorkflowError('比較画像がありません')
        for entry in comparison['files']:
            self.verify_file(doc['id'], entry)
        for target in comparison['profile']['views'].values():
            if target.get('reference'):
                self.verify_file(doc['id'], target['reference'])
        return candidate

    def comparison_review(self, project_id, comparison_id, review):
        with self.store.update(project_id, 'comparison_reviewed') as doc:
            comparison = find(doc.get('comparisons', []), comparison_id)
            candidate = self._verify_comparison(doc, comparison)
            parts = {b['part_id'] for b in candidate['composition']}
            entries = review.get('parts', [])
            if len(entries) != len(parts) or {x.get('part_id') for x in entries} != parts:
                raise WorkflowError('比較レビューに全部品の評価が必要です')
            for entry in [review.get('whole', {}), review.get('preservation', {}), *entries]:
                if entry.get('result') not in ('pass', 'fail', 'uncertain'):
                    raise WorkflowError('レビューはpass/fail/uncertainで指定してください')
                require_text(entry.get('reason'))
            actor = review.get('actor')
            if actor not in ('user', 'codex'):
                raise WorkflowError('actorはuserまたはcodexです')
            production = self.verify_production(doc, candidate['production_plan_id'])
            requirements = review.get('requirements', [])
            required = {r['id'] for r in production['fixed']['requirements']}
            if len(requirements) != len(required) or {x.get('requirement_id') for x in requirements} != required:
                raise WorkflowError('親計画の全要件についてレビューが必要です')
            for entry in requirements:
                if entry.get('result') not in ('pass', 'fail', 'uncertain'):
                    raise WorkflowError('要件レビューはpass/fail/uncertainです')
                require_text(entry.get('reason'))
            saved = record(**copy.deepcopy({k: review[k] for k in
                                           ('whole', 'preservation', 'parts', 'requirements', 'actor')}))
            comparison['reviews'].append(saved)
            doc['reviews'].append(record(candidate_id=candidate['id'], actor=actor,
                entries=copy.deepcopy(requirements), summary=review['whole']['reason'],
                comparison_id=comparison_id, comparison_review_id=saved['id']))
        return saved

    def quality_issue_add(self, project_id, production_id, issue):
        issue = copy.deepcopy(issue)
        if type(issue.get('mandatory', True)) is not bool:
            raise WorkflowError('mandatoryは真偽値です')
        issue.setdefault('mandatory', True)
        require_text(issue.get('repair'))
        if not issue.get('candidate_id') or not issue.get('evidence_reference_ids'):
            raise WorkflowError('課題には発見候補と一次資料のIDが必要です')
        if not issue.get('source_views') or not set(issue['source_views']) <= set(VIEWS):
            raise WorkflowError('課題の確認方向を指定してください')
        # Base method stores the repair instruction as part of the issue.
        return super().quality_issue_add(project_id, production_id, issue)

    def quality_issue_evaluate(self, project_id, issue_id, candidate_id, result, note, comparison_id=None):
        with self.store.update(project_id, 'quality_issue_evaluated') as doc:
            issue = find(doc.get('quality_issues', []), issue_id)
            if comparison_id is None:
                raise WorkflowError('課題の再評価には--comparisonが必要です')
            comparison = find(doc.get('comparisons', []), comparison_id)
            self._verify_comparison(doc, comparison)
            if comparison['candidate_id'] != candidate_id or comparison['production_plan_id'] != issue['production_plan_id']:
                raise WorkflowError('課題と比較画像の候補・親計画が一致しません')
            if not comparison['reviews']:
                raise WorkflowError('全体・部品の比較レビューを先に記録してください')
            if result not in ('resolved', 'reduced', 'unchanged', 'regressed', 'unclear'):
                raise WorkflowError('課題の解消度が不正です')
            evaluation = record(candidate_id=candidate_id, comparison_id=comparison_id,
                                result=result, note=require_text(note))
            issue['evaluations'].append(evaluation)
            issue['state'] = result
        return evaluation

    def _completion_blockers(self, doc, production, candidate_id):
        reasons = []
        if any(s['production_plan_id'] == production['id'] and s['state'] not in ('finished', 'abandoned')
               for s in doc.get('edit_sessions', [])):
            reasons.append('編集セッションが未終了です')
        if not candidate_id:
            return ['完成候補IDが未指定です']
        candidate, _ = self._candidate(doc, candidate_id)
        if candidate['kind'] != 'character' or candidate['production_plan_id'] != production['id']:
            return ['同じ親計画の全身候補が必要です']
        comparisons = [x for x in doc.get('comparisons', [])
                       if x['candidate_id'] == candidate_id and x['state'] == 'succeeded']
        if not comparisons:
            return ['この候補の比較画像とレビューが必要です']
        comparison = comparisons[-1]
        self._verify_comparison(doc, comparison)
        if not comparison['reviews']:
            reasons.append('比較レビューがありません')
        else:
            review = comparison['reviews'][-1]
            if any(e['result'] != 'pass' for e in
                   [review['whole'], review['preservation'], *review['parts'], *review['requirements']]):
                reasons.append('全体・部品・保持・要件に未合格があります')
        if any(not t.get('reference') for t in comparison['profile']['views'].values()):
            reasons.append('比較用の方向資料が不足しています')
        for issue in doc.get('quality_issues', []):
            if issue['production_plan_id'] != production['id']:
                continue
            evaluations = [e for e in issue['evaluations'] if e['candidate_id'] == candidate_id
                           and e.get('comparison_id') == comparison['id']]
            if (issue.get('mandatory') and (not evaluations or evaluations[-1]['result'] != 'resolved')
                    or evaluations and evaluations[-1]['result'] == 'regressed'):
                reasons.append('課題の解消・退行確認が必要です: ' + issue['id'])
        return reasons

    def completion_set(self, project_id, production_id, candidate_id, reason):
        with self.store.update(project_id, 'completion_candidate_set') as doc:
            production = self.verify_production(doc, production_id)
            blockers = self._completion_blockers(doc, production, candidate_id)
            if blockers:
                raise WorkflowError(' / '.join(blockers))
            previous = [x for x in doc.get('completion_history', []) if x['production_plan_id'] == production_id]
            item = record(production_plan_id=production_id, candidate_id=candidate_id,
                          reason=require_text(reason), supersedes=previous[-1]['id'] if previous else None)
            doc.setdefault('completion_history', []).append(item)
            production.update(completion_candidate_id=candidate_id, completion_record_id=item['id'])
        return item

    def completion_status(self, project_id, production_id):
        doc = self.store.load(project_id)
        production = self.verify_production(doc, production_id)
        candidate_id = production.get('completion_candidate_id')
        try:
            blockers = self._completion_blockers(doc, production, candidate_id)
        except (WorkflowError, OSError) as exc:
            blockers = [str(exc)]
        return dict(production_plan_id=production_id, completion_candidate_id=candidate_id,
                    state='in_progress' if blockers else 'complete', blockers=blockers)

    def set_approved(self, project_id, candidate_id, reason):
        doc = self.store.load(project_id)
        candidate = find(doc['candidates'], candidate_id)
        if candidate.get('production_plan_id'):
            production = find(doc['production_plans'], candidate['production_plan_id'])
            if production['fixed']['scope'].get('quality_loop_version', 2) >= 3:
                status = self.completion_status(project_id, production['id'])
                if status['state'] != 'complete' or status['completion_candidate_id'] != candidate_id:
                    raise WorkflowError('v3正式採用には有効な完成候補の指定が必要です')
        return super().set_approved(project_id, candidate_id, reason)

    def export(self, project_id, name, evidence, expected_selection=None):
        doc = self.store.load(project_id)
        for candidate in doc['candidates']:
            if candidate['kind'] != 'character' or candidate['status'] != 'selected' or not candidate.get('production_plan_id'):
                continue
            production = find(doc['production_plans'], candidate['production_plan_id'])
            if production['fixed']['scope'].get('quality_loop_version', 2) >= 3:
                status = self.completion_status(project_id, production['id'])
                if status['state'] != 'complete' or status['completion_candidate_id'] != candidate['id']:
                    raise WorkflowError('v3出力には有効な完成候補の指定が必要です')
        return super().export(project_id, name, evidence, expected_selection)

    def status(self, project_id):
        result = super().status(project_id)
        doc = self.store.load(project_id)
        result['v3_completion'] = [self.completion_status(project_id, p['id'])
                                   for p in doc.get('production_plans', []) if p['state'] == 'approved'
                                   and p['fixed']['scope'].get('quality_loop_version', 2) >= 3]
        result['open_edit_sessions'] = [s for s in doc.get('edit_sessions', [])
                                        if s['state'] not in ('finished', 'abandoned')]
        incomplete = [s for s in result['v3_completion'] if s['state'] != 'complete']
        if incomplete:
            result['next'] = 'v3: ' + ' / '.join(incomplete[-1]['blockers'])
        return result

    def repair_queue(self, project_id, production_id, candidate_id):
        doc = self.store.load(project_id)
        candidate, _ = self._candidate(doc, candidate_id)
        if candidate['production_plan_id'] != production_id:
            raise WorkflowError('修正対象の親計画が一致しません')
        result = []
        for issue in doc.get('quality_issues', []):
            if issue['production_plan_id'] != production_id:
                continue
            evaluations = [e for e in issue['evaluations'] if e['candidate_id'] == candidate_id]
            state = evaluations[-1]['result'] if evaluations else 'unreviewed'
            if state != 'resolved':
                result.append(dict(issue, candidate_state=state))
        return sorted(result, key=lambda i: (not i['mandatory'], i['priority'], i['id']))

    def candidate_edit_session_start(self, project_id, production_id, candidate_id, issue_ids=()):
        doc = self.store.load(project_id)
        issues = [find(doc.get('quality_issues', []), i) for i in issue_ids]
        if any(i['production_plan_id'] != production_id for i in issues):
            raise WorkflowError('課題の親計画が一致しません')
        item = super().candidate_edit_session_start(project_id, production_id, candidate_id)
        folder = self.store.path(project_id, item['working_file']).parent
        with self.store.update(project_id, 'edit_session_issues_linked') as doc:
            session = find(doc['edit_sessions'], item['id'])
            session['issue_ids'] = list(issue_ids)
            item['issue_ids'] = list(issue_ids)
        write(folder / 'session.json', item)
        return dict(item, manifest_path=str(folder / 'session.json'),
                    helper_path=str(REPO / 'scripts/blender_session.py'),
                    repairs=issues,
                    next='MCPでblender_session.connect(manifest_path, open_copy=True)を呼び、candidate edit-bindを実行')

    def candidate_edit_session_bind(self, project_id, session_id):
        with self.store.update(project_id, 'candidate_edit_session_bound') as doc:
            session = find(doc.get('edit_sessions', []), session_id)
            if session['state'] != 'open':
                raise WorkflowError('未接続のopenセッションが必要です')
            candidate, _ = self._candidate(doc, session['candidate_id'])
            working = self.store.path(project_id, session['working_file'])
            observation = read(working.parent / 'connection.json')
            if (observation.get('session_id') != session_id or
                    observation.get('candidate_id') != candidate['id'] or
                    no_links(observation['filepath']) != working or
                    observation.get('sha256') != session['source_sha256'] or sha(working) != session['source_sha256']):
                raise WorkflowError('MCP接続報告と作業コピーが一致しません')
            parts = ({candidate['part_id']} if candidate['kind'] == 'part'
                     else {b['part_id'] for b in candidate['composition']})
            if {x.get('part_id') for x in observation.get('objects', [])} != parts:
                raise WorkflowError('MCP接続先の部品IDが候補と一致しません')
            session.update(state='connected', connection=observation)
        return session

    def candidate_edit_session_finish(self, project_id, session_id, edit, incoming):
        # Reserve before running Blender so a second finish cannot duplicate output.
        with self.store.update(project_id, 'candidate_edit_session_importing') as doc:
            session = find(doc.get('edit_sessions', []), session_id)
            if session['state'] == 'finished':
                return find(doc['candidates'], session['result_candidate_id'])
            if session['state'] not in ('connected', 'failed'):
                raise WorkflowError('接続照合が必要です。importing状態は結果確認まで再実行できません')
            self._candidate(doc, session['candidate_id'])
            working = self.store.path(project_id, session['working_file'])
            if no_links(incoming) != working:
                raise WorkflowError('編集結果にはこのセッションのworking.blendを指定してください')
            capture = read(working.parent / 'capture.json')
            if (capture.get('session_id') != session_id or capture.get('candidate_id') != session['candidate_id']
                    or no_links(capture['filepath']) != working or sha(working) != capture.get('sha256')):
                raise WorkflowError('MCP保存報告と編集結果のhashが一致しません')
            operations = capture.get('operations')
            if not isinstance(operations, list) or not operations:
                raise WorkflowError('編集操作の記録が必要です')
            for operation in operations:
                require_text(operation)
            if not isinstance(edit, dict):
                raise WorkflowError('edit manifestはオブジェクトです')
            edit = dict(edit, session_id=session_id, session_source_id=session['candidate_id'],
                        operations=operations, issue_ids=session.get('issue_ids', []))
            if edit.get('mode') == 'part_transform':
                targets = edit.get('target_part_ids', [])
                for name, evidence in [('before_transform', session['connection']),
                                       ('after_transform', capture)]:
                    edit.setdefault(name, {p: evidence.get('transforms', {}).get(p) for p in targets})
            if edit['issue_ids']:
                affected = {p for i in edit['issue_ids']
                            for p in find(doc['quality_issues'], i)['affected_part_ids']}
                if not set(edit.get('target_part_ids', [])) <= affected:
                    raise WorkflowError('修正部品が関連付けた課題の対象外です')
            session.update(state='importing', capture=capture, error=None)
        try:
            result = self.revision_run(project_id, session['candidate_id'],
                                       session['production_plan_id'], edit, working)
        except BaseException as exc:
            with self.store.update(project_id, 'candidate_edit_session_failed') as doc:
                current = find(doc['edit_sessions'], session_id)
                current.update(state='failed' if isinstance(exc, (ValueError, OSError)) else 'result_unknown',
                               error=str(exc))
            raise
        with self.store.update(project_id, 'candidate_edit_session_finished') as doc:
            current = find(doc['edit_sessions'], session_id)
            current.update(state='finished', result_candidate_id=result['id'], closed_at=now())
        return result

    def candidate_edit_session_recover(self, project_id, session_id):
        with self.store.update(project_id, 'edit_session_recovered') as doc:
            session = find(doc.get('edit_sessions', []), session_id)
            matches = [c for c in doc['candidates'] if c.get('parent_id') == session['candidate_id']]
            recovered = []
            for candidate in matches:
                if not candidate.get('generation_id'):
                    continue
                plan = find(doc['plans'], candidate['generation_id'])
                if plan['state'] == 'succeeded' and (plan['fixed'].get('edit') or {}).get('session_id') == session_id:
                    recovered.append(candidate)
            if len(recovered) != 1:
                raise WorkflowError('成功した派生候補を一意に復元できません。runの状態を確認してください')
            self._candidate(doc, recovered[0]['id'])
            session.update(state='finished', result_candidate_id=recovered[0]['id'], closed_at=now())
        return session

    def candidate_edit_session_abandon(self, project_id, session_id, reason):
        with self.store.update(project_id, 'edit_session_abandoned') as doc:
            session = find(doc.get('edit_sessions', []), session_id)
            if session['state'] not in ('open', 'connected', 'failed'):
                raise WorkflowError('実行中・結果不明・完了済みのセッションは保留終了できません')
            session.update(state='abandoned', closed_at=now(), reason=require_text(reason))
        return session
