"""External adapters with a durable running state and immutable artifacts."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time

from .storage import WorkflowError, find, fingerprint, no_links, read, record, sha, uid, write

REPO = Path(__file__).resolve().parents[2]


def load_config(path):
    path = no_links(path)
    config = read(path)
    if set(config) != {'blender'}:
        raise WorkflowError('実行設定はblenderのパスだけを指定してください')
    for key in ('blender',):
        value = Path(config[key])
        config[key] = str(no_links(value if value.is_absolute() else path.parent / value))
    return config


def process(command, output, env, cwd):
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    start = time.perf_counter()
    with output.open('xb') as log:
        child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                 env=env, cwd=cwd, creationflags=flags)
        try:
            code = child.wait(timeout=1800)
        except (KeyboardInterrupt, subprocess.TimeoutExpired):
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=10)
            raise
    if code:
        raise WorkflowError(f'外部処理が失敗しました（code={code}）。ログ: {output}')
    return {'seconds': time.perf_counter() - start, 'return_code': code}


def execute(workbench, project_id, plan_id, config):
    store = workbench.store
    existing = find(store.load(project_id)['plans'], plan_id)
    if existing['fixed'].get('engine') == 'blender_authoring':
        return execute_authoring(workbench, project_id, plan_id, config)
    if existing['fixed'].get('stage') == 'geometry':
        raise WorkflowError('旧式の造形計画は実行できません。Blender直接造形の新しい計画を作成してください')
    failure = None
    result = None
    with store.update(project_id, 'plan_executed') as doc:
        plan = find(doc['plans'], plan_id)
        if plan['state'] != 'approved' or not plan['approval']:
            raise WorkflowError('明示承認済みの未実行計画だけを実行できます')
        fixed = plan['fixed']
        if fingerprint(fixed) != plan['plan_hash']:
            raise WorkflowError('計画hashが一致しません')
        if fixed.get('production_plan_id'):
            production = workbench.verify_production(doc, fixed['production_plan_id'])
            if production['content_hash'] != fixed['production_hash'] or fixed['stage'] not in production['fixed']['scope']['stages']:
                raise WorkflowError('親計画の承認範囲が一致しません')
            if fixed.get('reference_pack_id'):
                pack = workbench.verify_pack(doc, fixed['reference_pack_id'])
                if pack['content_hash'] != fixed['reference_pack_hash'] or pack['production_plan_id'] != production['id']:
                    raise WorkflowError('資料パックの承認範囲が一致しません')
            reserved = store.path(project_id, f'runs/{fixed["run_id"]}')
            if (not reserved.is_dir() or
                    read(reserved / 'plan.json')['fixed'] != fixed or
                    read(reserved / 'plan.json')['plan_hash'] != plan['plan_hash']):
                raise WorkflowError('予約済みrunの固定計画が一致しません')
        if fixed['adapter_config'] != config:
            raise WorkflowError('承認したアダプタ設定と実行設定が一致しません')
        for code in fixed['code']:
            if sha(no_links(code['path'])) != code['sha256']:
                raise WorkflowError('計画後に実装が更新されました。新しい計画を作ってください')
        for ref in fixed['references']:
            workbench.verify_file(project_id, ref)
        for candidate in fixed['inputs'] + ([fixed['source']] if fixed['source'] else []):
            for file in candidate['files']:
                workbench.verify_file(project_id, file)
        if fixed['stage'] == 'image_prepare':
            plan.update(state='blocked', error='画像描き起こしアダプタは未実装です。既存の生成用画像をimage registerで登録できます。')
            return plan
        lock = REPO / 'experiments/runs/.execution.lock'
        lock.parent.mkdir(parents=True, exist_ok=True)
        no_links(lock)
        try:
            with lock.open('x', encoding='utf-8') as stream:
                json.dump({'pid': os.getpid(), 'project_id': project_id, 'plan_id': plan_id}, stream)
        except FileExistsError as exc:
            raise WorkflowError('他の外部処理または残存ロックがあります。自動で奪いません') from exc
        try:
            run_id = fixed.get('run_id') or uid()
            folder = store.path(project_id, f'runs/{run_id}')
            if not fixed.get('production_plan_id'):
                folder.mkdir(parents=True, exist_ok=False)
            plan.update(state='running', run=f'runs/{run_id}', error=None)
            store.save(doc)
            if not fixed.get('production_plan_id'):
                write(folder / 'plan.json', plan)
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8',
                       PYTHONUNBUFFERED='1')
            parent = fixed['source']
            if fixed['stage'] in ('assembly', 'surface'):
                parts = []
                if fixed['stage'] == 'assembly':
                    for binding, candidate in zip(fixed['composition'], fixed['inputs']):
                        mesh = next((f for f in candidate['files'] if f['file'].endswith('.obj')), None)
                        blend_part = next((f for f in candidate['files'] if f['file'].endswith('.blend')), None)
                        if candidate.get('provenance') in ('blender_authoring', 'manual_blend') and blend_part:
                            parts.append(dict(binding, blend=str(workbench.verify_file(project_id, blend_part))))
                        elif mesh:
                            parts.append(dict(binding, mesh=str(workbench.verify_file(project_id, mesh))))
                        else:
                            raise WorkflowError('組み立てには編集可能な.blendまたはOBJ部品が必要です')
                blend = next((f for f in parent['files'] if f['file'].endswith('.blend')), None) if parent else None
                artifact_folder = folder / ('outputs.pending' if fixed.get('production_plan_id') else 'outputs')
                artifact_folder.mkdir()
                job = {'stage': fixed['stage'], 'parts': parts, 'composition': fixed['composition'],
                       'source': str(workbench.verify_file(project_id, blend)) if blend else None,
                       'materials': fixed['materials'], 'edit': fixed['edit'], 'output': str(artifact_folder)}
                command = [config['blender'], '--background', '--factory-startup', '--disable-autoexec',
                           '--python-exit-code', '1', '--python', str(REPO / 'scripts/blender_workbench.py'),
                           '--', str(folder / 'job.json')]
                job['command'] = command
                write(folder / 'job.json', job)
                metrics = process(command, folder / 'blender.log', env, REPO)
                checks = read(artifact_folder / 'checks.json')
                if checks.get('success') is not True:
                    raise WorkflowError('Blenderの検査結果が不合格です')
                if fixed.get('production_plan_id'):
                    artifact_folder.rename(folder / 'outputs')
                    artifact_folder = folder / 'outputs'
                kind, stage = 'character', 'surface' if fixed['stage'] == 'surface' else 'geometry'
            else:
                raise WorkflowError('未対応の実行工程です')
            files = [{'file': f.relative_to(store.directory(project_id)).as_posix(), 'sha256': sha(f)}
                     for f in sorted(artifact_folder.rglob('*')) if f.is_file()]
            if not files:
                raise WorkflowError('完成した成果物がありません')
            result = record(kind=kind, part_id=fixed['part_id'], description=fixed['prompt'],
                            parent_id=parent['id'] if parent else None,
                            generation_id=plan_id, stage=stage, provenance='executed',
                            status='pending', history=[], files=files,
                            composition=fixed['composition'], materials=fixed['materials'],
                            shape_confirmed=fixed['stage'] == 'surface', ue_verified=False,
                            production_plan_id=fixed.get('production_plan_id'),
                            run_id=run_id, reference_pack_id=fixed.get('reference_pack_id'))
            doc['candidates'].append(result)
            plan.update(state='succeeded', candidates=[result['id']], metrics=metrics)
        except BaseException as exc:
            plan.update(state='result_unknown' if isinstance(exc, (KeyboardInterrupt, subprocess.TimeoutExpired)) else 'failed',
                        error=str(exc))
            failure = exc
        finally:
            lock.unlink()
    if failure:
        raise failure
    return result


def execute_authoring(workbench, project_id, plan_id, config):
    """Execute a reserved v2 run. A failed attempt is never retried in place."""
    store = workbench.store
    failure = None
    result = None
    with store.update(project_id, 'blender_authoring_executed') as doc:
        plan = find(doc['plans'], plan_id)
        if plan['state'] != 'approved' or plan.get('approval', {}).get('kind') != 'parent_scope':
            raise WorkflowError('親計画から承認継承した未実行計画が必要です')
        fixed = plan['fixed']
        if fingerprint(fixed) != plan['plan_hash'] or fixed['project_id'] != project_id:
            raise WorkflowError('造形計画のhashまたは案件IDが一致しません')
        production = workbench.verify_production(doc, fixed['production_plan_id'])
        pack = workbench.verify_pack(doc, fixed['reference_pack_id'])
        if (production['content_hash'] != fixed['production_hash'] or
                pack['content_hash'] != fixed['reference_pack_hash'] or
                pack['production_plan_id'] != production['id']):
            raise WorkflowError('承認した親計画・資料パックの版と一致しません')
        if fixed['adapter_config'] != config:
            raise WorkflowError('承認したBlender設定と実行設定が一致しません')
        action = store.path(project_id, fixed['script'])
        adapter = REPO / 'scripts' / 'blender_authoring.py'
        if sha(action) != fixed['script_hash'] or sha(adapter) != fixed['adapter_hash']:
            raise WorkflowError('造形スクリプトまたはアダプタが計画後に変更されています')
        folder = store.path(project_id, f'runs/{fixed["run_id"]}')
        if sha(folder / 'job.json') != fixed['job_hash'] or sha(folder / 'input-manifest.json') != fixed['input_manifest_hash']:
            raise WorkflowError('固定したBlender jobまたは入力一覧が変更されています')
        if (not folder.is_dir() or read(folder / 'plan.json')['fixed'] != fixed or
                read(folder / 'plan.json')['plan_hash'] != plan['plan_hash']):
            raise WorkflowError('予約済みrunの固定計画が一致しません')
        lock = REPO / 'experiments/runs/.execution.lock'
        lock.parent.mkdir(parents=True, exist_ok=True)
        no_links(lock)
        try:
            with lock.open('x', encoding='utf-8') as stream:
                json.dump({'pid': os.getpid(), 'project_id': project_id, 'plan_id': plan_id}, stream)
        except FileExistsError as exc:
            raise WorkflowError('他の外部処理または残存ロックがあります') from exc
        try:
            plan.update(state='running', error=None)
            store.save(doc)
            pending = folder / 'outputs.pending'
            if pending.exists() or (folder / 'outputs').exists():
                raise WorkflowError('run出力が既に存在します。再実行しません')
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')
            metrics = process(read(folder / 'job.json')['command'], folder / 'blender.log', env, REPO)
            checks = read(pending / 'checks.json')
            if checks.get('success') is not True or checks.get('part_id') != fixed['part_id'] or checks['faces'] > fixed['face_limit']['max_faces']:
                raise WorkflowError('Blender造形の構造検査が不合格です')
            from .workflow import image_info
            required = ['model.blend', 'model.obj', 'intent.json', 'checks.json',
                        'previews/front.png', 'previews/side.png', 'previews/back.png', 'previews/oblique.png']
            for name in required:
                path = pending / name
                if not path.is_file() or not path.stat().st_size:
                    raise WorkflowError(f'必要な造形成果物がありません: {name}')
                if name.endswith('.png'):
                    image_info(path)
            candidate_id = uid()
            manifest = {'candidate_id': candidate_id, 'parent_candidate_id': None,
                        'plan_id': plan_id, 'run_id': fixed['run_id'],
                        'files': [{'file': name, 'sha256': sha(pending / name)} for name in required]}
            write(pending / 'manifest.json', manifest)
            pending.rename(folder / 'outputs')
            files = [{'file': f'runs/{fixed["run_id"]}/outputs/{name}',
                      'sha256': sha(folder / 'outputs' / name)} for name in required + ['manifest.json']]
            result = record(kind='part', part_id=fixed['part_id'], description=fixed['recipe']['intent'],
                            parent_id=None, generation_id=plan_id, stage='geometry',
                            provenance='blender_authoring', status='pending', history=[], files=files,
                            composition=[], materials=[], shape_confirmed=False, ue_verified=False,
                            production_plan_id=production['id'], reference_pack_id=pack['id'],
                            run_id=fixed['run_id'], intent=fixed['recipe']['intent'], checks=checks)
            result['id'] = candidate_id
            doc['candidates'].append(result)
            plan.update(state='succeeded', candidates=[candidate_id], metrics=metrics)
        except BaseException as exc:
            plan.update(state='result_unknown' if isinstance(exc, (KeyboardInterrupt, subprocess.TimeoutExpired)) else 'failed',
                        error=str(exc))
            failure = exc
        finally:
            lock.unlink()
    if failure:
        raise failure
    return result
