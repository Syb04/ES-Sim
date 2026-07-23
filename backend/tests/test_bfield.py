"""一様磁場 (Boris 法) のテスト (prompts/51)。

1. Boris 回転行列: 厳密なノルム保存と小 dt での回転角 ≈ ωc·dt
2. trace ジャイロ運動 (Bz): 軌道半径がラーマー半径 r_L = mv/(|q|B) と一致、
   エネルギー保存
3. trace E×B ドリフト: 案内中心速度が E×B/B² と一致
4. trace 面内磁場 (By): v ∥ x̂ の電子が x-z 面内で旋回し y は不変
5. PIC: 無電場でのジャイロ運動のエネルギー厳密保存
6. rz + 非ゼロ b_field はバリデーションエラー、b_field 全ゼロは磁場なしと同値
"""

import math

import numpy as np
import pytest
from pydantic import ValidationError

from es_sim.fem import solve
from es_sim.meshing import generate_mesh
from es_sim.particles import ME, QE, _boris_matrix, trace
from es_sim.pic import PicSimulation
from es_sim.schema import Project

L = 0.02  # ドメイン一辺 [m]


def _box_project(extra: dict, voltage_top: float = 0.0) -> dict:
    """全周 Dirichlet の正方形 (上辺のみ voltage_top、他 0V)。"""
    return {
        "geometry": {
            "domain": {"polygon": [[0, 0], [L, 0], [L, L], [0, L]]},
            "boundaries": [
                {"edges": [0, 1, 3], "type": "dirichlet", "voltage": 0.0},
                {"edges": [2], "type": "dirichlet", "voltage": voltage_top},
            ],
        },
        "mesh": {"size": 1.5e-3},
    } | extra


def test_boris_matrix_properties():
    b = np.array([0.3, -0.2, 0.5])
    dt = 1e-11
    r = _boris_matrix(-QE, ME, dt, b)
    # 厳密なノルム保存 (直交行列)
    v = np.array([1.0e6, -2.0e6, 0.5e6])
    assert np.linalg.norm(r @ v) == pytest.approx(np.linalg.norm(v), rel=1e-12)
    # B 方向成分は不変
    bh = b / np.linalg.norm(b)
    assert (r @ bh) @ bh == pytest.approx(1.0, rel=1e-12)
    # 回転角 = 2·atan(ωc·dt/2) (Boris の厳密な回転角。小 dt では ωc·dt に一致)
    wc = QE * np.linalg.norm(b) / ME
    v_perp = np.cross(bh, np.array([1.0, 0.0, 0.0]))
    v_perp /= np.linalg.norm(v_perp)
    cos_a = float((r @ v_perp) @ v_perp)
    assert math.acos(min(1.0, cos_a)) == pytest.approx(2.0 * math.atan(wc * dt / 2.0), rel=1e-9)


ENERGY_EV = 100.0
BZ = 0.01


def _speed(energy_ev: float) -> float:
    return math.sqrt(2.0 * energy_ev * QE / ME)


def test_trace_gyro_radius_bz():
    """Bz のみ・無電場: 電子が半径 r_L = mv/(|q|B) の円軌道を描く。"""
    v0 = _speed(ENERGY_EV)
    r_l = ME * v0 / (QE * BZ)  # ≈ 3.4e-3 m
    project = Project.model_validate(
        _box_project(
            {
                "b_field": {"bz": BZ},
                "particles": {
                    "emitter": {
                        "kind": "point", "p1": [L / 2, L / 2], "n": 1,
                        "energy_ev": ENERGY_EV, "direction_deg": 0.0, "spread_deg": 0.0,
                    },
                    "dt": None,
                    "n_steps": 400,
                    "save_every": 1,
                },
            }
        )
    )
    mesh = generate_mesh(project)
    sol = solve(project, mesh)
    out = trace(project, mesh, sol)

    pts = out.trajectories[0]  # (n_frames, 2)
    assert not out.absorbed[0]
    # 軌道点の重心 = 円の中心。各点の中心からの距離が r_L と一致
    center = pts.mean(axis=0)
    dist = np.linalg.norm(pts - center, axis=1)
    assert float(dist.mean()) == pytest.approx(r_l, rel=0.02)
    assert float(dist.std()) / r_l < 0.02
    # エネルギー保存 (Boris は厳密にノルム保存、E=0)
    assert out.final_energy_ev[0] == pytest.approx(ENERGY_EV, rel=1e-9)


