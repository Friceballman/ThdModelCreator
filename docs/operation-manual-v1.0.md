# 操作マニュアル ver1.0｜ユーザー参加テスト・案件立案から静止モデル完成まで

履歴資料。通常の操作は[操作マニュアル ver1.1](operation-manual.md)を参照する。以下の長い構文は互換用に保持している。

更新日：2026-10-19。対象：現在の初期管理CLI。実装済み機能に合わせた操作資料であり、キャラクターの造形品質を保証するものではない。

## 1. このマニュアルで完成させるもの

具体例は「青い帽子のマネキン」。既存の人体ベースと、TripoSRで生成する帽子を組み合わせ、静止表示用の.blend・OBJ・材質付きsource一式を出力する。身体の造形を一から生成する工程や、リグ・UEでの動作確認は今回の例に含めない。

案件立案→資料の取り込み→要件整理→部品構成の確認→身体ベースの登録→帽子画像の準備と確認→帽子OBJの生成→仮組み→必要な修正→形状確定→部品ごとの材質適用→最終レビュー→選択・正式採用→出力、の順に進む。

通常、ユーザーは会話で希望を伝え、Codexが以下のCLIを操作する。ユーザーが全コマンドを手入力する必要はない。コマンド例は、処理と保存内容を確認したい場合、または自分で操作する場合に使う。

このページの作成は生成実行の承認ではない。承認を伴う例文・コマンドは、その案件でユーザーが実際に内容を確認した後に使う。一括実行せず、各「ユーザー確認」で止まる。

## 2. 現在できること・別途対応が必要なこと

- 実装済み：案件、画像資料とタグ、要件履歴、部品ID、計画承認、生成用画像の保存・入力承認、TripoSRによるOBJ生成、Blenderでの配置・組み立て、対象部品の拡大縮小、標準材質、レビュー、source出力、再開情報の読み戻し。
- 画像準備：外部で用意した結果を取り込み、計画・親画像・処理方法と関連付ける。CLIから画像描き起こしツールを自動起動する機能は未実装。
- 見た目の確認：ユーザーがBlenderで行ってよい。compareは情報とプレビューのパスを返し、GUIを開かない。
- 未対応または未検証：任意のスカルプト、滑らかな接合、自由な部品交換編集、画像テクスチャ生成、UV展開・ベイク、リグ・ウェイト、UE、アニメーション。

TripoSRに渡すのは一枚の画像。三面図を並べた画像を複数視点入力としては使わない。CLIの--promptは計画・意図を記録する文章で、TripoSRのテキスト条件ではない。形状に反映したい変更は入力画像または後続のBlender処理で表現する。

## 3. 起動準備とコマンドの読み方

PowerShellを使う。次の初期設定を同じターミナルで一度行う。

```powershell
Set-Location 'C:\Codex_Projects\ThDModelCreator'
$WorkbenchPython = 'C:\AI_test\TripoSR\.venv\Scripts\python.exe'
function Invoke-Mwb {
    & $WorkbenchPython -B .\mwb.py @args
    if ($LASTEXITCODE -ne 0) { throw "mwb failed: exit=$LASTEXITCODE" }
}
Invoke-Mwb config show
Invoke-Mwb doctor
Invoke-Mwb status
```

Invoke-Mwbは、このマニュアル内で入力を短くするPowerShell関数。例として `Invoke-Mwb doctor` は `& $WorkbenchPython -B .\mwb.py doctor` と同じCLIを呼ぶ。失敗時は先へ進めないよう例外を出す。JSONを受け取る例では--jsonとConvertFrom-Jsonを使う。

doctorは実行ファイルやキャッシュの存在確認。GPUや品質全体の合格を意味しない。確認に失敗したら設定とパスをCodexに調べてもらい、既存TripoSR環境を再構築しない。

既定の保存先はリポジトリのprojects。--root・--config・--jsonはサブコマンドより前に置く。別保存先を使う場合は全コマンドで同じ--rootを指定する。途中で切り替えると別の案件保存領域を参照する。

