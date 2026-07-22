"""構造格子メッシュモード (mesh.mode='structured') のテスト (prompts/34)。

1. 平行平板: 解析解 (V 線形) と <1e-8 で一致、要素数 = 2·nx·ny
2. 格子整合の矩形 conductor: 穴と Dirichlet 節点、/solve の V 範囲
3. circle conductor (階段近似): 角形外導体の同軸類似容量が解析値と 5% 以内
4. periodic (上下): 対辺節点の電位一致・x 線形解
5. PIC スモーク: 構造格子で 100 ステップ、粒子数保存
6. 非矩形 domain は明確な ValueError
"""

import math

import numpy as np
import pytest

from es_sim.fem import EPS0, solve
from es_sim.meshing import generate_mesh
from es_sim.particles import _locate_initial
from es_sim.pic import PicSimulation
from es_sim.schema import Project

D, H, V1 = 0.1, 0.05, 100.0


def _plate_project(boundaries, regions=(), size=0.01, domain=None) -> Project:
    return Project.model_validate(
        {
            "geometry": {
                "domain": {"polygon": domain or [[0, 0], [D, 0], [D, H], [0, H]]},
                "regions": list(regions),
                "boundaries": boundaries,
            },
            "mesh": {"size": size, "mode": "structured"},
        }
    )


# ---- 1. 平行平板 (解析解一致・要素数) ---------------------------------------------


def test_structured_parallel_plates_linear():
    size = 0.01
    project = _plate_project(
        [{"edges": [3], "voltage": 0.0}, {"edges": [1], "voltage": V1}], size=size
    )
    mesh = generate_mesh(project)

    nx, ny = round(D / size), round(H / size)
    assert len(mesh.triangles) == 2 * nx * ny
    assert len(mesh.nodes) == (nx + 1) * (ny + 1)

    sol = solve(project, mesh)
    v_exact = V1 * mesh.nodes[:, 0] / D
    assert np.max(np.abs(sol.v - v_exact)) < 1e-8 * V1
    # エネルギーも解析値と一致 (線形場は P1 で厳密)
    w_exact = 0.5 * EPS0 * (V1 / D) ** 2 * D * H
    assert sol.energy == pytest.approx(w_exact, rel=1e-10)


def test_structured_requires_axis_aligned_rectangle():
    """非矩形 domain では明確な ValueError になる。"""
    # 三角形 domain
    with pytest.raises(ValueError, match="矩形"):
        generate_mesh(_plate_project(
            [{"edges": [0], "voltage": 0.0}],
            domain=[[0, 0], [0.1, 0], [0.05, 0.05]],
        ))
    # 斜め辺を持つ4角形
    with pytest.raises(ValueError, match="軸平行"):
        generate_mesh(_plate_project(
            [{"edges": [0], "voltage": 0.0}],
            domain=[[0, 0], [0.1, 0.01], [0.1, 0.05], [0, 0.05]],
        ))


# ---- 2. 格子整合の矩形 conductor ---------------------------------------------------


def test_structured_rect_conductor_hole_and_dirichlet():
    size = 0.01
    v_el = 30.0
    rx1, rx2, ry1, ry2 = 0.04, 0.06, 0.02, 0.03  # 格子に整合する座標
    project = _plate_project(
        [{"edges": [3], "voltage": 0.0}, {"edges": [1], "voltage": V1}],
        regions=[
            {
                "id": "el",
                "type": "conductor",
                "polygon": [[rx1, ry1], [rx2, ry1], [rx2, ry2], [rx1, ry2]],
                "voltage": v_el,
            }
        ],
        size=size,
    )
    mesh = generate_mesh(project)

    # 穴: conductor 内包要素 (2セル = 4三角形) が除去されている
    nx, ny = round(D / size), round(H / size)
    assert len(mesh.triangles) == 2 * nx * ny - 4
    cent = mesh.nodes[mesh.triangles].mean(axis=1)
    inside = (
        (cent[:, 0] > rx1) & (cent[:, 0] < rx2) & (cent[:, 1] > ry1) & (cent[:, 1] < ry2)
    )
    assert not np.any(inside)

    # Dirichlet 節点: 電極輪郭の格子節点 (3×2 = 6 個) が v_el
    on_contour = (
        (mesh.nodes[:, 0] >= rx1 - 1e-12) & (mesh.nodes[:, 0] <= rx2 + 1e-12)
        & (mesh.nodes[:, 1] >= ry1 - 1e-12) & (mesh.nodes[:, 1] <= ry2 + 1e-12)
    )
    contour_idx = np.nonzero(on_contour)[0]
    assert len(contour_idx) == 6
    for n in contour_idx:
        assert mesh.dirichlet.get(int(n)) == pytest.approx(v_el)

    sol = solve(project, mesh)
    assert sol.v.min() >= -1e-6 * V1
    assert sol.v.max() <= V1 * (1.0 + 1e-6)
    assert sol.v[contour_idx] == pytest.approx(np.full(len(contour_idx), v_el))


