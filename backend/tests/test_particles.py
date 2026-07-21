"""荷電粒子軌道追跡のテスト (仕様書 §8 / prompts/11 検証ケース)。

平行平板の一様電場を固定場として、解析解 (加速・放物運動) と比較する。
"""

import math

import numpy as np
import pytest

from es_sim.fem import solve
from es_sim.meshing import generate_mesh
from es_sim.particles import ME, QE, trace
from es_sim.schema import Project

D, H, V1 = 0.1, 0.05, 100.0  # 平行平板: 幅 D [m], 高さ H [m], 右側(陽極)電位 V1 [V]
MESH_SIZE = 0.005


def _parallel_plate_project(particles: dict) -> Project:
    return Project.model_validate(
        {
            "geometry": {
                "domain": {"polygon": [[0, 0], [D, 0], [D, H], [0, H]]},
                "boundaries": [
                    {"edges": [3], "type": "dirichlet", "voltage": 0.0},   # 左辺(陰極)
                    {"edges": [1], "type": "dirichlet", "voltage": V1},    # 右辺(陽極)
                ],
            },
            "mesh": {"size": MESH_SIZE},
            "particles": particles,
        }
    )


# ---- 加速テスト -------------------------------------------------------------


def test_acceleration_matches_analytic_energy_and_tof():
    """陰極付近から静止発射した電子が陽極に到達するときの
    final_energy_ev と飛行時間が解析解と一致すること(相対誤差 <1%)。"""
    x_start = 1e-4  # 陰極 (x=0) からわずかに離れた位置から発射
    project = _parallel_plate_project(
        {
            "species": {"preset": "electron"},
            "emitter": {
                "kind": "point",
                "p1": [x_start, H / 2],
                "n": 1,
                "energy_ev": 0.0,
                "direction_deg": 0.0,
            },
            "dt": None,
            "n_steps": 2000,
            "save_every": 5,
        }
    )
    mesh = generate_mesh(project)
    sol = solve(project, mesh)
    result = trace(project, mesh, sol)

    assert result.absorbed[0]

    d = D - x_start
    e_field = V1 / D
    energy_exact_ev = e_field * d  # = 陰極から陽極までの電位差ぶんの運動エネルギー[eV]
    t_exact = math.sqrt(2.0 * d * ME / (QE * e_field))

    assert result.final_energy_ev[0] == pytest.approx(energy_exact_ev, rel=1e-2)
    assert result.tof[0] == pytest.approx(t_exact, rel=1e-2)


def test_dt_auto_estimate_is_reasonable():
    """dt自動推定が極端に粗すぎ/細かすぎないこと (加速テストと同じ設定を利用)。

    - 飛行時間全体をカバーするのに必要なステップ数が数十~数千のオーダーに収まる
      (1ステップで飛ばしすぎない、かつ極小刻みで無駄に遅くならない)
    """
    x_start = 1e-4
    project = _parallel_plate_project(
        {
            "species": {"preset": "electron"},
            "emitter": {
                "kind": "point",
                "p1": [x_start, H / 2],
                "n": 1,
                "energy_ev": 0.0,
                "direction_deg": 0.0,
            },
            "dt": None,
            "n_steps": 2000,
            "save_every": 5,
        }
    )
    mesh = generate_mesh(project)
    sol = solve(project, mesh)
    result = trace(project, mesh, sol)

    d = D - x_start
    e_field = V1 / D
    t_exact = math.sqrt(2.0 * d * ME / (QE * e_field))

    steps_to_cross = t_exact / result.dt
    # 目安: 数十~数百ステップで横断する程度の刻み幅であること
    assert 10.0 < steps_to_cross < 2000.0


# ---- 放物軌道テスト ----------------------------------------------------------


def test_parabolic_trajectory_matches_analytic():
    """一様電場に直交する初速で発射した電子の軌道が解析解の放物線と一致すること
    (吸収前の中間点で位置誤差が数%以内)。"""
    x0, y0 = 0.01, 0.025
    energy_ev = 5.0
    project = _parallel_plate_project(
        {
            "species": {"preset": "electron"},
            "emitter": {
                "kind": "point",
                "p1": [x0, y0],
                "n": 1,
                "energy_ev": energy_ev,
                "direction_deg": 90.0,  # 電場(x方向)と直交するy方向に射出
            },
            "dt": None,
            "n_steps": 4000,
            "save_every": 1,
        }
    )
    mesh = generate_mesh(project)
    sol = solve(project, mesh)
    result = trace(project, mesh, sol)

    v0 = math.sqrt(2.0 * energy_ev * QE / ME)
    e_field = V1 / D
    a = QE * e_field / ME  # 電子は陰極(x=0)→陽極(x=D)方向に加速

    dt = result.dt
    traj = result.trajectories[0]  # (n_frames, 2)  save_every=1 なので frame i は時刻 i*dt

    # 上壁 (y=H) に到達するまでの時間より十分手前の中間フレームで比較する
    t_wall = (H - y0) / v0
    t_mid = 0.4 * t_wall
    idx = int(round(t_mid / dt))
    assert idx < len(traj) - 1

    t = idx * dt
    x_exact = x0 + 0.5 * a * t ** 2
    y_exact = y0 + v0 * t

    x_num, y_num = traj[idx]
    assert x_num == pytest.approx(x_exact, rel=0.05, abs=1e-4)
    assert y_num == pytest.approx(y_exact, rel=0.05, abs=1e-4)


# ---- 吸収テスト --------------------------------------------------------------


def test_particle_absorbed_by_conductor():
    """円形電極(conductor領域)に向けて発射した粒子が absorbed になること。"""
    size = 0.1
    circle_center = (0.06, 0.05)
    circle_radius = 0.01
    project = Project.model_validate(
        {
            "geometry": {
                "domain": {"polygon": [[0, 0], [size, 0], [size, size], [0, size]]},
                "regions": [
                    {
                        "id": "electrode",
                        "type": "conductor",
                        "shape": {"kind": "circle", "center": list(circle_center), "radius": circle_radius},
                        "voltage": 0.0,
                    }
                ],
                "boundaries": [
                    {"edges": [3], "type": "dirichlet", "voltage": 0.0},
                    {"edges": [1], "type": "dirichlet", "voltage": 0.0},
                ],
            },
            "mesh": {"size": 0.005},
            "particles": {
                "species": {"preset": "electron"},
                "emitter": {
                    "kind": "point",
                    "p1": [0.01, circle_center[1]],
                    "n": 3,
                    "energy_ev": 100.0,
                    "direction_deg": 0.0,  # 円の中心へ向けて直進
                    "spread_deg": 0.0,
                },
                "dt": None,
                "n_steps": 3000,
                "save_every": 5,
            },
        }
    )
    mesh = generate_mesh(project)
    sol = solve(project, mesh)
    result = trace(project, mesh, sol)

    assert np.all(result.absorbed)
    assert all(t is not None and t > 0 for t in result.tof.tolist())
