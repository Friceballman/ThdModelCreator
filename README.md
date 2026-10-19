# ThdModelCreator

画像資料からキャラクター部品を設計し、Blenderで造形・組み立て・材質付け・点検するローカルCLIハーネスです。3D処理の実行先はBlenderだけです。画像生成はハーネス外で行い、結果を資料として取り込みます。

ver2では親計画、造形用資料パック、部品ごとのBlender直接造形と前候補の修正、仮組み、材質、手修正取込、追加点検、静止モデルのsource出力を扱います。試行枠は実行開始時だけ消費し、状態キーワードで候補を探せます。通常の見た目確認画像は材質適用済み全身候補で生成します。単純形状の実機一巡試験は通過していますが、任意のキャラクター品質、画像の描き起こし、UV・ベイク、リグ、UE連携は未検証または未実装です。

新規制作の基準は[仕様書 ver2.0](docs/spec-v2.0.md)と[操作メモ](docs/operation-manual-v2.0.md)です。ver1の資料は履歴として保持します。旧案件の記録・候補は読み取れますが、旧式の造形計画は再実行できません。既存の `projects/` は移動・削除しません。

## 起動

Python 3.11以上とPillow、Blender 5.2系を使用します。`experiments/config.example.json` の `blender` パスを参照し、既定ではPATH上の `python` で起動します。別のPythonを使う場合は `MWB_PYTHON` を指定します。3D生成用の別環境は必要ありません。

```powershell
.\mwb.cmd doctor
.\mwb.cmd project list
python -B -m unittest discover -s tests -q
```

PowerShellでは `. .\mwb.ps1` で `mwb` 関数を読み込めます。`--root`、`--config`、`--json` はサブコマンドの前に置きます。`mwb doctor` はBlenderファイルの存在確認のみで、造形や品質検査は行いません。

明示的なBlender一巡試験は `python -B scripts/smoke_v2.py` です。試験は隔離した一時案件に出力し、通常の自動テストはBlenderを起動しません。

コードと仕様はGitで管理し、制作案件・個人設定・生成物・試験成果物はGitへ追加しません。案件全体を別途バックアップしてください。共通の人体ベース候補は[出典とライセンス](assets/body-bases/makehuman-hm08/README.md)を確認してください。

## 履歴資料

- [設計書 ver1.0案](docs/design-v1.0.md)
- [UX仕様書 ver1.1](docs/ux-spec-v1.1.md)
- [接続検証結果](docs/integration-results-2026-10-18.md)
- [旧操作マニュアル](docs/operation-manual-v1.0.md)
- [作業指針](AGENTS.md)
