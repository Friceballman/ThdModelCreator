# ver3.5 指定キャラクターのリグ検証レシピ

案件 `e2fbd0be-7077-4411-aab9-62fa8ce06c80` の実機検証に用いた内部スクリプト。公開CLIの操作は引き続き `mwb animation input/show` の二つである。別キャラクターへ適用できる自動リグ機能ではない。

原本は候補 `47dab7b4-5ba2-4702-be3f-ec2ffe6ea04c` と同じhashの `exports/fd13ce2d-48f8-4a61-b359-9a136387f79b/outputs/model.blend`。初期リグは案件内の第3試作 `runs/8d5cd4c7-e9c6-497e-b45b-4ab1b8b967d1/outputs/model.blend` を起点とした。途中の局所補正と固定入力は各runの `plan.json`、`action.py`、`input.blend`、`job.json` に残っている。

## 実行契約

リポジトリを作業ディレクトリにして、内部の `run_case.py` に未使用のstage名、Blenderスクリプト、案件内の親モデル、UTF-8のパラメータJSONを渡す。JSONには変更理由 `reason` が必要。各スクリプト固有のパラメータは実行済みrunの `job.json` を参照する。

```powershell
& 'C:\AI_test\TripoSR\.venv\Scripts\python.exe' -B experiments/rigging-v35-case/run_case.py <new-stage> <script.py> <parent-model.blend> <parameters.json>
```

実行前に原本・親・スクリプト・パラメータを固定し、新UUIDの作業コピーだけを変更する。Blenderは既存の設定 `experiments/config.example.json` を使って逐次実行する。成功時のみ `outputs.pending` を `outputs` に確定する。失敗・中断したrunは残し、新stageで修正する。既存stageの再実行や原本の上書き、正式採用は行わない。権限・実行環境・依存関係を自動変更しない。

## スクリプトの役割

| ファイル | 対象 |
| --- | --- |
| `body_retopology.py` | 内部の腕・脚を衣服の断面と対応する構造へ組み直し、根元だけを接続する |
| `repair_internal_seams.py` | 内部の接続境界を補修する |
| `repair_body_weights.py` | 下半身への腕ウェイト混入を拒否・補正し、腰の深さを調整する |
| `body_clearance.py` | 内部腕の余裕を局所調整する |
| `build_confirmation_actions.py` | 関節面の向きをそろえ、5つの確認用ActionをFKキーへベイクする |
| `raster_audit.py` | 全フレーム・半フレーム・診断姿勢を四方向から分離色で描画する |
| `classify_raster_pixels.py` | 画素内9本のレイと重心座標で、赤画素を元の首と内部身体へ分類する |
| `export_fbx.py` | 骨格と5クリップを出力し、共通骨格への再割当て・再読込を検査する |
| `verify_delivery.py` | 原本保持、103メッシュ、首、骨・ウェイト、眼球、干渉、接地を検査する |
| `render_previews.py` / `make_review.py` | 15fpsの四方向画像、GIF、一覧HTMLを作る |

身体の局所補正は順序依存であり、上表を単純に先頭から実行するものではない。最終モデルまでの親関係は案件内の `planning/rigging-v35-20261023/iteration-*-context.json` と各runの固定計画を辿る。最終確認済みのモデル・検査runは [検証記録](../../docs/rigging-validation-2026-10-23.md) を正本とする。

FBXの個別クリップにも同じスキン済みメッシュを含める。骨だけの書出しでは再読込時のrest姿勢が変わったためである。UEでは既存Skeletonを指定し、必要に応じてクリップのメッシュ読込みを無効にする。UE実機検証は別工程であり、Blender再読込だけで互換性合格とはしない。

数値計測とCodexの見た目のレビュー、利用者による正式採用を区別する。元から見える首を内部身体の露出として数えず、画素を元の表面位置まで遡って分類する。有限の画素・方向・フレームによる検証であり、任意角度や別の服装への保証ではない。
