# ver3.5 操作手順｜静止モデルからリグを試す設備

## 利用者の入力

まず静止候補に対し、必要な動作と守るべき外観を文章で入力する。指定済み完成品の候補IDは `47dab7b4-5ba2-4702-be3f-ec2ffe6ea04c`。以下の文章は書式例であり、この案件の確定要件ではない。

指定モデルとの対応は次のとおり。`mwb animation` はフォルダ名ではなく、案件台帳 `project.json` の候補IDを受け取る。

- 案件ID：`e2fbd0be-7077-4411-aab9-62fa8ce06c80`。
- 利用者指定ファイル：`exports/fd13ce2d-48f8-4a61-b359-9a136387f79b/outputs/model.blend`。フォルダ名 `fd13ce2d-...` は元の制作runのIDで、同フォルダの `plan.json` も `runs/fd13ce2d-...` を指す。
- 案件台帳の対応候補ID：`47dab7b4-5ba2-4702-be3f-ec2ffe6ea04c`。この候補が登録するファイルは `runs/fd13ce2d-48f8-4a61-b359-9a136387f79b/outputs/model.blend`。
- 上記二つの `.blend` のSHA-256は、ともに `f69f023673167b00b333bbfe132632f54ad4ad4d0fcf19e8f3dcee6bb7a3558f`。ファイル内容が同一であることを確認した。目視照合用の正面画像は指定フォルダ内の `outputs/previews/front.png`。

案件台帳の正式な `exports` 記録は別に存在し、IDは `f5935021-b6d5-49e8-a2e6-1610ac726af1`、保存先は `exports/f57fd1a8-6e61-4b7f-a637-d1ceb5a85abf`、候補IDは `85a225d1-7c6d-4cf3-a7aa-bd7dd5bfa24b`。今回の `animation` コマンドは、利用者指定の `fd13ce2d-.../outputs/model.blend` と一致する候補 `47dab7b4-...` を対象とする。

```powershell
mwb animation input 47dab7b4-5ba2-4702-be3f-ec2ffe6ea04c --text "必要な動作、動かす箇所、守る外観、UEでの用途を記載"
mwb animation show 47dab7b4-5ba2-4702-be3f-ec2ffe6ea04c
```

長い要件はUTF-8のJSONファイルを `--file` で渡せる。最低限は `{"text":"..."}`。Codexが根拠を照合して構造化する場合のみ、任意の `details` に `motions`、`preserve`、`unknowns`、`parent_id` を記録する。各動作はUUIDの `id`、`text`、根拠の `evidence`、`state`（`confirmed` / `proposed` / `unknown`）、`acceptance` を持つ。`preserve` と `unknowns` は文章の配列。入力だけでは実行承認にも品質合格にもならない。新しい版を入れると古い版に基づく未実行計画は無効になる。

## 検証担当者の内部手順

公開CLIのUXは上記二操作だけにする。検証担当者は `RiggingLab` の内部APIで、要件の根拠を確かめ、登録済み候補を読取り診断し、骨・各メッシュの追従方式・試験ポーズ・元ポーズ許容誤差を含む計画を作成する。`inspect(project_id, candidate_id)` の結果が `ready=true` であり、対応する出力hashが保たれていることを確認する。`plan(project_id, requirement_id, inspection_id, definition)` は実行せず固定計画を作る。動作と保持条件に未確定事項があればリグ計画を拒否する。

計画の `plan_hash` と動作・対象部品・保持条件の根拠を照合してから、該当範囲の実行承認を `approve(project_id, experiment_id, expected_hash, evidence)` で記録する。`execute` は承認済み計画を一度だけ作業コピーへ適用する。全メッシュを `static`（部分試作のみ）、`rigid`、または全頂点の明示ウェイトを持つ `weights` のいずれかで指定する。全身試作に未追従のメッシュは残せない。元の非対称ポーズをrest姿勢として扱い、メッシュ形状や材質を変えずに骨とArmature modifierを追加する。形状修正が必要なら別の計画にする。

各runの `outputs/checks.json`、`outputs/model.blend`、基準・rest・ポーズの四方向画像を確認する。`succeeded` はファイル処理と元ポーズの数値検査に限る。外観と動作は別々に根拠画像を付けて `review` し、未確認は `uncertain` と記録する。試験ポーズは始点・中間・終点を含む離散サンプルであり、連続再生やUEでの動作はまだ保証しない。中断時はrunとロック・Blenderプロセスを調査し、完了済み出力だけを `recover` で登録する。重複実行しない。

