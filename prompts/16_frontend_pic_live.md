# サブエージェント指示: フェーズ3 PICパネル + ライブ表示(フロントエンド)

対象リポジトリ: `/home/claude/ES-Sim/frontend`(npm install 済み)

ES-Sim(Tauri 2 + React 18 + TS strict)に PIC のUIを追加する。
バックエンドの WebSocket プロトコルとスキーマ契約は
`/home/claude/ES-Sim/prompts/15_backend_pic_core.md` を参照し、型を完全一致させること。
必ず現状のコード(App.tsx / CadCanvas.tsx / types.ts / panels/)を読んでから着手すること。

## やること

### 1. types.ts

- `VoltageRf`(amplitude/freq_hz/phase_deg)を追加し、`Region` と `BoundaryCondition` に
  `voltage_rf?` を追加
- `PicSettings` / `PicFrame` / `PicDiag` など契約通りの型を追加。`Project.pic?` を追加

### 2. RF電圧の入力UI(App のサイドパネル)

- conductor 領域のプロパティに「RF重畳」チェック → ON で振幅[V]・周波数[Hz]・位相[deg]入力
- 境界条件(Dirichlet辺)にも同様のRF入力(コンパクトで良い)

### 3. PICパネル(新規 `src/panels/PicPanel.tsx`)

- 初期プラズマ: 有効チェック、密度[m^-3]、Te[eV]、Ti[eV]、イオン質量[amu]、イオン固定、シード
- 注入: 有効チェック、種(電子/イオン)、電流[A/m](エミッタはフェーズ2の設定を共用する旨を注記)
- マクロ粒子数、dt(空欄=自動)、ステップ数、フレーム間隔
- これらは project.pic として保存/読込対象(particles と同様、Undo履歴外)
- 実行制御: 「PIC開始」/「停止」ボタン、進捗バー(step/n_steps)、警告表示(started の warnings)
- 診断表示: 数値(現在の粒子数、φ範囲、壁吸収数)+
  **小さな履歴チャート**(canvas直描き、横軸時刻、縦軸: 運動E・場E・全E の3曲線と粒子数)

### 4. WebSocketクライアント(新規 `src/picClient.ts`)

- `ws://127.0.0.1:8317/ws/pic` に接続し、start/stop コマンド送信、
  started/frame/done/error をコールバックで通知する薄いクラス
- 切断・エラー時はパネルにエラー表示して待機状態に戻る

### 5. ライブ描画(CadCanvas)

- `picFrame` prop を追加:
  - φ(節点値)を既存の電位カラーマップと同じ経路で描画(started で受け取った mesh を使用。
    フレームごとに v_min/v_max を再計算)
  - 粒子を点描画: 電子=シアン、イオン=オレンジ(1px〜2px、多数でも軽いように)
- 実行中は既存の Solve 結果表示より優先。done 後は最後のフレームを表示し続ける

## 制約

- 新しい npm 依存を追加しない。コメントは日本語。TS strict 維持
- 既存機能(スケッチ、Solve/Mesh、Trace、プロファイル、Undo/Redo等)を壊さない
- フレーム描画はrequestAnimationFrame的な過剰最適化は不要(frame_every で間引かれてくる前提)

## 完了条件

`cd /home/claude/ES-Sim/frontend && npx tsc && npx vite build` 成功。
最後に変更ファイル一覧と操作方法の要約のみを報告。
