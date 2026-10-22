from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .storage import Store, WorkflowError, find, read, record, fingerprint, identifier
from .recovery import resume
from .workflow import Workbench, ROLES, VIEWS, STAGES
from .runtime import execute, load_config
from .v2 import V2Workbench
from .v3 import V3Workbench
from .rigging import RiggingLab

REPO = Path(__file__).resolve().parents[2]


def owner(store, collection, item_id):
    target = identifier(item_id)
    matches = [d['id'] for d in store.list() if any(x.get('id') == target for x in d.get(collection, []))]
    if len(matches) != 1:
        raise WorkflowError('対象IDの案件を一意に特定できません。保存先と完全なIDを確認してください')
    return matches[0]


def confirmation(title, snapshot, evidence=None):
    if evidence is not None:
        if not evidence.strip():
            raise WorkflowError('承認根拠・理由は空にできません')
        return evidence
    if not sys.stdin.isatty():
        raise WorkflowError('非対話実行では確認済みの--evidenceまたは--reasonが必要です。自動承認しません')
    print(title, file=sys.stderr)
    print(json.dumps(snapshot, ensure_ascii=False, indent=2), file=sys.stderr)
    print('対象と内容を確認して実行しますか？ [y/N]: ', end='', file=sys.stderr, flush=True)
    try:
        answer = input().strip().lower()
    except EOFError as exc:
        raise WorkflowError('確認入力が終了しました。変更していません') from exc
    if answer not in ('y', 'yes'):
        raise WorkflowError('操作を取り消しました。変更していません')
    return f'端末で対象と内容を表示し、利用者がyと回答: {title}'


def make_plan(wb, store, pid, args):
    doc = store.load(pid)
    source = find(doc['candidates'], args.source) if args.source else None
    part_id = args.part
    stage = args.stage
    if args.input:
        image = find(doc['candidates'], args.input)
        part_id = part_id or image['part_id']
        stage = stage or 'geometry'
    elif args.bind:
        stage = stage or 'assembly'
    elif args.material:
        stage = stage or 'surface'
    elif source:
        stage = stage or ('image_prepare' if source['kind'] == 'prepared_image' else 'assembly')
        part_id = part_id or (source['part_id'] if source['kind'] == 'prepared_image' else None)
    else:
        stage = stage or 'image_prepare'
    recipe = read(args.recipe) if args.recipe else {}
    if args.recipe and (args.bind or args.material or args.location or args.rotation or args.scale):
        raise WorkflowError('--recipeと簡易配置・材質オプションは併用できません')
    if args.bind:
        if stage != 'assembly' or args.group == 'edit':
            raise WorkflowError('--bindは新しいassembly計画で使用します')
        recipe['bindings'] = []
        for cid in args.bind:
            c = find(doc['candidates'], cid)
            if c['kind'] != 'part':
                raise WorkflowError('--bindは部品候補IDを指定します')
            recipe['bindings'].append(dict(part_id=c['part_id'], candidate_id=cid,
                                           location=[0, 0, 0], rotation_degrees=[0, 0, 0], scale=[1, 1, 1]))
    if args.material:
        if stage != 'surface':
            raise WorkflowError('--materialはsurface計画で使用します')
        mapping = {}
        for mid in args.material:
            m = find(doc['materials'], mid)
            if m['part_id'] in mapping:
                raise WorkflowError('同じ部品の材質を重複指定できません')
            mapping[m['part_id']] = mid
        recipe['materials'] = mapping
    if args.group == 'edit' and stage == 'assembly':
        recipe.setdefault('bindings', source.get('composition') if source else None)
        if args.scale:
            if not part_id or args.location or args.rotation:
                raise WorkflowError('限定拡大は--partと--scaleを指定します。位置・回転は新しいassembly計画へ')
            recipe['edit'] = {'part_id': part_id, 'scale_factor': float(args.scale)}
        if not recipe.get('edit'):
            raise WorkflowError('現状の全身編集は--part <部品ID> --scale <倍率>に対応します')
    elif any((args.location, args.rotation, args.scale)):
        if stage != 'assembly' or not part_id or not recipe.get('bindings'):
            raise WorkflowError('配置指定は--bindで部品を割り当て、--partで対象を選んでください')
        binding = next((b for b in recipe['bindings'] if b['part_id'] == part_id), None)
        if not binding:
            raise WorkflowError('配置対象の部品が割当にありません')
        for name, value in (('location', args.location), ('rotation_degrees', args.rotation), ('scale', args.scale)):
            if value:
                binding[name] = [float(x) for x in value.split(',')]
    if not part_id and stage == 'image_prepare':
        structures = [p for p in doc['part_plans'] if p['state'] == 'approved']
        if structures and len(structures[-1]['parts']) == 1:
            part_id = structures[-1]['parts'][0]['id']
        else:
            raise WorkflowError('画像準備の対象を--part <部品ID>で指定してください')
    return wb.plan(pid, stage, args.prompt, args.reference, part_id, args.input, args.source,
                   recipe.get('bindings'), recipe.get('materials'), recipe.get('edit'),
                   getattr(args, 'production', None))


