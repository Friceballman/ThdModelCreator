# 操作マニュアル ver1.1｜初めての資料取り込み・部品生成・モデル完成

更新日：2026-10-19。対象：Windows / PowerShell、Python 3.11以上、現在のModel Workbench。画像生成ハーネスの操作マニュアルに合わせ、短いコマンドと対象IDを中心に案内する。

仕様の基準は[UX仕様書 ver1.1](https://app.notion.com/p/3fdf252ab68381f0b19cc0fa5b190e61)。このマニュアルは実装と照合した操作案内で、実キャラクター制作の合格報告ではない。旧版の長いコマンドは互換用に残してある。

## 1. このハーネスで何をするのか

資料の用途と制作要件を整理し、部品を用意してBlenderで組み立て、材質を適用してモデルを出力する。案件立案→資料→要件→部品構成→生成用画像→部品生成→仮組み・修正→形状確定→材質→レビュー・選択→出力、の順に進める。

操作窓口は2つ。Codexとの会話で相談・資料理解・計画提示・承認・レビューを行い、`mwb` で画像・モデル・判断を保存する。ユーザーは全コマンドを手入力する必要はない。見た目はユーザーがBlenderで確認してよい。

このページでは「身体ベースに青い帽子を載せた静止マネキン」を例にする。身体は取得済みのMakeHumanベース、帽子はTripoSRで生成。検証対象と合格基準は案件ごとに決める。

### 最初に覚える言葉

| 名前 | 意味 | IDを確認する操作 |
| --- | --- | --- |
| 案件 / Project | 制作目標と資料・成果物をまとめる箱 | `mwb project list` |
| 参照 / Reference | 元画像と、その役割・優先順位 | `mwb reference list $ProjectId` |
| 要件 / Requirement | 保持・変更・改善する条件 | `mwb requirement list $ProjectId` |
| 部品 / Part | 身体・帽子等の継続して使う固有ID | `mwb part list $ProjectId` |
| 生成計画 / Plan | 入力・要件・設定を固定した一回分の計画 | `mwb generate list $ProjectId` |
| 候補 / Candidate | 保存された画像・部品形状・全身モデル | `mwb candidate list $ProjectId` |
| 材質 / Material | 特定の部品形状へ割り当てる材質 | `mwb material list $ProjectId` |

部品IDは役割を表し、部品候補IDはその形状の一つの版を表す。取り違えない。IDは完全なUUID v4。「現在の案件」は暗黙に保持しない。

### コマンドの基本形

```powershell
# 作成や一覧は案件IDを指定
mwb generate plan $ProjectId --input $ImageId --prompt '帽子を一回生成する'
mwb generate list $ProjectId
# 作成後の操作は、対象IDだけを指定
mwb generate show $PlanId
mwb generate request-approval $PlanId
mwb generate approve $PlanId
mwb generate execute $PlanId
mwb candidate show $CandidateId
```

plan・approveだけではTripoSRやBlenderは起動しない。executeが外部処理を起動する。画像生成ハーネスのiwbでは会話で画像生成するが、mwbのgeometry・assembly・surfaceはローカルツールをexecuteする点が違う。

対象IDから、指定した保存先の案件を特定する。IDが見つからない・重複する場合は停止し、別案件や「最後の候補」を推測しない。

## 2. 初回の準備

### 2.1 起動場所とコマンドを確認する

この端末では、iwbと同じ既存PATH上のユーザー用 `Python\bin` へmwb.cmdを登録済み。通常は `mwb --help`、`mwb project list` のように直接入力でき、以下の関数読み込みは不要。起動と日本語引数付きの試験案件保存を確認した。登録は既存Pythonパッケージ・PATH・プロファイルを変更しない。

このディレクトリで直接使う場合は `.\mwb.cmd --help`、`.\mwb.cmd doctor` と入力できる。事前準備は不要で、以下の例のmwbを `.\mwb.cmd` に置き換えて使う。コマンドプロンプトでは `mwb` で起動できる。PowerShellでmwbという短い名前を使いたい場合は、以下の関数読み込みを行う。

PowerShellを開き、セッションの最初に次を実行する。

```powershell
Set-Location -LiteralPath 'C:\Codex_Projects\ThDModelCreator'
. .\mwb.ps1
mwb --help
mwb config show
mwb doctor
```

`. .\mwb.ps1` は、このターミナルに短い `mwb` 関数を読み込む操作。先頭のドットと空白が必要。インストール、永続PATH・PowerShellプロファイルの変更、TripoSR環境の依存更新は行わない。新しいターミナルでは再度読み込む。

既定では `C:\AI_test\TripoSR\.venv\Scripts\python.exe` を使う。doctorはパス・キャッシュの存在確認で、GPUや品質全体の保証ではない。設定不備はCodexと確認し、既存環境を再構築しない。

関数を読み込まない場合の同等の起動方法：

```powershell
& 'C:\AI_test\TripoSR\.venv\Scripts\python.exe' -B .\mwb.py --help
```

### 2.2 保存先を確認する

既定は `C:\Codex_Projects\ThDModelCreator\projects`。既存画像ハーネスとは異なり、保存先はこのリポジトリを基準とし、起動ディレクトリでは変わらない。別の保存先なら共通オプション--rootを、全操作で同じように指定する。

```powershell
mwb --root '.cache/my-test' project list
mwb --json project list
```

--root・--config・--jsonはサブコマンドより前。設定の実行ファイル等の相対パスは設定JSONの場所を基準にする。一覧は現在すべて端末表示で、--terminalも使える。画像生成ハーネスのVS Code一覧キャッシュは未実装。

### 2.3 資料と承認の準備

- 資料と入力画像はPNG・JPEG・WebP。パスに空白があれば引用符で囲む。
- CLIの--promptは意図を記録する文章。TripoSRのテキスト条件ではなく、形状変更は入力画像やBlender処理で表す。
- TripoSRは一枚の画像を入力する。三面図の並置を複数視点入力として使わない。
- 画像の描き起こしは、利用できる会話の画像生成・編集ツール等で行い、外部結果を登録する。CLIから画像生成ツールを直接起動する機能は未実装。
- この資料の例文は実行承認ではない。各計画をユーザーが確認してから、該当するapproveやexecuteへ進む。

### 2.4 IDの入力と端末での確認

各作成コマンドの出力からIDをコピーし、以下のように変数へ入れる。例の「返却された…ID」は実際の完全なUUIDに置き換える。

```powershell
$ProjectId = '返却された案件ID'
$PlanId = '返却された生成計画ID'
$CandidateId = '返却された候補ID'
```

approve、画像入力承認、候補の判断、出力等は、理由や承認証拠を引数で指定しなければ対象と内容を端末へ表示する。内容を読んで意図した操作なら `y`、中止は `n` またはEnter。hashの転記は不要だが、内部のhash検証は継続する。

Codexが非対話で操作する場合は、会話で得た明示承認を--evidence、判断理由を--reasonへ渡す。非対話で証拠がない操作は拒否し、自動で承認しない。

```powershell
# 会話でこの計画を承認された後だけ。非対話操作の例
mwb generate approve $PlanId --evidence 'ユーザーが提示済みのこの計画を承認'
```

## 3. 案件を作る

会話例：「青い帽子を載せた静止マネキンを作りたいです。まず資料と完成条件を整理してください。」

```powershell
mwb project create --name '青い帽子のマネキン' --prompt '既存人体ベースと帽子による静止モデルの制作テスト'
$ProjectId = '返却された案件ID'
mwb project show $ProjectId
mwb project note $ProjectId --kind decision --prompt '今回の対象は静止モデル。リグ・関節変形・UEは完成条件に含めない'
```

この例の合格基準案は、身体形状の保持、帽子に目立つ浮き・めり込みがないこと、4方向の確認、出力先.blendの再読み込み。許容差や資料への一致度は案件ごとにユーザーと決める。

## 4. 資料を取り込んで用途を付ける

次のパスは実在するユーザー資料に置き換える。

```powershell
mwb reference add $ProjectId 'C:\Images\hat-front.png' --role design --view front --priority 1 --prompt '帽子の輪郭と配色の主資料。背景は使わない'
$FrontRefId = '返却された参照ID'
mwb reference list $ProjectId
mwb reference show $FrontRefId
```

側面・背面等も同様に登録する。roleは用途、viewは方向、priorityは1〜5で1が最優先。画像を案件へコピーし、元ファイルを変えない。Codexは保存された画像を実際に読み、資料間の矛盾や推定部分を説明する。

会話例：「正面の輪郭を優先してください。資料にない帽子内部は推定として残してください。」

```powershell
mwb project note $ProjectId --kind open_question --prompt '帽子内部の断面は資料なし。中空構造や実際に被れる形状かは未確定'
```

ユーザー確認：何を根拠にするか、優先順位、不明な部分。複数資料を使う計画では--referenceを繰り返し指定する。未登録の資料を暗黙に使わない。

## 5. 制作要件を登録する

```powershell
mwb requirement add $ProjectId --category must_keep --prompt '身体ベースの形状は帽子の調整で変えない'
$KeepBodyId = '返却された要件ID'
mwb requirement add $ProjectId --category must_change --prompt '帽子を頭へ配置し、4方向で目立つ浮き・めり込みがないことを確認する'
$FitHatId = '返却された要件ID'
mwb requirement list $ProjectId
```

must_keepは保持、must_changeは必要な変更、improveは改善。条件変更は理由を付けて改訂し、過去計画は変えない。

```powershell
mwb requirement update $FitHatId --prompt '正面・側面・背面・斜めで帽子の配置とつばの輪郭を確認する' --reason '確認対象を明確化'
mwb requirement history $ProjectId
```

## 6. 部品構成を確認し、身体ベースを用意する

### 6.1 部品構成案を作る

```powershell
mwb part plan $ProjectId --name '身体' --name '帽子' --prompt '身体は連続した既存ベース、帽子は独立した交換可能部品として構成する'
$PartPlanId = '返却された部品構成案ID'
mwb part list $ProjectId
```

ユーザー確認：身体・腕・脚を細分化しすぎていないか、この部品構成でよいか。確認後に承認する。

```powershell
mwb part approve $PartPlanId
$BodyPartId = '一覧に表示された身体の部品ID'
$HatPartId = '一覧に表示された帽子の部品ID'
```

構成案IDと、各部品のIDは別。高度な構成改訂では既存部品IDを維持するため、Codexが従来の--file形式を利用できる。ユーザーがJSONを作る必要はない。

### 6.2 身体の候補を登録する

ユーザーが体型・頭身・ポーズをBlenderで確認し、今回のベースとしてよいと判断してから取り込む。

```powershell
mwb asset add $ProjectId 'assets/body-bases/makehuman-hm08/derived/body-base.obj' --part $BodyPartId --prompt 'CC0のMakeHuman人体ベース。仮身長1.7m、リグとUEは未確認'
$BodyCandidateId = '返却された部品候補ID'
mwb candidate show $BodyCandidateId
```

確認用ファイルは `assets/body-bases/makehuman-hm08/derived/body-base.blend`。同フォルダのREADMEとmanifestに出典・ライセンスを保持している。共通ベースを直接上書きしない。asset addは初期実装では外部材質を参照しないOBJ用で、任意のFBXや.blendは取り込めない。

## 7. 生成用画像を準備し、ユーザーが確認する

### 7.1 画像準備計画を作って承認する

```powershell
mwb generate plan $ProjectId --part $HatPartId --reference $FrontRefId --prompt '資料を基に帽子だけを一個写す入力画像を準備。輪郭と配色を保持し、見えない部分は推定と明記する'
$ImagePlanId = '返却された生成計画ID'
mwb generate show $ImagePlanId
mwb generate request-approval $ImagePlanId
```

入力画像等の指定がなければimage_prepareとして計画する。複数部品がある場合は--partで対象を明示する。

ユーザー確認：何を残し、どの方向で、どこを描き直すか。この画像準備の内容を承認した後だけ次へ。

```powershell
mwb generate approve $ImagePlanId
```

### 7.2 外部ツールで画像を用意し、登録する

ここではexecuteを使わない。画像準備アダプタは未実装なので、承認内容に沿って会話の画像生成・編集等で作成する。画像をローカルへ保存できた後に登録する。

```powershell
mwb generate register $ImagePlanId 'C:\Images\hat-prepared-v1.png' --method image_generation
$HatImageId = '返却された画像候補ID'
mwb candidate show $HatImageId
```

処理方法は実態に応じ、crop（切り抜き）、background_removal（背景除去）、image_generation（描き起こし）、external（その他）を指定する。計画は外部結果受領として完了し、CLIが画像生成を実行したとは記録しない。

### 7.3 出来た画像を入力として承認する

ユーザーが保存画像を実際に見て、帽子一つが写っているか、元資料に一致するか、身体・背景・複数視点が混ざっていないかを確認する。

```powershell
mwb image approve $HatImageId
```

画像作成計画の承認と、出来た画像の入力承認は別。geometry計画では確認済み画像を固定する。

画像を修正する場合：

```powershell
mwb edit plan $ProjectId --source $HatImageId --reference $FrontRefId --prompt '輪郭と配色を保ち、背景だけを整理する'
$ImageEditPlanId = '返却された編集用の生成計画ID'
mwb edit show $ImageEditPlanId
mwb edit request-approval $ImageEditPlanId
# この編集計画をユーザーが承認した後
mwb edit approve $ImageEditPlanId
# 外部で画像を編集し、ファイルを受け取った後
mwb edit register $ImageEditPlanId 'C:\Images\hat-prepared-v2.png' --method background_removal
```

新しい画像候補IDを受け取り、見た目を確認してimage approveを行う。以後の$HatImageIdは新しい候補IDに更新する。旧画像と親子関係は保持される。

## 8. 部品の生成計画を確認し、OBJを生成する

```powershell
mwb generate plan $ProjectId --input $HatImageId --reference $FrontRefId --prompt '承認した帽子画像から一回だけOBJを生成する'
$GeometryPlanId = '返却された生成計画ID'
mwb generate show $GeometryPlanId
mwb generate request-approval $GeometryPlanId
```

--inputの画像からgeometry工程と部品IDを特定する。ユーザーは入力画像、対象部品、回数1回、設定を確認する。承認後のみ実行。

```powershell
mwb generate approve $GeometryPlanId
mwb generate execute $GeometryPlanId
$HatCandidateId = '返却された部品候補ID'
mwb report show $GeometryPlanId
mwb candidate show $HatCandidateId
```

RTX 3050 Tiの4GB環境ではCUDA・chunk1024・解像度128・ベイクなしの逐次処理が基本。--promptに設定値を書き足すだけで実行設定が変わるわけではない。

候補のOBJをBlenderへインポートし、輪郭、背面の破綻、余分な突起、用途に必要な厚み・内側を確認する。生成成功と品質合格は別。帽子内部が中空であることも自動では保証しない。

再生成は新しい計画で行う。親候補と入力画像を指定する。

```powershell
mwb generate plan $ProjectId --source $HatCandidateId --input $HatImageId --reference $FrontRefId --prompt '確認した入力画像から帽子を再生成する。前候補は保持'
```

同じ画像なら似た結果になる可能性がある。文章だけ変えれば形状が変わるとは扱わない。実行する新計画は再度確認・承認する。

## 9. 仮組みし、必要な修正を行って形状を確定する

### 9.1 部品候補IDから組み立てる

--bindを部品候補ごとに指定する。部品IDは候補から取得する。配置を変える部品だけ--partで指定し、--location・--rotation・--scaleを与える。未指定の部品は位置・回転0、スケール1。

```powershell
mwb generate plan $ProjectId --bind $BodyCandidateId --bind $HatCandidateId --part $HatPartId --location '0,0,1.65' --scale '0.25,0.25,0.25' --prompt '身体を保持し、独立した帽子を頭部へ仮配置する'
$AssemblyPlanId = '返却された生成計画ID'
mwb generate show $AssemblyPlanId
mwb generate request-approval $AssemblyPlanId
```

数値は書式例で、フィット済みの値ではない。Codexが実メッシュの寸法・向き・原点を確認して値を提案する。座標はZ-up・身体の正面-Y、回転は度、身体の仮身長は1.7m。自然文からCLIが自動で最適配置する機能はない。

ユーザー確認後：

```powershell
mwb generate approve $AssemblyPlanId
mwb generate execute $AssemblyPlanId
$AssemblyCandidateId = '返却された全身候補ID'
mwb candidate show $AssemblyCandidateId
```

filesにあるmodel.blendをBlenderで開き、正面・側面・背面・斜めでフィットを確認する。ファイルのパスは案件フォルダ基準。組み立ては別オブジェクトの配置で、表面の溶接・接合品質の保証ではない。全ての承認済み部品を1回ずつ割り当てる。

### 9.2 対象部品だけ拡大する

会話例：「身体を変えず、帽子だけ10%大きくしてください。」専用編集では--sourceで全身候補、--partで対象、--scaleで倍率を指定する。

```powershell
mwb edit plan $ProjectId --source $AssemblyCandidateId --part $HatPartId --scale 1.1 --prompt '身体を保持し、帽子だけ原点基準で10%大きくする'
$EditPlanId = '返却された生成計画ID'
mwb edit show $EditPlanId
mwb edit request-approval $EditPlanId
# この変更をユーザーが承認した後
mwb edit approve $EditPlanId
mwb edit execute $EditPlanId
$EditedCandidateId = '返却された全身候補ID'
mwb candidate compare $AssemblyCandidateId $EditedCandidateId
```

新しい.blendでも確認する。compareは構成とプレビューのパスを返すが、画像を開いたり品質を自動判定したりしない。位置・回転を変える場合は、新しいassembly計画で同じ部品を指定し、対象以外の値を保持する。旧候補と変更理由はproject noteへ残す。

### 9.3 形状を確定する

修正を行わなければ仮組み候補、行った場合は修正後の候補から、今回の形状を選ぶ。

```powershell
$ShapeCandidateId = 'ユーザーが形状を確認した全身候補ID'
mwb candidate confirm-shape $ShapeCandidateId
```

確認対象を読んでyと答える。これは材質工程へ進む形状の確定で、最終採用ではない。修正を省略しても、この操作は行う。

## 10. 全身を見ながらマテリアルを作成・適用する

材質の--sourceには全身候補ではなく、部品の形状候補IDを指定する。対応する部品IDは自動取得する。

```powershell
mwb material create $ProjectId --source $BodyCandidateId --name '灰色の身体' --color '0.55,0.55,0.55' --roughness 0.75
$BodyMaterialId = '返却された材質ID'
mwb material create $ProjectId --source $HatCandidateId --name '青い帽子' --color '0.05,0.20,0.65' --roughness 0.85
$HatMaterialId = '返却された材質ID'
mwb material list $ProjectId
mwb generate plan $ProjectId --source $ShapeCandidateId --material $BodyMaterialId --material $HatMaterialId --prompt '形状と配置を保ち、身体に灰色、帽子に青の材質を適用する'
$SurfacePlanId = '返却された生成計画ID'
mwb generate show $SurfacePlanId
mwb generate request-approval $SurfacePlanId
```

ユーザーは形状版と割当を確認し、承認後のみ実行する。

```powershell
mwb generate approve $SurfacePlanId
mwb generate execute $SurfacePlanId
$FinalCandidateId = '返却された材質付き全身候補ID'
mwb candidate compare $ShapeCandidateId $FinalCandidateId
mwb candidate show $FinalCandidateId
```

BlenderのMaterial Preview等で全身の色・粗さ・金属感を確認する。付属のWorkbenchプレビューは材質色の簡易表示。現在はPrincipled BSDFの数値指定で、AIによる画像テクスチャ生成、UV展開、ベイクは行わない。

帽子を再生成・交換したら新しい形状候補に材質を作る。別の形状版へ古い材質を誤適用する計画は拒否する。

## 11. レビュー・選択・正式採用を記録する

### 11.1 要件別にレビューする

ユーザーが実際に確認した結果を記録する。確認していない項目にはuncertainを使う。以下は判断理由の記入例で、実際の確認結果へ置き換える。

```powershell
mwb review $FinalCandidateId --requirement $KeepBodyId --result uncertain --prompt '身体保持は構造検査と見た目の確認が未完了'
mwb review $FinalCandidateId --requirement $FitHatId --result uncertain --prompt '帽子のフィットを4方向で確認する必要がある'
```

resultはpass・fail・uncertain・not_applicable。一回の簡易reviewでは一要件を評価し、複数要件は繰り返す。全てのレビューは別記録として保持され、過去評価を上書きしない。総合評価や複数要件を一つにまとめる詳細JSONはCodexが--fileで登録できる。

### 11.2 出力したい全身候補を選ぶ

```powershell
mwb candidate select $FinalCandidateId
mwb candidate list $ProjectId --kind character
```

表示対象を確認してyと答える。selectedの全身候補を全て出力するので、過去の選択も確認する。出力から外したい候補はhold、却下はreject。

```powershell
# 必要な場合だけ実行。対象候補IDを指定する
mwb candidate hold $AssemblyCandidateId
```

### 11.3 正式採用は別に設定する

```powershell
# ユーザーが最終採用を指示し、レビューを確認した後だけ
mwb project set-approved $ProjectId $FinalCandidateId
```

正式採用にはselectedの全身候補とレビューが必要。ただしCLIは全条件passや審美品質を自動保証しない。未確認・不合格が残る場合の扱いは理由を付けてユーザーが決める。試験出力だけなら正式採用は不要。出力先確認も完成条件なら、第12節を終えてから採用する。

## 12. 名前付き出力・保存先・レポートを確認する

### 12.1 選択したモデルを出力する

```powershell
mwb candidate list $ProjectId --kind character
mwb project export $ProjectId --name '青い帽子のマネキン'
```

対象候補・名前を確認してyと答える。selectedが0件なら出力せず終了する。1件なら指定名のフォルダ、複数なら候補ID順に_001等を付ける。出力名にパスやWindows予約名は使えない。同名で再実行しても新しい出力IDへ保存する。

```text
projects/<案件ID>/exports/<出力ID>/
├─ 青い帽子のマネキン/
│  ├─ model.blend
│  ├─ model.obj
│  ├─ model.mtl
│  ├─ front.png / side.png / back.png / perspective.png
│  ├─ checks.json
│  └─ composition.json
└─ manifest.json
```

表現可能な材質付き出力ならMTLを含む。内部ファイル名は参照整合のため固定。画像生成ハーネスの「画像ファイル自体に名前を付ける」仕様とはこの部分が異なる。.blendが編集原本で、OBJ/MTLが同じ材質表現を保持する保証はない。出力形式は現在sourceのみで、UE完成検証済み出力ではない。

ユーザーが出力先の.blendを開き、形状・配色・候補との一致を確認する。その結果もreviewやproject noteに保存する。元資料・候補・共通人体ベースを直接上書きせず、手修正は別名でCodexへ引き継ぐ。

### 12.2 迷ったらこの順番

```powershell
mwb status $ProjectId
mwb generate show $PlanId
mwb report show $PlanId
mwb candidate list $ProjectId --generation $PlanId
mwb candidate show $CandidateId
```

show・reportは対象IDだけでよい。候補のfilesは案件フォルダ基準の相対パス。案件フォルダは `projects/<案件ID>/` で、画像生成ハーネスのproject-xxxxxxxxというslugではない。GUIを開くopenコマンドは現在未実装。

### 12.3 保存内容とログ

```text
projects/<案件ID>/
├─ project.json             案件・資料・要件・構成・計画・候補・材質・レビュー等の索引
├─ references/              コピーした元資料
├─ artifacts/               取り込んだ画像・既存部品
├─ runs/<実行ID>/           固定計画、job、ログ、生成物、検査、プレビュー
├─ recovery/<UUID>.json     更新時の案件索引全文チェックポイント
└─ exports/<出力ID>/        選択済み全身候補のコピーとmanifest
```

会話全文は自動保存しない。重要な判断・未決事項・次の作業はproject noteで残す。JSONは通常閲覧用とし、案件索引を手で書き換えない。

## 13. 停止・エラー時の読み方

| 状態 | 意味・次の操作 |
| --- | --- |
| draft | 計画作成済み。内容を提示して承認待ちへ |
| awaiting_approval | ユーザーの明示承認待ち |
| approved | 承認済みで未実行。対象を確認してexecuteへ |
| running | 実行中。別の処理を重複起動しない |
| succeeded | 実行または外部結果の保存が成功。品質合格・正式採用とは別 |
| blocked | 未実装等で停止。理由を確認し、新計画または対応済み経路へ |
| failed | ログと原因を確認し、修正後は新計画で再試行 |
| result_unknown | プロセス・結果をCodexが確認するまで再生成しない |
| cancelled | 実行前に取消済み |

```powershell
# 実行前の計画だけ取消できる
mwb generate cancel $PlanId --reason '入力画像を見直すため'
```

- IDが見つからない：保存先と完全なIDを確認。別の--rootでは同じIDを探せない。
- 非対話確認で停止：会話で承認済みならその証拠を--evidence／--reasonへ記録。まだなら承認を得る。
- hash不一致：入力またはコードが変わっている。新しい計画を作って確認し直す。
- image_prepareがblocked：executeではなく、承認済み新計画への外部結果registerを使う。
- ロック残存・結果不明：CodexがPID、開始時刻、ログ、出力を照合する。即削除・自動再実行しない。
- 出力0件：selectedのcharacter候補があるか確認。部品や画像だけの選択では出力しない。

終了コードは0成功、2構文、3操作失敗、130中断。状態と日本語メッセージも確認する。PowerShellのmwb関数は終了コードを$LASTEXITCODEへ返す。失敗したコマンドの後は続けず、原因を確認する。

## 14. 作業終了・再開・動作確認チェック

### 別の会話から再開する

```powershell
mwb project list
mwb project resume $ProjectId
mwb project note $ProjectId --kind next_step --prompt '最後に確認した候補ID、未決事項、次の作業をここへ記載する'
```

会話例：「この案件IDの続きを、フォルダとresumeの内容から復元してください。まだ再生成しないでください。」Codexが資料、要件、計画、承認証拠、候補と親ID、レビュー、ログ、実体hashを読み戻す。recoveryは索引の冗長化であり、画像やモデルを複製するものではない。

バックアップはprojects全体。Git対象外なのでpushは案件バックアップにならない。モデルだけでは要件・履歴・採用判断を復元できない。

### 生成なしで確認できる範囲

- [ ] mwbという短いコマンドで起動できる。
- [ ] 案件・資料・要件・部品構成を保存して完全なIDを確認できる。
- [ ] 対象IDだけでshow・承認待ち等を操作できる。
- [ ] 計画作成だけでは外部処理が始まらない。
- [ ] 未承認画像・誤った部品ID・別形状版の材質を拒否する。
- [ ] 中止・失敗でも元資料と過去候補が残る。

### 個別承認を受けた制作で確認する範囲

- [ ] 元資料と生成用画像を比較し、ユーザーが入力画像を承認できる。
- [ ] 一回分のTripoSR生成を実行し、OBJ候補を保持できる。
- [ ] 全身.blendをBlenderで開き、4方向でフィットを確認できる。
- [ ] 対象の拡大で他部品が保持される。
- [ ] 形状確定後の材質適用で形状と配置が保持される。
- [ ] レビュー・選択・正式採用を区別できる。
- [ ] 出力先モデルとmanifestを確認でき、過去の出力が残る。
- [ ] 生成速度以外に、修正時間、失敗、ユーザーが迷った箇所も記録できる。

## 15. 確認範囲と現在の制約

画像生成ハーネスの `docs/operation-manual.md`、Notionの同マニュアル、CLI実装を参照し、準備→案件→資料→要件→計画→確認・実行→レビュー・出力→ログ→エラー→チェック、の書式を揃えた。3D固有の部品構成・仮組み・材質を追加している。

コマンドは現在の `src/model_workbench/cli.py` と照合済み。PowerShellの36コードブロックに構文エラーがなく、89件のCLI呼び出しの引数とhelp例を確認した。自動テスト28件が合格し、既存OBJによる仮組み・限定編集・材質・source出力の互換経路も再確認した。今回、新規TripoSR生成は行っていない。

既存の二つのID、--goal／--description／--text、--hash、--recipe／--fileを使う構文も互換用に保持する。データ移行・既存案件の書き換え・TripoSR環境の依存更新は不要。

| 以前の指定 | 通常の指定 |
| --- | --- |
| Pythonパス＋mwb.py＋コマンド | セッション初期化後は `mwb` |
| generate show 案件ID 計画ID | `mwb generate show $PlanId` |
| generate approve 案件ID 計画ID --hash … --evidence … | `mwb generate approve $PlanId`、内容確認後y |
| candidate show 案件ID 候補ID | `mwb candidate show $CandidateId` |
| 入力画像登録時に計画・部品等を重ねて指定 | `mwb generate register $ImagePlanId '画像パス'` |
| JSONで部品・配置・材質・レビューを記述 | 通常は--name、--bind、--material、簡易review。詳細JSONはCodex用に継続 |

自然文だけからCLIが部品分割や形状・配置を自動推論する機能はない。Codexが会話を解釈し、明示したIDや必要な数値へ落とし込む。高度な造形、手修正.blendの候補自動登録、UV・ベイク、リグ、UEは未実装または未検証。実キャラクターの完成品質は今後のユーザー参加テストで評価する。

参照：[画像生成ハーネスの操作マニュアル](https://app.notion.com/p/3fbf252ab683813c8135c84d8a81c0af)、[制作フロー](https://app.notion.com/p/3fdf252ab68381a5b65ff7bc939e3dcd)。ローカル補足：`docs/session-resume.md`、`assets/body-bases/makehuman-hm08/README.md`。マニュアルの変更だけを根拠に、実生成・造形・UEを検証済みとは扱わない。
