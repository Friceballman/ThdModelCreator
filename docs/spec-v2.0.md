# 仕様書 ver2.0｜Blender直接造形型キャラクター制作ハーネス

作成日：2026-10-19。状態：実装用仕様。実装・実機検証の完了を意味しない。

本書は[ver2.0構想](design-v2.0.md)を実装可能な契約へ具体化したもの。衝突する箇所は本書を優先する。企画の目的、元資料・過去候補の保全、CLIを正本とする管理、レビューと正式採用の分離、source出力、UE・動作の段階的検証はver1.0から維持する。ver1.0の当初仕様書に記載された未実装の案を、現在の機能と混同しない。

## 1. 対象と完了条件

対象は単一ユーザーのWindowsローカル制作。二次元資料を元に、CodexがBlender 5.2系の操作スクリプトを作成・実行して部品形状を制作し、仮組み、材質、静止全身候補、名前付きsource出力まで扱う。Blenderを唯一の3D実行先とし、任意のキャラクターの品質は保証しない。旧案件の記録は読めるが、旧式の造形計画は再実行しない。

本版の「完成候補」は、部品の形状、配置、材質、4方向の確認画像、検査と由来を保存した静止モデルを指す。リグ、関節変形、UE上の表示・動作、UV・ベイク、精密な顔や指は完成条件に含めない。必要なら別工程として計画し、未検証をmanifestへ表示する。

## 2. 利用者との契約

通常の一巡で利用者が関わる場面は、案件立ち上げ、画像インポート、タグ付け、制作計画、全部品の造形用資料パック確認、完成候補確認の六つ。前四つは一つの会話でまとめられる。Codexは部品分解、画像準備、造形、仮組み、材質、自己点検を承認範囲内で進める。途中の成果は常時一覧・閲覧可能だが、通常は工程ごとの追加承認を求めない。

ユーザーは制作計画で、目的・用途、保持／変更／改善条件、対象部品、許す制作方法と修正範囲、試行上限、造形の面数目標、材質の扱い、source出力を確認する。造形用資料パックでは、部品別の資料画像・図面、寸法・接続、推定を確認する。完成候補では、全身と任意の途中工程IDを見て修正対象・選択・保留・正式採用・出力を指示する。

範囲外の部品追加、元資料の変更、別の3D生成サービスへの切替、確認済み資料パックの差替え、試行上限超過、利用条件不明の資産採用は自動実行しない。明示されたユーザーの修正指示が具体的な計画を特定できる場合は、その発言を承認根拠として新計画を記録し、同じ確認を繰り返さない。対象や範囲が曖昧な場合だけ確認する。沈黙を承認にしない。

## 3. 基本データ契約

案件の正本は `projects/<project-id>/project.json`。`schema_version=1` と既存配列 `references / requirements / part_plans / plans / candidates / materials / reviews / exports / events / notes` を維持する。新規案件には `workflow_version=2` と `production_plans=[]`、`reference_packs=[]` を追加する。旧案件で新項目がない場合は空配列・ver1として読み、読み取りだけで書き換えない。新規の操作を行ったときに必要な項目だけ加える。ver1 CLIでver2案件を編集する互換性は保証しない。

全ての記録はUUID v4の完全なID、案件ID、UTC日時を持つ。ファイル参照は案件ルート相対のPOSIX形式とSHA-256。案件外への参照、リンク・ジャンクション、上位移動は拒否する。外から持ち込むファイルは検証して案件へコピーする。元資料、承認済み資料パック、登録済み候補、出力を上書きしない。索引の更新は案件単位ロック、回復チェックポイント、原子的な保存を使う。

部品IDは身体・帽子等の継続する対象、部品候補IDはその版。Blender内で一部品が複数オブジェクトでも同一部品IDを付け、各オブジェクトに `mwb_part_id`、`mwb_source_candidate_id`、`mwb_object_role` を保存する。全身候補は部品候補ID、変換、接続方式、材質IDのスナップショットを持つ。後から選択部品が変わっても過去候補には反映しない。共通座標は右手系、Z上、正面-Y、単位m。実寸が不明なら推定根拠を記す。

## 4. 制作計画（親計画）