def emit(value, json_output):
    if json_output:
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return
    if isinstance(value, list):
        print(f'件数: {len(value)}')
        for i, item in enumerate(value, 1):
            print(f'\n--- {i} ---')
            emit(item, False)
    elif isinstance(value, dict):
        labels = {'id': 'ID', 'name': '名前', 'goal': '目的', 'state': '状態',
                  'next': '次の操作', 'part_id': '部品ID', 'plan_hash': '計画hash',
                  'shape_confirmed': '形状確定', 'status': '選択状態', 'file': 'ファイル'}
        for key, item in value.items():
            print(f'{labels.get(key, key)}: {json.dumps(item, ensure_ascii=False) if isinstance(item, (dict, list)) else item}')
    else:
        print(value)


def parser():
    p = argparse.ArgumentParser(prog='mwb', description='キャラクター制作管理。作成時は案件ID、以後は対象IDで操作します。')
    p.add_argument('--root', default=str(REPO / 'projects'), help='案件の保存先。既定はリポジトリ内projects')
    p.add_argument('--config', default=str(REPO / 'experiments/config.example.json'), help='外部実行環境のJSON設定')
    p.add_argument('--json', action='store_true', help='機械処理用の全文JSON')
    top = p.add_subparsers(dest='group', required=True)

    def group(name, help_text):
        return top.add_parser(name, help=help_text).add_subparsers(dest='action', required=True)

    def command(g, name, help_text, project=True):
        c = g.add_parser(name, help=help_text)
        if project:
            c.add_argument('project_id', help='完全な案件UUID')
        return c

    status = top.add_parser('status', help='状況と次の操作を表示')
    status.add_argument('project_id', nargs='?')
    cfg = group('config', '外部実行パスと保存先を表示')
    command(cfg, 'show', '設定を表示', False)
    top.add_parser('doctor', help='Blender実行ファイルの存在を調べる。インストール・生成は行わない')
    g = group('project', '案件の作成・一覧・採用・出力')
    c = command(g, 'create', '新しい案件を作成', False)
    c.add_argument('--name', required=True)
    c.add_argument('--goal', '--prompt', dest='goal', required=True)
    c.add_argument('--workflow-version', choices=[2, 3], type=int, default=2,
                   help='新規案件の制作ハーネス版（既定2、v3運用は3）')
    command(g, 'list', '案件一覧', False).add_argument('--terminal', action='store_true')
    command(g, 'show', '案件の全記録を表示')
    command(g, 'resume', '文脈・入力整合性・保留計画・ロックを読み取り専用で確認')
    c = command(g, 'note', '次回のCodexへ引き継ぐ決定・未決事項・次の作業を保存')
    c.add_argument('--kind', choices=['decision', 'open_question', 'next_step'], required=True)
    c.add_argument('--text', '--prompt', dest='text', required=True)
    for action in ('archive', 'set-approved', 'export'):
        c = command(g, action, {'archive': '読取専用にする', 'set-approved': '正式採用を記録', 'export': '選択済み全身候補を原本出力'}[action])
        if action == 'set-approved':
            c.add_argument('candidate_id')
        if action == 'export':
            c.add_argument('--name')
            c.add_argument('--profile', choices=['source'], default='source')
        c.add_argument('--reason', help='会話で確認済みの指示。省略時は端末で対象を確認')

    g = group('reference', '画像の取り込みと役割・方向・優先度')
    for action in ('add', 'update', 'show', 'list'):
        c = command(g, action, action)
        if action == 'add':
            c.add_argument('path')
        if action in ('update', 'show'):
            c.add_argument('reference_id')
        if action in ('add', 'update'):
            c.add_argument('--role', choices=ROLES, required=action == 'add')
            c.add_argument('--description', '--prompt', dest='description', required=action == 'add')
            c.add_argument('--priority', type=int, default=3 if action == 'add' else None)
            c.add_argument('--view', choices=VIEWS, default='unknown' if action == 'add' else None)
        if action == 'update':
            c.add_argument('--reason', required=True)
        if action == 'list':
            c.add_argument('--terminal', action='store_true')

    g = group('requirement', '維持・変更・改善条件と履歴')
    for action in ('add', 'update', 'retire', 'list', 'history'):
        c = command(g, action, action)
        if action in ('update', 'retire'):
            c.add_argument('requirement_id')
            c.add_argument('--reason', required=True)
        if action in ('add', 'update'):
            c.add_argument('--text', '--prompt', dest='text', required=True)
        if action == 'add':
            c.add_argument('--category', choices=['must_keep', 'must_change', 'improve'], required=True)
            c.add_argument('--priority', type=int, default=3)
            c.add_argument('--part')
        if action == 'list':
            c.add_argument('--terminal', action='store_true')

    g = group('animation', 'ver3.5検証用のアニメーション要件入力・確認。モデルは変更しない')
    c = command(g, 'input', '静止候補に対する動作要件を新しい版として保存', project=False)
    c.add_argument('candidate_id')
    inputs = c.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--text', help='必要な動作や保持条件の文章。実行承認とは別')
    inputs.add_argument('--file', help='textとdetailsを持つ構造化要件JSON')
    c = command(g, 'show', '同じ静止候補に対する入力履歴を確認', project=False)
    c.add_argument('candidate_id')

    g = group('part', '部品構成の提案と確認')
    c = command(g, 'plan', '部品構成JSONを新しい版として登録')
    c.add_argument('--file', help='詳細な部品構成JSON。--nameと排他')
    c.add_argument('--name', action='append', help='部品名。複数回指定できる')
    c.add_argument('--reason', '--prompt', dest='reason', required=True)
    c = command(g, 'approve', '部品構成の明示承認')
    c.add_argument('part_plan_id')
    c.add_argument('--hash', help='互換用。省略時も内部で現在の内容hashを検証する')
    c.add_argument('--evidence', help='会話での明示承認。省略時は端末で対象を確認')
    c = command(g, 'list', '構成版・部品の一覧')
    c.add_argument('--terminal', action='store_true')

    g = group('production', 'ver2親計画の固定・承認')
    command(g, 'plan', '制作範囲を固定').add_argument('--file', required=True)
    command(g, 'list', '親計画一覧')
    for action in ('show', 'request-approval', 'approve', 'cancel'):
        c = command(g, action, action, False)
        c.add_argument('production_plan_id')
        if action == 'approve':
            c.add_argument('--evidence')
        if action == 'cancel':
            c.add_argument('--reason', required=True)

    g = group('reference-pack', '部品別の造形用資料パック')
    c = command(g, 'brief', 'Codexの画像生成に渡す部品別資料準備の指示', project=False)
    c.add_argument('production_plan_id')
    c = command(g, 'create', '資料パックを登録')
    c.add_argument('--production', required=True)
    c.add_argument('--file', required=True)
    command(g, 'list', '資料パック一覧')
    for action in ('show', 'request-approval', 'approve'):
        c = command(g, action, action, False)
        c.add_argument('pack_id')
        if action == 'approve':
            c.add_argument('--evidence')

    g = group('quality-issue', '全体比較から抽出した課題と部品修正の追跡')
    c = command(g, 'add', 'レビュー課題を記録', project=False)
    c.add_argument('--production', required=True)
    c.add_argument('--file', required=True, help='title/category/affected_part_ids等を含むJSON')
    c = command(g, 'list', '課題一覧')
    c.add_argument('--production')
    c = command(g, 'evaluate', '候補上での課題解消度を記録', project=False)
    c.add_argument('issue_id')
    c.add_argument('--candidate', required=True)
    c.add_argument('--comparison', required=True)
    c.add_argument('--result', choices=['resolved', 'reduced', 'unchanged', 'regressed', 'unclear'], required=True)
    c.add_argument('--reason', required=True)
    c = command(g, 'next', '候補ごとの未解決課題と修正指示', project=False)
    c.add_argument('--production', required=True)
    c.add_argument('--candidate', required=True)

    g = group('completion', '制作完了候補を1件指定。正式採用とは別の記録')
    c = command(g, 'set', '完成版候補を指定', project=False)
    c.add_argument('--production', required=True)
    c.add_argument('--candidate', required=True)
    c.add_argument('--reason', required=True)
    c = command(g, 'list', '完成候補の変更履歴', project=False)
    c.add_argument('--production', required=True)

    c = command(g, 'show', '現在の完成候補と未完了理由', project=False)
    c.add_argument('--production', required=True)
    g = group('comparison', '同条件の全身・部品レンダーと一次資料の比較')
    c = command(g, 'brief', '候補と参照資料から初回比較条件を作る', project=False)
    c.add_argument('candidate_id')
    c = command(g, 'create', 'Blenderで比較画像を作る', project=False)
    c.add_argument('candidate_id')
    c.add_argument('--file', required=True)
    c = command(g, 'review', '全体・部品・保持・全要件のレビュー', project=False)
    c.add_argument('comparison_id')
    c.add_argument('--file', required=True)
    c = command(g, 'show', '比較条件・画像・レビューを表示', project=False)
    c.add_argument('comparison_id')
    command(g, 'list', '比較記録を一覧')

    for name, kind in [('asset', 'part'), ('image', 'prepared_image')]:
        g = group(name, '既存の部品OBJ／生成用画像の登録')
        c = command(g, 'add' if name == 'asset' else 'register', '入力を検証・コピーし候補として登録')
        c.add_argument('path')
        c.add_argument('--part', required=True)
        c.add_argument('--description', '--prompt', dest='description', required=True)
        if name == 'image':
            c.add_argument('--plan', help='外部で実施した承認済みimage_prepare計画ID')
            c.add_argument('--method', choices=['crop', 'background_removal', 'image_generation', 'external'], default='external')
            c = command(g, 'approve', 'ユーザーが見た生成用画像を資料として承認')
            c.add_argument('candidate_id')
            c.add_argument('--hash', help='互換用のinput_hash')
            c.add_argument('--evidence', help='会話での明示承認。省略時は端末で画像IDとhashを確認')

    g = group('material', '標準材質の作成・版の保持')
    c = command(g, 'create', '色・粗さ・金属度から新しい材質を定義。まだ適用しない')
    c.add_argument('--part', help='省略時はsourceの部品ID')
    c.add_argument('--source', required=True)
    c.add_argument('--name')
    c.add_argument('--color')
    c.add_argument('--file', help='意図・領域・shaderを含むver2材質レシピ')
    c.add_argument('--roughness', type=float, default=0.5)
    c.add_argument('--metallic', type=float, default=0)
    command(g, 'list', '材質一覧').add_argument('--terminal', action='store_true')

    for name in ('generate', 'edit'):
        g = group(name, '固定計画と承認・実行' if name == 'generate' else '親候補からの限定編集計画')
        c = command(g, 'plan', '入力を固定するだけで生成・Blender起動は行わない')
        c.add_argument('--stage', choices=STAGES, help='入力の種類から推定。曖昧なら明示する')
        c.add_argument('--prompt')
        if name == 'generate':
            c.add_argument('--engine', choices=['blender_authoring'])
            c.add_argument('--production')
            c.add_argument('--reference-pack')
            c.add_argument('--file', help='Blender造形レシピJSON')
        c.add_argument('--reference', action='append', default=[])
        c.add_argument('--part')
        c.add_argument('--input')
        c.add_argument('--source', required=name == 'edit')
        c.add_argument('--recipe', help='bindings / materials / editを持つJSON')
        c.add_argument('--bind', action='append', default=[], help='組み立てる部品候補ID。複数回指定')
        c.add_argument('--material', action='append', default=[], help='割り当てる材質ID。複数回指定')
        c.add_argument('--location', help='対象--partの位置 x,y,z（assembly）')
        c.add_argument('--rotation', help='対象--partの回転角 x,y,z（assembly）')
        c.add_argument('--scale', help='generate: x,y,z / edit: 対象--partの拡大率')
        for action in ('show', 'request-approval', 'approve', 'execute', 'cancel', 'list', 'register'):
            if action == 'register':
                c = command(g, action, '承認済み画像準備計画へ外部画像結果を登録', project=False)
                c.add_argument('plan_id')
                c.add_argument('path')
                c.add_argument('--method', choices=['crop', 'background_removal', 'image_generation', 'external'], default='external')
                c.add_argument('--prompt', help='結果の説明。省略時は計画のprompt')
                continue
            c = command(g, action, action)
            if action == 'list':
                c.add_argument('--terminal', action='store_true')
                if name == 'generate':
                    c.add_argument('--stage', choices=(*STAGES, 'inspect'))
                    c.add_argument('--production')
                continue
            c.add_argument('plan_id')
            if action == 'approve':
                c.add_argument('--hash', help='互換用。内部で計画hashを検証')
                c.add_argument('--evidence', help='会話での明示承認。省略時は端末で対象を確認')
            if action == 'cancel':
                c.add_argument('--reason', required=True)

    g = group('candidate', '候補の確認・比較・選択・形状確定')
    c = command(g, 'list', '候補一覧')
    c.add_argument('--kind', choices=['prepared_image', 'part', 'character'])
    c.add_argument('--generation', help='生成計画IDで候補を絞る')
    c.add_argument('--keyword', help='状態キーワードで候補を絞る')
    c.add_argument('--terminal', action='store_true')
    for action in ('show', 'select', 'hold', 'reject', 'confirm-shape'):
        c = command(g, action, action)
        c.add_argument('candidate_id')
        if action == 'show':
            c.add_argument('--trace', action='store_true')
        if action != 'show':
            c.add_argument('--reason', help='会話での判断理由。省略時は端末で対象を確認')
    c = command(g, 'import-blend', 'ユーザー手修正.blendを派生候補として取込')
    c.add_argument('blend_path')
    c.add_argument('--source', required=True)
    c.add_argument('--production', required=True)
    c.add_argument('--file', required=True)
    c = command(g, 'edit-start', '候補IDからBlender MCP編集用コピーを作成', project=False)
    c.add_argument('candidate_id')
    c.add_argument('--production', required=True)
    c.add_argument('--issue', action='append', default=[])
    c = command(g, 'edit-finish', '編集結果を検証し親候補の派生候補として登録', project=False)
    c.add_argument('session_id')
    c.add_argument('--result', required=True, help='Blender MCPで保存した編集後.blend')
    c.add_argument('--file', required=True, help='mode/target_part_ids/changed_by/reason等のedit manifest')
    c = command(g, 'edit-bind', 'MCPが観測したシーン・候補ID・hashを照合', project=False)
    c.add_argument('session_id')
    c = command(g, 'edit-show', '編集セッションの状態とエラーを表示', project=False)
    c.add_argument('session_id')
    c = command(g, 'edit-recover', '登録済み派生候補から中断後のセッションを復元', project=False)
    c.add_argument('session_id')
    c = command(g, 'edit-abandon', '作業ファイルを保持してセッションを終了', project=False)
    c.add_argument('session_id')
    c.add_argument('--reason', required=True)
    c = command(g, 'inspect', '元候補を変更せず追加の4方向点検を作成')
    c.add_argument('candidate_id')
    c.add_argument('--production', required=True)
    c = command(g, 'keywords', '候補の状態キーワード一覧を記録')
    c.add_argument('candidate_id')
    c.add_argument('--keyword', action='append', default=[], help='状態キーワード。複数回指定')
    c.add_argument('--reason', required=True)
    c = command(g, 'compare', '候補IDを2件以上指定。旧構文の先頭案件IDも使用可', project=False)
    c.add_argument('candidate_ids', nargs='+')
    c = top.add_parser('review', help='要件別レビューを保存')
    c.add_argument('project_id', nargs='?', help='旧構文互換。通常は候補IDだけ指定')
    c.add_argument('candidate_id')
    c.add_argument('--file', help='詳細レビューJSON。--requirement等と排他')
    c.add_argument('--requirement', help='評価する要件ID')
    c.add_argument('--result', choices=['pass', 'fail', 'uncertain', 'not_applicable'])
    c.add_argument('--prompt', help='判断理由と総評')
    c.add_argument('--actor', choices=['user', 'codex'], default='user')
    g = group('report', '生成計画・結果・次の操作を表示')
    c = command(g, 'show', '計画と状態・成果物を表示')
    c.add_argument('plan_id')
    # Resource IDs own their project. Keep the old two-ID form as an optional prefix.
    resource_fields = {'reference_id', 'requirement_id', 'part_plan_id', 'candidate_id', 'plan_id',
                       'production_plan_id', 'pack_id', 'issue_id', 'session_id'}
    for group_action in top.choices.values():
        for sub in group_action._actions:
            if isinstance(sub, argparse._SubParsersAction):
                for child in sub.choices.values():
                    fields = {x.dest for x in child._actions}
                    if group_action.prog.endswith(' project') or not fields & resource_fields:
                        continue
                    for field in child._actions:
                        if field.dest == 'project_id':
                            field.nargs = '?'
                            field.help = '旧構文互換。通常は対象IDのみ指定'
    return p


