import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./style.css";

/**
 * エラーバウンダリ: 描画中の例外で画面全体がブラックアウトするのを防ぎ、
 * エラー内容と「再読み込み」ボタンを表示する。
 */
class ErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { error: Error | null }
> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: 24, color: "#d8dce4", fontFamily: "system-ui" }}>
          <h2 style={{ marginBottom: 12 }}>表示エラーが発生しました</h2>
          <pre
            style={{
              background: "#242830", padding: 12, borderRadius: 4,
              whiteSpace: "pre-wrap", fontSize: 12, marginBottom: 12,
            }}
          >
            {String(this.state.error?.stack ?? this.state.error)}
          </pre>
          <button
            style={{
              background: "#4da3ff", color: "#fff", border: "none",
              borderRadius: 4, padding: "6px 14px", cursor: "pointer",
            }}
            onClick={() => location.reload()}
          >
            再読み込み
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>,
);
