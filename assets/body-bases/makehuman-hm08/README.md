# MakeHuman HM08 人体ベース候補

取得日：2026-10-19。人体ベースの候補確保という利用者の承認に基づく保存。各制作案件への正式採用は別途確認する。

公式出典：https://github.com/makehumancommunity/makehuman

取得版：`a8bc2d54ff0ac92e78ff71431b1023eda42bf482`。元メッシュは `makehuman/data/3dobjs/base.obj`。

公式LICENSE.mdの資産条項およびbase.obj内の個別宣言ではCC0-1.0。原本・LICENSE.md・CC0全文LICENSE.ASSETS.mdを保持した。URL・取得版・SHA-256はmanifest.json。MakeHuman本体のアプリケーションコードは取得・導入していない。

## 利用するファイル

- `base.obj`：公式原本。補助形状と関節位置のマーカーを含む。直接の制作入力には使わない。
- `derived/body-base.obj`：bodyグループのみの単一メッシュ。初期CLIのasset addに渡せる。
- `derived/body-base.blend`：ユーザーがBlenderで開いて体型・ポーズ・顔・背面等を確認するための編集原本候補。
- `derived/derivation.json`：処理内容、原本hash、派生ファイルhash、読み込み検証結果。

派生処理は `scripts/prepare_body_base.py`。原本のY-upをZ-up・正面-Yへ変換し、XY中心・足元Z=0、仮の身長1.7mに正規化した。この寸法はキャラクター資料から得た値ではなく、案件で調整するための仮定。上流UV座標を引き継いだが、UVの外観品質は未審査。

13,380頂点／13,378面。Blender 5.2でOBJ・.blendの再読み込みと身長を確認済み。リグ・スキンウェイト・衣服・画像テクスチャは含めない。目・歯等の独立した完成パーツも含めない。関節変形・UE・特定キャラクターへの適合性は未検証。

案件では、承認された身体部品IDに対して派生OBJを `asset add` し、体型・頭身・ポーズ・接続位置を資料に照らして確認する。元ベースをそのまま完成キャラクターと扱わず、案件ごとのコピーから編集候補を派生させる。
