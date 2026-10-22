# 操作手順 ver3.0｜比較・部品修正・完成版の指定

本書は対話検証用の追加手順である。案件、部品構成、親計画、資料パック、生成計画の作成と明示承認は [ver2.0操作手順](operation-manual-v2.0.md) に従う。新規案件は `project create --workflow-version 3` を指定する。既存のv2案件は自動移行しない。

以下の `mwb` は `mwb.cmd` または `python -B mwb.py` を表す。IDは省略形でなく完全なUUIDを使う。JSONファイルはUTF-8で保存する。通常の案内には `--json` を付けると後続操作に使いやすい。

## 1. 資料をそろえる

```text
mwb --json reference-pack brief <親計画ID>
```

表示される一次資料のパスと部品別の指示を使い、低ポリ部品ガイドの正面・側面・上面と、部品を組み合わせた全身予想図を用意する。背面は資料があれば追加する。画像生成を使った場合は元資料からの推定として登録し、一次資料と置き換えない。ハーネスは画像を自動生成しない。

資料パックの各部品には `source_reference_ids`、`dimensions`、`anchors`、`color_zones`、`consistency`、`uncertainties`、`images`、`low_poly` を入れる。`images` は最低でも `front`、`side`、`top` が必要で、各画像に `file`、`view`、`method`、`inferred`、`uncertainties`、`source_reference_id` を指定する。`low_poly` には `retained_features` と配列の `omitted_details` を入れる。全身予想図 `assembly_concept` には `file`、`source_reference_ids`、`method`、`inferred: true`、`uncertainties` を指定する。由来とhashは登録時に固定される。承認前に画像を人が確認する。

```text
mwb reference-pack create <案件ID> --production <親計画ID> --file pack.json
mwb reference-pack request-approval <資料パックID>
mwb reference-pack approve <資料パックID> --evidence "画像と一次資料を確認した理由"
```

## 2. 全身と部品を同じ条件で比較する

全身候補を得たら、先に比較条件の案を出す。

```text
mwb --json comparison brief <全身候補ID>
mwb --json comparison create <全身候補ID> --file comparison.json
```

`comparison.json` の例。`reference_id` は親計画に含まれる資料IDに置き換える。複数方向が1枚にある資料では、`crop` を画像幅・高さに対する0〜1の矩形で指定する。

```json
{
  "camera": "auto",
  "views": {
    "front": {"reference_id": "<正面資料ID>", "source_view": "front"},
    "side": {"reference_id": "<側面資料ID>", "source_view": "side"},
    "top": {"reference_id": "<上面資料ID>", "source_view": "top"}
  }
}
```

初回比較で正投影カメラと部品拡大カメラを固定する。出力の `sheet-front.png` などは一次資料、全身、各部品の全身スケール画像、各部品の拡大画像を並べる。資料が欠ける方向は `missing_reason` を明記して比較はできるが、完成判定は通らない。次の全身候補には `{"reuse":"<前回比較ID>"}` を渡して視点と参照領域を再利用する。比較レンダラーを変更した後は新しい基準比較を作る。

画像を実際に確認して `comparison review` を記録する。全身、保持条件、構成に含まれる全部品、親計画の全要件それぞれに `pass`、`fail`、`uncertain` と理由が必要である。

```json
{
  "actor": "codex",
  "whole": {"result": "fail", "reason": "正面で頭部の幅が一次資料より広い"},
  "preservation": {"result": "pass", "reason": "指定外の部品の輪郭は維持"},
  "parts": [{"part_id": "<部品ID>", "result": "fail", "reason": "頭部の外形が広い"}],
  "requirements": [{"requirement_id": "<要件ID>", "result": "fail", "reason": "正面の幅が未一致"}]
}
```

`parts` と `requirements` は上の1件例を対象の全件に増やす。`actor: user` は実際に利用者が判断した場合だけ使う。

```text
mwb comparison review <比較ID> --file review.json
```

## 3. 全体差異を部品へ戻す

全身の問題を見つけたら課題票を作る。`affected_part_ids` は1件以上、接合問題なら関係部品を含める。一次資料ID、方向、修正指示を必ず書く。

```json
{
  "title": "頭部の外形が広い",
  "category": "part_shape",
  "candidate_id": "<発見した全身候補ID>",
  "affected_part_ids": ["<頭部ID>"],
  "evidence_reference_ids": ["<正面資料ID>"],
  "source_views": ["front"],
  "repair": "立方体の外形幅を一次資料に合わせる。くり抜きと歯車を保持する",
  "priority": 1,
  "mandatory": true
}
```

