// PIC WebSocket クライアント (薄いラッパ)。
// ws://127.0.0.1:<port>/ws/pic に接続し、start/stop コマンドを送信する。
// サーバーからの started/frame/done/error 通知はコールバックへそのまま中継する。
// 接続エラー・切断時は onError / onClose を呼び、パネル側で待機状態に戻せるようにする。

import type {
  PicClientCommand,
  PicDoneMsg,
  PicErrorMsg,
  PicFrameMsg,
  PicServerMessage,
  PicStartedMsg,
  Project,
} from "./types";
import { getPort } from "./backendPort";

// 接続の都度ポート番号を組み立てる (GUIでの変更を即座に反映するため、定数 URL は使わない)
function wsUrl(): string {
  return `ws://127.0.0.1:${getPort()}/ws/pic`;
}

export interface PicClientCallbacks {
  onStarted?: (msg: PicStartedMsg) => void;
  onFrame?: (msg: PicFrameMsg) => void;
  onDone?: (msg: PicDoneMsg) => void;
  onError?: (detail: string) => void;
  // 接続が閉じた (正常終了・異常切断いずれも) ときに呼ばれる
  onClose?: () => void;
}

export class PicClient {
  private ws: WebSocket | null = null;
  private cb: PicClientCallbacks;

  constructor(cb: PicClientCallbacks) {
    this.cb = cb;
  }

  // コールバックを差し替える (continue で同じ接続・インスタンスを使い回しつつ、
  // 呼び出し側の状態管理を start 時と切り替えたい場合に使う)
  setCallbacks(cb: PicClientCallbacks): void {
    this.cb = cb;
  }

  // WebSocket を新規に張り、接続確立後に onOpenSend で渡されたコマンドを送信する。
  // メッセージの振り分け (started/frame/done/error → コールバック) は start/continueRun で共通なのでここにまとめる
  private connect(onOpenSend: (ws: WebSocket) => void): void {
    this.close();
    let ws: WebSocket;
    try {
      ws = new WebSocket(wsUrl());
    } catch (e) {
      this.cb.onError?.(String(e));
      return;
    }
    this.ws = ws;

    ws.onopen = () => onOpenSend(ws);

    ws.onmessage = (ev: MessageEvent<string>) => {
      let msg: PicServerMessage;
      try {
        msg = JSON.parse(ev.data) as PicServerMessage;
      } catch (e) {
        this.cb.onError?.(`受信データの解析に失敗しました: ${String(e)}`);
        return;
      }
      switch (msg.type) {
        case "started":
          this.cb.onStarted?.(msg);
          break;
        case "frame":
          this.cb.onFrame?.(msg);
          break;
        case "done":
          this.cb.onDone?.(msg);
          break;
        case "error":
          this.cb.onError?.((msg as PicErrorMsg).detail);
          break;
      }
    };

    ws.onerror = () => {
      this.cb.onError?.("WebSocket接続エラーが発生しました (backend が起動しているか確認してください)");
    };

    ws.onclose = () => {
      this.ws = null;
      this.cb.onClose?.();
    };
  }

  // 接続して start コマンドを送る (project は pic 設定込みで渡すこと)
  start(project: Project): void {
    this.connect((ws) => {
      const cmd: PicClientCommand = { cmd: "start", project };
      ws.send(JSON.stringify(cmd));
    });
  }

  // 保持中のシミュレーション状態から追加実行する continue コマンドを送る。
  // 直前の start/continue と同じ接続が開いたままならそれをそのまま使い (サーバー側は1つの
  // WebSocketセッション内で start→done→continue のループを回す)、接続が閉じていれば
  // (ページ再読込やタイムアウト等で切断された場合) 新規接続してから送信する
  continueRun(opts: {
    n_steps: number;
    frame_every?: number;
    avg_steps?: number | null;
    phase_bins?: number | null;
  }): void {
    const cmd: PicClientCommand = { cmd: "continue", ...opts };
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(cmd));
      return;
    }
    this.connect((ws) => ws.send(JSON.stringify(cmd)));
  }

  // stop コマンドを送る (接続していなければ何もしない)
  stop(): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      const cmd: PicClientCommand = { cmd: "stop" };
      this.ws.send(JSON.stringify(cmd));
    }
  }

  // 接続を明示的に閉じる (コールバックは発火させない)
  close(): void {
    if (this.ws) {
      this.ws.onopen = null;
      this.ws.onmessage = null;
      this.ws.onerror = null;
      this.ws.onclose = null;
      this.ws.close();
      this.ws = null;
    }
  }
}