親計画は `production_plans[]` に保持する。必須の固定内容は `project_id`、`part_plan_id` とその内容hash、使用する参照ID・版・ファイルhash、要件ID・版、`scope`、`deliverables`、`approval`。`scope` には対象部品ID、許す工程（image_prepare / geometry / assembly / surface / inspect / source_export）、造形方式 `blender_authoring`、対象外、保持条件を入れる。既存OBJの取り込みは入力資料であり、造形エンジンではない。

試行上限は `max_reference_drafts_per_part`、`max_geometry_runs_per_part`、`max_assembly_runs`、`max_surface_runs` の正整数で指定する。計画の作成・承認・取消は消費せず、実行が `running` に遷移したときだけ一回消費する。`succeeded / failed / result_unknown` も消費済みとして数え、実行前に拒否された計画は数えない。実行開始直前に上限を再検査する。`result_unknown` は調査が終わるまで枠を保持する。部品ごとに `target_faces` と `max_faces`、見た目の判定観点、許す処理時間の目安を記す。共通の固定面数や品質点数は設けない。Codexが案件の用途と部品の見え方から値を提案し、ユーザーが親計画で確認する。

`production plan --file` の入力は次の形とし、ID・版・hashはCLIが登録時に確定する。以下の数値は形式例であり、案件の合格値ではない。

```json
{
  "part_plan_id": "<approved-part-plan-id>",
  "reference_ids": ["<reference-id>"],
  "requirement_ids": ["<requirement-id>"],
  "scope": {
    "part_ids": ["<body-part-id>", "<hat-part-id>"],
    "stages": ["image_prepare", "geometry", "assembly", "surface", "inspect", "source_export"],
    "geometry_engines": ["blender_authoring"],
    "allowed_edits": ["part_shape", "part_transform", "material_parameters"],
    "max_reference_drafts_per_part": 2,
    "max_geometry_runs_per_part": 3,
    "max_assembly_runs": 2,
    "max_surface_runs": 2,
    "face_limits": {"<body-part-id>": {"target_faces": 3000, "max_faces": 6000}},
    "must_preserve": ["<requirement-id>"],
    "excluded": ["ue_export"]
  },
  "deliverables": ["editable_blend", "obj", "four_view_previews", "source_export"],
  "reason": "制作対象と保持条件を記述"
}
```

親計画の状態は `draft → awaiting_approval → approved`、実行前は `cancelled` にできる。親計画自体は外部処理を走らせず、進捗は子計画から算出する。承認では表示した固定内容のhashと会話上の承認根拠を保存する。承認後の固定内容は変更せず、範囲変更は新しい親計画IDを作る。部品構成案は親計画に版を固定し、従来の `part approve` を同じユーザー判断に紐づけて記録する。二度の独立した確認操作を要求しない。

## 5. 造形用資料パック

`reference_packs[]` は `id / production_plan_id / part_plan_id / parent_pack_id / parts / files / content_hash / state / approval` を持つ。部品ごとの `parts` には部品ID、使う元資料IDと領域、優先順位、方向別画像または構築図、寸法・比率、接続アンカー、色・模様の領域、各方向の整合所見、推定と未確定事項を必須とする。画像には `method=original / crop / background_removal / image_generation / drawing / external` と由来を記す。元資料から派生した画像は元資料を置き換えない。

正面・側面・背面等のうち造形に必要な方向を部品ごとに選ぶ。単純な球などは寸法付き構築図でよい。画像生成で補った背面や隠れた断面は `inferred=true` とし、根拠と確信度ではなく具体的な不確実性を書く。矛盾する正面・側面の輪郭、寸法、材質領域はパック承認前に列挙する。各方向の資料は由来と推定の有無を個別に管理する。

Codexは必要な画像準備を実施し、外部画像生成ツールを使った場合も入力、処理方法、結果ファイルhashをCLIで登録する。画像生成アダプタがハーネス内にあるとは仮定しない。作成したパックは全対象部品を一括提示する。ユーザー承認後は `state=approved` と内容hashを保存する。変更時は新IDのパックを作り、旧パックと旧候補を残す。造形子計画の作成・実行時には、承認済みパックIDと一致するファイルhashが必須。

