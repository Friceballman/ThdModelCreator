"""Explicit Blender integration test using existing assets, never new TripoSR generation."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.cache/ux-smoke'


def main(with_geometry=False):
    WORK.mkdir(parents=True, exist_ok=True)

    def cli(*arguments):
        command = [sys.executable, '-B', str(ROOT / 'mwb.py'), '--root', str(WORK / 'projects'), '--json', *arguments]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, encoding='utf-8', timeout=1800)
        if result.returncode:
            raise RuntimeError(result.stderr + result.stdout)
        return json.loads(result.stdout)

    project = cli('project', 'create', '--name', 'UX統合試験・椅子の部品代用',
                  '--goal', '実装の接続試験。キャラクター品質・人の最終採用を評価しない。新規生成なし。')
    pid = project['id']
    print(f'試験案件: {pid}', flush=True)
    reference = cli('reference', 'add', pid, 'C:/AI_test/TripoSR/examples/chair.png',
                    '--role', 'design', '--description', '試験用画像。形状制作の品質評価ではない', '--view', 'perspective')
    requirement = cli('requirement', 'add', pid, '--category', 'must_keep', '--text', '対照部品の形状と配置を維持する')
    parts_file = WORK / f'{pid}-parts.json'
    parts_file.write_text(json.dumps([{'name': '試験対象部品'}, {'name': '保持対象部品'}]), encoding='utf-8')
    proposal = cli('part', 'plan', pid, '--file', str(parts_file), '--reason', '試験の2部品構成')
    cli('part', 'approve', pid, proposal['id'], '--hash', proposal['content_hash'],
        '--evidence', '自動検証用の既存資産2部品。実キャラクターの構成承認ではない')
    parts = [p['id'] for p in proposal['parts']]
    candidates = [cli('asset', 'add', pid, 'C:/AI_test/TripoSR/output/chair-rtx3050ti/0/mesh.obj',
                       '--part', part, '--description', '既存椅子OBJを技術試験の部品として利用') for part in parts]

    def run(plan):
        cli('generate', 'request-approval', pid, plan['id'])
        cli('generate', 'approve', pid, plan['id'], '--hash', plan['plan_hash'],
            '--evidence', '依頼済みの実装検証に含む試験資産の処理。実制作物の採用ではない')
        return cli('generate', 'execute', pid, plan['id'])

    if with_geometry:
        image = cli('image', 'register', pid, 'C:/AI_test/TripoSR/examples/chair.png',
                    '--part', parts[0], '--description', '承認済みの公式椅子画像による1回の生成試験')
        cli('image', 'approve', pid, image['id'], '--hash', image['input_hash'],
            '--evidence', '明示された試験用椅子画像を確認済み。キャラクター資料の確認ではない')
        candidates[0] = run(cli('generate', 'plan', pid, '--stage', 'geometry', '--part', parts[0],
                                '--input', image['id'], '--reference', reference['id'],
                                '--prompt', '承認済みの椅子画像を1回、CUDA・chunk1024・解像度128で生成する'))
        print('TripoSRの画像→OBJを1回実行・検証・候補登録: 合格', flush=True)
    recipe = WORK / f'{pid}-assembly.json'
    recipe.write_text(json.dumps({'bindings': [
        {'part_id': part, 'candidate_id': candidate['id'], 'location': [index * 0.9, 0, 0],
         'scale': [1 if index == 0 else 0.5] * 3}
        for index, (part, candidate) in enumerate(zip(parts, candidates))]}), encoding='utf-8')

    assembly = run(cli('generate', 'plan', pid, '--stage', 'assembly', '--prompt', '2部品を配置する接続試験',
                       '--reference', reference['id'], '--recipe', str(recipe)))
    print('仮組み・4方向プレビュー・再読み込み: 合格', flush=True)
    edit_recipe = WORK / f'{pid}-edit.json'
    edit_recipe.write_text(json.dumps({'edit': {'part_id': parts[0], 'scale_factor': 1.1}}), encoding='utf-8')
    edited = run(cli('edit', 'plan', pid, '--source', assembly['id'], '--stage', 'assembly',
                     '--prompt', '対象だけを10%拡大し、対照を保持する試験', '--recipe', str(edit_recipe)))
    print('対象部品の拡大・対照部品の保持: 合格', flush=True)
    cli('candidate', 'confirm-shape', pid, edited['id'], '--reason', '試験で数値・構造検査を確認。造形の審美的な採用ではない')
    materials = [cli('material', 'create', pid, '--part', part, '--source', candidate['id'],
                     '--name', '青い試験材質' if index == 0 else '赤い試験材質',
                     '--color', '0.05,0.25,0.8' if index == 0 else '0.8,0.1,0.05', '--roughness', '0.6')
                 for index, (part, candidate) in enumerate(zip(parts, candidates))]
    material_recipe = WORK / f'{pid}-materials.json'
    material_recipe.write_text(json.dumps({'materials': {m['part_id']: m['id'] for m in materials}}), encoding='utf-8')
    surfaced = run(cli('generate', 'plan', pid, '--stage', 'surface', '--source', edited['id'],
                       '--prompt', '形状を保持し2部品へ標準材質を適用する試験', '--recipe', str(material_recipe)))
    print('標準材質の適用・形状保持・再読み込み: 合格', flush=True)
    review_file = WORK / f'{pid}-review.json'
    review_file.write_text(json.dumps({'entries': [{'requirement_id': requirement['id'], 'result': 'pass',
                                                   'reason': 'Blenderの構造検査で対照部品を保持'}],
                                       'summary': '技術試験の結果。キャラクター品質やUE動作は未評価。'}), encoding='utf-8')
    cli('review', pid, surfaced['id'], '--file', str(review_file))
    cli('candidate', 'select', pid, surfaced['id'], '--reason', '試験用の出力対象')
    exported = cli('project', 'export', pid, '--name', '色付き組み立て試験', '--reason', '試験用source出力')
    config = json.loads((ROOT / 'experiments/config.example.json').read_text(encoding='utf-8'))
    export_manifest = WORK / 'projects' / pid / exported['file']
    verified = subprocess.run([config['blender'], '--background', '--factory-startup', '--disable-autoexec',
                               '--python-exit-code', '1', '--python', str(ROOT / 'scripts/check_source_export.py'),
                               '--', str(export_manifest)], capture_output=True, timeout=120)
    (WORK / 'projects' / pid / 'export-check.log').write_bytes(verified.stdout + verified.stderr)
    if verified.returncode:
        raise RuntimeError('出力先でのBlender再読み込み検証が失敗しました')
    print('名前付きsource出力・別保存先のBLEND/OBJ/材質再読み込み: 合格', flush=True)
    comparison = cli('candidate', 'compare', pid, assembly['id'], surfaced['id'])
    status = cli('status', pid)
    summary = {'project_id': pid, 'project_dir': str(WORK / 'projects' / pid),
               'assembly_id': assembly['id'], 'edited_id': edited['id'], 'surface_id': surfaced['id'],
               'export': exported, 'comparison_count': len(comparison), 'status': status,
               'new_generations': 1 if with_geometry else 0, 'ue_verified': False}
    summary['export_reload_verified'] = True
    (WORK / 'latest.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='既存OBJによるUX統合試験。既定で新規生成しません')
    parser.add_argument('--with-geometry', action='store_true',
                        help='承認済みの場合のみ、公式椅子画像を1回だけTripoSRで新規生成する')
    main(parser.parse_args().with_geometry)