```powershell
# 別保存先を調べる構文例。以下の本編は既定のprojectsを使う
Invoke-Mwb --root '.cache/another-test' --json project list --terminal
Invoke-Mwb --help
Invoke-Mwb generate plan --help
```

後続の変数には、その案件の実際のUUIDや返却オブジェクトが入る。変数の値を省略UUIDや文字列「身体のUUID」へ置き換えない。ターミナルを閉じると変数・関数は消えるが、案件の記録は残る。再開は第16節を参照。

## 4. 案件を立案し、完成条件を記録する

会話例：「青い帽子を載せた静止マネキンを作りたいです。身体は確保済みの人体ベースを候補にし、帽子だけ生成してください。まず資料と完成条件を整理してください。」

検証対象・合格基準は案件ごとに決める。この例の案は、身体ベースの形状を保つ、帽子に目立つ浮き・めり込みがない、4方向を確認する、出力先の.blendを開ける、まで。具体的な許容差や資料への一致度はユーザーと決める。

```powershell
$Project = Invoke-Mwb --json project create --name '青い帽子のマネキン' --goal '人体ベースと帽子による静止モデルの制作・対話操作テスト' | ConvertFrom-Json
$ProjectId = $Project.id
$ProjectDir = Join-Path (Join-Path $PWD.Path 'projects') $ProjectId
$InputDir = Join-Path $ProjectDir 'inputs'
New-Item -ItemType Directory -Force -Path $InputDir | Out-Null

$KeepBody = Invoke-Mwb --json requirement add $ProjectId --category must_keep --text '身体ベースの形状を保持し、帽子の調整で変えない' --priority 1 | ConvertFrom-Json
$FitHat = Invoke-Mwb --json requirement add $ProjectId --category must_change --text '帽子を頭に配置し、正面・側面・背面・斜めで目立つ浮きやめり込みがないことをユーザーが確認する' --priority 1 | ConvertFrom-Json
$Finish = Invoke-Mwb --json requirement add $ProjectId --category improve --text '全身の色を確認し、出力先の.blendをBlenderで開ける状態にする' --priority 2 | ConvertFrom-Json
Invoke-Mwb project note $ProjectId --kind decision --text '静止モデルが今回の対象。リグ、関節変形、UE動作は今回の完成条件に含めない'
Invoke-Mwb requirement list $ProjectId --terminal
```

must_keepは保持、must_changeは必要な変更、improveは改善。合否の結果は後でreviewへ記録する。実際の条件が違えばtextを案件に合わせる。

ユーザー確認：目的、完成条件、対象外、今回使う資料が希望と合っているか。

## 5. 元資料を取り込み、タグを付ける

次のC:\Images内のファイルは例示。ユーザーが用意した実在ファイルに置き換える。三方向の資料がない場合はあるものだけ登録し、不明な方向を未確定と記録する。

```powershell
$FrontRef = Invoke-Mwb --json reference add $ProjectId 'C:\Images\hat-test\front.png' --role design --view front --description '帽子の輪郭と配色の主資料。背景は使わない' --priority 1 | ConvertFrom-Json
$SideRef = Invoke-Mwb --json reference add $ProjectId 'C:\Images\hat-test\side.png' --role orthographic --view side_left --description '帽子の奥行きとつばの形の補助資料' --priority 2 | ConvertFrom-Json
$BackRef = Invoke-Mwb --json reference add $ProjectId 'C:\Images\hat-test\back.png' --role design --view back --description '帽子背面の補助資料' --priority 2 | ConvertFrom-Json
Invoke-Mwb reference list $ProjectId --terminal
```

roleは役割、viewは方向、priorityは1〜5で1が最優先。登録は案件内へのコピーで元ファイルを変えない。Codexは保存された画像を実際に読み、共通点・矛盾・不明点を説明する。登録成功だけで資料を理解済みと扱わない。

側面・背面を登録しない場合は、以後の計画からも該当する--referenceと変数を省く。実在しない資料や空のIDを指定しない。

会話例：「正面の輪郭を優先してください。側面と背面は補助で、描かれていない裏側は推定として残してください。」

