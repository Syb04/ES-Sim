# サブエージェント指示: PICの続き実行UI(フロントエンド)

対象リポジトリ: `/home/claude/ES-Sim/frontend`(npm install 済み)

バックエンドのWSプロトコル契約は `/home/claude/ES-Sim/prompts/32_backend_continue.md` を参照。
picClient.ts / App.tsx / panels/PicPanel.tsx を読んでから着手すること。

## やること

1. **picClient.ts**: `continueRun(opts: {n_steps: number, frame_every?: number,
   avg_steps?: number | null, phase_bins?: number | null})` を追加
   (`{"cmd":"continue", ...}` を送信。接続が閉じていれば再接続してから送る)

2. **PicPanel**: 実行制御に「**続きから実行**」ボタンを追加:
   - 有効条件: 直前の実行が done 済み(または stop 済み)で、現在実行中でない
   - 押すと現在の計算設定の n_steps / frame_every / avg_steps / phase_bins で continue
   - 「ジオメトリ・プラズマ設定の変更は続き実行には反映されません(粒子状態・表面電荷・
     時刻は前回から継続)」のヒント表示
   - ジオメトリを編集(commitProject / Undo / Redo)したら続き実行ボタンを無効化する
     (サーバー状態と食い違うため。App に「前回実行後にプロジェクトが変わったか」フラグ)

3. **App.tsx**:
   - `runPicContinue`: picHistory は**クリアせず**、continue の frame diag を追記。
     done では history(追加区間分)を既存へ**連結**する。fields / cycle / collector /
     picFields 等は新しい done の内容で**置き換え**。進捗バーは追加分基準でリセット
   - ライブフレーム・結果表示・アニメーション状態は新しい実行区間の内容へ自然に切り替わること
   - 実行中の状態管理(picRunning等)は start と共通化

## 制約

新しい npm 依存なし。日本語コメント。TS strict 維持。既存機能を壊さない。

## 完了条件

`cd /home/claude/ES-Sim/frontend && npx tsc && npx vite build` 成功。
変更ファイル一覧と操作方法の要約のみ報告。
