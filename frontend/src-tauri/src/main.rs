// Rust シェルは薄く保つ (仕様書 §14)。
// 将来: Python バックエンドのサイドカー起動 (tauri-plugin-shell) をここに追加する。
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
