"""軸対称 (rz) モードのテスト (prompts/39)。x = z (軸方向)、y = r (径方向)。

1. 円筒コンデンサ: V(r) = V1·ln(b/r)/ln(b/a) と一致 (<1e-2)。xy では線形 (対比)
2. エネルギー/容量: W = ½CV1²、C = 2πεL/ln(b/a) と数%以内
3. 軸を含む解: 有限で軸上 ∂V/∂r ≈ 0
4. 粒子: Ez 加速の解析解一致 (vθ=0)、L 保存 + エネルギー保存 (vθ≠0)、軸交差の鏡映
5. バリデーション: y<0 domain・軸への Dirichlet・pic 実行のエラー
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


def _cyl_project(coord: str, mesh_size: float = 0.002) -> Project:
    """円筒コンデンサ: domain 矩形 [0,L]×[a,b]、下辺 r=a に V1・上辺 r=b に 0V。"""
    return Project.model_validate(
        {
            "coord": coord,
            "geometry": {
                "domain": {"polygon": [[0, A], [LZ, A], [LZ, B], [0, B]]},
                "boundaries": [
                    {"edges": [0], "voltage": V1},   # 下辺 r=a
                    {"edges": [2], "voltage": 0.0},  # 上辺 r=b (左右は Neumann)
                ],
            },
            "mesh": {"size": mesh_size},
        }
    )


# ---- 1. 円筒コンデンサ (対数分布) と xy 対比 ---------------------------------------


def test_cylindrical_capacitor_log_profile():
    project = _cyl_project("rz")
    mesh = generate_mesh(project)
    sol = solve(project, mesh)

    r = mesh.nodes[:, 1]
    v_exact = V1 * np.log(B / r) / np.log(B / A)
    err = np.max(np.abs(sol.v - v_exact)) / V1
    assert err < 1e-2

    # メッシュ細分で誤差が改善する (収束性)
    fine = _cyl_project("rz", mesh_size=0.001)
    mesh_f = generate_mesh(fine)
    sol_f = solve(fine, mesh_f)
    err_f = np.max(np.abs(sol_f.v - V1 * np.log(B / mesh_f.nodes[:, 1]) / np.log(B / A))) / V1
    assert err_f < err

    # 対比: 平面 (xy) モードでは線形になる (= r 重みが効いている証拠)
    project_xy = _cyl_project("xy")
    mesh_xy = generate_mesh(project_xy)
    sol_xy = solve(project_xy, mesh_xy)
    v_lin = V1 * (B - mesh_xy.nodes[:, 1]) / (B - A)
    assert np.max(np.abs(sol_xy.v - v_lin)) < 1e-8 * V1


# ---- 2. エネルギー / 容量 -----------------------------------------------------------


def test_cylindrical_capacitor_energy():
    """W = ½·C·V1²、C = 2πεL/ln(b/a) [F] と数%以内 (rz のエネルギーは [J])。"""
    project = _cyl_project("rz")
    mesh = generate_mesh(project)
    sol = solve(project, mesh)

    c_exact = 2.0 * math.pi * EPS0 * LZ / math.log(B / A)
    w_exact = 0.5 * c_exact * V1**2
    assert sol.energy == pytest.approx(w_exact, rel=0.03)


# ---- 3. 軸 (r=0) を含む解 ----------------------------------------------------------


def _disk_project(particles: dict | None = None, pic: dict | None = None) -> Project:
    """軸対称の平行平板 (円板コンデンサ中心部): domain [0,L]×[0,R]、左右 Dirichlet。"""
    data = {
        "coord": "rz",
        "geometry": {
            "domain": {"polygon": [[0, 0], [LZ, 0], [LZ, 0.02], [0, 0.02]]},
            "boundaries": [
                {"edges": [3], "voltage": 0.0},   # 左 (z=0)
                {"edges": [1], "voltage": V1},    # 右 (z=L)。下辺 (軸) は自然境界
            ],
        },
        "mesh": {"size": 0.0015},
    }
    if particles is not None:
        data["particles"] = particles
    if pic is not None:
        data["pic"] = pic
    return Project.model_validate(data)


def test_axis_included_solution_finite_and_flat():
    project = _disk_project()
    mesh = generate_mesh(project)
    sol = solve(project, mesh)

    assert np.all(np.isfinite(sol.v))
    # 解は V ≈ V1·z/L (r に依存しない)
    v_exact = V1 * mesh.nodes[:, 0] / LZ
    assert np.max(np.abs(sol.v - v_exact)) < 1e-2 * V1
    # 軸上 (r=0) 付近の要素で ∂V/∂r ≈ 0 (|Er| << V1/L)
    r_cent = mesh.nodes[mesh.triangles][:, :, 1].mean(axis=1)
    near_axis = r_cent < 0.002
    assert np.any(near_axis)
    assert np.max(np.abs(sol.e_field[near_axis, 1])) < 0.02 * V1 / LZ


# ---- 4. 粒子軌道 (rz) --------------------------------------------------------------


def test_rz_acceleration_matches_analytic():
    """一様 Ez 場での加速 (vθ=0)。エネルギー・飛行時間が解析解と一致する。"""
    z0 = 1e-4
    project = _disk_project(
        particles={
            "species": {"preset": "electron"},
            "emitter": {"kind": "point", "p1": [z0, 0.01], "n": 1, "energy_ev": 0.0},
            "dt": None,
            "n_steps": 3000,
            "save_every": 10,
        }
    )
    mesh = generate_mesh(project)
    sol = solve(project, mesh)
    result = trace(project, mesh, sol)

    assert result.absorbed[0]
    d = LZ - z0
    e_field = V1 / LZ
    energy_exact = e_field * d
    t_exact = math.sqrt(2.0 * d * ME / (QE * e_field))
    assert result.final_energy_ev[0] == pytest.approx(energy_exact, rel=0.02)
    assert result.tof[0] == pytest.approx(t_exact, rel=0.02)
    # vθ=0 なので面内運動: r は不変
    traj = result.trajectories[0]
    assert np.max(np.abs(traj[:, 1] - 0.01)) < 1e-6


def test_rz_angular_momentum_and_energy_conservation():
    """無電場・vθ≠0 (maxwell の第3成分) の自由粒子: r(t) が角運動量保存の解析解
    r(t) = √((r0+vr·t)² + (vθ·t)²) と一致し、全エネルギーが保存する。"""
    n, seed, kt = 8, 42, 0.01
    z0, r0 = 0.015, 0.035
    dt, n_steps = 1e-10, 100
    emitter = {
        "kind": "point", "p1": [z0, r0], "n": n,
        "energy_ev": 0.0, "energy_dist": "maxwell",
        "temperature_ev": kt, "seed": seed,
    }
    project = Project.model_validate(
        {
            "coord": "rz",
            "geometry": {
                "domain": {"polygon": [[0, A], [LZ, A], [LZ, B], [0, B]]},
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

    # 初期速度 (vz, vr, vθ) を同じ seed で再現して解析解と比較
    _, v0 = _init_particles(Emitter.model_validate(emitter), ME, vtheta=True)
    assert v0.shape == (n, 3) and np.any(v0[:, 2] != 0.0)

    t = n_steps * dt
    r_exact = np.sqrt((r0 + v0[:, 1] * t) ** 2 + (v0[:, 2] * t) ** 2)
    z_exact = z0 + v0[:, 0] * t
    final = result.trajectories[:, -1, :]
    # L = r·vθ の保存を含む径方向運動 (遠心力 + vθ = L/r) の検証
    assert np.allclose(final[:, 1], r_exact, rtol=1e-6)
    assert np.allclose(final[:, 0], z_exact, rtol=1e-6)

    # 全エネルギー保存 (無電場なので運動エネルギー一定)
    e0_ev = 0.5 * ME * np.sum(v0**2, axis=1) / QE
    assert np.allclose(result.final_energy_ev, e0_ev, rtol=1e-3)


def test_rz_axis_crossing_mirrors():
    """L=0 の粒子が軸へ向かい、r → −r, vr → −vr の鏡映で通過する。"""
    z0, r0 = 0.015, 0.01
    energy_ev = 10.0
    dt, n_steps = 2e-11, 600
    project = _disk_project(
        particles={
            "species": {"preset": "electron"},
            "emitter": {
                "kind": "point", "p1": [z0, r0], "n": 1,
                "energy_ev": energy_ev, "direction_deg": -90.0,  # −r 方向 (軸へ)
            },
            "dt": dt,
            "n_steps": n_steps,
            "save_every": 5,
        }
    )
    # 無電場にする (左右とも 0V)
    project = project.model_copy(deep=True)
    project.geometry.boundaries[1].voltage = 0.0
    mesh = generate_mesh(project)
    sol = solve(project, mesh)
    result = trace(project, mesh, sol)

    assert not result.absorbed[0]  # 軸 (下辺) では吸収されず鏡映される
    traj = result.trajectories[0]
    v = math.sqrt(2.0 * energy_ev * QE / ME)
    t = n_steps * dt
    assert v * t > r0  # 軸を必ず横切る設定
    # r は常に非負で、鏡映後の解析解 |r0 − v·t| に一致する
    assert np.min(traj[:, 1]) >= 0.0
    assert traj[-1, 1] == pytest.approx(abs(r0 - v * t), rel=1e-3)
    # 反射後は +r 方向へ直進 (z は不変)
    assert result.final_angle_deg[0] == pytest.approx(90.0, abs=1.0)
    assert traj[-1, 0] == pytest.approx(z0, abs=1e-6)


# ---- 5. バリデーション -------------------------------------------------------------


def test_rz_validation_errors():
    # y < 0 の頂点を含む domain
    with pytest.raises(ValidationError, match="y"):
        Project.model_validate(
            {
                "coord": "rz",
                "geometry": {
                    "domain": {"polygon": [[0, -0.01], [LZ, -0.01], [LZ, B], [0, B]]},
                    "boundaries": [],
                },
                "mesh": {"size": 0.002},
            }
        )

    # 対称軸 (y=0) の辺への Dirichlet 指定
    with pytest.raises(ValidationError, match="対称軸"):
        Project.model_validate(
            {
                "coord": "rz",
                "geometry": {
                    "domain": {"polygon": [[0, 0], [LZ, 0], [LZ, B], [0, B]]},
                    "boundaries": [{"edges": [0], "voltage": 0.0}],
                },
                "mesh": {"size": 0.002},
            }
        )

    # pic + rz は明確なエラー
    project = _disk_project(
        pic={"dt": 1e-9, "n_steps": 10, "n_macro": 10, "frame_every": 10}
    )
    with pytest.raises(ValueError, match="軸対称"):
        PicSimulation(project)
