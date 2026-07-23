"""デュアル周波数 RF 電圧のテスト (prompts/49)。

1. スキーマ: voltage_rf に単一 / リストのどちらも指定できる
2. V(t): 2成分の Dirichlet 値が解析式 V_dc + ΣA_k sin(ω_k t + φ_k) と一致
3. 単一周波数の後方互換: リスト1成分と単一指定が同値
4. 位相分解の基本周波数 = 全成分の最小周波数
5. デュアル周波数 CCP スモーク: NaN なしで実行できる
"""

import math

import numpy as np

from es_sim.pic import PicSimulation
from es_sim.schema import Project, rf_components

L = 0.02
H = 0.01

F_LO = 2.0e6
F_HI = 27.12e6


def _dual_project(voltage_rf, n_steps: int = 10) -> Project:
    return Project.model_validate(
        {
            "geometry": {
                "domain": {"polygon": [[0, 0], [L, 0], [L, H], [0, H]]},
                "boundaries": [
                    {"edges": [3], "type": "dirichlet", "voltage": -10.0, "voltage_rf": voltage_rf},
                    {"edges": [1], "type": "dirichlet", "voltage": 0.0},
                ],
            },
            "mesh": {"size": 1.5e-3},
            "pic": {
                "initial_plasma": {
                    "density": 1e14, "te_ev": 2.0, "ti_ev": 0.03,
                    "ion_mass_amu": 40.0, "seed": 0,
                },
                "n_macro": 2000,
                "dt": 1e-10,
                "n_steps": n_steps,
                "frame_every": 100,
                "phase_bins": 8,
            },
        }
    )


DUAL = [
    {"amplitude": 500.0, "freq_hz": F_LO, "phase_deg": 0.0},
    {"amplitude": 100.0, "freq_hz": F_HI, "phase_deg": 90.0},
]


def test_schema_accepts_single_and_list():
    p1 = _dual_project({"amplitude": 100.0, "freq_hz": 13.56e6})
    p2 = _dual_project(DUAL)
    assert len(rf_components(p1.geometry.boundaries[0].voltage_rf)) == 1
    assert len(rf_components(p2.geometry.boundaries[0].voltage_rf)) == 2


def test_dual_dirichlet_values():
    """RF 電極節点の V(t) が解析式と一致する (数ステップ分の時刻で確認)。"""
    sim = PicSimulation(_dual_project(DUAL))
    # RF 電極 (V_dc = -10) の行を特定する
    rf_rows = np.nonzero(sim.rf_amp[:, 0] > 0.0)[0]
    assert len(rf_rows) > 0
    assert sim.rf_amp.shape[1] == 2
    for t in (0.0, 3.7e-9, 1.23e-8, 8.9e-8):
        vd = sim._dirichlet_values(t)
        expected = (
            -10.0
            + 500.0 * math.sin(2.0 * math.pi * F_LO * t)
            + 100.0 * math.sin(2.0 * math.pi * F_HI * t + math.pi / 2.0)
        )
        assert np.allclose(vd[rf_rows], expected, rtol=0, atol=1e-9)
        # 接地電極は 0 のまま
        gnd = np.nonzero((sim.v_dc == 0.0))[0]
        assert np.allclose(vd[gnd], 0.0)


def test_single_list_equivalence():
    """1成分リストと単一オブジェクト指定の V(t) が完全一致する。"""
    single = {"amplitude": 100.0, "freq_hz": 13.56e6, "phase_deg": 30.0}
    sim_a = PicSimulation(_dual_project(single))
    sim_b = PicSimulation(_dual_project([single]))
    for t in (0.0, 1e-9, 5e-8):
        assert np.array_equal(sim_a._dirichlet_values(t), sim_b._dirichlet_values(t))


def test_cycle_fundamental_freq():
    """位相分解の基本周波数 = 全成分の最小周波数 (低周波側)。"""
    sim = PicSimulation(_dual_project(DUAL))
    assert sim._cycle_freq == F_LO
    assert sim._cycle_period == 1.0 / F_LO


def test_dual_freq_ccp_smoke():
    """デュアル周波数 CCP を 100 ステップ実行して NaN が出ないこと。"""
    sim = PicSimulation(_dual_project(DUAL, n_steps=100))
    history, _ = sim.run_batch()
    for key in ("ke_e", "fe", "phi_min", "phi_max"):
        arr = np.asarray(history[key])
        assert np.all(np.isfinite(arr)), f"{key} に非有限値"
    # 電位の振れ幅が両成分を反映して ±(500+100+|dc|) 程度に収まる
    assert np.max(np.abs(history["phi_max"])) < 700.0
