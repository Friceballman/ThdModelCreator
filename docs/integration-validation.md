# TripoSR → Blender 接続検証

作成日：2026-10-18。

## 目的と現在の優先順位

設計書ver1.0の正式なUX・管理CLIより先に、既存TripoSRとBlenderを使って以下の処理が成立するかを確認する。今回の指示による検証用の足場であり、設計書第16章の全項目が承認・実装済みになったことを意味しない。

1. 単一画像からTripoSRでOBJを生成する（承認した実生成のある場合）。
2. 対象OBJと対照OBJを別部品IDのままBlenderへ取り込む。
3. 位置・回転・スケールを指定して組み立て、変更前の.blendを保存する。
4. 指定した部品だけを10%拡大し、他部品を保持する。
5. 同じ4方向のカメラから変更前後をレンダリングする。
6. 変更後の.blendとOBJを書き出し、両.blendと出力OBJを再読み込みする。
7. 部品単位の形状hash・変換、検査結果、処理ログ、成果物hashを保存する。

公式の椅子を2つの部品として使うのは、部品識別・配置・保持の検査を切り分けるため。身体や帽子の形状を生成した試験ではない。

## 実行環境

- 実験ランナー：Python標準ライブラリのみ。既存TripoSRのPython 3.11をそのまま利用可能。
- 形状生成：既存TripoSRのPython・torch・モデル重み。
- 取り込み・編集・描画：既存Blenderの内蔵Python。
- 設定例：`experiments/config.example.json`。

個人環境のパスを変える場合は設定例を `experiments/config.local.json` にコピーし、各コマンドへ `--config experiments/config.local.json` を指定する。設定内の相対パスは設定ファイルの場所、レシピ内の相対入力パスはレシピの場所が基準。絶対パスも許可する。

既存環境を移動・更新しない。推論には既存のHugging Face・U2Netキャッシュを指定する。Hugging Faceはオフラインモードで実行し、必要な重みや設定がなければ失敗する。U2Netも既存のキャッシュを使う。初回取得が必要な場合は別途確認し、勝手に導入や再ダウンロードをしない。

## 検証用のファイル

| ファイル | 役割 |
| --- | --- |
| `scripts/validate_flow.py` | 入力検証、計画固定、順次外部実行、保存、ログ、hash |
| `scripts/triposr_probe.py` | 既存run.pyの実行、CUDAと生成メッシュの確認、GPUピーク計測 |
| `scripts/blender_flow_probe.py` | 部品ID保持、配置、対象の拡大、保存・描画・再読み込み |
| `experiments/recipes/reuse-chair.json` | 新規生成なし。既存椅子OBJを2部品として使う |
| `experiments/recipes/generate-chair.json` | 公式椅子画像から1回生成し、既存椅子OBJを対照部品に使う |
| `tests/test_validate_flow.py` | 計画・承認hash・入力変更・不正入力等の非生成テスト |

## 手順

以下はリポジトリ直下のPowerShell用。実行例のパス・hashは各自のplan出力で置き換える。

### 1. 存在確認

```powershell
$ProbePython = 'C:\AI_test\TripoSR\.venv\Scripts\python.exe'
& $ProbePython -B scripts/validate_flow.py doctor
```

doctorが調べるのは実行ファイル・ルート・キャッシュの存在。版の互換性やキャッシュ内の全モデルの完全性までは保証しない。版とCUDAの実動作は実行ログで確認する。

### 2. 既存OBJで計画を作る

```powershell
& $ProbePython -B scripts/validate_flow.py plan --recipe experiments/recipes/reuse-chair.json
```

planは入力と実験スクリプト、既存TripoSRのrun.pyのSHA-256、部品構成、対象編集、設定を固定し、`experiments/plans/<id>.json` を保存する。生成・Blender起動は行わない。表示されるnew_generationsは0。

### 3. 内容確認後に実行

```powershell
$PlanPath = 'experiments/plans/planで表示されたID.json'
$PlanHash = 'planで表示されたplan_hash'
& $ProbePython -B scripts/validate_flow.py run --plan $PlanPath --approve-plan $PlanHash
```

`--approve-plan` は、その計画を会話・運用上で明示承認した後にだけ渡す。本人認証や改ざん防止の署名ではない。hash一致を確認するローカルの誤実行防止策。

入力・コードが計画作成後に変わった場合は実行を拒否する。既に実行した計画は再実行しない。失敗後も状態・ログを確認してから新しい計画を作り直す。

### 4. 新規生成を含む接続確認

