"""gmsh による三角形メッシュ生成。仕様書 §5 参照。

前提 (フェーズ0):
- regions は domain の内部に完全に含まれ、互いに重ならない
- conductor 領域は穴として抜き、輪郭節点を Dirichlet にする
- dielectric / charge 領域は独立サーフェスとして要素タグを保持する
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import gmsh
import numpy as np

from .schema import Project, Region

# 円形状の多角形分割数の下限・上限 (仕様書 §8 スキーマ契約参照)
CIRCLE_SEGMENTS_MIN = 24
CIRCLE_SEGMENTS_MAX = 720


@dataclass
class Mesh:
    nodes: np.ndarray          # (N, 2) float64
    triangles: np.ndarray      # (M, 3) int64
    tri_region: np.ndarray     # (M,) int64  regions のインデックス。-1 は背景 (真空)
    dirichlet: dict[int, float] = field(default_factory=dict)  # 節点番号 -> 電位 [V] (直流分)
    # 節点番号 -> (振幅 [V], 周波数 [Hz], 位相 [deg])。PIC のみ使用 (フェーズ1/2 は無視)
    dirichlet_rf: dict[int, tuple[float, float, float]] = field(default_factory=dict)


def _add_polygon(points, lc: float):
    """点列から閉曲線ループを作る。(curve_tags, loop_tag) を返す。"""
    pts = [gmsh.model.geo.addPoint(x, y, 0.0, lc) for x, y in points]
    curves = [
        gmsh.model.geo.addLine(pts[i], pts[(i + 1) % len(pts)])
        for i in range(len(pts))
    ]
    loop = gmsh.model.geo.addCurveLoop(curves)
    return curves, loop


def _circle_polygon(center: tuple[float, float], radius: float, h: float) -> list[tuple[float, float]]:
    """円を多角形近似する。分割数は特性長 h から

        n = clamp(ceil(2*pi*r / h), CIRCLE_SEGMENTS_MIN, CIRCLE_SEGMENTS_MAX)

    で決め、開始角0・反時計回りで頂点列を返す (仕様書 §8 スキーマ契約参照)。
    """
    n = math.ceil(2.0 * math.pi * radius / h)
    n = max(CIRCLE_SEGMENTS_MIN, min(CIRCLE_SEGMENTS_MAX, n))
    cx, cy = center
    theta = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False)
    return [(cx + radius * math.cos(t), cy + radius * math.sin(t)) for t in theta]


def _region_polygon(region: Region, h: float) -> list[tuple[float, float]]:
    """領域の輪郭ポリゴンを解決する。

    polygon 指定の領域はそのまま返し、shape (circle) 指定の領域は
    その領域の特性長 h (local_size があればそれ、なければ mesh.size) で
    多角形化する。
    """
    if region.polygon is not None:
        return region.polygon
    assert region.shape is not None  # schema のバリデーションで保証済み
    return _circle_polygon(region.shape.center, region.shape.radius, h)


def generate_mesh(project: Project) -> Mesh:
    geo = project.geometry
    lc = project.mesh.size
    local = {ls.region: ls.size for ls in project.mesh.local_sizes}

    # interruptible=False: シグナルハンドラを登録しない
    # (FastAPI はワーカースレッドで実行するため必須)
    gmsh.initialize(interruptible=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("es_sim")

        outer_curves, outer_loop = _add_polygon(geo.domain.polygon, lc)

        hole_loops = []            # domain サーフェスから抜くループ
        region_surfaces = []       # (region_index, surface_tag)
        conductor_curves = []      # (voltage, [curve_tags])

        for i, region in enumerate(geo.regions):
            r_lc = local.get(region.id, lc)
            polygon = _region_polygon(region, r_lc)
            curves, loop = _add_polygon(polygon, r_lc)
            hole_loops.append(loop)
            if region.type == "conductor":
                if region.voltage is None:
                    raise ValueError(f"conductor '{region.id}' に voltage がありません")
                conductor_curves.append((region.voltage, region.voltage_rf, curves))
            else:
                surf = gmsh.model.geo.addPlaneSurface([loop])
                region_surfaces.append((i, surf))

        background_surface = gmsh.model.geo.addPlaneSurface([outer_loop, *hole_loops])
        gmsh.model.geo.synchronize()
        gmsh.model.mesh.generate(2)

        # ---- 節点 ---------------------------------------------------------
        node_tags, coords, _ = gmsh.model.mesh.getNodes()
        node_tags = np.asarray(node_tags, dtype=np.int64)
        nodes = np.asarray(coords, dtype=np.float64).reshape(-1, 3)[:, :2]
        tag_to_index = np.zeros(node_tags.max() + 1, dtype=np.int64)
        tag_to_index[node_tags] = np.arange(len(node_tags))

        # ---- 要素 (サーフェスごとに領域タグを付ける) ------------------------
        tri_list, region_list = [], []

        def _collect(surface_tag: int, region_index: int) -> None:
            etypes, _, enodes = gmsh.model.mesh.getElements(2, surface_tag)
            for etype, conn in zip(etypes, enodes):
                if etype != 2:  # 3節点三角形のみ
                    continue
                tris = tag_to_index[np.asarray(conn, dtype=np.int64)].reshape(-1, 3)
                tri_list.append(tris)
                region_list.append(np.full(len(tris), region_index, dtype=np.int64))

        _collect(background_surface, -1)
        for region_index, surf in region_surfaces:
            _collect(surf, region_index)

        triangles = np.concatenate(tri_list)
        tri_region = np.concatenate(region_list)

        # ---- Dirichlet 節点 ------------------------------------------------
        dirichlet: dict[int, float] = {}
        dirichlet_rf: dict[int, tuple[float, float, float]] = {}

        def _curve_nodes(curve_tag: int) -> np.ndarray:
            tags, _, _ = gmsh.model.mesh.getNodes(1, curve_tag, includeBoundary=True)
            return tag_to_index[np.asarray(tags, dtype=np.int64)]

        def _assign(n: int, voltage: float, rf) -> None:
            """節点に直流分と RF 成分を設定する (RF なしなら既存 RF を消して上書き)。"""
            dirichlet[n] = voltage
            if rf is not None:
                dirichlet_rf[n] = (rf.amplitude, rf.freq_hz, rf.phase_deg)
            else:
                dirichlet_rf.pop(n, None)

        # 外周エッジの境界条件 (エッジ i は outer_curves[i])
        for bc in geo.boundaries:
            for edge in bc.edges:
                for n in _curve_nodes(outer_curves[edge]):
                    _assign(int(n), bc.voltage, bc.voltage_rf)

        # 電極輪郭 (電極の指定を優先して上書き)
        for voltage, rf, curves in conductor_curves:
            for c in curves:
                for n in _curve_nodes(c):
                    _assign(int(n), voltage, rf)

        return Mesh(nodes=nodes, triangles=triangles,
                    tri_region=tri_region, dirichlet=dirichlet,
                    dirichlet_rf=dirichlet_rf)
    finally:
        gmsh.finalize()
