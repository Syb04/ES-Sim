// テキストファイルの保存ユーティリティ。
// Tauri の WebView では Blob + <a download> によるダウンロードが機能しないため、
// Tauri 環境かどうかを判定し、Tauri 内ではネイティブの保存ダイアログ + ファイル書き込みを、
// ブラウザ環境 (npm run dev 等) では従来通り Blob ダウンロードを使う。

/**
 * 実行環境が Tauri アプリ内かどうかを判定する。
 * "__TAURI_INTERNALS__" は Tauri v2 の WebView に注入されるグローバルオブジェクト。
 */
function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

/**
 * テキストファイルを保存する。
 * - Tauri 内: 保存ダイアログでパスを選ばせてからファイルへ書き込む(キャンセル時は false を返す)
 * - ブラウザ内: 従来通り Blob + <a download> でダウンロードする
 *
 * @param defaultName 既定のファイル名 (例: "project.json")
 * @param content 書き込む文字列内容
 * @param filterName 保存ダイアログのファイル種別フィルタ名 (例: "JSON")
 * @param extensions フィルタの拡張子一覧 (例: ["json"])
 * @returns 保存できた場合 true、ユーザーがキャンセルした場合 false
 * @throws 保存に失敗した場合は例外を投げる (呼び出し側の既存エラー表示に流す)
 */
export async function saveTextFile(
  defaultName: string,
  content: string,
  filterName: string,
  extensions: string[]
): Promise<boolean> {
  if (isTauri()) {
    // ブラウザ実行時にモジュール解決で落ちないよう、動的 import にする
    const { save } = await import("@tauri-apps/plugin-dialog");
    const { writeTextFile } = await import("@tauri-apps/plugin-fs");
    const path = await save({
      defaultPath: defaultName,
      filters: [{ name: filterName, extensions }],
    });
    if (!path) return false; // キャンセル
    await writeTextFile(path, content);
    return true;
  }

  // ブラウザ環境: 従来通り Blob + a.click() でダウンロードする
  const blob = new Blob([content], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  try {
    const a = document.createElement("a");
    a.href = url;
    a.download = defaultName;
    a.click();
  } finally {
    URL.revokeObjectURL(url);
  }
  return true;
}
