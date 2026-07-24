# 66: DSMC 計算中の粒子挙動の可視化 (ライブ粒子表示)

## 背景 (ユーザー要望)

「DSMC計算中の粒子挙動は可視化できるかな？」
PIC はライブフレーム (WebSocket frame メッセージの間引き粒子) をキャンバスに
散布描画している。DSMC も進捗メッセージ (ws_dsmc の progress) に間引いた
粒子位置を同梱すれば同じことができる。

## backend

### es_sim/dsmc.py

- `run(callback, should_stop)` の callback へ渡す情報に**間引き粒子位置**を追加する。
  既存の callback シグネチャを確認し、互換を保ちつつ拡張する
  (例: callback(step, positions) 形式に変更し、server 側の呼び出しも合わせる)。
- 間引き: 最大 2000 点 (PIC の frame と同じ上限)。
  `idx = np.linspace(0, n-1, 2000).astype(int)` 等の等間隔サンプルで良い
  (順序に物理的意味はないが、injection で末尾に足されるため等間隔の方が偏らない)。
- 座標は self.x (m 単位、(x,y) または (z,r))。rz 系でも self.x は描画平面の
  2次元座標なのでそのまま送って良い (キャンバス座標系と同じ向きかを
  PIC の粒子送信 (pic.py の frame 生成) と見比べて確認すること)。

### es_sim/server.py

- `_run_dsmc_session` の progress 送信に `particles: [[x,y], ...]` を追加。
  100ステップごとの頻度は現状のまま。
- started メッセージは変更不要。

## frontend

### src/types.ts / src/dsmcClient.ts

- progress メッセージ型に `particles?: [number, number][]` を追加し、
  onProgress コールバックへ通す。

### src/App.tsx

- `gasLiveParticles: Point[] | null` state を追加。onProgress で更新、
  onDone / onError / 新規実行開始時に null へリセット。
- CadCanvas へ `gasParticles={gasRunning ? gasLiveParticles : null}` を渡す
  (実行中のみ表示。完了後は結果フィールド表示に切り替わるため残さない)。

### src/canvas/CadCanvas.tsx

- 新 prop `gasParticles?: Point[] | null` を追加。非null なら描画ループで
  小さい点 (PIC の粒子描画と同じ体裁、色はガスらしい灰白系 例 #c8ccd4、
  半径~1.2px) を散布描画する。PIC の picFrame 粒子描画箇所を参考に、
  同じ座標変換 (world→screen) を使う。
- 描画順: メッシュ/領域の上、選択ハイライトの下あたり (PIC 粒子と同等)。

### src/panels/GasPanel.tsx

- setup セクションの実行ボタン付近に「粒子を表示」チェックボックス
  (既定 ON、ローカルでなく App state で保持: `gasShowParticles`)。
  OFF なら CadCanvas へ null を渡す。

## 検証

- backend: 既存テストが全件通ること (`python -m pytest tests/ -q`)。
  callback 拡張に伴うテスト修正があれば行う。加えて、小ケースで
  run(callback) を呼び callback が粒子配列 (≤2000点、有限値) を受け取る
  ことを確認するテストを1件追加。
- frontend: `npx tsc --noEmit && npx vite build`。
- WebSocket 実挙動: uvicorn をポート 8399 で起動し、python の websockets
  クライアントで examples/dsmc 相当の小ケースを流して progress に particles が
  含まれることを確認する (確認後プロセスは停止、スクリプトは削除)。

## 注意

- コメントは日本語で「なぜ」を書く既存スタイル。
- git commit はしない。
- progress メッセージのサイズ: 2000点 × 2値 × ~20文字 ≈ 80KB/送信・100ステップ毎
  なので問題なし。