```powershell
Invoke-Mwb project note $ProjectId --kind open_question --text '帽子の内側の断面は資料なし。外観用の配置を先に評価し、実際に被れる中空構造かは未確定'
# 必要な場合だけ、理由を付けてタグや要件を改訂する構文例
Invoke-Mwb reference update $ProjectId $SideRef.id --priority 3 --reason '正面資料を優先するため補助資料の順位を変更'
```

ユーザー確認：資料の役割・優先順位と、推定する箇所。元資料と後で作る生成用画像を混同しない。

## 6. 部品構成を承認し、身体ベースを取り込む

この例では身体と帽子の2部品。曲がる身体を腕・脚の小片に分けず、連続した身体ベースを使う。

```powershell
$PartsFile = Join-Path $InputDir 'parts-v1.json'
@(
    @{ name = '身体'; description = '連続したMakeHuman人体ベース。静止表示用として適合性を確認する' },
    @{ name = '帽子'; description = '独立した生成部品。身体の形状を保ちながら配置する' }
) | ConvertTo-Json -Depth 10 | Set-Content -Encoding utf8 $PartsFile
$Proposal = Invoke-Mwb --json part plan $ProjectId --file $PartsFile --reason '身体と独立した帽子の2部品を提案' | ConvertFrom-Json
Invoke-Mwb part list $ProjectId --terminal
```

ユーザー確認：「この2部品で進める」「身体にこのベースを使う」を確認する。承認後のみ以下を行う。

```powershell
Invoke-Mwb part approve $ProjectId $Proposal.id --hash $Proposal.content_hash --evidence 'ユーザーが身体と帽子の2部品構成を確認し承認'
$BodyPartId = $Proposal.parts[0].id
$HatPartId = $Proposal.parts[1].id
$Body = Invoke-Mwb --json asset add $ProjectId 'assets/body-bases/makehuman-hm08/derived/body-base.obj' --part $BodyPartId --description '公式CC0人体ベースの身体のみ。身長1.7mは仮寸法。リグ・UE未検証' | ConvertFrom-Json
Invoke-Mwb project note $ProjectId --kind decision --text '身体候補はMakeHuman HM08の派生OBJ。共通assets内のREADME・manifestに出典とCC0ライセンスを保持。案件ではコピーから制作する'
```

身体ベースの確認用ファイルは `assets/body-bases/makehuman-hm08/derived/body-base.blend`。Blenderで体型・頭身・ポーズを見て、資料に合うか判断する。既存ベースを使う判断と、完成モデルの正式採用は別。

初期CLIのasset addは外部材質参照のないOBJ用。任意のFBXや.blendを同じコマンドに渡さない。取り込んだ部品は自動で全身へ配置されない。

## 7. 帽子の生成用画像を準備し、画像そのものを承認する

まずCodexが全資料を見て、TripoSRへ渡す一枚の画像の作成案を提示する。例：「帽子だけを一つ、輪郭が見える斜め方向で描き、背景を整理する。三面図は一枚に並べない」。資料にない部分の補完は推定と明記する。

```powershell
$ImagePlan = Invoke-Mwb --json generate plan $ProjectId --stage image_prepare --part $HatPartId --reference $FrontRef.id --reference $SideRef.id --reference $BackRef.id --prompt '帽子だけを一個写した入力画像を準備する。正面の輪郭と青い配色を保持し、補助資料から斜め方向を補完。不明な断面は推定と明記する' | ConvertFrom-Json
Invoke-Mwb generate show $ProjectId $ImagePlan.id
Invoke-Mwb generate request-approval $ProjectId $ImagePlan.id
```

ユーザー確認：どの画像を根拠に、何を残し、どこを描き直すか。承認後だけ次へ進む。

```powershell
Invoke-Mwb generate approve $ProjectId $ImagePlan.id --hash $ImagePlan.plan_hash --evidence 'ユーザーが帽子入力画像の作成方針と推定箇所を確認し承認'
```

ここではgenerate executeを使わない。image_prepareの自動実行アダプタは未実装で、executeするとblockedになる。画像生成・画像編集などの利用可能な外部ツールで、承認内容に沿って作業する。ツールが利用できない場合は、ユーザーが用意した画像を受け取る。実行していない画像生成を実施済みと記録しない。

