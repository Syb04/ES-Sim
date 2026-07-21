# サブエージェント指示: ラインプロファイルのフロントUI

対象リポジトリ: `/home/claude/ES-Sim/frontend`(npm install 済み)

## 背景

ES-Sim は 2D静電場FEMアプリ(Tauri 2 + React 18 + TS strict)。バックエンドに
`POST /profile` が実装済み(`backend/es_sim/schema.py` の ProfileRequest / ProfileResult 参照):

- リクエスト: `{ project, p1: [x,y], p2: [x,y], n: 200 }`
- レスポンス: `{ s: number[], v: (number|null)[], e_abs: (number|null)[] }`(領域外は null)

直前に別エージェントが移動/Undo・Redo を実装しているので、必ず現状のコードを読んでから着手すること。

## やること

### 1. 型とAPI

- `src/types.ts` に `ProfileResult` 型を追加(上記と同期)
- `src/api.ts` に `profile(project, p1, p2, n)` を追加

### 2. プロファイルツール(CadCanvas.tsx)

- ツール `"profile"` を追加(App のツールバーにボタン追加)
- 1点目クリック → ラバーバンド表示 → 2点目クリックで確定し `onProfileLine(p1, p2)` を App に通知。Esc でキャンセル
- 確定済みのプロファイル線はキャンバス上にオーバーレイ表示(白破線+端点マーカー)。
  新しい線を引くか、プロファイルパネルを閉じたら消える

### 3. グラフパネル(新規 `src/panels/ProfilePanel.tsx`)

- プロファイル線確定時に `/profile` を呼び(解析結果の有無に関わらず呼んで良い。エラーはパネル内に表示)、
  キャンバス下部に高さ ~220px のパネルを出して V と |E| の2曲線を表示
- グラフは canvas 直描き(依存追加禁止)。要件:
  - 横軸 s [mm]、左縦軸 V [V](実線・アクセント色)、右縦軸 |E| [V/m](実線・別色)
  - 軸目盛り(3〜6本程度)と数値ラベル、null 区間は線を切る
  - マウスホバーで縦カーソル線+その位置の s / V / |E| 値を表示
- パネルに「CSV保存」ボタン(s,v,e_abs のCSVをBlobダウンロード、ファイル名 `profile.csv`)と閉じるボタン
- ジオメトリ等が変わって解析結果が破棄されたらパネルも閉じる(App の setResult(null) 箇所と連動)

## 制約

- 新しい npm 依存を追加しない。コメントは日本語。TS strict 維持
- 既存機能(スケッチ、移動、Undo/Redo、可視化、保存/読込)を壊さない

## 完了条件

`cd /home/claude/ES-Sim/frontend && npx tsc && npx vite build` が成功すること。
最後に変更・追加したファイルの一覧と操作方法の要約のみを報告すること。
