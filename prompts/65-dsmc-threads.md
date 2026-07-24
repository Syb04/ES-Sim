# 65: DSMC のマルチコア化 (walk のチャンク並列)

## 背景 (ユーザー要望)

「DSMCの計算もマルチコア化できるかな？」
PIC は prompts/50 で walk (粒子のメッシュ横断探索) をチャンク並列化済み
(`PicSimulation._walk_chunked_submit`)。DSMC の `_move` も同じ `_walk_step`
(particles.py) を使っており、粒子ごとに独立・乱数不使用・決定的なので、
同じ方式でチャンク並列化しても**結果はビット単位で逐次実行と一致**する。

## 変更

### backend/es_sim/schema.py

- `DsmcSettings` に `threads: int = 1` を追加 (ge=1、le は PicSettings.threads と
  同じ制約に合わせる)。docstring/コメントも PIC 側の書き方に合わせる。

### backend/es_sim/dsmc.py

- `__init__` で `self._nthreads = max(1, int(s.threads))`、threads > 1 なら
  `ThreadPoolExecutor(max_workers=self._nthreads, thread_name_prefix="dsmc-chunk")`
  を生成 (pic.py の `_chunk_pool` と同じ構成)。
- `_walk_chunked(elem, x_new)` ヘルパを追加: pic.py の `_walk_chunked_submit` を
  参考に、n < 4096 または pool なしなら逐次 `_walk_step`、それ以外は
  k=threads チャンクに分割して submit し、**この関数内で完了を待って** 結合結果を
  返す同期版 (DSMC は種が1つなので futures を外へ持ち回す必要がない)。
  コメントに「粒子ごとに独立・読み取り共有のみ・乱数不使用の決定的処理なので
  チャンク分割しても結果は逐次と完全一致する」旨を書く。
- `_move` の2箇所の `_walk_step` 呼び出しを `_walk_chunked` に置き換える
  (2箇所目の残余レグ walk は粒子数が少ないので n<4096 フォールバックで自然に逐次になる)。
- 注意: dsmc.py の `_walk_step` 呼び出しは l_new を渡していない。ヘルパでも
  同じ引数構成 (l_new 相当は None) を維持する。

### frontend

- `frontend/src/types.ts`: DsmcSettings に `threads: number` を追加
  (既定値の補完箇所があればそこにも)。
- `frontend/src/panels/GasPanel.tsx`: setup セクションの「初期条件・計算設定」に
  「スレッド数」入力 (CommitNumberInput、整数、最小1) を追加。ヒント文は
  PicPanel と同様「walk 探索の並列スレッド数。結果は1と完全一致。CPUコア数程度まで」。
  既存プロジェクト読込 (threads 未定義) でも壊れないように `dsmc.threads ?? 1` で表示。

## テスト (backend/tests/)

- 既存の DSMC テストファイルに追加: 小さめのケース (数千粒子・数十ステップ) で
  threads=1 と threads=4 の DsmcResult (n/t/u/p 等の全フィールド) が
  **完全一致** (np.array_equal) することを確認するテスト。
- `cd backend && python -m pytest tests/ -q` が全件通ること (現在 133 passed)。

## 検証

- backend: pytest 全件パス。
- frontend: `cd frontend && npx tsc --noEmit && npx vite build`。
- 可能なら examples の DSMC ケース (または合成ケース) で threads=1/4 の
  実行時間を計測してスピードアップ目安を報告する (time.perf_counter で数ステップ)。

## 注意

- コメントは日本語で「なぜ」を書く既存スタイル。
- git commit はしない。