def dispatch(args):
    store = Store(args.root)
    config = load_config(args.config)
    wb = V3Workbench(store, config)
    g, a = args.group, getattr(args, 'action', None)
    pid = getattr(args, 'project_id', None)
    if g == 'candidate' and a == 'compare':
        ids = args.candidate_ids
        if len(ids) >= 3 and (store.directory(ids[0]) / 'project.json').is_file():
            pid, args.candidate_ids = ids[0], ids[1:]
        elif ids:
            pid = owner(store, 'candidates', ids[0])
    if g in ('quality-issue', 'completion') and getattr(args, 'production', None):
        pid = owner(store, 'production_plans', args.production)
    if g == 'quality-issue' and a == 'evaluate':
        pid = owner(store, 'quality_issues', args.issue_id)
    if g == 'candidate' and a in ('edit-finish', 'edit-bind', 'edit-show', 'edit-recover', 'edit-abandon'):
        pid = owner(store, 'edit_sessions', args.session_id)
    if g == 'comparison' and getattr(args, 'comparison_id', None):
        pid = owner(store, 'comparisons', args.comparison_id)
    if pid is None:
        for field, collection in (('plan_id', 'plans'), ('candidate_id', 'candidates'),
                                  ('reference_id', 'references'), ('requirement_id', 'requirements'),
                                  ('part_plan_id', 'part_plans'), ('production_plan_id', 'production_plans'),
                                  ('pack_id', 'reference_packs')):
            target = getattr(args, field, None)
            if target:
                pid = owner(store, collection, target)
                break
    if g == 'config':
        return {'root': str(store.root), 'config_file': str(Path(args.config).resolve()), 'adapters': config}
    if g == 'doctor':
        checks = {key: {'path': value, 'exists': Path(value).exists()} for key, value in config.items()}
        if not all(value['exists'] for value in checks.values()):
            raise WorkflowError('Blender実行ファイルがありません。config showで設定を確認してください')
        return {'checks': checks, 'scope': 'Blender実行ファイルの存在確認のみ。造形品質や互換性全体の保証ではない'}
    if g == 'status':
        return wb.status(pid) if pid else [wb.status(d['id']) for d in store.list()]
    if g == 'project':
        if a == 'create':
            return store.create(args.name, args.goal, args.workflow_version)
        if a == 'list':
            return [{'id': d['id'], 'name': d['name'], 'state': d['state']} for d in store.list()]
        if a == 'show':
            return store.load(pid)
        if a == 'resume':
            return resume(wb, pid)
        if a == 'note':
            if not args.text.strip():
                raise WorkflowError('引き継ぎ内容は空にできません')
            with store.update(pid, 'handoff_note_added') as doc:
                item = record(kind=args.kind, text=args.text)
                doc.setdefault('notes', []).append(item)
            return item
        if a == 'archive':
            args.reason = confirmation('案件をアーカイブ', store.load(pid), args.reason)
            with store.update(pid, 'project_archived') as doc:
                if any(p['state'] in ('running', 'result_unknown') for p in doc['plans']):
                    raise WorkflowError('実行中・結果不明の計画があります')
                doc['state'] = 'archived'
                doc['events'].append(record(reason=args.reason))
            return {'state': 'archived'}
        if a == 'set-approved':
            args.reason = confirmation('全身候補を正式採用', find(store.load(pid)['candidates'], args.candidate_id), args.reason)
            return wb.set_approved(pid, args.candidate_id, args.reason)
        selected = sorted([c for c in store.load(pid)['candidates'] if c['kind'] == 'character' and c['status'] == 'selected'], key=lambda c: c['id'])
        if not selected:
            return {'count': 0, 'message': '選択済み全身候補は0件です'}
        reason = confirmation('選択済み全身候補をsource出力', {'project_id': pid, 'name': args.name, 'candidates': selected}, args.reason)
        return wb.export(pid, args.name, reason, expected_selection=fingerprint(selected))
    if g == 'reference':
        if a == 'add':
            return wb.reference_add(pid, args.path, args.role, args.description, args.priority, args.view)
        if a == 'update':
            return wb.reference_update(pid, args.reference_id, args.reason, role=args.role,
                                       description=args.description, priority=args.priority, view=args.view)
        return store.load(pid)['references'] if a == 'list' else find(store.load(pid)['references'], args.reference_id)
    if g == 'requirement':
        if a == 'add':
            return wb.requirement_add(pid, args.category, args.text, args.priority, args.part)
        if a in ('update', 'retire'):
            return wb.requirement_update(pid, args.requirement_id, args.reason,
                                         getattr(args, 'text', None), a == 'retire')
        return store.load(pid)['requirements']
    if g == 'animation':
        rigging = RiggingLab(store, config)
        if a == 'show':
            return rigging.requirements_show(pid, args.candidate_id)
        value = read(args.file) if args.file else {'text': args.text}
        if not isinstance(value, dict) or set(value) - {'text', 'details'}:
            raise WorkflowError('要件JSONはtextと任意のdetailsを指定します')
        return rigging.requirements_input(pid, args.candidate_id, value['text'], value.get('details'))
    if g == 'part':
        if a == 'plan':
            if bool(args.file) == bool(args.name):
                raise WorkflowError('--nameを1回以上指定するか、--fileのいずれかを指定してください')
            return wb.part_plan(pid, read(args.file) if args.file else [{'name': n, 'description': args.reason} for n in args.name], args.reason)
        if a == 'approve':
            proposal = find(store.load(pid)['part_plans'], args.part_plan_id)
            evidence = confirmation('部品構成案を承認', proposal, args.evidence)
            return wb.part_approve(pid, args.part_plan_id, args.hash or proposal['content_hash'], evidence)
        return store.load(pid)['part_plans']
    if g == 'production':
        if a == 'plan':
            return wb.production_plan(pid, read(args.file))
        if a == 'list':
            return store.load(pid).get('production_plans', [])
        item = find(store.load(pid).get('production_plans', []), args.production_plan_id)
        if a == 'show':
            return item
        evidence = (confirmation('制作計画と部品構成を承認', item, args.evidence)
                    if a == 'approve' else args.reason if a == 'cancel' else None)
        return wb.production_transition(pid, args.production_plan_id, a, evidence)
    if g == 'reference-pack':
        if a == 'brief':
            return wb.reference_brief(pid, args.production_plan_id)
        if a == 'create':
            return wb.reference_pack_create(pid, args.production, read(args.file))
        if a == 'list':
            return store.load(pid).get('reference_packs', [])
        item = find(store.load(pid).get('reference_packs', []), args.pack_id)
        if a == 'show':
            return item
        evidence = confirmation('全部品の造形用資料パックを承認', item, args.evidence) if a == 'approve' else None
        return wb.reference_pack_transition(pid, args.pack_id, a, evidence)
    if g == 'quality-issue':
        if a == 'next':
            return wb.repair_queue(pid, args.production, args.candidate)
        if a == 'add':
            return wb.quality_issue_add(pid, args.production, read(args.file))
        if a == 'evaluate':
            return wb.quality_issue_evaluate(pid, args.issue_id, args.candidate, args.result, args.reason, args.comparison)
        issues = store.load(pid).get('quality_issues', [])
        return [i for i in issues if not args.production or i['production_plan_id'] == args.production]
    if g == 'completion':
        if a == 'show':
            return wb.completion_status(pid, args.production)
        if a == 'set':
            return wb.completion_set(pid, args.production, args.candidate, args.reason)
        return [x for x in store.load(pid).get('completion_history', [])
                if x['production_plan_id'] == args.production]
    if g == 'comparison':
        if a == 'brief':
            return wb.comparison_brief(pid, args.candidate_id)
        if a == 'create':
            return wb.comparison_run(pid, args.candidate_id, read(args.file))
        if a == 'review':
            return wb.comparison_review(pid, args.comparison_id, read(args.file))
        comparisons = store.load(pid).get('comparisons', [])
        return find(comparisons, args.comparison_id) if a == 'show' else comparisons
    if g in ('asset', 'image'):
        if g == 'image' and a == 'approve':
            image = find(store.load(pid)['candidates'], args.candidate_id)
            evidence = confirmation('この画像を造形資料として承認（画像を実際に見てから回答）', image, args.evidence)
            return wb.image_approve(pid, args.candidate_id, args.hash or fingerprint(image['files']), evidence)
        item = wb.candidate_import(pid, args.path, 'part' if g == 'asset' else 'prepared_image', args.part,
                                   args.description, getattr(args, 'plan', None), getattr(args, 'method', 'external'))
        return dict(item, input_hash=fingerprint(item['files'])) if g == 'image' else item
    if g == 'material':
        if a == 'list':
            return store.load(pid)['materials']
        source = find(store.load(pid)['candidates'], args.source)
        if args.file:
            if any((args.name, args.color, args.part)):
                raise WorkflowError('--fileと簡易材質指定は併用できません')
            return wb.material_recipe_create(pid, args.source, read(args.file))
        if not args.name or not args.color:
            raise WorkflowError('簡易材質には--nameと--colorが必要です')
        return wb.material_create(pid, args.part or source['part_id'], args.source, args.name,
                                  [float(x) for x in args.color.split(',')], args.roughness, args.metallic)
    if g in ('generate', 'edit'):
        if a == 'plan':
            if g == 'generate' and args.engine == 'blender_authoring':
                if args.stage != 'geometry' or not all((args.production, args.reference_pack, args.part, args.file)):
                    raise WorkflowError('Blender造形には--stage geometry、--production、--reference-pack、--part、--fileが必要です')
                return wb.geometry_plan(pid, args.production, args.reference_pack, args.part,
                                        read(args.file), source_id=args.source)
            if not args.prompt:
                raise WorkflowError('従来方式の計画には--promptが必要です')
            return make_plan(wb, store, pid, args)
        if a == 'register':
            plan = find(store.load(pid)['plans'], args.plan_id)
            image = wb.candidate_import(pid, args.path, 'prepared_image', plan['fixed']['part_id'],
                                        args.prompt or plan['fixed']['prompt'], plan['id'], args.method)
            return dict(image, input_hash=fingerprint(image['files']))
        if a == 'list':
            return [p for p in store.load(pid)['plans']
                    if (not getattr(args, 'stage', None) or p['fixed']['stage'] == args.stage)
                    and (not getattr(args, 'production', None) or p.get('production_plan_id') == args.production)]
        if a == 'show':
            return find(store.load(pid)['plans'], args.plan_id)
        if a == 'execute':
            result = execute(wb, pid, args.plan_id, config)
            if result.get('state') == 'blocked':
                raise WorkflowError(result['error'])
            return result
        expected, evidence = getattr(args, 'hash', None), getattr(args, 'evidence', None) or getattr(args, 'reason', None)
        if a == 'approve':
            plan = find(store.load(pid)['plans'], args.plan_id)
            evidence = confirmation('この固定計画を承認（実行開始とは別）', plan, evidence)
            expected = expected or plan['plan_hash']
        return wb.transition(pid, args.plan_id, a, expected, evidence)
    if g == 'candidate':
        candidates = store.load(pid)['candidates']
        if a == 'edit-bind':
            return wb.candidate_edit_session_bind(pid, args.session_id)
        if a == 'edit-show':
            return find(store.load(pid).get('edit_sessions', []), args.session_id)
        if a == 'edit-recover':
            return wb.candidate_edit_session_recover(pid, args.session_id)
        if a == 'edit-abandon':
            return wb.candidate_edit_session_abandon(pid, args.session_id, args.reason)
        if a == 'edit-start':
            return wb.candidate_edit_session_start(pid, args.production, args.candidate_id, args.issue)
        if a == 'edit-finish':
            return wb.candidate_edit_session_finish(pid, args.session_id, read(args.file), args.result)
        if a == 'import-blend':
            return wb.revision_run(pid, args.source, args.production, read(args.file), args.blend_path)
        if a == 'inspect':
            return wb.revision_run(pid, args.candidate_id, args.production)
        if a == 'keywords':
            return wb.candidate_keywords(pid, args.candidate_id, args.keyword, args.reason)
        if a == 'list':
            return [c for c in candidates if (not args.kind or c['kind'] == args.kind)
                    and (not args.generation or c.get('generation_id') == args.generation)
                    and (not args.keyword or args.keyword in c.get('state_keywords', []))]
        if a == 'show':
            item = find(candidates, args.candidate_id)
            if args.trace:
                return wb.candidate_trace(pid, args.candidate_id)
            return dict(item, input_hash=fingerprint(item['files'])) if item['kind'] == 'prepared_image' else item
        if a == 'compare':
            if len(args.candidate_ids) < 2:
                raise WorkflowError('比較には2件以上の候補が必要です')
            return [{'candidate': c, 'preview_paths': [str(store.path(pid, f['file'])) for f in c['files'] if f['file'].endswith('.png')]}
                    for c in [find(candidates, cid) for cid in args.candidate_ids]]
        reason = confirmation('候補の判断を記録: ' + a, find(candidates, args.candidate_id), args.reason)
        return wb.candidate_state(pid, args.candidate_id, a, reason)
    if g == 'review':
        if args.file and any((args.requirement, args.result, args.prompt)):
            raise WorkflowError('--fileと簡易レビュー指定は併用できません')
        if not args.file and not all((args.requirement, args.result, args.prompt)):
            raise WorkflowError('--requirement・--result・--promptを指定するか、--fileを使用してください')
        review = read(args.file) if args.file else {'entries': [{'requirement_id': args.requirement, 'result': args.result, 'reason': args.prompt}], 'summary': args.prompt}
        return wb.review(pid, args.candidate_id, review['entries'], review['summary'], args.actor)
    if g == 'report':
        return {'plan': find(store.load(pid)['plans'], args.plan_id), 'status': wb.status(pid)}
    raise WorkflowError('未対応コマンド')


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    args = parser().parse_args(argv)
    try:
        result = dispatch(args)
        emit(result, args.json)
        return 0
    except KeyboardInterrupt:
        print('中断しました。保存状態とプロセスを確認してください。', file=sys.stderr)
        return 130
    except (WorkflowError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f'操作を停止しました: {exc}', file=sys.stderr)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
