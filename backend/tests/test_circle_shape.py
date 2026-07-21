"""円領域のパラメトリック形状 (Region.shape) のテスト。仕様書 prompts/08 参照。

circle shape は「中心+半径」のみを保持し、メッシュ生成時に多角形化する。
これにより多角形頂点間隔がメッシュサイズの下限にならないことを確認する。
"""

import math

import numpy as np
import pytest
from pydantic import ValidationError

from es_sim.fem import EPS0, solve
from es_sim.meshing import generate_mesh
from es_sim.schema import Project
from verification.coax_convergence import (
    A,
    B,
    V1,
    c_exact,
    circle_polygon,
    polygon_count,
)


def _domain_with_circle_region(mesh_size: float, region_type: str = "dielectric") -> dict:
    """外周が正方形、内部に circle shape 領域を1つ持つプロジェクトデータを作る。"""
    data = {
        "geometry": {
            "domain": {"polygon": [[0, 0], [0.1, 0], [0.1, 0.1], [0, 0.1]]},
            "regions": [
                {
                    "id": "circ",
                    "type": region_type,
                    "shape": {"kind": "circle", "center": [0.05, 0.05], "radius": 0.02},
                    "eps_r": 2.0,
                }
            ],
            "boundaries": [
                {"edges": [3], "voltage": 0.0},
                {"edges": [1], "voltage": 100.0},
            ],
        },
        "mesh": {"size": mesh_size},
    }
    return data


# ---- バリデーション ---------------------------------------------------------


def test_region_requires_polygon_or_shape():
    """polygon も shape も指定しない場合は ValidationError。"""
    data = _domain_with_circle_region(0.01)
    del data["geometry"]["regions"][0]["shape"]
    with pytest.raises(ValidationError):
        Project.model_validate(data)


def test_region_rejects_both_polygon_and_shape():
    """polygon と shape の両方を指定した場合は ValidationError。"""
    data = _domain_with_circle_region(0.01)
    data["geometry"]["regions"][0]["polygon"] = [
        [0.03, 0.03], [0.07, 0.03], [0.07, 0.07], [0.03, 0.07],
    ]
    with pytest.raises(ValidationError):
        Project.model_validate(data)


def test_region_accepts_shape_only():
    """shape のみの指定は問題なく検証を通る。"""
    data = _domain_with_circle_region(0.01)
    project = Project.model_validate(data)
    assert project.geometry.regions[0].polygon is None
    assert project.geometry.regions[0].shape.kind == "circle"


# ---- 分割数連動 (メッシュサイズが粗いほど節点数が減る) -------------------------


def test_mesh_size_controls_node_count_for_circle_region():
    """同じ circle shape 領域で mesh.size を変えると、
    粗い方 (0.008) の総節点数が細かい方 (0.002) より明確に少ないこと。

    従来の48角形固定ポリゴンでは頂点間隔がメッシュサイズの下限になり、
    この差が生まれなかった (prompts/08 背景参照)。
    """
    coarse_project = Project.model_validate(_domain_with_circle_region(0.008))
    fine_project = Project.model_validate(_domain_with_circle_region(0.002))

    coarse_mesh = generate_mesh(coarse_project)
    fine_mesh = generate_mesh(fine_project)

    assert len(coarse_mesh.nodes) < 0.5 * len(fine_mesh.nodes)


# ---- 精度: 同軸円筒 (内導体を circle shape) -----------------------------------


def _build_coax_with_circle_inner(mesh_size: float) -> Project:
    """内導体を circle shape、domain を外周多角形 (test_coax.py と同様) とした
    同軸円筒プロジェクトを構築する。"""
    n_outer = polygon_count(B, mesh_size)
    outer = circle_polygon(B, n_outer)
    data = {
        "version": 1,
        "unit": "m",
        "geometry": {
            "domain": {"polygon": outer},
            "regions": [
                {
                    "id": "inner_conductor",
                    "type": "conductor",
                    "shape": {"kind": "circle", "center": [0.0, 0.0], "radius": A},
                    "voltage": V1,
                }
            ],
            "boundaries": [
                {"edges": list(range(n_outer)), "type": "dirichlet", "voltage": 0.0},
            ],
        },
        "mesh": {"size": mesh_size},
    }
    return Project.model_validate(data)


def test_coax_circle_shape_capacitance_accuracy():
    """内導体を circle shape にした同軸円筒で、mesh.size 0.002 の容量が
    解析値と相対誤差2%以内であること。"""
    mesh_size = 0.002
    project = _build_coax_with_circle_inner(mesh_size)
    mesh = generate_mesh(project)
    sol = solve(project, mesh)

    c_num = 2.0 * sol.energy / V1 ** 2
    c_err = abs(c_num - c_exact()) / c_exact()
    assert c_err < 0.02


def test_circle_polygonization_segment_count():
    """_region_polygon の分割数規則 n = clamp(ceil(2*pi*r/h), 24, 720) を直接確認する。"""
    from es_sim.meshing import _region_polygon
    from es_sim.schema import Region

    region = Region.model_validate(
        {"id": "c", "type": "dielectric", "shape": {"kind": "circle", "center": [0, 0], "radius": 0.01}}
    )

    # 通常ケース
    h = 0.002
    polygon = _region_polygon(region, h)
    expected_n = math.ceil(2.0 * math.pi * 0.01 / h)
    assert len(polygon) == expected_n

    # 下限 (非常に粗いメッシュサイズ)
    polygon_coarse = _region_polygon(region, 100.0)
    assert len(polygon_coarse) == 24

    # 上限 (非常に細かいメッシュサイズ)
    polygon_fine = _region_polygon(region, 1e-9)
    assert len(polygon_fine) == 720
