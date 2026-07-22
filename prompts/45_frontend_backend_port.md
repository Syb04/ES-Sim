# サブエージェント指示: バックエンドポートのGUI設定

対象リポジトリ: `/home/claude/ES-Sim/frontend`(npm install 済み、cargo あり)

現在バックエンドのポートは 8317 固定(api.ts の BASE、picClient の ws URL、
リリースビルドのサイドカー spawn 引数)。GUIから変更できるようにする。

## 設計

1. **`src/backendPort.ts`(新規)** — ポート設定の単一窓口:
   - `getPort(): number` — メモリ上の現在値(初期化は下記)。既定 8317
   - `setPort(n): Promise<void>` — 値を更新し、localStorage(`es-sim.backendPort`)へ保存。
     さらに Tauri 内なら fs プラグインで **AppConfig ディレクトリの `backend-port.txt`** にも
     書き込む(動的 import、失敗は握りつぶさずエラーを返す)
   - `initPort(): Promise<number>` — 起動時初期化: Tauri 内なら AppConfig の
     backend-port.txt を読み(あれば優先)、無ければ localStorage、無ければ 8317
2. **api.ts / picClient.ts** — `BASE` 定数をやめ、リクエスト/接続の都度
   `http://127.0.0.1:${getPort()}` / `ws://127.0.0.1:${getPort()}/ws/pic` を組み立てる
3. **UI(App のツールバー右側、backend 接続状態の隣)**:
   - 小さな「ポート」数値入力(確定式)。変更すると setPort → health 即再チェック
   - ヒント(title か status 文言): 「開発時は uvicorn の --port をこの値に合わせてください。
     配布版ではアプリ再起動後にサイドカーへ反映されます」
   - App 起動時に `initPort()` を await してから health チェックを開始する
4. **Rust(src-tauri/src/main.rs)** — リリースビルドのサイドカー spawn 前に、
   `app.path().app_config_dir()` の `backend-port.txt` を読み(parse 失敗・不存在は 8317)、
   その値を `--port` に渡す。capabilities の shell 引数 validator は数値なので変更不要のはず
   (要確認)。AppConfig ディレクトリが無ければ作成不要(読みのみ)
5. capabilities: fs の AppConfig 読み書きが許可されているか確認し、不足なら追加
   (既存の fs:scope ** があるので恐らく不要だが、AppConfig への書き込みは
   `fs:allow-appconfig-write-recursive` 等の明示が必要なら追加)

## 制約

新しい npm 依存なし(既存の plugin-fs を使用)。日本語コメント。TS strict 維持。
既存機能(保存/読込・PIC実行・続き実行)を壊さない。

## 完了条件

`npx tsc && npx vite build` 成功、`cd src-tauri && cargo check` 成功。
変更ファイル一覧と動作仕様(開発時/配布時それぞれのポート変更の流れ)のみ報告。