外部で得た画像を保存し、次のパスを実際の出力画像へ置き換えて登録する。

```powershell
$HatImage = Invoke-Mwb --json image register $ProjectId 'C:\Images\hat-test\hat-prepared-v1.png' --part $HatPartId --plan $ImagePlan.id --method image_generation --description '承認済み画像準備計画の外部結果。背面・断面の推定はレビュー対象' | ConvertFrom-Json
Invoke-Mwb candidate show $ProjectId $HatImage.id
```

methodは実際の処理に合わせ、crop（切り抜き）、background_removal（背景除去）、image_generation（描き起こし）、external（その他）を使う。登録画像は案件内にコピーされる。計画は外部結果受領として完了し、CLIが画像生成を実行したとは記録しない。

ユーザー確認：保存された画像を実際に見て、対象が帽子一つか、元資料と一致するか、不要な身体・背景・複数視点が混ざっていないかを判断する。良ければ入力承認する。

```powershell
Invoke-Mwb image approve $ProjectId $HatImage.id --hash $HatImage.input_hash --evidence 'ユーザーがこの画像を見て資料との一致を確認し、帽子生成の入力として承認'
```

画像作成計画の承認と、出来た画像の入力承認は別。未承認画像ではgeometry計画を作れない。

修正する場合は、新しいimage_prepare計画に--source $HatImage.idを指定して親画像から派生させる。その新計画を確認・承認し、外部結果を--plan付きで登録、新画像を確認・承認する。古いファイルと候補は上書きしない。既に適切な入力画像がある場合は--planなしで直接登録できるが、image approveは必要。

## 8. 帽子のOBJを一回生成する

```powershell
$GeometryPlan = Invoke-Mwb --json generate plan $ProjectId --stage geometry --part $HatPartId --input $HatImage.id --reference $FrontRef.id --reference $SideRef.id --reference $BackRef.id --prompt '確認済みの帽子画像からOBJを一回生成。CUDA、chunk1024、メッシュ解像度128、ベイクなし' | ConvertFrom-Json
Invoke-Mwb generate show $ProjectId $GeometryPlan.id
Invoke-Mwb generate request-approval $ProjectId $GeometryPlan.id
```

ユーザー確認：入力画像ID、対象部品、実行回数1回、設定、保存先。承認後のみ実行する。

```powershell
Invoke-Mwb generate approve $ProjectId $GeometryPlan.id --hash $GeometryPlan.plan_hash --evidence 'ユーザーが指定画像から帽子OBJを一回生成する計画を承認'
$Hat = Invoke-Mwb --json generate execute $ProjectId $GeometryPlan.id | ConvertFrom-Json
Invoke-Mwb report show $ProjectId $GeometryPlan.id
Invoke-Mwb candidate show $ProjectId $Hat.id
```

RTX 3050 Tiの4GB環境では逐次処理する。初期設定はchunk1024・解像度128で固定され、--promptに別の値を書いても設定変更にはならない。モデルや背景除去用データの既存キャッシュを利用し、CPUへ自動切替しない。

geometryの結果はpart候補で、OBJを含む。Blenderの「ファイル→インポート→Wavefront OBJ」から確認できる。保存先はcandidate showのfilesを案件フォルダ基準で解決する。後の仮組みでは.blendも作られる。

ユーザー確認：帽子らしい輪郭、背面の破綻、余分な面や突起、用途に対して必要な厚み・内側。生成成功は品質合格ではない。帽子内部が中空になっていることも自動では保証しない。

再生成するなら新しいgeometry計画を作り、--source $Hat.idで親形状、--inputで今回の画像候補を指定する。計画を改めて承認し、別候補として生成する。同じ画像なら同種の結果になる可能性があり、文章だけ変えて形状が変わるとは扱わない。

## 9. 身体と帽子を仮組みする

身体はZ-up・正面-Y、足元Z=0、仮身長1.7mに調整済み。TripoSR部品の寸法・原点・向きは実寸と一致するとは限らない。帽子の位置・回転・スケールを確認して組み合わせる。

