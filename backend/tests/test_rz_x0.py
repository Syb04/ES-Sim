"""左辺 (x=0) を軸とする軸対称モード rz_x0 のテスト (prompts/41)。

rz_x0: x = r (径方向)、y = z (軸方向)、対称軸は x=0。

1. 円筒コンデンサ (縦向き): V(r) = V1·ln(b/r)/ln(b/a) と一致、容量が解析値と数%以内
2. rz との等価性: 90°回転した同一物理で解・容量がほぼ一致
3. 粒子: vθ≠0 の L 保存・軌道解析解一致 (rz テストの回転版)、軸 (x=0) 交差の鏡映
4. バリデーション: x<0 domain・x=0 辺への Dirichlet・pic 実行のエラー
"""

import math

import numpy as np
import pytest
from pydantic import ValidationError

from es_sim.fem import EPS0, solve
from es_sim.meshing import generate_mesh
from es_sim.particles import ME, QE, _init_particles, trace
from es_sim.pic import PicSimulation
from es_sim.schema import Emitter, Project

A, B = 0.02, 0.05   # 内径 a・外径 b [m]
LZ = 0.03           # 軸方向長さ [m]
V1 = 100.0


def _cyl_x0_project(mesh_size: float = 0.002) -> Project:
    """縦向き円筒コンデンサ: domain [a,b]×[0,L]、左辺 x=a に V1・右辺 x=b に 0V。"""
    return Project.model_validate(
        {
            "coord": "rz_x0",
            "geometry": {
                "domain": {"polygon": [[A, 0], [B, 0], [B, LZ], [A, LZ]]},
                "boundaries": [
                    {"edges": [3], "voltage": V1},   # 左辺 r=a
                    {"edges": [1], "voltage": 0.0},  # 右辺 r=b (上下は Neumann)
                ],
            },
            "mesh": {"size": mesh_size},
        }
    )


def _cyl_rz_project(mesh_size: float = 0.002) -> Project:
    """rz (横向き) の同一物理: domain [0,L]×[a,b]、下辺 r=a に V1・上辺 r=b に 0V。"""
    return Project.model_validate(
        {
            "coord": "rz",
            "geometry": {
                "domain": {"polygon": [[0, A], [LZ, A], [LZ, B], [0, B]]},
                "boundaries": [
                    {"edges": [0], "voltage": V1},
                    {"edges": [2], "voltage": 0.0},
                ],
            },
            "mesh": {"size": mesh_size},
        }
    )


# ---- 1. 円筒コンデンサ (縦向き) ----------------------------------------------------


def test_rz_x0_cylindrical_capacitor():
    project = _cyl_x0_project()
    mesh = generate_mesh(project)
    sol = solve(project, mesh)

    r = mesh.nodes[:, 0]  # rz_x0 の径方向は x
    v_exact = V1 * np.log(B / r) / np.log(B / A)
    assert np.max(np.abs(sol.v - v_exact)) / V1 < 1e-2

    c_exact = 2.0 * math.pi * EPS0 * LZ / math.log(B / A)
    assert sol.energy == pytest.approx(0.5 * c_exact * V1**2, rel=0.03)


# ---- 2. rz との等価性 --------------------------------------------------------------


def test_rz_x0_matches_rz_rotated():
    """同一物理 (90°回転) で rz と rz_x0 の解・容量が数値的にほぼ一致する。"""
    p_rz, p_x0 = _cyl_rz_project(), _cyl_x0_project()
    m_rz, m_x0 = generate_mesh(p_rz), generate_mesh(p_x0)
    s_rz, s_x0 = solve(p_rz, m_rz), solve(p_x0, m_x0)

    # 容量 (エネルギー) の一致
    assert s_x0.energy == pytest.approx(s_rz.energy, rel=1e-2)

    # 中心付近 (r = (a+b)/2, z = L/2) の電位の一致 (メッシュは異なるので最近傍節点)
    r_mid, z_mid = 0.5 * (A + B), 0.5 * LZ
    i_rz = int(np.argmin(np.hypot(m_rz.nodes[:, 0] - z_mid, m_rz.nodes[:, 1] - r_mid)))
    i_x0 = int(np.argmin(np.hypot(m_x0.nodes[:, 0] - r_mid, m_x0.nodes[:, 1] - z_mid)))
    assert s_x0.v[i_x0] == pytest.approx(s_rz.v[i_rz], abs=1e-2 * V1)


# ---- 3. 粒子 (回転版) --------------------------------------------------------------


