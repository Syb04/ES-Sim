// Rust シェルは薄く保つ (仕様書 §14)。
// 配布ビルドでは Python バックエンド (PyInstaller 製) をサイドカーとして
// 自動起動し、アプリ終了時に kill する (prompts/44)。
// 開発モード (`tauri dev`) ではサイドカーを起動しない — デバッグは従来通り
// 手動 uvicorn (`uvicorn es_sim.server:app --port 8317`) を使う。
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::sync::Mutex;

use tauri::Manager;
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

/// 起動したバックエンドの子プロセスハンドル (終了時の kill 用)
struct BackendChild(Mutex<Option<CommandChild>>);

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_shell::init())
        .manage(BackendChild(Mutex::new(None)))
        .setup(|app| {
            // 配布ビルドのみサイドカーを起動する (cfg!(debug_assertions) で分岐)
            if !cfg!(debug_assertions) {
                let sidecar = app
                    .shell()
                    .sidecar("es-sim-backend")
                    .expect("failed to create es-sim-backend sidecar command")
                    .args(["--port", "8317"]);
                let (mut rx, child) = sidecar
                    .spawn()
                    .expect("failed to spawn es-sim-backend sidecar");
                *app.state::<BackendChild>().0.lock().unwrap() = Some(child);
                // 出力イベントを排出し続ける (チャネル詰まり防止。内容は捨てて良い)
                tauri::async_runtime::spawn(async move {
                    while let Some(_event) = rx.recv().await {}
                });
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let tauri::RunEvent::Exit = event {
                // アプリ終了時にバックエンドの子プロセスを確実に殺す
                if let Some(child) = app.state::<BackendChild>().0.lock().unwrap().take() {
                    let _ = child.kill();
                }
            }
        });
}
