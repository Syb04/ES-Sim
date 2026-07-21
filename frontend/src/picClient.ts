// PIC WebSocket クライアント (薄いラッパ)。
// ws://127.0.0.1:8317/ws/pic に接続し、start/stop コマンドを送信する。
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

const WS_URL = "ws://127.0.0.1:8317/ws/pic";

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
  private readonly cb: PicClientCallbacks;

  constructor(cb: PicClientCallbacks) {
    this.cb = cb;
  }

  // 接続して start コマンドを送る (project は pic 設定込みで渡すこと)
  start(project: Project): void {
    this.close();
    let ws: WebSocket;
    try {
      ws = new WebSocket(WS_URL);
    } catch (e) {
      this.cb.onError?.(String(e));
      return;
    }
    this.ws = ws;

    ws.onopen = () => {
      const cmd: PicClientCommand = { cmd: "start", project };
      ws.send(JSON.stringify(cmd));
    };

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
