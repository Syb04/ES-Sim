# サブエージェント指示: PICの続き実行(バックエンド)

対象リポジトリ: `/home/claude/ES-Sim/backend`(pic.py / server.py の最新実装が前提)

PIC 実行の完了(または停止)後に、**粒子状態・表面電荷・時刻・乱数状態を保持したまま
追加ステップを実行**できるようにする。

## WSプロトコル契約(フロントと共通)

- 既存: `{"cmd":"start", "project":...}` — 新規実行。完了/停止後もシミュレーション状態を
  サーバー側に保持する(プロセス内のスロット1つ。新しい start で置き換え)
- 追加: `{"cmd":"continue", "n_steps": 2000, "frame_every": 20, "avg_steps": null,
  "phase_bins": null}` — 保持中の状態から追加実行。avg_steps/phase_bins は null なら
  前回設定を踏襲。保持状態が無ければ `{"type":"error","detail":...}`
- continue の応答は start と同形: `started`(dt・n_steps=追加分・warnings・mesh)→
  `frame`(step は追加分内の番号で良いが `t` は通算時刻)→ `done`(history は**追加区間分**、
  fields / cycle / collector は**追加区間の平均**で再計算)

## 実装

- server.py: モジュールレベルの保持スロット(`_last_sim` + asyncio.Lock)。
  実行中の start/continue は拒否(error)。done/stop 後も sim を保持
- pic.py: `prepare_continue(n_steps, frame_every, avg_steps, phase_bins)` を追加:
  диагностика history・平均/位相/コレクタのアキュムレータを**リセット**し、
  粒子状態(x, v, w, elem)・q_surf・時刻 t・step_count・乱数 Generator・注入状態は**維持**。
  警告(ωpe·dt 等)は現在の粒子から再評価しなくて良い(前回のものを流用可)
- **重要な検証性質**: 乱数 Generator と粒子状態を保持するため、
  「200ステップ連続実行」と「100ステップ実行 → continue で100ステップ」は
  (平均区間を揃えなければ粒子状態が)**ビット単位で一致**するはず。これをテストで保証する
- 診断 history の t は通算時刻で単調増加すること(フロントはチャートに追記する)

## テスト(`tests/test_continue.py` 新規)

1. **ビット一致**: MCC・RF付き小ケースで、200ステップ連続 vs 100+continue(100) の
   粒子位置・速度・q_surf・粒子数が完全一致(平均系アキュムレータは比較対象外)
2. **時刻の連続性**: continue 後の history["t"] が前回最終時刻から連続
3. **保持なしエラー**: 状態なしで continue するとエラーになること(WS TestClient)
4. **fields再計算**: continue 区間の avg_steps 指定で fields が返ること
5. 既存65テストを壊さない

## 制約

新しい依存なし。日本語コメント。スキーマ/プロトコルは追加のみ(後方互換)。

## 完了条件

`python -m pytest tests/ -q` 全件パス。変更ファイル一覧とテスト結果のみ報告。