```text
mwb quality-issue add --production <親計画ID> --file issue.json
mwb --json quality-issue next --production <親計画ID> --candidate <全身候補ID>
```

修正後の候補で比較画像とレビューを作り、同じ候補・比較IDに対して課題を再評価する。`resolved`、`reduced`、`unchanged`、`regressed`、`unclear` を使う。`reduced` は未完了のままである。

```text
mwb quality-issue evaluate <課題ID> --candidate <修正後全身候補ID> --comparison <新比較ID> --result reduced --reason "正面幅は縮小したが側面が未一致"
```

## 4. 候補IDを指定した対話編集

利用者が提示した候補IDを用いて編集セッションを開始する。課題IDは必要に応じて複数指定する。

```text
mwb --json candidate edit-start <全身候補ID> --production <親計画ID> --issue <課題ID>
```

返された `manifest_path` と `helper_path` を使い、接続中のBlenderに対してBlender MCPのPython実行機能から次を実行する。`connect` は未保存のシーンを開き替えず、作業コピーのファイル・hash・部品IDを `connection.json` に記録する。

```python
import runpy
helper = runpy.run_path(r"<helper_path>")
helper["connect"](r"<manifest_path>", open_copy=True)
```

```text
mwb candidate edit-bind <セッションID>
```

接続照合後にBlender MCPで指定部品を編集する。保存時に、実際に行った操作を短い文章の配列で渡す。`capture` はセッションIDが付いた同じ作業コピーを保存し、hashを `capture.json` に記録する。

```python
helper["capture"](r"<manifest_path>", ["頭部外形の頂点を正面資料に合わせて移動"])
```

`edit.json` の例を作り、返された `working_path` と同じファイルを `--result` に渡す。修正種類は `part_shape`、`part_transform`、`material_parameters` から選ぶ。変更対象外が維持されたかはBlenderの検査結果と新しい比較レビューで確認する。

```json
{
  "mode": "part_shape",
  "target_part_ids": ["<頭部ID>"],
  "changed_by": "codex",
  "reason": "正面輪郭の差を縮める"
}
```

```text
mwb --json candidate edit-finish <セッションID> --result <working_path> --file edit.json
```

全身の形状修正では新しい全身候補に加え、変更部品の単体 `.blend` 候補も作る。その候補を用いた再組立てが可能である。中断時は `candidate edit-show <セッションID>` で状態を確認する。派生候補だけ登録済みなら `candidate edit-recover <セッションID>` を使う。開始済みだが取込みを行わないセッションは `candidate edit-abandon <セッションID> --reason <理由>` で終了し、作業ファイルを残す。`importing` / `result_unknown` はrunの状態を確認してから扱う。

親計画に該当する `allowed_edits` がなく、後から利用者が具体的な手直しを依頼した場合、`edit.json` に `user_authorization` を追加できる。`actor: "user"`、実際の依頼文を入れた `evidence`、編集元の `source_candidate_id`、今回の `mode`、`target_part_ids` を指定する。候補・種類・対象部品の一致を確認し、実行計画に追加承認とそのhashを保存する。元の親計画は変更しない。工程の許可・回数上限・対象外の保持検査は引き続き適用する。会話上の依頼がない操作に追加承認を作ってはならない。

一つのメッシュの面ごとに複数材質を割り当てた部品は、`material_parameters` のmanifestに `material_storage: "embedded_blend"` を指定する。オブジェクト役割ごとの単色レシピへ変換せず、編集後の材質と面の割当を部品 `.blend` ごと保存する。再組立ては更新された構成部品候補を使用する。

## 5. 完成版を一つに決める

```text
mwb --json completion show --production <親計画ID>
mwb completion set --production <親計画ID> --candidate <全身候補ID> --reason "全方向と全部品を確認した"
```

完成判定には最新の比較と全項目が合格したレビュー、必須課題の同じ比較上での解消、未終了セッションがないことが必要である。完成候補IDは親計画に一つ保持し、更新履歴を残す。正式採用とsource出力は別操作である。静止画像の合格は関節変形やUE動作の合格を意味しない。

## 6. 内部検証の範囲

`python -B -m unittest discover -s tests -q` は状態遷移と拒否条件を検証する。`python -B scripts/smoke_v3.py` は隔離したテスト案件でBlender 5.2を起動し、比較、編集コピーの接続・保存照合、変更部品の抽出・再組立て、完成IDまでを確認する。スモークテストの画像評価は模擬判定であり、元キャラクターへの外観一致を示さない。ライブBlender MCP接続はサーバー起動後に対話で確認する。
