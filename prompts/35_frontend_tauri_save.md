# サブエージェント指示: Tauri環境での保存ボタン修正(ファイル保存ダイアログ対応)

対象リポジトリ: `/home/claude/ES-Sim/frontend`(npm install 済み、cargo あり)

## 背景(不具合)

プロジェクト「保存」・プロファイル「CSV保存」・IEDF/IADF「CSV保存」は
Blob + `<a download>` 方式のため、**Tauri の WebView ではダウンロード処理が無く無反応**になる
(ブラウザ実行 `npm run dev` では動作する)。Tauri 公式のダイアログ+FSプラグインで修正する。

## やること

1. **依存追加**(今回は許可):
   - `npm install @tauri-apps/plugin-dialog @tauri-apps/plugin-fs`
   - `src-tauri/Cargo.toml` に `tauri-plugin-dialog = "2"`、`tauri-plugin-fs = "2"`
   - `src-tauri/src/main.rs` の Builder に `.plugin(tauri_plugin_dialog::init())`
     `.plugin(tauri_plugin_fs::init())` を追加
   - `src-tauri/capabilities/default.json` の permissions に
     `"dialog:default"`、`"fs:default"`、および任意パス書き込みを許可する
     `{"identifier": "fs:scope", "allow": [{"path": "**"}]}` を追加
     (fs:default に write-text-file の allow が含まれない場合は
     `"fs:allow-write-text-file"` も追加。Tauri 2 の実際のスキーマに合わせて調整すること)

2. **保存ユーティリティ `src/saveFile.ts`(新規)**:
   ```ts
   export async function saveTextFile(defaultName: string, content: string, filterName: string, extensions: string[]): Promise<boolean>
   ```
   - Tauri 判定: `"__TAURI_INTERNALS__" in window`
   - Tauri 内: `@tauri-apps/plugin-dialog` の `save({defaultPath, filters})` でパスを取得し、
     `@tauri-apps/plugin-fs` の `writeTextFile` で書き込む(キャンセル時 false)。
     **動的 import** にして、ブラウザ実行時にモジュール解決で落ちないようにする
   - ブラウザ内: 従来通り Blob + a.click()
   - 失敗時は例外を投げ、呼び出し側が既存のエラー表示に流せるようにする

3. **置き換え**: 以下の3箇所の Blob ダウンロードを `saveTextFile` に置換:
   - App.tsx の `saveProject`(project.json)
   - ProfilePanel の CSV保存(profile.csv)
   - PicPanel の IEDF/IADF CSV保存(iedf.csv)
   - 保存失敗時は各所の既存エラー表示へ(alert は使わない)

4. **検証**:
   - `npx tsc && npx vite build` 成功
   - `cd src-tauri && cargo check` が通ること(初回はクレート取得で時間がかかる。
     ネットワークあり。エラーが出たら Cargo.toml/main.rs/capabilities を修正)

## 制約

日本語コメント。TS strict 維持。既存機能を壊さない。「読込」(input type=file) は
WebView でも動作するため変更しない。

## 完了条件

tsc / vite build / cargo check の3つが成功。変更ファイル一覧と動作仕様の要約のみ報告。