以下の位置とスケールは記述例であり、フィット済みの値ではない。Codexがメッシュ寸法と頭部位置を調べて初期値を提案し、実際の候補に合わせて変更する。rotation_degreesの単位は度。

```powershell
$AssemblyFile = Join-Path $InputDir 'assembly-v1.json'
@{ bindings = @(
    @{ part_id = $BodyPartId; candidate_id = $Body.id; location = @(0,0,0); rotation_degrees = @(0,0,0); scale = @(1,1,1) },
    @{ part_id = $HatPartId; candidate_id = $Hat.id; location = @(0,0,1.65); rotation_degrees = @(0,0,0); scale = @(0.25,0.25,0.25) }
) } | ConvertTo-Json -Depth 12 | Set-Content -Encoding utf8 $AssemblyFile
$AssemblyPlan = Invoke-Mwb --json generate plan $ProjectId --stage assembly --recipe $AssemblyFile --prompt '身体と帽子を別オブジェクトのまま配置し、フィットを確認する' | ConvertFrom-Json
Invoke-Mwb generate show $ProjectId $AssemblyPlan.id
Invoke-Mwb generate request-approval $ProjectId $AssemblyPlan.id
```

ユーザー確認：使用する身体・帽子候補、配置と寸法、身体を変えない方針。

```powershell
Invoke-Mwb generate approve $ProjectId $AssemblyPlan.id --hash $AssemblyPlan.plan_hash --evidence 'ユーザーがこの部品候補と配置での仮組み計画を承認'
$Assembly = Invoke-Mwb --json generate execute $ProjectId $AssemblyPlan.id | ConvertFrom-Json
$Shape = $Assembly
$BlendEntry = $Assembly.files | Where-Object { $_.file -like '*.blend' } | Select-Object -First 1
$ModelPath = Join-Path $ProjectDir $BlendEntry.file
$ModelPath
```

表示された.blendをBlenderの「ファイル→開く」で開く。正面・側面・背面・斜めから、頭身、帽子の大きさ、位置、隙間、めり込み、身体の保持を見る。仮組み結果には4方向PNGとchecks.jsonも含まれる。

合体は、この段階では部品の配置と全身候補の構成保存を指す。身体と帽子を一つのメッシュへ溶接することではない。全ての承認済み部品を1回ずつ割り当てる必要があり、足りないと計画を作れない。

## 10. 対話で修正し、形状を確定する

会話例：「身体は変えず、帽子だけ10%大きくしてください。まだ正式採用しないでください。」

現在の専用編集は、全身候補中の一部品をオブジェクト原点基準で拡大縮小する処理。帽子の頂点を部分的に彫り直す処理ではない。

以下の編集コマンドは必要な場合だけ行う。修正が不要ならコマンドを省き、この節末尾の形状確定へ進む。

```powershell
$EditFile = Join-Path $InputDir 'hat-scale-v1.json'
@{ edit = @{ part_id = $HatPartId; scale_factor = 1.1 } } | ConvertTo-Json -Depth 10 | Set-Content -Encoding utf8 $EditFile
$EditPlan = Invoke-Mwb --json edit plan $ProjectId --source $Shape.id --stage assembly --recipe $EditFile --prompt '帽子だけを原点基準で1.1倍。身体の形状と配置は保持' | ConvertFrom-Json
Invoke-Mwb generate show $ProjectId $EditPlan.id
Invoke-Mwb generate request-approval $ProjectId $EditPlan.id
# ユーザーが変更内容を確認・承認した後のみ
Invoke-Mwb generate approve $ProjectId $EditPlan.id --hash $EditPlan.plan_hash --evidence 'ユーザーが帽子だけ1.1倍にする限定編集を承認'
$Edited = Invoke-Mwb --json generate execute $ProjectId $EditPlan.id | ConvertFrom-Json
Invoke-Mwb candidate compare $ProjectId $Shape.id $Edited.id
$Shape = $Edited
```

ユーザーは編集後の.blendも開く。拡大で頭との位置関係が変わるため、再度フィットを確認する。比較情報の出力だけで見た目の確認を済ませない。

