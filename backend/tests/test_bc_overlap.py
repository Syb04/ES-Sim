"""対称/周期境界 + 外枠に重なる領域のテスト (prompts/22)。

1. 境界重なり: 外枠に重なる矩形電極 (半分はみ出し) のメッシュ生成と /solve
2. 対称性: 全平行平板と対称辺で半分にした問題の解が対称軸上で一致
3. 周期 (場): 上下周期の平行平板で対辺の節点電位が一致し、解が x のみの関数
4. 周期 (粒子): /trace で斜め発射粒子が y をラップして進み、吸収されない
5. 対称 (粒子): symmetry 辺で /trace 粒子が反射する
"""

import math

import numpy as np
import pytest
from pydantic import ValidationError

from es_sim.fem import solve
from es_sim.meshing import generate_mesh
from es_sim.particles import ME, QE, trace
from es_sim.schema import Project

D, H, V1 = 0.1, 0.05, 100.0  # 平行平板: 幅 D [m], 高さ H [m], 右側電位 V1 [V]


def _plate_project(boundaries, regions=(), mesh_size=0.005, height=H, particles=None) -> Project:
    data = {
        "geometry": {
            "domain": {"polygon": [[0, 0], [D, 0], [D, height], [0, height]]},
            "regions": list(regions),
            "boundaries": boundaries,
        },
        "mesh": {"size": mesh_size},
    }
    if particles is not None:
        data["particles"] = particles
    return Project.model_validate(data)


# ---- スキーマ (後方互換・periodic バリデーション) ------------------------------


def test_schema_backward_compatible_and_periodic_validation():
    """type 省略は従来通り dirichlet。periodic は2本の平行対辺のみ受け付ける。"""
    project = _plate_project([{"edges": [3], "voltage": 0.0}])
    assert project.geometry.boundaries[0].type == "dirichlet"

    # periodic: エッジ数が2本でなければエラー
    with pytest.raises(ValidationError):
        _plate_project([{"edges": [0], "type": "periodic"}])
    # periodic: 平行でない2辺 (底辺と右辺) はエラー
    with pytest.raises(ValidationError):
        _plate_project([{"edges": [0, 1], "type": "periodic"}])
    # periodic: 平行・同長の対辺は通る
    project = _plate_project([{"edges": [0, 2], "type": "periodic"}])
    assert project.geometry.boundaries[0].type == "periodic"


# ---- 1. 外枠に重なる矩形電極 ---------------------------------------------------


def test_electrode_overlapping_domain_edge():
    """左辺に重なる矩形電極 (半分はみ出し) でメッシュ生成が成功し、
    電極輪郭に Dirichlet が付き、/solve が妥当な V 範囲を返す。"""
    v_el = 30.0
    x_el, y1, y2 = 0.02, 0.01, 0.04
    project = _plate_project(
        boundaries=[
            {"edges": [3], "voltage": 0.0},   # 左辺
            {"edges": [1], "voltage": V1},    # 右辺
        ],
        regions=[
            {
                "id": "electrode",
                "type": "conductor",
                # 左半分 (x < 0) は domain の外にはみ出している
                "polygon": [[-x_el, y1], [x_el, y1], [x_el, y2], [-x_el, y2]],
                "voltage": v_el,
            }
        ],
    )
    mesh = generate_mesh(project)

    # はみ出した部分は黙って domain にクリップされる (domain 外に節点が無い)
    assert np.all(mesh.nodes[:, 0] >= -1e-9)
    assert np.all(mesh.nodes[:, 0] <= D + 1e-9)
    # 電極内部 (0 < x < 0.02, 0.01 < y < 0.04) は穴 (節点が無い)
    inside = (
        (mesh.nodes[:, 0] > 1e-6) & (mesh.nodes[:, 0] < x_el - 1e-6)
        & (mesh.nodes[:, 1] > y1 + 1e-6) & (mesh.nodes[:, 1] < y2 - 1e-6)
    )
    assert not np.any(inside)

    # 電極輪郭 (domain 内に残った3辺) の節点に電極の Dirichlet が付く
    nodes = mesh.nodes
    tol = 1e-9
    on_right = (np.abs(nodes[:, 0] - x_el) < tol) & (nodes[:, 1] >= y1 - tol) & (nodes[:, 1] <= y2 + tol)
    on_bottom = (np.abs(nodes[:, 1] - y1) < tol) & (nodes[:, 0] >= -tol) & (nodes[:, 0] <= x_el + tol)
    on_top = (np.abs(nodes[:, 1] - y2) < tol) & (nodes[:, 0] >= -tol) & (nodes[:, 0] <= x_el + tol)
    contour = np.nonzero(on_right | on_bottom | on_top)[0]
    assert len(contour) >= 8
    for n in contour:
        assert mesh.dirichlet.get(int(n)) == pytest.approx(v_el)

    # 左辺の電極区間外は外周 BC (0V) のまま
    on_left_free = (np.abs(nodes[:, 0]) < tol) & ((nodes[:, 1] < y1 - 1e-6) | (nodes[:, 1] > y2 + 1e-6))
    assert np.any(on_left_free)
    for n in np.nonzero(on_left_free)[0]:
        assert mesh.dirichlet.get(int(n)) == pytest.approx(0.0)

    # /solve 相当: 最大値原理より V は [0, 100] の範囲
    sol = solve(project, mesh)
    assert np.all(np.isfinite(sol.v))
    assert sol.v.min() >= -1e-6 * V1
    assert sol.v.max() <= V1 * (1.0 + 1e-6)
    assert sol.v[contour] == pytest.approx(np.full(len(contour), v_el))