# ---- 3. circle conductor (階段近似) の容量 ------------------------------------------


def test_structured_circle_conductor_square_coax_capacitance():
    """角形外導体 + 円形内導体の同軸類似構造。解析値
    C = 2πε0 / ln(1.0787·W/d) (W: 外導体一辺, d: 内導体直径) と 5% 以内。"""
    w_out = 0.08    # 外導体 (domain) の一辺
    a = 0.015       # 内導体半径 (太い同軸: W/d ≈ 2.7)
    size = 0.0004   # 階段近似誤差を抑える格子幅 (r/h = 37.5、実測誤差 ~2.5%)
    project = Project.model_validate(
        {
            "geometry": {
                "domain": {
                    "polygon": [
                        [-w_out / 2, -w_out / 2], [w_out / 2, -w_out / 2],
                        [w_out / 2, w_out / 2], [-w_out / 2, w_out / 2],
                    ]
                },
                "regions": [
                    {
                        "id": "inner",
                        "type": "conductor",
                        "shape": {"kind": "circle", "center": [0.0, 0.0], "radius": a},
                        "voltage": V1,
                    }
                ],
                "boundaries": [{"edges": [0, 1, 2, 3], "voltage": 0.0}],
            },
            "mesh": {"size": size, "mode": "structured"},
        }
    )
    mesh = generate_mesh(project)
    sol = solve(project, mesh)

    c_num = 2.0 * sol.energy / V1**2
    c_exact = 2.0 * math.pi * EPS0 / math.log(1.0787 * w_out / (2.0 * a))
    assert abs(c_num - c_exact) / c_exact < 0.05


# ---- 4. periodic (上下) ------------------------------------------------------------


def test_structured_periodic_field():
    project = _plate_project(
        [
            {"edges": [3], "voltage": 0.0},
            {"edges": [1], "voltage": V1},
            {"edges": [0, 2], "type": "periodic"},
        ],
        size=0.005,
    )
    mesh = generate_mesh(project)
    assert mesh.periodic_map is not None

    sol = solve(project, mesh)
    top = np.nonzero(mesh.nodes[:, 1] > H - 1e-12)[0]
    bottom = np.nonzero(mesh.nodes[:, 1] < 1e-12)[0]
    assert len(top) == len(bottom) >= 3
    top = top[np.argsort(mesh.nodes[top, 0])]
    bottom = bottom[np.argsort(mesh.nodes[bottom, 0])]
    assert np.allclose(mesh.nodes[top, 0], mesh.nodes[bottom, 0], atol=1e-12)
    assert np.allclose(sol.v[top], sol.v[bottom], atol=1e-9 * V1)

    v_exact = V1 * mesh.nodes[:, 0] / D
    assert np.max(np.abs(sol.v - v_exact)) < 1e-8 * V1


# ---- 5. PIC スモーク (粒子数保存) ---------------------------------------------------


def test_structured_pic_smoke_particle_conservation():
    """構造格子メッシュ + 上下鏡面反射で電子が 100 ステップ保存されること。"""
    h = 0.01
    project = Project.model_validate(
        {
            "geometry": {
                "domain": {"polygon": [[0, 0], [0.01, 0], [0.01, h], [0, h]]},
                "boundaries": [
                    {"edges": [3], "voltage": 0.0},
                    {"edges": [1], "voltage": 0.0},
                ],
            },
            "mesh": {"size": 8e-4, "mode": "structured"},
            "pic": {
                "dt": 1e-9,
                "n_steps": 100,
                "n_macro": 10,
                "frame_every": 100,
                "reflect_edges": [0, 2],
            },
        }
    )
    sim = PicSimulation(project)

    n = 300
    rng = np.random.default_rng(11)
    x = np.stack([rng.uniform(0.003, 0.007, n), rng.uniform(0.004, 0.006, n)], axis=1)
    vy = np.where(rng.random(n) < 0.5, 1.0, -1.0) * 2.0e6
    el = sim.species["electron"]
    el.x = x
    el.v = np.stack([np.zeros(n), vy, np.zeros(n)], axis=1)
    el.w = np.ones(n)
    el.elem = _locate_initial(sim.coeffs, x)

    history, _ = sim.run_batch()

    assert np.all(np.asarray(history["n_e"]) == n)
    assert el.wall_absorbed == 0
    assert np.all(el.x[:, 1] >= 0.0) and np.all(el.x[:, 1] <= h)
    assert np.allclose(np.abs(el.v[:, 1]), 2.0e6, rtol=1e-4)
    assert np.all(np.isfinite(history["phi_min"])) and np.all(np.isfinite(history["phi_max"]))
