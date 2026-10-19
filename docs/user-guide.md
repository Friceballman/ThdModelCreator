# 初期管理CLIの操作手順

通常の操作は[操作マニュアル ver1.1](operation-manual.md)を参照する。`. .\mwb.ps1` の後は `mwb` で起動でき、show・approve・candidate操作等は対象IDだけでよい。以下は互換構文を含む実装詳細の補足として保持する。

更新日：2026-10-19。これは現在の実装で利用できる操作の説明。目標仕様の全機能が完成したことを意味しない。

## 通常は会話で依頼する

> 「青い旅人」という案件を作り、正面・側面・背面の画像を取り込んでください。頭身と配色を維持し、身体・髪・帽子・持ち物に分ける案を確認したいです。まだ生成しないでください。

CodexがCLIで登録・整理し、部品構成と使用資料、計画を提示する。承認後に対象の生成・Blender処理を実行する。以後も「帽子だけ10%大きく」「身体は変えず材質だけ変更」「この候補を選択して名前付き出力」と会話する。

現在の局所編集はオブジェクトの拡大・縮小に限定する。未対応の編集を、対応済みとして無理に実行しない。

## 起動と保存先

```powershell
Set-Location 'C:\Codex_Projects\ThDModelCreator'
$Python = 'C:\AI_test\TripoSR\.venv\Scripts\python.exe'
& $Python -B mwb.py config show
& $Python -B mwb.py doctor
& $Python -B mwb.py status
```

`mwb.py` はインストール不要のランチャー。既存環境のPythonを使うが、環境の依存を変更しない。初期の画像検証にはその環境に既にあるPillowを利用する。管理環境の依存定義はpyproject.tomlに記載している。

既定の保存先は起動場所によらずリポジトリのprojects。設定は明示した `--config`、案件保存先は `--root` で変更する。設定の自動上位探索はまだ実装していない。

```powershell
& $Python -B mwb.py --root '.cache/my-trial' --json project list --terminal
```

一覧は完全なIDを省略せず端末に表示する。`--json` で構造化出力が得られる。`--terminal` は画像ハーネスと揃えた構文だが、現在は常に端末出力であり、VS Code表示・キャッシュは未実装。

## 案件・インポート・タグ・要件

```powershell
$Project = (& $Python -B mwb.py --json project create --name '青い旅人' --goal 'デフォルメキャラクターの制作') | ConvertFrom-Json
$ProjectId = $Project.id
& $Python -B mwb.py reference add $ProjectId 'C:\Images\front.png' --role orthographic --view front --description '頭身と輪郭の根拠。背景は使わない' --priority 1
& $Python -B mwb.py requirement add $ProjectId --category must_keep --text '頭身と配色を維持する'
& $Python -B mwb.py reference list $ProjectId --terminal
& $Python -B mwb.py requirement list $ProjectId --terminal
```

画像の登録は案件内への不変コピーで、元画像を変えない。役割・方向・説明・優先度を後で変更する場合はreference updateと--reasonを使う。要件の変更はrequirement update、廃止はretire、履歴はhistory。登録しただけで画像をCodexが視覚的に参照できたとは扱わない。

## 部品構成の確認

Codexが次のような入力JSONを準備し、CLIで正式な構成案として登録する。

```json
[
  {"name": "身体", "description": "連続した身体ベース。入手方法は確認する"},
  {"name": "帽子", "description": "独立した交換可能部品"}
]
```

```powershell
$Proposal = (& $Python -B mwb.py --json part plan $ProjectId --file '.cache/parts-input.json' --reason '部品構成の提案') | ConvertFrom-Json
# 会話で内容を確認・承認した後だけ記録する
& $Python -B mwb.py part approve $ProjectId $Proposal.id --hash $Proposal.content_hash --evidence '今回の部品構成への明示承認'
```

各部品にUUIDが付く。改訂時に既存部品IDを含めるとIDを維持し、新しい構成版を作る。JSONは入力文書で、正式な案件JSONを直接編集するものではない。

## 部品候補と生成計画

