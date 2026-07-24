# 68: PIC ステップ数の RFサイクル換算表示

## 背景 (ユーザー要望)

「PIC計算時にステップ数を指定すると思います。そのステップが何RFサイクルに
相当するのか表示する機能を追加してほしい」

RF放電の計算ではステップ数を「RF何周期分回すか」で決めたいことが多い。
換算は サイクル数 = n_steps × dt / T_rf (T_rf = 1/f_rf)。

## 仕様 (frontend のみ、PicPanel.tsx)

- 表示場所: 「PIC: 計算設定」セクションの「ステップ数」フィールドの直下に
  hint (`<p className="hint">`) として表示する。
- RF周波数の取得: `project.geometry.boundaries` の Dirichlet 境界の
  `voltage_rf` (単一 or 配列。types.ts の VoltageRf を確認) から、
  **全境界の全成分の周波数を重複排除して昇順に**集める。
  周波数 0 や未設定成分は除外。
- dt の決定 (換算に使う実効 dt):
  1. `pic.dt` が指定されていればそれ
  2. 指定なし (自動) の場合、直近の実行があれば `started.dt` (PicPanel は
     `started` prop を既に持っている)
  3. どちらも無ければ換算不能
- 表示内容 (周波数ごとに1行):
  - `13.56e6 Hz: 2000 ステップ ≈ 27.1 RFサイクル (1サイクル ≈ 73.7 ステップ)`
    の形式。周波数は formatNumber (CommitInput.tsx の既存関数) で整形、
    サイクル数は有効3桁程度 (toPrecision(3) 相当、1未満なら例 0.271)、
    ステップ/サイクルは小数1桁。
  - dt を started から取った場合は行末に「(前回実行の dt で換算)」を付ける。
  - 換算不能 (dt 自動かつ未実行) の場合:
    「dt が自動のため、RFサイクル換算は実行開始後に確定します」と1行表示。
  - RF が1つも設定されていない場合は何も表示しない (行自体を出さない)。
- 換算はサブサイクル等とは無関係 (電子 dt 基準) なので追加の係数は不要。

## 実装メモ

- PicPanel 内に小さいヘルパ `collectRfFrequencies(project): number[]` を置く。
  同等のロジックが FieldPanel の RfComponentsEditor 周辺にあれば流用可否を確認
  (なければ新設で良い)。voltage_rf は `VoltageRf | VoltageRf[] | undefined` の
  両形式に対応すること (rf_components の正規化と同じ扱い)。
- 表示は setup モード (`show("setup")`) のみで良い。

## 検証

- `cd frontend && npx tsc --noEmit && npx vite build` が通ること。
- 換算式の手計算チェックをコメントか最終報告に記載
  (例: dt=3e-11, 13.56MHz → T=7.3746e-8 s → 1サイクル≈2458.2ステップ、
   n_steps=2000 → 0.814 サイクル)。

## 注意

- backend には触れない。コメントは日本語で「なぜ」を書く既存スタイル。
- git commit はしない。