位置・回転を変更する場合は、新しいassemblyレシピへ同じ部品候補を割り当て、変更対象以外の値を保持した新規assembly計画を作る。これは既存の全身候補を--sourceで渡す限定拡大とは別経路で、新旧構成の確認はCodexとユーザーが行う。旧候補IDと変更理由はproject noteに残す。自由な造形修正や手修正.blendの候補取り込みは未対応のため、その場で対応方法を相談する。

形状が良ければ、ユーザーの確認後に記録する。

```powershell
Invoke-Mwb candidate confirm-shape $ProjectId $Shape.id --reason 'ユーザーが4方向と身体保持・帽子フィットを確認し、材質工程へ進む形状として確定'
```

confirm-shapeは材質工程へ進むための判断。最終モデルの正式採用や、リグ・関節品質の合格とは別。

## 11. 全身を見ながら各部品へ材質を適用する

身体は灰色、帽子は青の例。現在はPrincipled BSDFの色・Roughness・Metallicを設定する。詳細な模様、顔の描画、布の画像テクスチャ生成、UV・ベイクは行わない。

```powershell
$BodyMat = Invoke-Mwb --json material create $ProjectId --part $BodyPartId --source $Body.id --name '灰色マネキン' --color '0.55,0.55,0.55' --roughness 0.75 --metallic 0 | ConvertFrom-Json
$HatMat = Invoke-Mwb --json material create $ProjectId --part $HatPartId --source $Hat.id --name '青い帽子' --color '0.05,0.20,0.65' --roughness 0.85 --metallic 0 | ConvertFrom-Json
$MaterialsFile = Join-Path $InputDir 'materials-v1.json'
$MaterialMap = @{}
$MaterialMap[$BodyPartId] = $BodyMat.id
$MaterialMap[$HatPartId] = $HatMat.id
@{ materials = $MaterialMap } | ConvertTo-Json -Depth 10 | Set-Content -Encoding utf8 $MaterialsFile
$SurfacePlan = Invoke-Mwb --json generate plan $ProjectId --stage surface --source $Shape.id --recipe $MaterialsFile --prompt '形状と配置を保持し、身体は灰色・帽子は青の標準材質を適用' | ConvertFrom-Json
Invoke-Mwb generate show $ProjectId $SurfacePlan.id
Invoke-Mwb generate request-approval $ProjectId $SurfacePlan.id
```

材質の--sourceには対象部品の形状候補ID（Body.id、Hat.id）を渡す。全身候補Shape.idを渡す箇所とは違う。帽子を再生成・交換した場合は、新しい帽子形状に対応する材質を作る。

ユーザー確認：対象形状の版、全ての部品への材質割当、配色と質感。

```powershell
Invoke-Mwb generate approve $ProjectId $SurfacePlan.id --hash $SurfacePlan.plan_hash --evidence 'ユーザーが全身の材質割当と標準材質適用計画を承認'
$Surface = Invoke-Mwb --json generate execute $ProjectId $SurfacePlan.id | ConvertFrom-Json
Invoke-Mwb candidate compare $ProjectId $Shape.id $Surface.id
$SurfaceBlend = $Surface.files | Where-Object { $_.file -like '*.blend' } | Select-Object -First 1
Join-Path $ProjectDir $SurfaceBlend.file
```

表示された.blendをBlenderで開く。色だけでなく粗さ・金属度も確認する場合はMaterial PreviewやRendered表示で見る。付属のWorkbenchプレビューは材質色の簡易表示で、照明下の最終質感の判定には使わない。

材質が不適合なら、新しいmaterial IDとsurface計画を作り、旧候補を残して再適用する。形状修正が必要になった場合は形状工程へ戻り、影響する材質・UV等の確認をやり直す。

## 12. 最終レビューを保存する

ユーザー確認：この案件で定義した条件を、一つずつ実際の結果と照合する。自動検査と見た目の判断を分ける。UE等の対象外項目を「確認済み」にしない。

以下はレビューの書式例で、サンプルのため全項目uncertainにしてある。実際に確認してからresultとreasonを編集し、保存・登録する。resultはpass・fail・uncertain・not_applicable。

