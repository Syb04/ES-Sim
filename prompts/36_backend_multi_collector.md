# サブエージェント指示: 複数コレクタ対応(バックエンド)

対象リポジトリ: `/home/claude/ES-Sim/backend`(pic.py の最新実装が前提)

IEDF/IADF コレクタ(prompts/30)を複数設定できるようにする。

## スキーマ契約(フロントと共通)

- `Collector` に `label: str = ""` を追加(表示用。空なら "C1" 等をフロントが振る)
- `PicSettings.collectors: list[Collector] = []` を追加(**最大8個**、validator で検査)
- 既存の `PicSettings.collector`(単数)は**後方互換のため残し**、
  validator で「collector が設定され collectors が空なら collectors=[collector] に正規化、
  collector は None にする」変換を行う(以後の内部処理は collectors のみ参照)
- WS `done`: `"collectors": [CollectorResult...]`(collectors と同順、各要素は従来の
  CollectorResult と同形)。従来の単数 `"collector"` キーは
  collectors が1個のときのみ互換のため併せて出力する

## 実装

- pic.py のコレクタ記録を配列化: 前計算(接線・法線・tol)とサンプルストレージを
  コレクタごとに持ち、吸収イオンの判定は各コレクタに対してベクトル化で実施
  (1つのイオンが複数コレクタに同時該当する場合は両方に記録して良い)
- サンプル上限 50000 は**コレクタごと**に適用
- `prepare_continue` でのリセットも配列対応
- `run_batch` は `self.collector_results`(list)へ格納(旧 `collector_result` は
  1個目のエイリアスとして残す)

## テスト(`tests/test_multi_collector.py` 新規)

1. 既存 test_iedf の決定的ケースを2コレクタ(陰極全面+中央半分)で実行し、
   全面側は全イオン・半分側は対応するイオンのみが記録されること(単数時代と同値)
2. 後方互換: 旧形式 `collector`(単数)指定のプロジェクトが collectors=[1個] に正規化され、
   done に `collector`(単数)キーも出ること
3. 9個指定で ValidationError
4. 既存74テストを壊さない(test_iedf は正規化経由で従来通りパスすること)

## 制約

新しい依存なし。日本語コメント。スキーマは追加+互換変換のみ。

## 完了条件

`python -m pytest tests/ -q` 全件パス。変更ファイル一覧とテスト結果のみ報告。
