"""IEDF/IADF コレクタのテスト (prompts/30)。

1. 決定的ケース: 平行平板 DC (陰極 -100V)・無衝突・上下対称境界で、低温イオンを
   陰極前から静かに放して加速 → 陰極面コレクタで全イオンが記録され、
   エネルギーが電位差の期待値と数%以内・入射角がほぼ 0°
2. 範囲判定: コレクタ線分を陰極面の中央半分にすると記録数が減り、
   陰極面の外 (陽極面) に置くと記録 0
3. 重み整合: total_weight = Σ weights (truncated=false)。平均区間外の吸収は記録されない
"""

import numpy as np
import pytest

from es_sim.particles import QE, _locate_initial
from es_sim.pic import PicSimulation
from es_sim.schema import Project

L = 0.01           # 極板間隔 (x) [m]
HGT = 0.01         # ストリップ高さ (y) [m]
V_CATHODE = -100.0  # 陰極 (右辺) 電位 [V]
X0 = 0.002         # イオンの発射位置 (x) [m]
M_ION = 40.0 * 1.67262192369e-27  # Ar+ (既定の ion_mass_amu=40)


def _build(collector: dict | None, avg_steps: int | None = None) -> PicSimulation:
    """平行平板 DC + 上下対称境界の PIC を構築する (粒子は空で開始)。"""
    n_steps = 500
    pic: dict = {
        "dt": 2e-9,
        "n_steps": n_steps,
        "n_macro": 10,
        "frame_every": n_steps,
        "avg_steps": avg_steps if avg_steps is not None else n_steps,
        "collector": collector,
    }
    project = Project.model_validate(
        {
            "geometry": {
                "domain": {"polygon": [[0, 0], [L, 0], [L, HGT], [0, HGT]]},
                "boundaries": [
                    {"edges": [3], "voltage": 0.0},        # 左辺: 陽極 0V
                    {"edges": [1], "voltage": V_CATHODE},  # 右辺: 陰極 -100V
                    {"edges": [0, 2], "type": "symmetry"},  # 上下: 対称境界
                ],
            },
            "mesh": {"size": 8e-4},
            "pic": pic,
        }
    )
    return PicSimulation(project)


def _seed_ions(sim: PicSimulation, y: np.ndarray, w: np.ndarray) -> None:
    """低温イオン (静止) を x = X0 の縦線上に装荷する。"""
    n = len(y)
    x = np.stack([np.full(n, X0), y], axis=1)
    io = sim.species["ion"]
    io.x = x
    io.v = np.zeros((n, 3))
    io.w = w.astype(np.float64)
    io.elem = _locate_initial(sim.coeffs, x)


# 発射位置の電位から期待される衝突エネルギー [eV]:
# E = q·(V(X0) - V_cathode)、V(x) = V_CATHODE·x/L
E_EXPECTED = (V_CATHODE * X0 / L) - V_CATHODE  # = 80 eV


# ---- 1. 決定的ケース: エネルギーと入射角 -----------------------------------------


def test_all_ions_collected_with_expected_energy_and_angle():
    n = 10
    sim = _build({"p1": [L, 0.0], "p2": [L, HGT], "tol": None})  # 陰極全面
    _seed_ions(sim, np.linspace(0.001, 0.009, n), np.ones(n))
    history, _ = sim.run_batch()

    # 全イオンが陰極に到達して吸収されている
    assert history["n_i"][-1] == 0

    res = sim.collector_result
    assert res is not None
    assert res["count"] == n
    assert not res["truncated"]
    assert len(res["energies_ev"]) == n
    assert len(res["angles_deg"]) == n
    assert len(res["weights"]) == n

    # エネルギー: 電位差の期待値 (~80 eV) と数%以内
    assert np.allclose(res["energies_ev"], E_EXPECTED, rtol=0.03)
    # 入射角: 電場は x 方向のみ (vy = 0) なのでほぼ垂直入射
    assert np.all(np.abs(res["angles_deg"]) < 5.0)
    # 検算: 衝突速度から ½m|v|²/e を直接再現できる値になっている
    v_exp = np.sqrt(2.0 * E_EXPECTED * QE / M_ION)
    e_from_v = 0.5 * M_ION * v_exp**2 / QE
    assert e_from_v == pytest.approx(E_EXPECTED, rel=1e-12)


# ---- 2. 範囲判定 -----------------------------------------------------------------


def test_collector_segment_range():
    n = 10
    y = np.linspace(0.001, 0.009, n)

    # 陰極面の中央半分 (y = 0.0025〜0.0075) のコレクタ
    y1, y2 = 0.25 * HGT, 0.75 * HGT
    sim = _build({"p1": [L, y1], "p2": [L, y2], "tol": None})
    _seed_ions(sim, y, np.ones(n))
    sim.run_batch()
    res = sim.collector_result

    # vy = 0 なので吸収 y はほぼ発射時の y のまま → 区間内のイオンのみ記録される
    expected = int(np.count_nonzero((y >= y1) & (y <= y2)))
    assert 0 < expected < n
    assert res["count"] == expected
    assert np.allclose(res["energies_ev"], E_EXPECTED, rtol=0.03)

    # 陰極面の外 (陽極面 x=0) に置いた場合は記録 0
    sim = _build({"p1": [0.0, 0.0], "p2": [0.0, HGT], "tol": 1e-4})
    _seed_ions(sim, y, np.ones(n))
    sim.run_batch()
    res = sim.collector_result
    assert res["count"] == 0
    assert res["total_weight"] == 0.0
    assert len(res["energies_ev"]) == 0
    assert not res["truncated"]


# ---- 3. 重み整合・平均区間の限定 ---------------------------------------------------


def test_total_weight_matches_sum_and_window_restriction():
    n = 10
    w = np.arange(1.0, n + 1.0)  # 相異なる重み (合計 55)

    sim = _build({"p1": [L, 0.0], "p2": [L, HGT], "tol": None})
    _seed_ions(sim, np.linspace(0.001, 0.009, n), w)
    sim.run_batch()
    res = sim.collector_result

    assert not res["truncated"]
    assert res["count"] == n
    assert res["total_weight"] == pytest.approx(float(w.sum()), rel=1e-12)
    assert np.sum(res["weights"]) == pytest.approx(res["total_weight"], rel=1e-12)
    # 記録された重みは装荷した重みの並べ替え (順序は吸収順)
    assert np.array_equal(np.sort(res["weights"]), w)

    # 平均区間 (最後の 10 ステップ) 外で吸収されたイオンは記録されない
    sim = _build({"p1": [L, 0.0], "p2": [L, HGT], "tol": None}, avg_steps=10)
    _seed_ions(sim, np.linspace(0.001, 0.009, n), w)
    history, _ = sim.run_batch()
    assert history["n_i"][-1] == 0  # イオン自体は窓の手前で全て吸収済み
    res = sim.collector_result
    assert res["count"] == 0 and res["total_weight"] == 0.0