```powershell
& $ProbePython -B scripts/validate_flow.py plan --recipe experiments/recipes/generate-chair.json
```

この計画は公式chair.pngの生成を**1回**、CUDA、chunk_size=1024、mc_resolution=128、頂点カラーOBJ、テクスチャベイクなしで実行する。対照部品は既存OBJなので生成しない。計画確認・承認後に手順3のrunへ渡す。

この初期実験ではchunk_sizeを1024以下、mc_resolutionを128以下に制限する。GPUやCUDAカーネルが利用できない場合はCPUへ自動切替しない。OOM時も勝手に設定を下げて再生成しない。

### 5. 自動テスト

```powershell
& $ProbePython -B -m unittest discover -s tests -v
```

自動テストはBlender・TripoSR・画像生成を起動せず、試験用ファイルだけを使う。

## 成果物と確認箇所

実行ごとに新しいUUIDの `experiments/runs/<run-id>/` を作る。

```text
plan.json                       固定入力と計画hash
status.json                     running / succeeded / failed / interrupted、段階ごとの時間とログ
parts/<part-id>/source.*         入力のコピー
parts/<part-id>/generated/       新規生成した場合のOBJ・前処理画像・metrics.json
blender-job.json                 固定された部品配置と編集
baseline.blend                  修正前原本
edited.blend                    派生した修正後原本
edited.obj                      書き出し結果
baseline-{front,side,back,perspective}.png
edited-{front,side,back,perspective}.png
blender-check.json              形状・変換・保持・再読込の検査
triposr-<part-id>.log            新規生成時のみ
blender.log
manifest.json                   成功時の成果物一覧とSHA-256
```

- `status.json` のsucceededはこの技術試験の合格。キャラクター品質・正式採用・UE確認を表さない。
- `blender-check.json` のpreserved_partsで対照部品が保持されたことを確認する。
- target_edit_correctは対象のメッシュ・位置・回転を保持し、指定倍率のscale変更だけを行った検査。
- baseline_reload / edited_reloadは.blend再読み込み後の部品構造の一致。
- export_obj_reloadはOBJの再読み込み後の頂点・面数一致。表面接合やUV・材質の整合性まで保証する検査ではない。
- metricsのsecondsはtorch等の初期import・親ランナーの起動時間を含まない。stagesのsecondsはサブプロセスの起動から終了まで。GPUピークはPyTorchの割当・予約の値で、PC全体のVRAM使用量ではない。
- 対象の拡大はオブジェクト変換。メッシュを縫合したり、関節の形状を修正したりする試験ではない。

manifestは成果物・計画・実行ログを対象にし、更新するstatus自身とNumbaの作業キャッシュは含めない。実行状態はstatusで別途確認する。ログや成果物はGit管理しないため、必要な証跡はrunフォルダ全体を別途保管する。

## 失敗・中断時

- ログと入力コピーは残し、失敗を成功と扱わない。入力・出力を自動で上書き・削除しない。
- 外部処理の制限時間は各段階30分。中断・タイムアウト時は起動した子プロセスの停止を試みて待機する。
- 実験全体の `experiments/runs/.execution.lock` で同時実行を拒否する。異常終了で残った場合、自動で奪わない。
- 停止後も子孫プロセスが残っていないか確認する。プロセスの終了が確認できない場合やPC強制終了時の復旧は自動化していないため、再実行せず状態とログを照合する。
- 実験段階では失敗時の終了コードは1、中断は130。正式CLIの終了コード設計・結果不明解消コマンドは未実装。

## 入力と範囲の制限

- 初期の既存資産入力は、材質依存を持たない通常のOBJだけ。mtllib / usemtl等は依存を黙って落とさず拒否する。
- リンク・ジャンクション、部品IDの重複、パストラバーサルを拒否する。信頼済みのローカル設定・レシピを使用する。
- 1OBJにつき1メッシュを要求し、部品IDをオブジェクト属性に保持する。
- Blenderは背景・factory-startup・disable-autoexecで起動する。編集処理は検証スクリプトに書かれた拡大だけで、任意Pythonコードをレシピから実行しない。
- 単位はメートル・Z上・正面-Yの技術試験上の取り決め。実寸やキャラクターの向きが画像から決まったとは扱わない。
- 身体ベース、帽子等の実際の生成用画像、接続アンカー、部品のフィット、表面接合、PBR、リグ、アニメーション、UEは次の検証課題。

最初の接続試験後は、実際のキャラクター資料と身体ベース方針を決め、「身体＋帽子等の1部品」の品質・フィット・修正工数の検証へ進む。