def test_rz_x0_angular_momentum_and_energy_conservation():
    """無電場・vθ≠0 の自由粒子: r(t) = √((r0+vr·t)² + (vθ·t)²) と一致 (rz の回転版)。

    rz_x0 では面内速度は (vx, vy) = (v_r, v_z軸)、第3成分が vθ。
    """
    n, seed, kt = 8, 42, 0.01
    r0, z0 = 0.035, 0.015
    dt, n_steps = 1e-10, 100
    emitter = {
        "kind": "point", "p1": [r0, z0], "n": n,
        "energy_ev": 0.0, "energy_dist": "maxwell",
        "temperature_ev": kt, "seed": seed,
    }
    project = Project.model_validate(
        {
            "coord": "rz_x0",
            "geometry": {
                "domain": {"polygon": [[A, 0], [B, 0], [B, LZ], [A, LZ]]},
                "boundaries": [{"edges": [0, 1, 2, 3], "voltage": 0.0}],  # 無電場
            },
            "mesh": {"size": 0.002},
            "particles": {
                "species": {"preset": "electron"},
                "emitter": emitter,
                "dt": dt,
                "n_steps": n_steps,
                "save_every": n_steps,
            },
        }
    )
    mesh = generate_mesh(project)
    sol = solve(project, mesh)
    result = trace(project, mesh, sol)
    assert not np.any(result.absorbed)

    _, v0 = _init_particles(Emitter.model_validate(emitter), ME, vtheta=True)
    assert np.any(v0[:, 2] != 0.0)
    t = n_steps * dt
    # rz_x0: 径方向は x 成分 (v0[:,0])、軸方向は y 成分 (v0[:,1])
    r_exact = np.sqrt((r0 + v0[:, 0] * t) ** 2 + (v0[:, 2] * t) ** 2)
    z_exact = z0 + v0[:, 1] * t
    final = result.trajectories[:, -1, :]
    assert np.allclose(final[:, 0], r_exact, rtol=1e-6)  # L 保存を含む径方向運動
    assert np.allclose(final[:, 1], z_exact, rtol=1e-6)

    e0_ev = 0.5 * ME * np.sum(v0**2, axis=1) / QE
    assert np.allclose(result.final_energy_ev, e0_ev, rtol=1e-3)


def test_rz_x0_axis_crossing_mirrors():
    """L=0 の粒子が軸 (x=0) へ向かい、r → −r, vr → −vr の鏡映で通過する。"""
    r0, z0 = 0.01, 0.015
    energy_ev = 10.0
    dt, n_steps = 2e-11, 600
    project = Project.model_validate(
        {
            "coord": "rz_x0",
            "geometry": {
                # 軸 (x=0) を含む domain。左辺 (x=0) は自然境界 (Dirichlet 禁止)
                "domain": {"polygon": [[0, 0], [0.02, 0], [0.02, LZ], [0, LZ]]},
                "boundaries": [
                    {"edges": [0], "voltage": 0.0},  # 下辺 (z=0)
                    {"edges": [2], "voltage": 0.0},  # 上辺 (z=L) → 無電場
                ],
            },
            "mesh": {"size": 0.0015},
            "particles": {
                "species": {"preset": "electron"},
                "emitter": {
                    "kind": "point", "p1": [r0, z0], "n": 1,
                    "energy_ev": energy_ev, "direction_deg": 180.0,  # −x (軸へ)
                },
                "dt": dt,
                "n_steps": n_steps,
                "save_every": 5,
            },
        }
    )
    mesh = generate_mesh(project)
    sol = solve(project, mesh)
    result = trace(project, mesh, sol)

    assert not result.absorbed[0]  # 軸 (左辺) では吸収されず鏡映される
    traj = result.trajectories[0]
    v = math.sqrt(2.0 * energy_ev * QE / ME)
    t = n_steps * dt
    assert v * t > r0  # 軸を必ず横切る設定
    assert np.min(traj[:, 0]) >= 0.0
    assert traj[-1, 0] == pytest.approx(abs(r0 - v * t), rel=1e-3)
    # 反射後は +r (+x) 方向へ直進 (z は不変)
    assert result.final_angle_deg[0] == pytest.approx(0.0, abs=1.0)
    assert traj[-1, 1] == pytest.approx(z0, abs=1e-6)


# ---- 4. バリデーション -------------------------------------------------------------


def test_rz_x0_validation_errors():
    # x < 0 の頂点を含む domain
    with pytest.raises(ValidationError, match="x"):
        Project.model_validate(
            {
                "coord": "rz_x0",
                "geometry": {
                    "domain": {"polygon": [[-0.01, 0], [B, 0], [B, LZ], [-0.01, LZ]]},
                    "boundaries": [],
                },
                "mesh": {"size": 0.002},
            }
        )

    # 対称軸 (x=0) の辺への Dirichlet 指定
    with pytest.raises(ValidationError, match="対称軸"):
        Project.model_validate(
            {
                "coord": "rz_x0",
                "geometry": {
                    "domain": {"polygon": [[0, 0], [B, 0], [B, LZ], [0, LZ]]},
                    "boundaries": [{"edges": [3], "voltage": 0.0}],  # 左辺 = 軸
                },
                "mesh": {"size": 0.002},
            }
        )

    # pic + rz_x0 は明確なエラー (メッセージは「軸対称」で共通)
    project = Project.model_validate(
        {
            "coord": "rz_x0",
            "geometry": {
                "domain": {"polygon": [[A, 0], [B, 0], [B, LZ], [A, LZ]]},
                "boundaries": [{"edges": [1], "voltage": 0.0}],
            },
            "mesh": {"size": 0.002},
            "pic": {"dt": 1e-9, "n_steps": 10, "n_macro": 10, "frame_every": 10},
        }
    )
    with pytest.raises(ValueError, match="軸対称"):
        PicSimulation(project)
