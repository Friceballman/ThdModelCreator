# ver3.5 操作手順｜静止モデルからリグを試す設備

## 利用者の入力

まず静止候補に対し、必要な動作と守るべき外観を文章で入力する。指定済み完成品の候補IDは `47dab7b4-5ba2-4702-be3f-ec2ffe6ea04c`。以下の文章は書式例であり、この案件の確定要件ではない。

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

結果はGit管理外の `.local/v35-smoke/<run-id>/summary.json` に保存する。元候補、元資料、静止候補の採用状態は変更しない。今回未実装の外部モデル取込み、FBX・UE確認、連続動作、局所形状修正は [仕様書](spec-v3.5.md) に残した次段階の対象とする。