```powershell
$ReviewFile = Join-Path $InputDir 'review-final-v1.json'
@{
    entries = @(
        @{ requirement_id = $KeepBody.id; result = 'uncertain'; reason = '未記入。構造検査とユーザーの確認結果に置き換える' },
        @{ requirement_id = $FitHat.id; result = 'uncertain'; reason = '未記入。確認した方向とフィットの結果に置き換える' },
        @{ requirement_id = $Finish.id; result = 'uncertain'; reason = '未記入。配色と出力後の再読み込み結果を記録する' }
    )
    summary = 'レビュー記入用の下書き。正式採用の根拠としては未完成。'
} | ConvertTo-Json -Depth 12 | Set-Content -Encoding utf8 $ReviewFile
# JSON入力ファイルを実際のレビュー結果に編集した後に登録
Invoke-Mwb review $ProjectId $Surface.id --file $ReviewFile
```

reviewは評価内容を保存する機能。全要件の評価完了やpassだけであることを自動保証しない。fail・uncertainを残して採用するか、修正するかは理由を明示してユーザーが判断する。最終出力を開く確認は第14節の後に追記できる。

## 13. 出力候補を選び、必要なら正式採用する

```powershell
Invoke-Mwb candidate list $ProjectId --kind character --terminal
# ユーザーが出力する全身候補を選んだ後のみ
Invoke-Mwb candidate select $ProjectId $Surface.id --reason 'ユーザーがこの材質付き全身候補をsource出力対象として選択'
```

選択は複数件可能。出力はselectedの全身候補を全て含むので、過去の選択が残っていないか確認する。外したい候補はcandidate holdで保留へ変更する。candidate rejectは却下で、候補自体は消えない。

正式採用は別の操作。レビュー済みでselectedの全身候補を案件の採用モデルにする。試験出力だけなら、この操作は省略できる。

```powershell
# 任意。ユーザーが最終採用を指示し、レビュー内容を確認した後のみ
Invoke-Mwb project set-approved $ProjectId $Surface.id --reason 'ユーザーが今回の静止モデル完成版として正式採用'
```

generate approveは実行計画、image approveは入力画像、confirm-shapeは形状工程の区切り、candidate selectは出力候補、set-approvedは完成モデルの正式採用。用途を分けて記録する。

## 14. 名前付きで出力し、出力先を確認する

```powershell
$Export = Invoke-Mwb --json project export $ProjectId --name '青い帽子のマネキン' --profile source --reason 'ユーザーが選択済み全身候補のsource出力を依頼' | ConvertFrom-Json
$Export
if ($Export.count -eq 0) { throw '選択済み全身候補がありません' }
$ManifestPath = Join-Path $ProjectDir $Export.file
$Manifest = Get-Content -LiteralPath $ManifestPath -Raw -Encoding utf8 | ConvertFrom-Json
$ExportDir = Split-Path -Parent $ManifestPath
Get-ChildItem -LiteralPath $ExportDir -Recurse
```

保存先は `projects/<案件ID>/exports/<出力ID>/`。1候補なら「青い帽子のマネキン」フォルダ、複数候補なら候補ID順に_001等を付ける。フォルダ内はmodel.blend、model.obj、材質付きならmodel.mtl、4方向PNG、checks.json、composition.json等。manifest.jsonで候補IDとhashを追跡する。内部ファイル名は参照の整合性のため固定で、モデル本体の自由な名前変更は初期対応に含めない。

ユーザー確認：出力先のmodel.blendを開き、制作中の候補と同じ形状・配色になっているかを見る。必要ならOBJも読み込んで確認する。.blendが編集原本で、OBJ/MTLがBlender固有の材質を同じ表現で保持するとは限らない。これはsource出力で、UE向けの完成検証済み出力ではない。

確認後はレビューを新しい入力ファイルとして記録する。例えば第12節で作った下書きのFinish項目を実際の結果へ改訂し、summaryも更新してreviewを再登録すると、過去レビューを残せる。正式採用前なら、この確認後に第13節のset-approvedを行う。

全身候補の.blend、元画像、共通assets内の人体ベースは直接上書きしない。Blenderで手修正したい場合は別名で保存してCodexへ引き継ぐ。手修正.blendの候補自動登録は未対応。