# ---- 2. 対称境界 (場) ----------------------------------------------------------


def test_symmetry_half_matches_full_on_axis():
    """全平行平板と、対称辺 (y = H/2) で半分にした問題の解が対称軸上で一致する。"""
    full = _plate_project(
        [{"edges": [3], "voltage": 0.0}, {"edges": [1], "voltage": V1}],
        mesh_size=0.01,
    )
    mesh_full = generate_mesh(full)
    sol_full = solve(full, mesh_full)

    half = _plate_project(
        [
            {"edges": [3], "voltage": 0.0},
            {"edges": [1], "voltage": V1},
            {"edges": [2], "type": "symmetry"},  # 上辺 = 対称軸
        ],
        mesh_size=0.01,
        height=H / 2,
    )
    mesh_half = generate_mesh(half)
    sol_half = solve(half, mesh_half)

    # symmetry 辺には Dirichlet が付かない (自然境界)。角は左右辺の指定のみ
    axis_half = np.nonzero(np.abs(mesh_half.nodes[:, 1] - H / 2) < 1e-9)[0]
    assert len(axis_half) >= 3
    interior_axis = [
        int(n) for n in axis_half
        if 1e-6 < mesh_half.nodes[n, 0] < D - 1e-6
    ]
    assert interior_axis
    assert all(n not in mesh_half.dirichlet for n in interior_axis)

    # 双方とも解は V = V1 x / D (線形解は P1 で厳密) → 対称軸上で一致
    v_exact_full = V1 * mesh_full.nodes[:, 0] / D
    v_exact_half = V1 * mesh_half.nodes[:, 0] / D
    assert np.max(np.abs(sol_full.v - v_exact_full)) < 1e-8 * V1
    assert np.max(np.abs(sol_half.v - v_exact_half)) < 1e-8 * V1
    # 対称軸上の比較 (両者とも解析解に <1e-8 で一致するので相対誤差 <1e-8 で一致)
    axis_err = np.abs(sol_half.v[axis_half] - V1 * mesh_half.nodes[axis_half, 0] / D)
    assert np.max(axis_err) < 1e-8 * V1


# ---- 3. 周期境界 (場) ----------------------------------------------------------


def test_periodic_field_parallel_plates():
    """上下周期の平行平板 (左右 Dirichlet): 対辺の節点電位が一致し、
    解が x のみの関数 (解析解と一致) になる。"""
    project = _plate_project(
        [
            {"edges": [3], "voltage": 0.0},
            {"edges": [1], "voltage": V1},
            {"edges": [0, 2], "type": "periodic"},  # 下辺・上辺
        ]
    )
    mesh = generate_mesh(project)
    assert mesh.periodic_map is not None

    sol = solve(project, mesh)

    # 上下対辺の節点電位の一致: 上辺の各節点に同じ x の下辺節点が存在し電位が等しい
    top = np.nonzero(mesh.nodes[:, 1] > H - 1e-9)[0]
    bottom = np.nonzero(mesh.nodes[:, 1] < 1e-9)[0]
    assert len(top) == len(bottom) and len(top) >= 3
    top = top[np.argsort(mesh.nodes[top, 0])]
    bottom = bottom[np.argsort(mesh.nodes[bottom, 0])]
    assert np.allclose(mesh.nodes[top, 0], mesh.nodes[bottom, 0], atol=1e-9)
    assert np.allclose(sol.v[top], sol.v[bottom], atol=1e-9 * V1)

    # 解が x のみの関数 (線形解析解と一致)
    v_exact = V1 * mesh.nodes[:, 0] / D
    assert np.max(np.abs(sol.v - v_exact)) < 1e-8 * V1
    e_exact = V1 / D
    assert np.allclose(sol.e_field[:, 0], -e_exact, rtol=1e-8)
    assert np.max(np.abs(sol.e_field[:, 1])) < 1e-8 * e_exact


