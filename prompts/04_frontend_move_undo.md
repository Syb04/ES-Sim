# サブエージェント指示: 図形の移動 + Undo/Redo

対象リポジトリ: `/home/claude/ES-Sim/frontend`(npm install 済み)

## 背景

ES-Sim は 2D静電場FEMアプリ(Tauri 2 + React 18 + TS strict)。`App.tsx` が project state と
編集操作(領域追加/削除/プロパティ変更、domain寸法、境界条件、メッシュサイズ、保存/読込)を持ち、
`CadCanvas.tsx` にスケッチツール(select/polyline/rect/circle)がある。
必ず現状のコードを読んでから着手すること。

## やること

### 1. Undo/Redo(App.tsx)

- project の履歴管理を導入する。実装は「スナップショット方式」:
  `past: Project[]` / `future: Project[]` を持ち、**編集操作の確定時**に past へ積む
- 対象操作: 領域の追加・削除・プロパティ変更・リネーム・移動(移動はドラッグ完了時に1エントリ)、
  domain寸法変更、境界条件変更、メッシュサイズ変更、プロジェクト読込
- 数値入力の連続変化で履歴が溢れないよう、input の `onChange` ではなく確定タイミング
  (`onBlur` / Enter)で履歴を積む方式にするか、同一フィールドの連続編集は1エントリにまとめる
- 履歴上限 100 エントリ(超えたら古いものから捨てる)
- Undo = Ctrl+Z、Redo = Ctrl+Y と Ctrl+Shift+Z。ツールバーにボタンも追加(不可時は disabled)
- Undo/Redo 時は解析結果を破棄し(`setResult(null)`)、選択解除もしくは存在チェック

### 2. 図形の移動(CadCanvas.tsx)

- **select ツールで選択済み領域を左ドラッグで移動**できるようにする
  - mousedown が選択中領域の内部なら移動開始(そうでなければ従来のクリック選択)
  - ドラッグ中は移動プレビュー(半透明 or 破線輪郭)を表示
  - グリッドスナップONなら移動量をスナップ幅に量子化
  - mouseup で確定し、`onMoveRegion(id, dx, dy)` を App に通知(App側で polygon を平行移動し履歴を積む)
  - Esc でドラッグ中キャンセル
- 既存のパン(中ボタン/Space+左ドラッグ)と競合しないこと(Space押下中はパン優先)
- 矢印キーでの微動(選択中領域をスナップ幅ぶん移動、これも1操作=1履歴)も追加

## 制約

- 新しい npm 依存を追加しない。コメントは日本語。TS strict 維持
- 既存機能(スケッチ、可視化トグル、保存/読込、Solve)を壊さない
- 履歴ロジックはカスタムフック `src/useHistory.ts` に切り出すと見通しが良い(任意)

## 完了条件

`cd /home/claude/ES-Sim/frontend && npx tsc && npx vite build` が成功すること。
最後に変更・追加したファイルの一覧と操作方法の要約のみを報告すること。
