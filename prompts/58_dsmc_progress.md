# 58: DSMC 計算進捗の表示 (WebSocket 化)

## バックエンド (実装済み・変更しないこと)

`/ws/dsmc` WebSocket を追加した (PIC の /ws/pic と同じ流儀):

- 送信: `{"cmd": "start", "project": {...}}` で実行開始、`{"cmd": "stop"}` で中断
- 受信メッセージ:
  - `{"type": "started", "n_steps": N, "dt": s, "n_particles": k}`
  - `{"type": "progress", "step": i, "n_steps": N, "n_particles": k}` — 100ステップごと
  - `{"type": "done", "result": DsmcResult}` — result は REST /dsmc と同形
  - `{"type": "error", "detail": "..."}` — 失敗時 (平均区間前の停止もエラーになる)
- REST /dsmc も残っている (後方互換) が、GUI は WS を使う

## フロントエンド作業

1. **dsmcClient.ts** (新規): `picClient.ts` を参考に WS クライアントを実装。
   コールバック { onStarted, onProgress, onDone, onError, onClose }、
   start(project) / stop()。URL は `ws://127.0.0.1:${getPort()}/ws/dsmc`
   (backendPort.ts の getPort を使う。picClient と同じ流儀)

2. **App.tsx**: `runDsmc()` を api.dsmc (REST) から dsmcClient (WS) に置き換え:
   - `gasRunning` state (実行中フラグ)、`gasProgress` state ({step, nSteps, nParticles} | null)
   - onStarted で progress リセット + running true、onProgress で更新、
     onDone で gasResult 設定 + running false、onError で gasError + running false
   - `stopDsmc()` を追加して GasPanel へ渡す

3. **GasPanel.tsx**:
   - 「ガス流れ計算」ボタンは実行中 disabled、隣に「停止」ボタン (実行中のみ有効)
   - 実行中は進捗表示: プログレスバー (step/n_steps %) + テキスト
     「ステップ i / N (粒子数 k)」。既存のスタイルに合わせる
     (PicPanel の進捗表示があれば流儀を合わせる)
   - 完了/エラー時の表示は既存のまま

4. **style.css**: プログレスバーが必要なら簡素なもの (.gas-progress 等) を追加

## 検証

`cd /home/claude/ES-Sim/frontend && npx tsc --noEmit && npx vite build` が通ること。
コミットはしない (呼び出し元が行う)。
