# ver2.0 ハーネス操作メモ

基準仕様は [spec-v2.0.md](spec-v2.0.md)。この文書は実装済みCLIの入口を示す。`<...>` は実際のUUIDまたはファイルパスに置き換える。共通オプション `--root`、`--config`、`--json` はサブコマンドより前に置く。`mwb --help` と各サブコマンドの `--help` で引数を確認できる。

## 通常の順序

1. `mwb project create --name ... --goal ...` で案件を作り、`mwb reference add`、`mwb requirement add`、`mwb part plan` で資料・要件・部品案を登録する。
2. `mwb production plan <project-id> --file production.json` で親計画を固定する。`production request-approval <id>` の後、ユーザーが内容を見た会話上の承認を `production approve <id> --evidence "..."` に記録する。この操作は部品案も同じ承認に紐付ける。
3. 必要な派生画像があれば、承認範囲内で `generate plan ... --stage image_prepare --production <id>` を作り、外部画像ツールの結果を `generate register <plan-id> <image>` で登録する。画像生成アダプタは内蔵されていない。
4. `mwb reference-pack create <project-id> --production <id> --file pack.json` で全部品の資料パックを登録し、`reference-pack request-approval <id>` と `reference-pack approve <id> --evidence "..."` で一括確認する。
5. 部品ごとに `mwb generate plan <project-id> --stage geometry --engine blender_authoring --production <id> --reference-pack <id> --part <id> --file recipe.json` を作る。計画作成だけではBlenderを起動せず試行枠も消費しない。`mwb generate execute <plan-id>` の開始で試行を一回消費する。`.blend`、OBJ、intent、checksは `runs/<run-id>/outputs/` に残り、部品の確認画像は標準生成しない。前候補を修正する場合は同じコマンドに `--source <part-candidate-id>` を付け、レシピに `change_keywords` を指定する。
6. 全部品の候補IDを指定した仮組みレシピを `mwb generate plan <project-id> --stage assembly --production <id> --prompt "..." --recipe assembly.json` で登録・実行する。仮組みの構造検査が成功したら、`mwb candidate confirm-shape <project-id> <candidate-id> --reason "..."` で材質工程への内部ゲートを通す。通常ここでは見た目確認を行わない。
7. `mwb material create <project-id> --source <part-candidate-id> --file material.json` で各部品の材質意図とパラメータを保存し、`mwb generate plan <project-id> --stage surface --production <id> --source <character-id> --prompt "..." --recipe surface.json` を実行する。
8. 材質適用済み全身候補の4方向画像を見て `mwb review <candidate-id> --file review.json --actor codex` で自己点検し、ユーザーの最終レビューを別記録にする。`mwb candidate show <project-id> <candidate-id> --trace` で資料・計画・部品・材質・runを辿れる。候補を選択し、必要なら `mwb project set-approved <project-id> <candidate-id> --reason "..."` で正式採用した後、`mwb project export <project-id> --name <name> --reason "..."` でsource出力する。選択と正式採用と出力は別操作。

## JSONの最小例と制約

`production.json` は仕様書第4章の例を参照。`scope.stages`、`geometry_engines`、全部品の `face_limits`、各試行上限、資料IDと要件IDが必要。`reference-pack` は全部品を同時に含め、各部品に `source_reference_ids`、`dimensions`、`anchors`、`color_zones`、`consistency`、`uncertainties`、`images` または `construction` を指定する。画像には `file`、`source_reference_id`、`view`、`method`、`inferred`、`uncertainties` を記す。案件内画像は案件相対POSIXパス、外部画像は絶対パスで指定でき、外部画像はパック内へ不変コピーする。

造形用 `recipe.json` の例：

```json
{"script":"C:/path/to/action.py","intent":"資料の輪郭と厚みを表す低面数の部品","state_keywords":["低ポリゴン","背面推定"]}
```

`action.py` は `def build(job):` を定義し、Blender Pythonでメッシュを制作する。修正時は前候補の `.blend` が開いた状態で呼ばれる。レシピには `change_keywords`（例：`["頂点を調整"]`）を必ず追加する。成果物の保存・構造検査はアダプタが担当し、4方向レンダーは材質適用済み全身候補で行う。Blender内の各メッシュへ `mwb_object_role` を設定すると、同一部品内の材質領域をオブジェクト単位で割り当てられる。承認後にスクリプト、job、資料ファイルのhashが変われば実行を拒否する。造形スクリプトはユーザー権限で実行されるため、信頼できるローカルコードのみ指定する。

仮組みレシピは `{"bindings":[{"part_id":"<id>","candidate_id":"<id>","location":[0,0,0],"rotation_degrees":[0,0,0],"scale":[1,1,1]}]}` の形。材質レシピは `{"name":"布","intent":"...","reference_regions":[],"shader":{"base_color":[0.4,0.3,0.2],"roughness":0.8,"metallic":0},"zones":[],"uncertainties":[]}` の形。必要ならshaderに `{"pattern":{"type":"noise","scale":8,"bump_strength":0.15,"secondary_color":[0.5,0.4,0.3]}}` を加えられる。`zones` は `name`、`object_role`、任意の `shader` を持ち、現実装の割当条件は `mwb_object_role` の完全一致。面内のUV塗分けやベイクは未対応。材質適用レシピは `{"materials":{"<part-id>":"<material-id>"}}`。

自己点検用 `review.json` は `{"entries":[{"requirement_id":"<id>","result":"pass","reason":"...","directions":["front","side","back","oblique"],"image_files":["runs/<run-id>/outputs/front.png"]}],"summary":"..."}`。`image_files` は材質適用済みの対象候補に実在するPNGパスにする。Codexによる自己点検は実際に画像を見て記録し、未確認なら `uncertain` と `impact` を記す。ユーザー最終レビューは `--actor user` で別に保存する。

手修正 `.blend` は `mwb candidate import-blend <project-id> <edited.blend> --source <candidate-id> --production <id> --file edit.json` で取り込む。`edit.json` には `mode`（`part_shape` / `part_transform` / `material_parameters`）、`target_part_ids`、`changed_by`、`reason` を入れる。状態を列挙する場合は `state_keywords` と `change_keywords` も入れられる。配置変更は、対象の各Blenderオブジェクト名をキーにした `before_transform` と `after_transform` も必須。対象外部品の形状・配置・材質変更、部品内で異なる配置変更、親候補のhash不一致は拒否する。追加点検は `mwb candidate inspect <project-id> <candidate-id> --production <id>`。どちらも新しいrunに保存され、旧候補を上書きしない。キーワードは `mwb candidate list <project-id> --keyword "..."` で検索し、`mwb candidate keywords <project-id> <candidate-id> --keyword "..." --reason "..."` で置換できる。

## 検証済み範囲

通常の自動テストはBlenderやGPUを起動しない。`scripts/smoke_v2.py` は一時案件を作る明示的なBlender接続試験で、単純な2オブジェクト部品を使って造形・手修正・仮組み・材質・点検・source出力を検証する。実案件の造形品質、複雑形状の自動制作、画像生成品質、リグ・UE・動作はこの試験で保証しない。`projects/` はGit対象にせず、案件全体を別途バックアップする。
