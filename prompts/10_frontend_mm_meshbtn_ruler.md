# サブエージェント指示: mm表示・Meshボタン・ルーラー文字サイズ

対象リポジトリ: `/home/claude/ES-Sim/frontend`(npm install 済み)

ES-Sim は 2D静電場FEMアプリ(Tauri 2 + React 18 + TS strict)。
必ず現状のコード(App.tsx / CadCanvas.tsx / CommitInput.tsx / api.ts / types.ts)を読んでから着手すること。
ユーザー要望による機能追加3件。

## 1. 長さ入力の mm 表示化

- 内部データ(project)は**従来通り m のまま**。UIの入出力だけ mm に変換する
- 対象: メッシュサイズ、domain の幅/高さ、円領域の中心X/Y・半径(すべての長さ入力欄)
- ラベルに `[mm]` を明記。表示は `m値 × 1000`、確定時に `/1000` して保存
- 換算ヘルパーを1箇所にまとめ、丸め誤差で値が揺れないよう表示は適度な桁数に
  (例: `parseFloat((m * 1000).toPrecision(10))`)

## 2. Mesh ボタン(メッシュ生成のみ)

- ツールバーの **Solve ボタンの左**に「Mesh」ボタンを追加
- 押すと `api.mesh(project)`(実装済み)を呼び、解析はせずメッシュのみ生成
- 結果表示: キャンバスに三角形要素のワイヤーフレームを描画
  (解析結果がない状態でも見えるように。線色 `rgba(216,220,228,0.45)` 程度、
  領域タグ `region_of_triangle` ≥ 0 の要素は各領域の種別色で薄く塗り分けると見やすい)
- サイドパネルに「メッシュ」セクション(節点数・要素数)を表示
- 状態管理: `meshResult` state を App に追加。Solve 実行時・ジオメトリ/メッシュ設定変更時・
  Undo/Redo 時は破棄(既存の `setResult(null)` 箇所と同じタイミング)
- Solve 結果(電位マップ)がある間は Solve 側の表示を優先(meshResult は破棄してよい)

## 3. ルーラー文字サイズの変更

- ルーラー目盛りラベルのフォントサイズを 小(9px)/中(11px)/大(14px) から選べる UI を追加
  (ツールバーのグリッドスナップ付近に小さな select で良い。ラベル「ルーラー文字」)
- CadCanvas に `rulerFontSize: number` prop を追加し、ルーラー描画に反映。
  ルーラー帯の幅もフォントサイズに応じて少し広げる(例 `max(24, fontSize * 2.2)`)
- 設定は App の state で保持(プロジェクトファイルには保存しない)

## 制約

- 新しい npm 依存を追加しない。コメントは日本語。TS strict 維持
- 既存機能(スケッチ、移動、Undo/Redo、グリップ、円shape、プロファイル、可視化、保存/読込)を壊さない
- プロジェクトJSONの形式・単位(m)は変更しない

## 完了条件

`cd /home/claude/ES-Sim/frontend && npx tsc && npx vite build` 成功。
最後に変更ファイル一覧と操作方法の要約のみを報告。