同梱の実機スモークテストは独立した合成モデルでリグの作成・保存・再読込・曲げを試し、指定候補は原本から隔離したコピーで読取り診断する。指定候補へのリグ適用はしない。

```powershell
& 'C:\AI_test\TripoSR\.venv\Scripts\python.exe' -B scripts/smoke_rigging.py --real-project e2fbd0be-7077-4411-aab9-62fa8ce06c80 --candidate 47dab7b4-5ba2-4702-be3f-ec2ffe6ea04c
```

結果はGit管理外の `.local/v35-smoke/<run-id>/summary.json` に保存する。元候補、元資料、静止候補の採用状態は変更しない。外部モデル取込みや汎用の局所修正・クリップ評価・FBX出力、UE結果取込みは共有APIには未実装。今回の指定案件に対する修正・5クリップ・FBX検証は次節の案件専用手順で実施した。

## 今回の完成モデルと5動作の確認

以下のパスは、すべて案件 `projects/e2fbd0be-7077-4411-aab9-62fa8ce06c80/` からの相対パス。元の静止モデルは上書きしていない。

- 確認用ページ：`planning/rigging-v35-20261023/review-50ec6d7c-c0c5-40ce-bc28-88f9b78551fb/index.html`。ブラウザーで開くと、5種類のGIFと四方向画像・全プレビューフレームを確認できる。
- 編集用モデル：`runs/0d62fec2-f5a5-41cb-b2b3-b68d0db15630/outputs/model.blend`。
- FBX一式：同じ `outputs/fbx/`。
- 数値と検証範囲：[検証記録](rigging-validation-2026-10-23.md)。ファイルとID・hashの対応は確認ページと同じフォルダの `artifact-manifest.json`。

Blender 5.2.0 LTSで編集用モデルを開くと、待機Actionと再生範囲が選択されている。スペースキーで再生・停止する。別の動作を見る場合は、下部のAction Editorで次のActionを選び、終了フレームも表に合わせる。再生速度は30fps。GIFは15fpsで書き出している。

| Action | 範囲 | 内容 |
| --- | --- | --- |
| `00_Source_Pose` | 1 | 元の非対称な静止ポーズへ戻す |
| `01_Idle` | 1–61 | 待機、頭部・眼球の小さな動き |
| `02_Walk` | 1–61 | その場での歩行2周期 |
| `03_Run` | 1–49 | その場での走行2周期 |
| `04_Hit_Recoil` | 1–45 | 被弾ののけ反りと復帰 |
| `05_Knockback` | 1–61 | 後方移動・浮き・着地 |

元モデルの見た目を照合するときは `00_Source_Pose` の1フレーム目を使う。手動で骨を動かす場合は `MWB_RIG` を選択してPose Modeへ切り替える。全21骨のFKリグであり、手足をドラッグして曲げるIKコントローラーや指の個別操作、衣服物理は追加していない。確認用Actionを変更する前に別名で保存する。

吹き飛びはrootが後方へ約0.9m移動するため、GIFの繰り返し時に開始位置へ戻る。被弾と吹き飛びのGIF末尾には確認用の停止時間がある。歩行・走行はその場再生であり、ゲーム内の移動速度やリターゲットの適合を確認したものではない。

## UE向けファイルを確認する手順

まず `SK_ClockCharacter.fbx` をSkeletal Meshとして読み込み、そのSkeletonを基準にする。各 `A_*.fbx` は同じスキン済みメッシュと個別のベイク済み動作を含むため、アニメーションを読み込むときは先ほどのSkeletonを指定し、重複するメッシュの読込みを無効にする。実際の項目名と取込み方式は対象UE版で確認する。

出力はBlenderのメートル単位、-Y前方・Z上方、21変形骨、余分なleaf boneなし、毎フレームのベイク。設定と再読込結果はモデルと同じ `outputs/checks.json` にある。Blenderの再読込では時間原点が1フレームずれており、相対時間を対応させて比較した。UEでのスケール・向き・開始時刻・root移動・材質・全クリップの再生は未検証で、取込み後に確認する。FBX再読込成功をUEでの動作確認済みとは扱わない。

## 検証担当者が反復を続ける場合

案件専用の実行・修正・監査・FBX・プレビューのレシピは [experiments/rigging-v35-case/README.md](../experiments/rigging-v35-case/README.md) を参照する。各runの入力・スクリプト・パラメータ・hashを保持しており、既存runを再実行せず新しいstageへ派生させる。今回のモデルに依存する検証設備であり、他の静止モデルを自動で同品質に変換できる機能ではない。正式採用とUE結果の登録は、この確認用成果物の作成とは別である。