## 15. 今回の動作テストで記録すること

- 案件の対象、完成条件、使った資料と推定箇所。
- 各確認でユーザーが迷った点、希望が正しく伝わったか、承認の対象が明確だったか。
- 画像候補・部品候補・全身候補のID、比較と判断の理由。
- 生成時間、失敗、修正にかかった時間、保持すべき身体が変わっていないか。
- 出力後の再読み込み結果。対象外のリグ・UE等を完了扱いしていないか。

```powershell
Invoke-Mwb project note $ProjectId --kind next_step --text '次回は出力先.blendのユーザー確認結果をレビューへ追記。現在の候補IDと未決事項もこのメモへ記載する'
Invoke-Mwb status $ProjectId
```

コマンドが通ったかと、モデルが希望通りかは別に記録する。この例の完成は、案件で合意した静止モデルの条件を満たし、ユーザーが結果と出力を確認できたこと。

## 16. 中断・エラー・別の会話からの再開

```powershell
# 新しいターミナルでは第3節の関数を再定義してから実行
Invoke-Mwb --json project list --terminal
# 一覧で案件を特定し、実際の完全なUUIDを設定
$ProjectId = 'ここを実際の案件UUIDに置き換える'
Invoke-Mwb status $ProjectId
Invoke-Mwb --json project resume $ProjectId
Invoke-Mwb generate list $ProjectId --terminal
Invoke-Mwb candidate list $ProjectId --terminal
```

会話例：「この案件IDの続きをお願いします。フォルダとproject resumeの記録から、資料、確定済み事項、未決事項、最後の候補、次の作業を復元してください。まだ再生成しないでください。」

Codexはnotes、要件履歴、構成、計画と承認根拠、候補と親ID、ログ、レビュー、出力、ファイルhashを確認して文脈を読み戻す。PowerShell変数も実際の記録から設定し直す。詳細はリポジトリの `docs/session-resume.md`。

- 未承認・hash不一致：現在の計画・画像を確認する。コードや入力が変わった計画は新規作成して再承認する。
- image_prepareがblocked：画像準備アダプタは未実装。新しい計画を承認し、第7節の外部結果登録の経路を使う。
- failed：report showで理由とrunのログを読む。原因修正後は新計画で再試行し、同じ計画を再実行しない。
- running/result_unknown、残存ロック：Codexにプロセスと出力を確認してもらう。ロックを手当たり次第に消したり、重複生成したりしない。
- モデルの見た目が不適合：入力画像、生成形状、配置、材質のどの段階に原因があるかを切り分け、対象工程から派生させる。
- 出力0件：selectedのcharacter候補があるか確認。画像・部品の選択だけではsource出力しない。

CLIの終了コードは0成功、2コマンド構文、3操作失敗、130中断。Invoke-Mwbは非0なら停止する。生成計画の状態や実体ファイルも確認し、終了コードだけで復旧を判断しない。

案件全体をバックアップする。project.jsonが索引、references・artifacts・runs等に実体、recoveryに索引の全文チェックポイントがある。recoveryだけでは画像・モデルは復元できない。projectsはGit管理対象外なので、Gitへのpushは制作案件のバックアップにならない。

## 17. 関連仕様・この資料の検証範囲

- [UX仕様書 ver1.1](https://app.notion.com/p/3fdf252ab68381f0b19cc0fa5b190e61)
- [制作フロー ver1.0](https://app.notion.com/p/3fdf252ab68381a5b65ff7bc939e3dcd)
- 実装根拠：`src/model_workbench/cli.py`、`workflow.py`、`runtime.py`、`storage.py`、`recovery.py`。
- ローカル補足：`docs/user-guide.md`、`docs/session-resume.md`、`assets/body-bases/makehuman-hm08/README.md`。

文書中のPowerShell構文とCLI引数を実装に照合済み。このマニュアル作成時には、ユーザーの実資料による新規生成や、上記の人体＋帽子の一連の制作を実行していない。キャラクターの完成品質は、これから行うユーザー参加テストで評価する。