- 既存の部品：`asset add <project-id> <obj-path> --part <part-id> --description <text>`。
- 生成用画像：`image register <project-id> <image-path> --part <part-id> --description <text>`。
- 形状生成計画：`generate plan <project-id> --stage geometry --part <part-id> --input <prepared-image-id> --prompt <text> [--reference <reference-id>]...`。

初期OBJ取り込みは、外部材質参照のない単一メッシュに限定する。人体ベース候補としてMakeHuman HM08のCC0メッシュを取得済み。`assets/body-bases/makehuman-hm08/derived/body-base.obj` を使用できる。出典・派生処理は同フォルダのREADME.mdに記載し、案件への正式採用は別途確認する。

計画を確認・承認し、実行する操作は工程共通。

```powershell
& $Python -B mwb.py generate show $ProjectId $PlanId
& $Python -B mwb.py generate request-approval $ProjectId $PlanId
# 利用者の会話での承認後のみ
& $Python -B mwb.py generate approve $ProjectId $PlanId --hash $PlanHash --evidence '承認内容の要旨'
& $Python -B mwb.py generate execute $ProjectId $PlanId
```

上記のID・hashは各計画の出力を使用する。approveだけでは外部処理を起動しない。計画には指定資料・要件版・部品構成・候補・材質・設定・コードhashを固定する。入力やコードが変われば新しい計画を作る。

TripoSRは既定でCUDA、チャンク1024、解像度128、テクスチャベイクなし。ローカルキャッシュを使い、CPUや他モデルへ自動切替しない。

画像準備は、資料の確認→image_prepare計画の承認→外部での作成→画像候補の登録→ユーザーの画像確認→入力承認→geometry計画の承認、という順序。画像の描き起こしを自動実行するアダプタは未実装で、image_prepareをexecuteするとblockedになる。外部ツールで処理する場合はexecuteせず、承認済み計画に結果を登録する。

```powershell
# image_prepare計画を承認してから、その計画の外部処理結果を登録
& $Python -B mwb.py image register $ProjectId 'C:\Images\prepared.png' --part $PartId --plan $ImagePlanId --method background_removal --description '元資料の輪郭を保持し背景のみ除去'
# 登録結果またはcandidate showのinput_hashを使い、ユーザーが画像を見て確認した後に実行
& $Python -B mwb.py image approve $ProjectId $ImageCandidateId --hash $ImageHash --evidence 'ユーザーが資料との一致と入力画像を確認'
```

methodはcrop・background_removal・image_generation・externalを区別する。既存画像の直接登録には--planが不要だが、geometry計画前の入力承認は必要。古い画像候補も未承認なら同様に承認する。生成計画の承認だけで画像確認済みとは扱わない。

同じ部品の画像を修正する場合、image_prepare計画の--sourceに親画像候補IDを指定する。外部結果を--plan付きで登録すると、新しいIDで親画像・資料スナップショット・計画・処理方法を保持する。計画は外部結果受領として完了し、CLIが画像生成を実行したとは記録しない。入力画像・過去候補は上書きしない。

## 仮組み・編集・形状確定

組み立ての入力レシピは、各部品に対応するpart候補IDを固定する。

```json
{
  "bindings": [
    {"part_id": "身体のUUID", "candidate_id": "身体候補のUUID", "location": [0, 0, 0], "rotation_degrees": [0, 0, 0], "scale": [1, 1, 1]},
    {"part_id": "帽子のUUID", "candidate_id": "帽子候補のUUID", "location": [0, 0, 1.6], "scale": [1, 1, 1]}
  ]
}
```

`generate plan --stage assembly --recipe <path>` で計画を作る。全ての部品を1回ずつ割り当てる。生成後は部品を分離した.blendとOBJ、4方向プレビュー、検査結果を持つcharacter候補になる。

限定編集は `edit plan --source <character-id> --stage assembly --recipe <path> --prompt <text>` を使い、レシピに `{"edit":{"part_id":"対象UUID","scale_factor":1.1}}` を指定する。親候補の構成・配置を基本として対象だけを拡大し、他部品の保持を検査する。

