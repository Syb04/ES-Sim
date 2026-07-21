"""ラインプロファイル (2点間の V・|E| サンプリング)。仕様書 §7 参照。"""

from __future__ import annotations

import numpy as np

from .fem import Solution
from .meshing import Mesh

_TOL = 1e-9  # 重心座標の許容誤差。三角形境界付近の浮動小数点誤差を吸収するマージン


def _barycentric(nodes: np.ndarray, tris: np.ndarray, pts: np.ndarray):
    """全要素・全サンプル点の重心座標を一括計算する (サンプル数×要素数の総当たり)。

    戻り値: l1, l2, l3  各 shape (K, M)  (K: サンプル点数, M: 要素数)
    """
    p = nodes[tris]  # (M, 3, 2)
    x1, y1 = p[:, 0, 0], p[:, 0, 1]
    x2, y2 = p[:, 1, 0], p[:, 1, 1]
    x3, y3 = p[:, 2, 0], p[:, 2, 1]
    denom = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)  # (M,)

    px = pts[:, 0][:, None]  # (K, 1)
    py = pts[:, 1][:, None]

    l1 = ((y2 - y3)[None, :] * (px - x3[None, :]) + (x3 - x2)[None, :] * (py - y3[None, :])) / denom[None, :]
    l2 = ((y3 - y1)[None, :] * (px - x3[None, :]) + (x1 - x3)[None, :] * (py - y3[None, :])) / denom[None, :]
    l3 = 1.0 - l1 - l2
    return l1, l2, l3  # (K, M) ずつ


def sample_line(
    mesh: Mesh,
    solution: Solution,
    p1: tuple[float, float],
    p2: tuple[float, float],
    n: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """線分 p1→p2 上を n 点等間隔サンプリングし、弧長 s [m]・電位 v [V]・|E| [V/m] を返す。

    所属三角形の特定は、各サンプル点に対する全要素の重心座標判定をベクトル化して行う
    (サンプル数×要素数の総当たり)。V は所属要素の P1 形状関数 (重心座標) で補間し、
    E は要素内一定として所属要素の値を用いる。どの要素にも属さない点 (電極の穴の中など
    領域外の点) は NaN にする。
    """
    p1a = np.asarray(p1, dtype=np.float64)
    p2a = np.asarray(p2, dtype=np.float64)
    t = np.linspace(0.0, 1.0, n)
    pts = p1a[None, :] + t[:, None] * (p2a - p1a)[None, :]  # (K, 2)
    length = float(np.linalg.norm(p2a - p1a))
    s = t * length

    tris = mesh.triangles
    l1, l2, l3 = _barycentric(mesh.nodes, tris, pts)  # (K, M)

    # 各点について「最も内側」な (3つの重心座標の最小値が最大の) 要素を選ぶ。
    # 領域内の点なら選ばれた要素の重心座標はすべて >= -TOL になり、
    # 領域外の点 (どの要素にも含まれない) なら最小値は大きく負のままになる。
    min_bary = np.minimum(np.minimum(l1, l2), l3)  # (K, M)
    best_elem = np.argmax(min_bary, axis=1)        # (K,)
    k_idx = np.arange(len(t))
    best_min = min_bary[k_idx, best_elem]
    inside = best_min >= -_TOL

    bl1 = l1[k_idx, best_elem]
    bl2 = l2[k_idx, best_elem]
    bl3 = l3[k_idx, best_elem]

    vt = solution.v[tris[best_elem]]  # (K, 3)
    v = bl1 * vt[:, 0] + bl2 * vt[:, 1] + bl3 * vt[:, 2]

    e = solution.e_field[best_elem]  # (K, 2)
    e_abs = np.hypot(e[:, 0], e[:, 1])

    v = np.where(inside, v, np.nan)
    e_abs = np.where(inside, e_abs, np.nan)

    return s, v, e_abs
