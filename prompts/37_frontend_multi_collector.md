# サブエージェント指示: 複数コレクタのUI(フロントエンド)

対象リポジトリ: `/home/claude/ES-Sim/frontend`(npm install 済み)

バックエンドのスキーマ契約は `/home/claude/ES-Sim/prompts/36_backend_multi_collector.md` を参照。
types.ts / App.tsx / canvas/CadCanvas.tsx / panels/PicPanel.tsx を読んでから着手すること。

## やること

1. **types.ts**: `PicCollectorSettings` に `label?: string`。
   `PicSettings.collectors?: PicCollectorSettings[]`(単数 `collector` は互換のため型に残す)。
   `PicDoneMsg.collectors?: PicCollectorResult[]`

2. **配置ツール**: コレクタツールで線分を確定するたびに `pic.collectors` へ**追加**
   (最大8個。達したらヒント表示)。ラベルは自動で "C1", "C2", ...(欠番は詰めない)。
   旧形式 `collector` 単数を持つプロジェクト読込時は collectors へ移行

3. **キャンバス表示**: すべてのコレクタを描画。色はコレクタごとに固定パレットから循環
   (黄・シアン・マゼンタ・緑…)。線分中点付近にラベル ("C1" 等) を小さく描く

4. **PICタブ「IEDF/IADF」セクション**:
   - コレクタ一覧: ラベル(編集可)・p1/p2 [mm]・tol [mm]・行ごとの削除ボタン。
     一覧の行クリックで選択(キャンバス上で選択中を強調)
   - done 受信後: 「表示コレクタ」セレクト(C1/C2/...)で選んだコレクタの
     IEDF/IADF ヒストグラムを表示(既存の HistogramChart を流用)。
     サンプル数・総実イオン数・truncated はコレクタごとに表示
   - CSV保存は選択中コレクタの生サンプル(ファイル名に ラベル を含める)
   - 実行結果が collectors 配列で来ない旧バックエンドとの互換は不要
     (単数 collector キーのみの場合は先頭扱いにできれば尚可)

## 制約

新しい npm 依存なし。日本語コメント。TS strict 維持。既存機能を壊さない。

## 完了条件

`cd /home/claude/ES-Sim/frontend && npx tsc && npx vite build` 成功。
変更ファイル一覧と操作方法の要約のみ報告。