# ---- 4. 周期境界 (粒子) --------------------------------------------------------


def test_periodic_particle_wraps_in_trace():
    """上下周期の場を横切る斜め発射粒子が y をラップして進み、吸収されない。
    x 方向の物理 (一様電場での加速) は解析解通り。"""
    v_right = 10.0  # 右辺電位 [V] → E = 100 V/m
    x0, y0 = 0.02, 0.01
    energy_ev = 5.0
    dt = 2e-10
    n_steps = 300
    project = _plate_project(
        [
            {"edges": [3], "voltage": 0.0},
            {"edges": [1], "voltage": v_right},
            {"edges": [0, 2], "type": "periodic"},
        ],
        particles={
            "species": {"preset": "electron"},
            "emitter": {
                "kind": "point",
                "p1": [x0, y0],
                "n": 1,
                "energy_ev": energy_ev,
                "direction_deg": 90.0,  # +y 方向に発射 (電場 x と直交)
            },
            "dt": dt,
            "n_steps": n_steps,
            "save_every": 5,
        },
    )
    mesh = generate_mesh(project)
    sol = solve(project, mesh)
    result = trace(project, mesh, sol)

    # 吸収されない (周期エッジは壁ではない)
    assert not result.absorbed[0]

    traj = result.trajectories[0]  # (n_frames, 2)
    # y は常に domain 内に留まり、少なくとも1回ラップする (フレーム間の大きな負ジャンプ)
    assert np.all(traj[:, 1] >= -1e-6)
    assert np.all(traj[:, 1] <= H + 1e-6)
    dy = np.diff(traj[:, 1])
    assert np.any(dy < -H / 2), "y のラップが起きていません"

    # x 方向の物理: 一様電場での等加速度運動 x(t) = x0 + a t^2 / 2
    t_total = n_steps * dt
    a = QE * (v_right / D) / ME
    x_exact = x0 + 0.5 * a * t_total**2
    assert traj[-1, 0] == pytest.approx(x_exact, rel=0.02)
    # y 方向は等速 (ラップ回数分の周期を足して比較)
    vy = math.sqrt(2.0 * energy_ev * QE / ME)
    n_wrap = int(np.sum(dy < -H / 2))
    y_exact = y0 + vy * t_total - n_wrap * H
    assert traj[-1, 1] == pytest.approx(y_exact, abs=1e-3)


# ---- 5. 対称境界 (粒子) --------------------------------------------------------


def test_symmetry_particle_reflects_in_trace():
    """symmetry 辺 (上辺) に達した /trace 粒子が鏡面反射する。"""
    x0, y0 = 0.05, 0.025
    energy_ev = 10.0
    dt = 5e-11
    n_steps = 500
    project = _plate_project(
        [
            {"edges": [3], "voltage": 0.0},
            {"edges": [1], "voltage": 0.0},   # 無電場 (直線運動)
            {"edges": [2], "type": "symmetry"},  # 上辺で鏡面反射
        ],
        particles={
            "species": {"preset": "electron"},
            "emitter": {
                "kind": "point",
                "p1": [x0, y0],
                "n": 1,
                "energy_ev": energy_ev,
                "direction_deg": 90.0,  # 上辺に垂直入射
            },
            "dt": dt,
            "n_steps": n_steps,
            "save_every": 5,
        },
    )
    mesh = generate_mesh(project)
    sol = solve(project, mesh)
    result = trace(project, mesh, sol)

    # 反射されて吸収されない
    assert not result.absorbed[0]

    traj = result.trajectories[0]
    vy = math.sqrt(2.0 * energy_ev * QE / ME)
    t_total = n_steps * dt
    t_top = (H - y0) / vy
    assert t_top < t_total < t_top + y0 / vy  # 反射後、下辺到達前に終了する設定

    # 上辺付近まで到達し、domain の外には出ない
    assert np.max(traj[:, 1]) > H - 2e-3
    assert np.all(traj[:, 1] <= H + 1e-9)
    # 反射後は -y 方向へ直進 (x は不変、速度の向きは -90°)
    y_exact = H - vy * (t_total - t_top)
    assert traj[-1, 1] == pytest.approx(y_exact, abs=1e-3)
    assert traj[-1, 0] == pytest.approx(x0, abs=1e-6)
    assert result.final_angle_deg[0] == pytest.approx(-90.0, abs=1.0)
    # エネルギーは保存される (鏡面反射は速さを変えない)
    assert result.final_energy_ev[0] == pytest.approx(energy_ev, rel=1e-6)
