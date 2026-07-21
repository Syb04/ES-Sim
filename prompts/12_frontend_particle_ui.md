# サブエージェント指示: フェーズ2 エミッタUI+軌道表示(フロントエンド)

対象リポジトリ: `/home/claude/ES-Sim/frontend`(npm install 済み)

ES-Sim(Tauri 2 + React 18 + TS strict)に粒子軌道追跡のUIを追加する。
必ず現状のコード(App.tsx / CadCanvas.tsx / types.ts / api.ts / style.css)を読んでから着手すること。
バックエンドには `POST /trace` が並行実装される。スキーマ契約は
`/home/claude/ES-Sim/prompts/11_backend_particle_trace.md` の「スキーマ契約」節を参照し、
**その型定義と完全に一致させること**(types.ts に Species / Emitter / ParticleSettings / TraceResult を追加、
Project.particles は optional)。

## やること

### 1. api.ts

- `trace(project): Promise<TraceResult>` を追加(`POST /trace`、body は project)

### 2. エミッタ配置ツール(CadCanvas)

- ツール `"emitter"` を追加(ツールバーにボタン「エミッタ」)
- ラインエミッタ: 1点目クリック → ラバーバンド → 2点目クリックで確定し
  `onSetEmitter(p1, p2)` を App に通知。Esc キャンセル
- エミッタが設定されていれば常時オーバーレイ表示: 緑系の線分+中点から
  `direction_deg` 方向の矢印(射出方向が分かるように)。point エミッタは×マーカー+矢印

### 3. 粒子パネル(サイドパネルに「粒子」セクション、または新規 `src/panels/ParticlePanel.tsx`)

- 粒子種: セレクト(電子/陽子/カスタム)。カスタム時は q [C]・m [kg] 入力
- エミッタ種別(line/point)、p1/p2 の数値表示(mm。ツールで設定した値の確認・微修正用)
- 粒子数 n、初期エネルギー [eV]、射出方向 [deg]、広がり半角 [deg]、
  dt [s](空欄=自動)、ステップ数、保存間隔
- これらは project.particles として保存/読込対象(既存の履歴 (Undo/Redo) には
  **含めなくて良い**。ジオメトリ編集と独立に管理してよいが、保存JSONには入れること)
- 「Trace」実行ボタン: `api.trace(project)` を呼ぶ(busy表示・エラー表示は既存 Solve と同様)。
  ジオメトリ変更で解析結果が破棄されるタイミングで trace 結果も破棄

### 4. 軌道表示(CadCanvas)

- `traceResult` prop を追加し、軌道をポリライン描画
  (色はシアン系 `rgba(0,200,255,0.5)` 程度、線幅1。粒子数が多くても見えるように半透明)
- 吸収された粒子の最終位置に小さな点(着地点)を描画
- 表示トグル「軌道」をツールバーまたはパネルに追加
- パネルに結果サマリ: 粒子数、吸収数/生存数、平均飛行時間、最終エネルギーの min/max

## 制約

- 新しい npm 依存を追加しない。コメントは日本語。TS strict 維持
- 既存機能を壊さない(スケッチ、移動、Undo/Redo、グリップ、円shape、プロファイル、可視化、mm入力、Mesh)

## 完了条件

`cd /home/claude/ES-Sim/frontend && npx tsc && npx vite build` 成功。
最後に変更ファイル一覧と操作方法の要約のみを報告。
