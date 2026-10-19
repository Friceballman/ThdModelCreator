"""Experimental integration runner; standard library only, not the production CLI."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
PLAN_DIR = ROOT / 'experiments' / 'plans'
RUN_DIR = ROOT / 'experiments' / 'runs'


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def canonical_hash(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode('utf-8')).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save_json(path, data):
    """Atomic replacement of this run's status, never another run's output."""
    path = Path(path)
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with tmp.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    tmp.replace(path)


def regular_file(path, base=ROOT):
    p = Path(path)
    p = p if p.is_absolute() else base / p
    # Reject symlinks and Windows reparse points, including parent junctions.
    for item in (p, *p.parents):
        if item.exists() and (item.is_symlink() or
                getattr(item.lstat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError(f'リンク／ジャンクションは入力に使えません: {item}')
    p = p.resolve(strict=True)
    if not p.is_file():
        raise ValueError(f'通常ファイルではありません: {p}')
    return p


def check_obj(path):
    # Material bundles will need an explicit dependency importer in a later test.
    vertices = faces = 0
    indices = []
    with Path(path).open(encoding='utf-8-sig') as stream:
        for line in stream:
            tokens = line.split()
            if not tokens:
                continue
            if tokens[0] in {'mtllib', 'usemtl', 'call', 'csh'}:
                raise ValueError(f'この検証では外部材質・コマンド付きOBJを扱いません: {path}')
            if tokens[0] == 'v':
                if len(tokens) < 4 or not all(math.isfinite(float(x)) for x in tokens[1:]):
                    raise ValueError(f'不正な頂点: {path}')
                vertices += 1
            elif tokens[0] == 'f':
                if len(tokens) < 4:
                    raise ValueError(f'不正な面: {path}')
                faces += 1
                for token in tokens[1:]:
                    index = int(token.split('/')[0])
                    indices.append(index if index > 0 else vertices + index + 1)
    if not vertices or not faces:
        raise ValueError(f'空のメッシュ: {path}')
    if any(index < 1 or index > vertices for index in indices):
        raise ValueError(f'面インデックスが頂点範囲外です: {path}')


def vector(value, positive=False):
    if (not isinstance(value, list) or len(value) != 3 or
            any(isinstance(x, bool) or not isinstance(x, (int, float)) or
                not math.isfinite(x) or (positive and x <= 0) for x in value)):
        raise ValueError('変換値は有限な3要素の数値配列（scaleは正数）が必要です')
    return value


def build_plan(config_path, recipe_path):
    config_path, recipe_path = regular_file(config_path), regular_file(recipe_path)
    config, recipe = read_json(config_path), read_json(recipe_path)
    for key in ('triposr_root', 'hf_home', 'u2net_home'):
        p = Path(config[key])
        config[key] = str((p if p.is_absolute() else config_path.parent / p).resolve(strict=True))
        if not Path(config[key]).is_dir():
            raise ValueError(f'ディレクトリがありません: {key}')
    for key in ('triposr_python', 'blender'):
        config[key] = str(regular_file(config[key], config_path.parent))
    recipe = dict(recipe)
    parts = recipe.get('parts', [])
    if not parts or len(parts) > 16:
        raise ValueError('部品数は1〜16です')
    seen, inputs = set(), []
    for part in parts:
        part_id = part['id']
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,47}', part_id) or part_id in seen:
            raise ValueError('部品IDが不正または重複しています')
        seen.add(part_id)
        if ('mesh' in part) == ('image' in part):
            raise ValueError('meshまたはimageの片方だけを指定してください')
        kind = 'mesh' if 'mesh' in part else 'image'
        path = regular_file(part[kind], recipe_path.parent)
        if kind == 'mesh':
            if path.suffix.lower() != '.obj':
                raise ValueError('既存メッシュの初期対応形式はOBJだけです')
            check_obj(path)
        elif path.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'}:
            raise ValueError('画像形式はPNG/JPEG/WebPです')
        part[kind] = str(path)
        for key, default in [('location', [0, 0, 0]), ('rotation_degrees', [0, 0, 0]),
                             ('scale', [1, 1, 1])]:
            part[key] = vector(part.get(key, default), key == 'scale')
        inputs.append({'part_id': part_id, 'kind': kind, 'path': str(path), 'sha256': digest(path)})
    edit = recipe['edit']
    factor = edit['scale_factor']
    if (edit['part_id'] not in seen or isinstance(factor, bool) or
            not isinstance(factor, (int, float)) or not math.isfinite(factor) or
            not 0.1 <= factor <= 10 or factor == 1):
        raise ValueError('編集は実在部品への倍率0.1〜10（1以外）を指定してください')
    recipe.setdefault('chunk_size', 1024)
    recipe.setdefault('mc_resolution', 128)
    if (type(recipe['chunk_size']) is not int or not 1 <= recipe['chunk_size'] <= 1024 or
            type(recipe['mc_resolution']) is not int or not 16 <= recipe['mc_resolution'] <= 128):
        raise ValueError('初期検証はchunk_size 1〜1024、mc_resolution 16〜128に限定します')
    code = [Path(__file__), ROOT / 'scripts' / 'triposr_probe.py',
            ROOT / 'scripts' / 'blender_flow_probe.py',
            Path(config['triposr_root']) / 'run.py']
    payload = {'schema_version': 1, 'plan_id': str(uuid.uuid4()),
               'created_at': datetime.now(timezone.utc).isoformat(),
               'config': config, 'recipe': recipe, 'inputs': inputs,
               'code': [{'path': str(p.resolve()), 'sha256': digest(p)} for p in code],
               'new_generations': sum(x['kind'] == 'image' for x in inputs)}
    return {'payload': payload, 'plan_hash': canonical_hash(payload)}


def verify_plan(plan, approval):
    if plan.get('plan_hash') != canonical_hash(plan['payload']) or approval != plan['plan_hash']:
        raise ValueError('計画hash／承認hashが一致しません')
    for item in plan['payload']['inputs'] + plan['payload']['code']:
        path = regular_file(item['path'])
        if digest(path) != item['sha256']:
            raise ValueError(f'計画作成後に入力・コードが変更されました: {path}')


def run_process(command, cwd, env, log_path, stages):
    started = time.perf_counter()
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    with log_path.open('xb') as log:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=log,
                                   stderr=subprocess.STDOUT, creationflags=flags)
        try:
            return_code = process.wait(timeout=1800)
        except (KeyboardInterrupt, subprocess.TimeoutExpired):
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
            raise
    stages.append({'command': command, 'seconds': time.perf_counter() - started,
                   'return_code': return_code, 'log': log_path.name})
    if return_code:
        raise RuntimeError(f'外部処理が失敗しました（code={return_code}）: {log_path}')


def execute(plan_path, approval):
    plan = read_json(regular_file(plan_path))
    verify_plan(plan, approval)
    # Experiment-wide lock: never steal a leftover lock after interruption.
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    if RUN_DIR.resolve() != RUN_DIR or PLAN_DIR.resolve() != PLAN_DIR:
        raise ValueError('検証保存先にリンクやジャンクションは使えません')
    lock_path = RUN_DIR / '.execution.lock'
    with lock_path.open('x', encoding='utf-8') as lock:
        json.dump({'pid': os.getpid(), 'plan_hash': approval}, lock)
    run_dir = None
    status = {'state': 'running', 'plan_hash': approval, 'stages': [],
              'created_at': datetime.now(timezone.utc).isoformat()}
    try:
        for previous in RUN_DIR.glob('*/plan.json'):
            if read_json(previous).get('plan_hash') == approval:
                raise ValueError('この計画は既に実行済みです。結果を確認し、新しい計画を作成してください')
        run_dir = RUN_DIR / str(uuid.uuid4())
        run_dir.mkdir()
        print(f'実行先: {run_dir}', flush=True)
        save_json(run_dir / 'plan.json', plan)
        save_json(run_dir / 'status.json', status)
        payload = plan['payload']
        config = payload['config']
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONUNBUFFERED='1',
                   PYTHONIOENCODING='utf-8', HF_HOME=config['hf_home'],
                   U2NET_HOME=config['u2net_home'], HF_HUB_OFFLINE='1',
                   TRANSFORMERS_OFFLINE='1', NUMBA_CACHE_DIR=str(run_dir / 'numba'))
        bindings = []
        for part, source in zip(payload['recipe']['parts'], payload['inputs']):
            part_dir = run_dir / 'parts' / part['id']
            part_dir.mkdir(parents=True)
            frozen = part_dir / ('source' + Path(source['path']).suffix.lower())
            shutil.copyfile(source['path'], frozen)
            if digest(frozen) != source['sha256']:
                raise ValueError('コピー中に入力が変化しました')
            if source['kind'] == 'mesh':
                mesh = frozen
            else:
                run_process([config['triposr_python'], '-B', str(ROOT / 'scripts/triposr_probe.py'),
                             '--root', config['triposr_root'], '--image', str(frozen),
                             '--output', str(part_dir / 'generated'),
                             '--chunk-size', str(payload['recipe']['chunk_size']),
                             '--mc-resolution', str(payload['recipe']['mc_resolution'])],
                            config['triposr_root'], env, run_dir / f'triposr-{part["id"]}.log',
                            status['stages'])
                mesh = part_dir / 'generated' / '0' / 'mesh.obj'
            check_obj(mesh)
            bindings.append(dict(part, mesh=str(mesh), source_sha256=source['sha256']))
        job = {'parts': bindings, 'edit': payload['recipe']['edit'], 'output': str(run_dir)}
        save_json(run_dir / 'blender-job.json', job)
        run_process([config['blender'], '--background', '--factory-startup', '--disable-autoexec',
                     '--python-exit-code', '1', '--python', str(ROOT / 'scripts/blender_flow_probe.py'),
                     '--', str(run_dir / 'blender-job.json')], ROOT, env,
                    run_dir / 'blender.log', status['stages'])
        result = read_json(run_dir / 'blender-check.json')
        if result.get('success') is not True:
            raise RuntimeError('Blenderでの保持・再読み込み検査が不合格です')
        files = [p for p in run_dir.rglob('*') if p.is_file() and
                 'numba' not in p.parts and p.name != 'status.json']
        save_json(run_dir / 'manifest.json', {'schema_version': 1, 'plan_hash': approval,
                  'files': [{'path': p.relative_to(run_dir).as_posix(), 'sha256': digest(p)} for p in sorted(files)]})
        status.update(state='succeeded', success=True,
                      scope='technical_connection_only_not_character_quality')
    except BaseException as exc:
        status.update(state='interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed',
                      success=False, error=repr(exc))
        raise
    finally:
        if run_dir is not None:
            save_json(run_dir / 'status.json', status)
        lock_path.unlink()
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return run_dir


def main():
    parser = argparse.ArgumentParser(description='TripoSR→Blenderの接続・組み立て・保持検査（実験用）')
    sub = parser.add_subparsers(dest='command', required=True)
    doctor = sub.add_parser('doctor', help='実行ファイルと既存キャッシュの存在確認。生成しない')
    doctor.add_argument('--config', default='experiments/config.example.json')
    plan = sub.add_parser('plan', help='入力とスクリプトのhashを固定。生成・Blender起動なし')
    plan.add_argument('--config', default='experiments/config.example.json')
    plan.add_argument('--recipe', required=True)
    run = sub.add_parser('run', help='内容を確認・承認した計画だけを実行')
    run.add_argument('--plan', required=True)
    run.add_argument('--approve-plan', required=True)
    args = parser.parse_args()
    if args.command == 'doctor':
        config_file = regular_file(args.config)
        config = read_json(config_file)
        checks = {}
        for key, value in config.items():
            p = Path(value)
            p = p if p.is_absolute() else config_file.parent / p
            checks[key] = {'path': str(p), 'exists': p.exists()}
        print(json.dumps(checks, ensure_ascii=False, indent=2))
        return 0 if all(x['exists'] for x in checks.values()) else 3
    if args.command == 'plan':
        data = build_plan(args.config, args.recipe)
        PLAN_DIR.mkdir(parents=True, exist_ok=True)
        path = PLAN_DIR / (str(uuid.uuid4()) + '.json')
        save_json(path, data)
        print(json.dumps({'plan': str(path), 'plan_hash': data['plan_hash'],
                          'new_generations': data['payload']['new_generations'],
                          'recipe': data['payload']['recipe']}, ensure_ascii=False, indent=2))
        return 0
    execute(args.plan, args.approve_plan)
    return 0


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('中断しました。実行先の状態とログを確認してください。', file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f'検証失敗: {exc}', file=sys.stderr)
        raise SystemExit(1)