def test_trace_exb_drift():
    """一様 E (上辺 +10V) + Bz: 案内中心速度が v_d = E×B/B² と一致。"""
    volt = 10.0
    e_y = -volt / L          # E = -∇φ (上が高電位 → E は -y 向き)
    v_d = e_y * (-1.0) / BZ * -1.0  # (E×B)/B² の x 成分 = Ey·Bz/(Bz²)·(-1)... 下で解析計算
    # E = (0, e_y, 0), B = (0, 0, BZ) → E×B = (e_y·BZ, 0, 0) → v_d_x = e_y/BZ
    v_d = e_y / BZ
    n_steps = 600
    dt = 1e-10
    # 一様電界にするため上下のみ Dirichlet (側面は自然境界 = 平行平板)
    project = Project.model_validate(
        {
            "geometry": {
                "domain": {"polygon": [[0, 0], [L, 0], [L, L], [0, L]]},
                "boundaries": [
                    {"edges": [0], "type": "dirichlet", "voltage": 0.0},
                    {"edges": [2], "type": "dirichlet", "voltage": volt},
                ],
            },
            "mesh": {"size": 1.5e-3},
            "b_field": {"bz": BZ},
            "particles": {
                "emitter": {
                    "kind": "point", "p1": [0.015, L / 2], "n": 1,
                    "energy_ev": 0.0, "direction_deg": 0.0, "spread_deg": 0.0,
                },
                "dt": dt,
                "n_steps": n_steps,
                "save_every": 10,
            },
        }
    )
    mesh = generate_mesh(project)
    sol = solve(project, mesh)
    out = trace(project, mesh, sol)
    assert not out.absorbed[0]
    pts = out.trajectories[0]
    t_total = n_steps * dt
    vx_avg = (pts[-1, 0] - pts[0, 0]) / t_total
    assert vx_avg == pytest.approx(v_d, rel=0.05)


def test_trace_inplane_by():
    """面内磁場 By と v ∥ x̂: x-z 面内で旋回し y は変わらない (F = qv×B ∝ ẑ)。"""
    v0 = _speed(ENERGY_EV)
    r_l = ME * v0 / (QE * BZ)
    project = Project.model_validate(
        _box_project(
            {
                "b_field": {"by": BZ},
                "particles": {
                    "emitter": {
                        "kind": "point", "p1": [L / 2, L / 2], "n": 1,
                        "energy_ev": ENERGY_EV, "direction_deg": 0.0, "spread_deg": 0.0,
                    },
                    "dt": None,
                    "n_steps": 400,
                    "save_every": 1,
                },
            }
        )
    )
    mesh = generate_mesh(project)
    sol = solve(project, mesh)
    out = trace(project, mesh, sol)
    pts = out.trajectories[0]
    # y は不変 (力は x-z 面内のみ)
    assert float(np.max(np.abs(pts[:, 1] - L / 2))) < 1e-12
    # x の振れ幅 = 直径 2 r_L (x-z 面内の円運動の投影)
    x_span = float(pts[:, 0].max() - pts[:, 0].min())
    assert x_span == pytest.approx(2.0 * r_l, rel=0.03)
    assert out.final_energy_ev[0] == pytest.approx(ENERGY_EV, rel=1e-9)


def test_pic_gyro_energy_conservation():
    """PIC + Bz・無電場: 単一電子の |v| が厳密に保存され、軌道が発散しない。"""
    project = Project.model_validate(
        _box_project(
            {
                "b_field": {"bz": BZ},
                "pic": {"n_macro": 10, "dt": 1e-11, "n_steps": 10, "frame_every": 100},
            }
        )
    )
    sim = PicSimulation(project)
    from es_sim.particles import _locate_initial

    el = sim.species["electron"]
    v0 = _speed(ENERGY_EV)
    el.x = np.array([[L / 2, L / 2]])
    el.v = np.array([[v0, 0.0, 0.0]])
    el.w = np.array([1.0])
    el.elem = _locate_initial(sim.coeffs, el.x)
    el.bary = None
    el.nidx = None
    for _ in range(200):
        sim.step()
    assert len(el.x) == 1
    speed = float(np.linalg.norm(el.v[0]))
    # E ≈ 0 (自己場のみ) なので Boris のノルム保存でエネルギーはほぼ厳密に保存
    assert speed == pytest.approx(v0, rel=1e-6)
    # 中心からラーマー半径程度に留まる
    r_l = ME * v0 / (QE * BZ)
    assert float(np.linalg.norm(el.x[0] - [L / 2, L / 2])) < 2.5 * r_l


def test_bfield_validation():
    # rz + 非ゼロ磁場はエラー
    with pytest.raises(ValidationError, match="b_field"):
        Project.model_validate(
            {
                "coord": "rz",
                "geometry": {"domain": {"polygon": [[0, 0], [L, 0], [L, L], [0, L]]}},
                "mesh": {"size": 2e-3},
                "b_field": {"bz": 0.01},
            }
        )
    # 全ゼロは rz でも許容 (磁場なしと同値)
    p = Project.model_validate(
        {
            "coord": "rz",
            "geometry": {"domain": {"polygon": [[0, 0], [L, 0], [L, L], [0, L]]}},
            "mesh": {"size": 2e-3},
            "b_field": {"bx": 0.0, "by": 0.0, "bz": 0.0},
        }
    )
    from es_sim.particles import b_vector

    assert b_vector(p) is None
