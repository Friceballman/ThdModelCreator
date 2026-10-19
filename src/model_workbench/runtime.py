"""External adapters with a durable running state and immutable artifacts."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time

from .storage import WorkflowError, find, fingerprint, no_links, read, record, sha, uid, write
from .workflow import obj_info

REPO = Path(__file__).resolve().parents[2]


def load_config(path):
    path = no_links(path)
    config = read(path)
    for key in ('triposr_root', 'triposr_python', 'blender', 'hf_home', 'u2net_home'):
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
    failure = None
    result = None
    with store.update(project_id, 'plan_executed') as doc:
        plan = find(doc['plans'], plan_id)
        if plan['state'] != 'approved' or not plan['approval']:
            raise WorkflowError('明示承認済みの未実行計画だけを実行できます')
        fixed = plan['fixed']
        if fingerprint(fixed) != plan['plan_hash']:
            raise WorkflowError('計画hashが一致しません')
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
            run_id = uid()
            folder = store.path(project_id, f'runs/{run_id}')
            folder.mkdir(parents=True, exist_ok=False)
            plan.update(state='running', run=f'runs/{run_id}', error=None)
            store.save(doc)
            write(folder / 'plan.json', plan)
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8',
                       PYTHONUNBUFFERED='1', HF_HOME=config['hf_home'], U2NET_HOME=config['u2net_home'],
                       HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', NUMBA_CACHE_DIR=str(folder / 'numba'))
            parent = fixed['source']
            if fixed['stage'] == 'geometry':
                source = workbench.verify_file(project_id, fixed['inputs'][0]['files'][0])
                metrics = process([config['triposr_python'], '-B', str(REPO / 'scripts/triposr_probe.py'),
                                   '--root', config['triposr_root'], '--image', str(source),
                                   '--output', str(folder / 'generated'), '--chunk-size', '1024', '--mc-resolution', '128'],
                                  folder / 'triposr.log', env, config['triposr_root'])
                obj_info(folder / 'generated/0/mesh.obj')
                metrics['model'] = read(folder / 'generated/metrics.json')
                artifact_folder = folder / 'generated/0'
                kind, stage = 'part', 'geometry'
            else:
                parts = []
                if fixed['stage'] == 'assembly':
                    for binding, candidate in zip(fixed['composition'], fixed['inputs']):
                        mesh = next((f for f in candidate['files'] if f['file'].endswith('.obj')), None)
                        if not mesh:
                            raise WorkflowError('組み立てにはOBJ部品が必要です')
                        parts.append(dict(binding, mesh=str(workbench.verify_file(project_id, mesh))))
                blend = next((f for f in parent['files'] if f['file'].endswith('.blend')), None) if parent else None
                artifact_folder = folder / 'outputs'
                artifact_folder.mkdir()
                job = {'stage': fixed['stage'], 'parts': parts, 'composition': fixed['composition'],
                       'source': str(workbench.verify_file(project_id, blend)) if blend else None,
                       'materials': fixed['materials'], 'edit': fixed['edit'], 'output': str(artifact_folder)}
                write(folder / 'job.json', job)
                metrics = process([config['blender'], '--background', '--factory-startup', '--disable-autoexec',
                                   '--python-exit-code', '1', '--python', str(REPO / 'scripts/blender_workbench.py'),
                                   '--', str(folder / 'job.json')], folder / 'blender.log', env, REPO)
                checks = read(artifact_folder / 'checks.json')
                if checks.get('success') is not True:
                    raise WorkflowError('Blenderの検査結果が不合格です')
                kind, stage = 'character', 'surface' if fixed['stage'] == 'surface' else 'geometry'
            files = [{'file': f.relative_to(store.directory(project_id)).as_posix(), 'sha256': sha(f)}
                     for f in sorted(artifact_folder.rglob('*')) if f.is_file()]
            if not files:
                raise WorkflowError('完成した成果物がありません')
            result = record(kind=kind, part_id=fixed['part_id'], description=fixed['prompt'],
                            parent_id=parent['id'] if parent else None,
                            generation_id=plan_id, stage=stage, provenance='executed',
                            status='pending', history=[], files=files,
                            composition=fixed['composition'], materials=fixed['materials'],
                            shape_confirmed=fixed['stage'] == 'surface', ue_verified=False)
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