資料パックのmanifestでは画像の実ファイルを案件相対パスで指定する。元画像と生成画像は同じ項目に由来を併記し、`inferred` と `uncertainties` を省略しない。CLIは対象部品の漏れ、参照IDの不在、画像のデコード失敗、hash不一致、承認済み部品構成との不一致を拒否する。

## 6. 子計画と承認の継承

子計画は従来の `plans[]` に保持し、`production_plan_id`、必要なら `reference_pack_id`、`part_id`、`stage`、親候補ID、入力とコードのhash、Blender job／レシピ、出力予定、保持検査を固定する。`stage` は既存の image_prepare / geometry / assembly / surface を維持し、読み取り対象から追加画像・検査を作る `inspect` を追加する。新規造形は `stage=geometry, engine=blender_authoring` のみ。旧計画の `engine` 欄がない記録も読み取るが実行は拒否する。`source_export` は親計画の許可範囲に含めるが、既存 `project export` で実行し、子計画のstageにはしない。

子計画は作成時に親計画の承認、対象部品・工程・方式、試行枠、参照・要件・部品構成、資料パックとそのhashを検査する。実行直前にも全て再検査する。適合した子計画の `state` は `approved` にし、`approval.kind=parent_scope`、親計画ID・親計画hash・資料パックID・資料パックhashを保存する。この記録は個別のユーザー承認を意味しない。親計画なしのver1互換経路は、従来どおり個別承認を要求する。二つの承認方式を混同しない。

実行状態は `approved → running → succeeded / failed / blocked / result_unknown`。同じ計画の二度目の実行、未承認・hash変更・案件違いは拒否する。失敗後の再試行は親計画の枠が残る場合も新子計画IDを作る。子計画の作成・承認ではBlenderやGPUを起動しない。

## 7. Blenderによる部品造形

Codexは資料パックから輪郭、特徴点、比率、厚み、接続位置、見せる方向を抽出し、最少の部品・面で仮形状を作る。プリミティブ、回転体、押し出し、カーブ、手作成メッシュ、既存の利用可能な身体ベースのどれを使うかを子計画のレシピへ明記する。身体・腕・脚は変形と見た目を考慮して連続形状を基本とし、面数だけを理由に細分化しない。帽子・装備等は独立オブジェクトにできる。

Blender Pythonによる一回の実行には `runs/<run-id>/action.py` と `job.json` を置き、実行したBlenderの版、引数、入力、パラメータ、スクリプトhash、ログを保存する。新しい子計画の作成時にrun IDとフォルダを予約してスクリプト・固定計画を置くが、この時点ではBlenderを起動しない。取消した計画のrunも証跡として残す。既存 `blender_workbench.py` は仮組み・材質の機能を維持し、造形は専用アダプタから固定済み `action.py` を実行する。実行は明示パスのBlenderをbackgroundで呼び、`--factory-startup --disable-autoexec --python-exit-code 1` を使う。スクリプトの計画時hashと実行直前hashが一致しなければ停止する。修正時は既存候補を読み込み可能だが、元ファイルを上書きせず新しいrunに別名保存する。

各造形試行では資料パックの寸法・方向・推定を参照し、構造と面数を検査する。面数削減で必要な輪郭を失う場合は面を残す。`target_faces` は努力目標、`max_faces` は超過時に候補登録を止める上限。部品候補には編集可能な `.blend`、交換用OBJ、intent、checksを登録し、部品単体の確認画像は標準生成しない。最終の材質適用済み全身候補で正面・側面・背面・斜めの4方向をレンダーし、見た目をCodexが実際に確認して評価する。見られなければ `uncertain` とする。必要な場合に限り `inspect` で追加レンダーを明示実行できる。

構造検査は少なくとも、空でないメッシュ、有限値、面インデックス、部品ID、軸・単位、境界箱、面数、欠損・重複の診断を行う。非多様体辺、穴、自己交差は用途に応じて評価し、`watertight=False` だけで不合格としない。陰影のスムーズ化と頂点位置を変える形状平滑化は別の操作名・レシピ・候補として記録する。

## 8. 仮組み・手動修正・材質

