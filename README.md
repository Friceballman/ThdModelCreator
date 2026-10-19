# ThdModelCreator

この端末では、iwbと同じ既存PATH上のユーザー用 `Python\bin` にmwb.cmdを登録済みです。PowerShellでも `mwb --help`、`mwb project list` と直接入力できます。関数の読み込みは不要です。登録用スクリプトはscripts/register-cli.ps1で、PATHやPythonパッケージは変更しません。リポジトリ内の `.\mwb.cmd` からも直接起動できます。

TripoSRとBlenderを接続し、キャラクターの部品生成・組み立て・反復修正が成立するかを検証するためのリポジトリです。

現在は、ver1の管理CLIとTripoSR互換経路に加え、ver2の親計画・造形用資料パック・CodexのBlender直接造形・仮組み・材質・手修正取込・追加点検・source出力を実装しています。単純形状のBlender一巡試験は通過していますが、任意のキャラクター品質、画像の描き起こし、UV・ベイク、リグ、UE連携は未検証または未実装です。

以下のver1資料は履歴として保持する。新規制作の基準はver2.0仕様書と操作メモを参照。

- [接続検証の手順と範囲](docs/integration-validation.md)
- [接続検証結果（2026-10-18）](docs/integration-results-2026-10-18.md)
- [設計書 ver1.0案](docs/design-v1.0.md)
- [UX仕様書 ver1.1](docs/ux-spec-v1.1.md)
- [現在の操作手順](docs/user-guide.md)
- [操作マニュアル ver1.1（短いmwbコマンド）](docs/operation-manual.md)
- [別の会話からの再開・復旧](docs/session-resume.md)
- [取得済み人体ベース候補（CC0）](assets/body-bases/makehuman-hm08/README.md)
- [初期実装・検証結果（2026-10-19）](docs/implementation-status-2026-10-19.md)
- [作業指針](AGENTS.md)
- [仕様書 ver2.0](docs/spec-v2.0.md)
- [ver2.0の操作メモ](docs/operation-manual-v2.0.md)

既存の `C:\AI_test\TripoSR` とBlenderを外部実行します。新しい依存の導入や既存環境の再構築は不要です。

最初にリポジトリ直下で存在確認を実行できます。このコマンドは生成やBlender起動を行いません。

```powershell
. .\mwb.ps1
mwb doctor
mwb status
```

実生成は、入力・回数・設定を明示した計画を利用者が確認した後に実行します。実験結果は `experiments/runs/` に実行ごとに保存し、Gitへは追加しません。成果物・ログを保管したい場合は実験フォルダ全体を別途バックアップしてください。

管理CLIの案件はリポジトリ直下の `projects/` に保存します。`--root` で保存先、`--config` で外部実行環境のJSONを指定できます。設定の相対パスは設定ファイル基準です。これらの共通オプションと `--json` はサブコマンドの前に指定します。

`mwb.ps1` はそのPowerShellセッションだけに短い `mwb` 関数を用意します。インストール・永続PATH変更は不要。作成時は案件ID、作成後は `mwb generate show <計画ID>`・`mwb candidate show <候補ID>` のように対象IDで操作します。通常の承認は `mwb generate approve <計画ID>` で対象を確認してyと回答します。Codexの非対話操作では会話の明示承認を--evidenceへ記録します。従来のPython直接起動・二つのID・hash指定・詳細JSONも互換用に保持しています。

```powershell
$Python = 'C:\AI_test\TripoSR\.venv\Scripts\python.exe'
& $Python -B mwb.py --help
& $Python -B mwb.py --json project list --terminal
& $Python -B -m unittest discover -s tests -v
```

既存資産によるBlender統合試験は、別途明示して起動します。通常の自動テストではBlenderやGPUを起動しません。

```powershell
# 新規TripoSR生成なし。既存椅子OBJを2部品として使用
& $Python -B scripts/smoke_ux.py
```

`scripts/smoke_ux.py --with-geometry` は、公式椅子画像の新規生成を1回含む別の試験です。生成計画を承認した場合だけ使用してください。各試験案件は `.cache/ux-smoke/projects/<project-id>/` に分離して保存します。

コードと仕様はGitで管理し、制作案件・個人設定・生成モデル・試験成果物はGitへ追加しません。共通の人体ベース候補は出典・ライセンスと一緒にassets/body-basesへ保持します。`projects/` 全体を別途バックアップしてください。パッケージ導入を行う場合は管理用の別仮想環境でのeditable installを想定しており、既存TripoSR環境へインストールする必要はありません。単体wheel配布は未検証です。
