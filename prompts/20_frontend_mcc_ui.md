# サブエージェント指示: MCC設定・LXCatインポートUI(フロントエンド)

対象リポジトリ: `/home/claude/ES-Sim/frontend`(npm install 済み)

ES-Sim(Tauri 2 + React 18 + TS strict)にMCC(モンテカルロ衝突)のUIを追加する。
バックエンドのスキーマ契約は `/home/claude/ES-Sim/prompts/19_backend_mcc_lxcat.md` を参照し、
型を完全一致させること。必ず現状のコード(types.ts / api.ts / panels/PicPanel.tsx /
panels/FieldPanel.tsx / App.tsx)を読んでから着手すること。

## やること

### 1. types.ts / api.ts

- `XsProcess` / `McSettings`(gas, electron_processes, ion_processes, seed)を追加。
  `PicSettings` に `mcc: McSettings | null` と `see_energy_ev: number` を追加。
  `Region` / `BoundaryCondition` に `see_gamma?: number` を追加。
  `PicDiag` に `coll_e?` / `ion_events?` / `see_events?` を追加(optional で後方互換)
- `api.lxcatParse(text, species): Promise<{processes, warnings}>`(`POST /lxcat/parse`)

### 2. PICタブに「MCC(衝突)」セクション(PicPanel 内または新規 McSection)

- 有効チェック(OFF なら pic.mcc = null)
- ガス設定: ガス名(表示用テキスト)、圧力 [Pa]、ガス温度 [K]
- **LXCatインポート**: 「電子断面積を読込」「イオン断面積を読込」ボタン(`<input type="file">`)。
  ファイルテキストを `api.lxcatParse` に送り、成功したら `pic.mcc.electron_processes` /
  `ion_processes` を置換。warnings があれば表示
- 読込済みプロセスの一覧表示: 種別・ラベル(短縮)・閾値 [eV]・点数。クリアボタン
- SEE電子の初期エネルギー [eV] 入力
- 乱数シード入力
- pic.mcc は project.pic の一部として保存/読込されることを確認(既存の合成ロジック)

### 3. γ(二次電子放出係数)入力(FieldPanel)

- conductor 領域のプロパティに「二次電子 γ」数値入力(既定 0)
- 境界条件(Dirichlet辺)にも同様の γ 入力(コンパクトに)

### 4. 診断表示(PicPanel)

- 実行中/完了後のサマリに累計の電子衝突数・電離数・SEE数を表示
  (diag の `coll_e` / `ion_events` / `see_events`。undefined なら「-」)

## 制約

- 新しい npm 依存を追加しない。コメントは日本語。TS strict 維持
- 既存機能を壊さない。toDiagArray(types.ts)に新フィールドを追加する場合は
  optional の扱い(undefined 許容)に注意

## 完了条件

`cd /home/claude/ES-Sim/frontend && npx tsc && npx vite build` 成功。
最後に変更ファイル一覧と操作方法の要約のみを報告。