全身を確認した後、`candidate confirm-shape <project-id> <candidate-id> --reason <text>` で形状確定を記録する。形状の審美的な良さが自動で保証されたという意味ではない。

## 材質の作成・適用

```powershell
& $Python -B mwb.py material create $ProjectId --part $PartId --source $PartCandidateId --name '青い布' --color '0.05,0.25,0.8' --roughness 0.8 --metallic 0
& $Python -B mwb.py material list $ProjectId --terminal
```

作成は新しい材質IDを発行するだけで、全身へ自動適用しない。対象の形状候補IDと結び付け、異なる形状版へ誤適用しない。

全身の全ての部品へ材質IDを割り当てた `{"materials":{"部品UUID":"材質UUID"}}` の入力レシピを用意し、`generate plan --stage surface --source <形状確定したcharacter-id> --recipe <path>` で計画する。承認・実行後、新しい全身候補ができる。

現在はBlenderのPrincipled BSDFの色・Roughness・Metallicを設定する。プレビューはWorkbenchの材質色表示で、PBR照明下の見た目の評価ではない。UV・画像テクスチャ・ベイクの生成はまだ行わない。

## 比較・レビュー・選択・出力

```powershell
& $Python -B mwb.py candidate compare $ProjectId $BeforeId $AfterId
& $Python -B mwb.py candidate select $ProjectId $AfterId --reason 'この全身候補を選択'
& $Python -B mwb.py project export $ProjectId --name '青い旅人' --reason 'この名前でsource出力する指示'
```

compareは構成・材質とプレビューの絶対パスを表示する。CLI単独では画像を開かない。Codexは実際にファイルを参照して会話で提示する。派生候補は親候補の比較用フレーミングを保持する。

見た目の確認は、ユーザーが各候補のmodel.blendをBlenderで開く運用でよい。色・粗さ・金属度はMaterial PreviewまたはRenderedでも確認する。候補ファイルを直接上書き保存せず、手修正は別名・別フォルダに保存する。手修正.blendを新候補として取り込む操作は未対応のため、保存後はCodexに引き継ぐ。レビューには見た候補IDと確認結果を記録する。

reviewはentriesとsummaryを持つJSON入力を受け、要件ごとの結果と理由を保存する。`project set-approved` はレビュー済み・selectedのcharacterを正式採用として設定する別操作で、生成や選択から自動採用しない。

source出力対象はselectedのcharacterだけ。partやprepared_imageは混ぜない。1件は基本名のフォルダ、複数は候補ID順の_001等のフォルダへまとめ、各フォルダ内のファイル名はmodel.blend、model.obj等の内部参照を保持した名前とする。最終モデルのファイル自体の任意名への変換は初期対応に含めない。

新しいexport ID配下にコピーし、manifestで出所とhashを追跡する。形状・材質・過去出力を変えない。Blender固有の材質とOBJ/MTLの表現は同一ではなく、.blendが編集原本。UE、リグ、アニメーションは未検証。

## 保存・失敗時

案件の正本は `projects/<project-id>/project.json`。参照、要件、構成版、計画、候補、レビュー等を1文書で原子的に更新し、画像・モデルは別の不変ディレクトリへ置く。実行前にrunningを保存し、失敗時は原因とログを残す。

中断・タイムアウトはresult_unknownとし、結果が分かるまで再実行しない。復旧の判断はCodexが担う。`project resume <案件ID>` は案件全文・hash検査・保留計画・ロック・.blendの所在を読み取り専用で表示する。`project note`で引き継ぎを保存し、索引の更新時にはrecoveryへ全文チェックポイントを残す。自動のロック解除・結果不明の解消は行わない。詳細は[再開・復旧手順](session-resume.md)を参照。

CLIの現在の終了コードは0成功、2構文、3入力・状態・実行等の操作失敗、130中断。設計書ver1.0の詳細分類は未実装。エラー文と保存状態を併せて確認する。

全身候補、ログ、材質、参照を含む案件全体をバックアップする。Gitだけをバックアップにしない。
