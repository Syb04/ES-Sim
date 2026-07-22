"""配布用バックエンド起動スクリプト (PyInstaller のエントリポイント、prompts/44)。

Tauri のサイドカーとして起動され、uvicorn で FastAPI サーバーを
127.0.0.1 (既定ポート 8317) に立ち上げる。

使い方:
    es-sim-backend [--port 8317] [--host 127.0.0.1]
"""

from __future__ import annotations

import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="ES-Sim backend server")
    parser.add_argument("--port", type=int, default=8317, help="待受ポート (既定: 8317)")
    parser.add_argument(
        "--host", default="127.0.0.1", help="待受アドレス (既定: 127.0.0.1)"
    )
    args = parser.parse_args()

    # ワーカー1・リロード無効 (配布バイナリ)。ログは標準出力へ
    uvicorn.run(
        "es_sim.server:app",
        host=args.host,
        port=args.port,
        workers=1,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