仮組みは承認された部品候補を部品IDごとに一度だけ割り当て、位置・回転・スケール、接続先とアンカーを固定する。全身は別オブジェクトを保持し、配置と表面接合を混同しない。仮組み子計画は部品ID・構成・非空メッシュ・保存後再読込・保持条件を機械検査し、新しいcharacter候補を作る。通常はここで見た目確認用画像を生成しない。親計画内の反復ならCodexが配置を調整できる。

ユーザーがBlenderで配置を手修正した場合は、作業ファイルを新しいrunへコピーして取り込む。対象の親全身候補ID、変更対象部品、変更前後の変換、変更者、理由を必須とする。各オブジェクトの部品IDを照合し、申告していない部品の形状・材質・変換が変わった場合は停止する。手修正で元の登録済み `.blend` が上書きされた場合はhash不一致を報告し、元候補が不変だったと扱わない。正常に取り込めたときだけ派生character候補として登録する。

部品単体の手修正 `.blend` も同じ取込経路を使い、親part候補と対象部品IDを指定して派生part候補にする。手修正は対応する造形または仮組みの試行枠を一回消費する。材質だけの手修正はsurfaceの試行枠に数える。どの種類か判定できないファイルは自動登録しない。

形状確定はユーザーの最終採用ではなく、材質工程へ進む内部の形状版の固定。仮組み候補の `checks.json` に `success=true` が記録され、ファイルhashが一致する場合に `shape_confirmed` を設定できる。これは構造ゲートであり、見た目の合格を意味しない。要件別の見た目自己点検とユーザーレビューは通常、材質適用後の全身候補について記録する。

材質レコードは `material_id / part_id / source_shape_candidate_id / name / intent / reference_regions / shader / zones / provenance` を持つ。標準はPrincipled BSDFの色・roughness・metallicと、必要な場合のプロシージャル模様・微細凹凸。複数色の帯などは一部品内の材質領域として扱える。領域の生成方法と推定はintentへ記録する。画像テクスチャ・UV・ベイクを使う場合は親計画と子計画へ明記する。異なる形状版への材質の誤適用を拒否する。Workbenchの色表示だけで最終質感を合格にせず、材質確認画像と設定値を照合する。.blendが編集原本であり、OBJ/MTLがノード材質を完全再現するとは扱わない。

## 9. 候補、レビュー、修正、出力

候補の `state_keywords` は状態を短い語句の配列として保持し、`candidate list --keyword` で絞り込み、`candidate keywords --keyword ... --reason` で履歴付き更新を行う。各語句は1〜64文字、最大32個、重複・制御文字は不可。前候補の造形修正は `generate plan --source <candidate-id>` と `change_keywords` を使い、同じ親計画・資料パック・部品の候補だけを修正元にできる。元の `.blend` を読み込んで新しいrunへ別名保存し、親候補ID、修正前後の状態語句、変更語句を記録する。旧候補および下流候補は自動で上書き・置換しない。造形スクリプトはユーザー権限で動く信頼済みのローカルコードのみ指定する。hash検査は改変検知であり、OS権限の隔離ではない。

候補種別 `prepared_image / part / character`、状態 `pending / selected / on_hold / rejected`、親候補ID、plan ID、run IDを維持する。部品候補と全身候補のファイルは案件ルート相対パスとhashで追跡する。`inspect` は元候補を上書きせず、新しいrunのプレビュー・checksを候補の `inspection_run_ids` に追加する。Codexの自己点検とユーザーのレビューは別記録にし、要件ごとに `pass / fail / uncertain / not_applicable`、理由、確認方向、画像IDを保存する。自動検査の合格を審美的な合格やユーザーの承認に読み替えない。

完成候補の提示では、全身4方向画像と `.blend`、部品構成版、資料パックID、部品候補ID、組み立ての変換、材質IDと狙い、要件別の自己点検、未確認事項を一覧できる。ユーザーの「帽子の背面を修正」「帯の色のみ変更」などは、対象工程へ戻る新子計画または新親計画になる。変更した資料パック・部品・材質から影響する下流候補を再点検し、旧候補を上書きしない。

