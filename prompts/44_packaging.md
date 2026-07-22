# サブエージェント指示: 配布パッケージ化(Tauriサイドカー + PyInstaller)

対象リポジトリ: `/home/claude/ES-Sim`(cargo・PyInstaller導入可・Linux環境)

エンドユーザーが「exe一つで起動」できる配布形態を整備する。
構成: Python バックエンドを PyInstaller で単一実行ファイル化し、
Tauri の **サイドカー (bundle.externalBin)** として同梱、アプリ起動時に自動起動する。
この環境は Linux なので **Windows バイナリのビルドは行わず**、ビルドスクリプト・設定・
ドキュメントを整備し、Linux で PyInstaller ビルドと起動スモーク・cargo check を通す。

## やること

1. **PyInstaller 仕様** `backend/es_sim_server.spec`(または --onedir/--onefile 判断はお任せ):
   - エントリ `backend/run_server.py`(新規: uvicorn を 127.0.0.1:8317 で起動する薄いスクリプト。
     `--port` 引数対応)
   - gmsh(共有ライブラリ同梱が必要)・scipy・numpy の hidden imports / binaries を
     正しく collect すること。**Linux でビルドして実行し、/health と /solve が通ることを確認**
2. **ビルドスクリプト**:
   - `scripts/build_backend.ps1`(Windows用)と `scripts/build_backend.sh`(Linux/検証用):
     venv 前提で pyinstaller 実行 → 生成物を
     `frontend/src-tauri/binaries/es-sim-backend-<target-triple>(.exe)` へ配置
     (Tauri の externalBin は target triple 付きファイル名を要求する。
     Windows: `es-sim-backend-x86_64-pc-windows-msvc.exe`)
3. **Tauri 側**:
   - `tauri.conf.json`: `bundle.externalBin: ["binaries/es-sim-backend"]`
   - `main.rs`: 起動時に tauri-plugin-shell の sidecar で `es-sim-backend` を spawn し、
     アプリ終了時に kill する(子プロセス管理。既に dialog/fs プラグイン導入済みの
     Builder に追記)。**開発モード(`tauri dev`)ではサイドカーを起動しない**
     (デバッグは従来通り手動 uvicorn)— `cfg!(debug_assertions)` で分岐
   - capabilities に shell サイドカー実行権限を追加
   - `cargo check` が通ること(binaries/ に placeholder が必要なら .gitignore と
     ダミー生成をスクリプトに含める。リポジトリにバイナリはコミットしない)
4. **ドキュメント** `docs/PACKAGING.md`(日本語):
   - Windows での配布ビルド全手順: backend ビルド → `npm run tauri build` → 生成物の場所
   - 開発モードとの違い、ポート競合時の対処、トラブルシューティング
     (gmsh DLL 不足・アンチウイルス誤検知など想定される問題)
5. README のセットアップ節から PACKAGING.md への参照を1行追加
   (README 本文の大改訂は別タスクが並行中なので、**追記は最小限**にして衝突を避ける)

## 完了条件

- Linux で: PyInstaller ビルド成功 → 生成バイナリ起動 → /health・/solve 疎通 → 終了
- `cargo check` 成功、`npx tsc && npx vite build` 成功(フロント変更があれば)
- `python -m pytest tests/ -q` 既存全件パス
変更ファイル一覧・Linuxスモーク結果・Windows手順の要約のみ報告。
