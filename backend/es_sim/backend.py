"""配列バックエンドの抽象化。

FEM の疎行列ソルブは常に CPU (scipy) で行う。
粒子プッシュ・電荷堆積などのホットループはここで得た xp
(numpy または cupy) で書き、実行時に切り替える。

JAX の GPU 実行は Windows ネイティブ未対応 (Linux/WSL2 限定) のため、
Windows で GPU を使う場合は CuPy (NVIDIA CUDA) を採用する。
"""

from __future__ import annotations

import numpy as np

_gpu_available: bool | None = None


def gpu_available() -> bool:
    """CuPy がインストールされ、CUDA デバイスが見えるかどうか。"""
    global _gpu_available
    if _gpu_available is None:
        try:
            import cupy  # noqa: F401

            cupy.cuda.runtime.getDeviceCount()
            _gpu_available = True
        except Exception:
            _gpu_available = False
    return _gpu_available


def get_xp(backend: str = "numpy"):
    """'numpy' | 'cupy' | 'auto' に応じた配列モジュールを返す。"""
    if backend == "numpy":
        return np
    if backend == "cupy":
        import cupy

        return cupy
    if backend == "auto":
        if gpu_available():
            import cupy

            return cupy
        return np
    raise ValueError(f"unknown backend: {backend}")


def to_numpy(a):
    """cupy 配列でも numpy 配列でも numpy に揃える。"""
    if hasattr(a, "get"):
        return a.get()
    return np.asarray(a)