`candidate select` と `project set-approved` は別操作とし、ver2の正式採用は材質適用済み・親計画の全要件に対するユーザー最終レビュー済み・selectedの全身候補を最大1件。通常の `project export --name` はselectedのcharacter全件だけを対象にし、画像・part候補を混ぜない。出力ごとに新しいexport IDを作り、`.blend`、OBJ/MTL（表現可能な範囲）、プレビュー、checks、composition、依存ファイル、材質の個別レシピ、出所とhashを含むmanifestを同梱する。未確認のUE・リグ・動作はmanifestに明記する。

## 10. CLIの追加・互換

既存 `mwb` と対象IDだけのshow／approve／executeを維持する。追加する外部コマンドは次を標準形とする。`--json`、`--root`、`--config` は従来どおりサブコマンドの前に置く。`--file` はUTF-8 JSONを読み、正本JSONを手編集させない。

```powershell
mwb production plan <project-id> --file <production-plan.json>
mwb production list <project-id>
mwb production show <production-plan-id>
mwb production request-approval <production-plan-id>
mwb production approve <production-plan-id>
mwb production cancel <production-plan-id> --reason <text>
mwb reference-pack create <project-id> --production <production-plan-id> --file <pack-manifest.json>
mwb reference-pack list <project-id>
mwb reference-pack show <pack-id>
mwb reference-pack request-approval <pack-id>
mwb reference-pack approve <pack-id>
mwb generate list <project-id> --stage <stage> --production <production-plan-id>
mwb generate plan <project-id> --stage geometry --engine blender_authoring --production <production-plan-id> --reference-pack <pack-id> --part <part-id> --file <recipe.json>
mwb generate execute <plan-id>
mwb candidate import-blend <project-id> <blend-path> --source <part-or-character-candidate-id> --production <production-plan-id> --file <edit-manifest.json>
mwb material create <project-id> --source <part-candidate-id> --file <material-recipe.json>
mwb candidate show <candidate-id> --trace
```

`production approve` と `reference-pack approve` は対象とhashを表示して確認を記録する。Codexによる非対話操作では実際の会話承認を `--evidence` で渡す。対象IDが見つからない、複数案件で曖昧、hashが変わった場合は停止する。既存 `generate` / `edit` / `candidate` / `material` / `review` / `project export` のうち造形以外の操作と履歴閲覧を維持し、親計画に紐づく子計画だけ承認継承を許す。旧式の造形計画は作成・実行しない。`generate list --stage image_prepare` で画像準備計画を探せるようにする。

`material-recipe.json` は少なくとも `name`、`intent`、`reference_regions`、`shader`（base_colorのsRGB値、roughness、metallic）、`zones`（領域名、割当条件、色・模様）、`uncertainties` を持つ。対応する部品形状候補以外へ適用しない。`candidate show --trace` は資料パック、親子計画、部品候補、run、材質、レビュー、exportへのID・案件相対パスを返す。ファイルを暗黙に開いたり候補を採用したりしない。

## 11. 案件フォルダと実体の配置

既定の案件ルートは起動場所によらず `projects/<project-id>/`。種類の記録を最初に作るまでディレクトリは存在しなくてよい。名前や表示順はパスの主キーにしない。

```text
projects/<project-id>/
├─ project.json
├─ references/<reference-id>/image.<ext>
├─ artifacts/<candidate-id>/              外から取り込んだ画像・OBJ等
├─ reference-packs/<pack-id>/
│  ├─ manifest.json
│  └─ parts/<part-id>/                    派生した方向別画像・図面
├─ runs/<run-id>/
│  ├─ plan.json                          固定子計画
│  ├─ job.json                           引数・方法・Blender版
│  ├─ input-manifest.json                案件相対パスと入力hash
│  ├─ action.py または manual-edit.json  実行した操作の再現情報
│  ├─ blender.log                        処理に応じたログ
│  └─ outputs/
│     ├─ manifest.json                   候補ID・親候補ID・出力hash
│     ├─ model.blend / model.obj         存在する工程だけ
│     ├─ intent.json / checks.json
│     └─ previews/front.png など
├─ recovery/<checkpoint-id>.json
└─ exports/<export-id>/
   ├─ manifest.json
   └─ <指定した出力名>/model.blend など
```

