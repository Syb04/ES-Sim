// バックエンドのポート番号設定 (GUIから変更可能にする単一窓口)。
// 開発時はブラウザ (npm run dev) でも動くよう、Tauri固有APIは動的importに閉じ込める
// (saveFile.ts と同じ方針)。
//
// 優先順位 (initPort での読み込み時): Tauri内の AppConfig/backend-port.txt
// (配布版のサイドカーが起動時に読む設定と共有) > localStorage > 既定値。
// setPort では常に両方 (localStorage と、Tauri内であれば AppConfig ファイル) を更新する。

const DEFAULT_PORT = 8317;
const LS_KEY = "es-sim.backendPort";
// AppConfig ディレクトリ直下に置く設定ファイル名。Rust側 (main.rs) もこの名前を読む
const CONFIG_FILE_NAME = "backend-port.txt";

// メモリ上の現在値。モジュール読み込み直後は既定値、initPort() 完了後に確定値へ更新される
let currentPort = DEFAULT_PORT;

/**
 * 実行環境が Tauri アプリ内かどうかを判定する。
 * "__TAURI_INTERNALS__" は Tauri v2 の WebView に注入されるグローバルオブジェクト
 * (saveFile.ts の isTauri と同じ判定方法)。
 */
function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

// 文字列をポート番号として解釈する。不正な値 (NaN・0以下) なら null を返す
function parsePort(text: string): number | null {
  const n = parseInt(text.trim(), 10);
  return Number.isFinite(n) && n > 0 ? n : null;
}

/** メモリ上の現在のポート番号を返す (初期化前は既定値 8317) */
export function getPort(): number {
  return currentPort;
}

/**
 * ポート番号を更新する。
 * - メモリ上の値 (以後の getPort() の戻り値) を即座に更新する
 * - localStorage (`es-sim.backendPort`、開発時の永続化用) へ保存する
 * - Tauri内であれば AppConfig ディレクトリの backend-port.txt にも書き込む
 *   (配布版のサイドカーは次回アプリ起動時にこのファイルを読んで --port へ渡す)
 * 書き込みに失敗した場合は例外を投げる (握りつぶさず、呼び出し側のエラー表示に委ねる)
 */
export async function setPort(n: number): Promise<void> {
  currentPort = n;
  localStorage.setItem(LS_KEY, String(n));
  if (isTauri()) {
    const { writeTextFile, BaseDirectory } = await import("@tauri-apps/plugin-fs");
    await writeTextFile(CONFIG_FILE_NAME, String(n), { baseDir: BaseDirectory.AppConfig });
  }
}

/**
 * 起動時にポート番号を初期化する。優先順位:
 * 1. Tauri内: AppConfig の backend-port.txt (存在し、内容が正しい数値であれば)
 * 2. localStorage (`es-sim.backendPort`)
 * 3. 既定値 8317
 * 取得した値をメモリ上の現在値へ反映してから返す。
 */
export async function initPort(): Promise<number> {
  if (isTauri()) {
    try {
      const { readTextFile, exists, BaseDirectory } = await import("@tauri-apps/plugin-fs");
      if (await exists(CONFIG_FILE_NAME, { baseDir: BaseDirectory.AppConfig })) {
        const text = await readTextFile(CONFIG_FILE_NAME, { baseDir: BaseDirectory.AppConfig });
        const n = parsePort(text);
        if (n !== null) {
          currentPort = n;
          return currentPort;
        }
      }
    } catch {
      // 読み込み失敗時 (権限・破損等) は localStorage / 既定値へフォールバックする
    }
  }

  const stored = localStorage.getItem(LS_KEY);
  const n = stored !== null ? parsePort(stored) : null;
  currentPort = n ?? DEFAULT_PORT;
  return currentPort;
}