新規のBlender制作、補修、確認レンダー、材質、手動編集の取込は必ずrun IDを持ち、`runs` から候補へ辿れる。`artifacts` は元の外部入力を不変コピーする場所。元資料は `references`。`reference-packs` のmanifestは既存画像を相対パスとhashで参照でき、複製を義務にしない。`proposals / inspections / external-runs` は旧案件の証跡として保持し、ver2の標準の書き込み先にしない。リポジトリ直下の `experiments/` は技術試験、`assets/` は共通資産で、案件の正本ではない。

## 12. 障害・復旧・互換

実行時は案件ロックと重い外部処理の共通ロックを分け、処理開始前に `running` と予約済みrun IDを保存する。入力・スクリプト・設定hashを再照合し、成果物をrun内の一時領域で作成、再読込とhash検査後に `outputs/` へ確定して候補登録する。失敗・中断でも旧資料・旧候補・旧出力は残す。結果不明はログ、PID、開始時刻、出力を調査するまで再実行しない。ロックを経過時間だけで奪わない。

旧案件はver2 CLIで参照できる。旧式の造形計画は再実行せず、必要なら新しいBlender親計画・資料パック・子計画を作る。旧run、`external-runs`、`inspections` のファイルは移動・削除しない。旧ファイルのうち索引に正式候補として登録されていないものを自動採用しない。必要なものは由来・hash・親候補を確認して新しいrunの正式候補として取り込む。recoveryは索引のチェックポイントであり、画像や.blendのバックアップではない。案件全体をバックアップする。

## 13. 実装順と検証

実装起点はGitの `ver1.0` ブランチにある `mwb.py`、`src/model_workbench/`、`scripts/blender_workbench.py`。現行 `ver2.0` ブランチでは、Git対象外の `projects/` と `experiments/` を保全する。新規パッケージや別の3D生成環境の導入は必要条件にしない。

1. `storage.py` と `workflow.py` に旧案件を壊さない `production_plans` / `reference_packs` の読取・保存・固定hash・承認を追加する。CLIに第10章のコマンドを加える。
2. 子計画の親範囲検査、試行枠、`approval.kind=parent_scope`、資料パックhash固定を追加する。従来の個別承認経路を保持する。
3. `runtime.py` にBlender造形アダプタとrun内の操作スクリプト・入力manifest・候補検査を接続する。仮組み・材質は既存アダプタを拡張する。
4. 手動編集.blendの取込、材質意図と領域、要件別自己点検、候補から全工程を辿る表示を追加する。
5. 小さな資産で承認・hash・案件分離・上限・失敗保全・旧案件読取・出力を自動検証し、GPUやBlenderを暗黙に起動しない。別の明示試験でBlenderの単純部品と非単純部品を制作して、4方向、面数、所要時間、修正時間、保持違反、材質、手動修正の再取込、source出力を確認する。

合格には、通常の制作で指定六場面のユーザー介入だけで初回の全身候補まで進むこと、部品・資料・材質のIDから実体と意図を辿れること、範囲外の自動実行を拒否すること、`external-runs` 等へ新規成果物を散らさないことが必要。機械的成功だけで造形品質合格とはしない。

## 14. 参照元と案件ごとに決める値

- 企画上の参照元：<mention-page url="https://app.notion.com/p/3fcf252ab683814c863df33656ed84bf"/>。
- 継承する制作フロー：<mention-page url="https://app.notion.com/p/3fdf252ab68381a5b65ff7bc939e3dcd"/>、<mention-page url="https://app.notion.com/p/3fdf252ab68381f0b19cc0fa5b190e61"/>。
- ver1の実装と操作：<mention-page url="https://app.notion.com/p/3fef252ab68381cb9145c11d60853f55"/>。
- 改善の根拠：<mention-page url="https://app.notion.com/p/3fef252ab6838005a979e7dc7b09aa5a"/> とユーザーによる実験後の追加指示。

案件ごとに決める値は、キャラクター、用途、表示距離、画風、部品の分け方、使用を認める身体ベース、寸法根拠、面数目標・上限、試行上限、材質の仕上がり条件、合格基準。これらは仕様の未決定事項ではなく、案件立ち上げと親計画で固定する入力である。
