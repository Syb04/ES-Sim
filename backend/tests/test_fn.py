"""FN (Fowler–Nordheim) 電界放出のテスト (prompts/46)。

1. FN 式の数値検証: テスト内に独立に書いた同式のスカラー実装と一致すること、
   境界挙動 (F ≤ 0 → 0、β スケーリング) が正しいこと
2. 平行平板 trace: 一様電界 E = V/d の陰極から放出した総電流が解析値
   J(V/d)·L と一致し、全粒子が陽極でエネルギー eV + E0 で吸収されること
3. 電界反転時は放出ゼロ (粒子なし・電流 0)
4. conductor 領域表面からの放出 (fn.regions)
5. PIC: 端数持ち越しにより放出マクロ数が I·t/(e·w) を再現すること
"""

import math

import numpy as np
import pytest

from es_sim.fem import solve
from es_sim.fn import FN_A, FN_B, FN_C, fn_current_density
from es_sim.meshing import generate_mesh
from es_sim.particles import ME, QE, trace
from es_sim.pic import PicSimulation
from es_sim.schema import Project

PHI = 4.5  # 仕事関数 [eV]


def _fn_scalar(f_field: float, phi: float, beta: float = 1.0) -> float:
    """テスト用の独立スカラー実装 (Murphy-Good + Forbes 近似)。"""
    F = beta * f_field
    if F <= 0.0:
        return 0.0
    f = min(FN_C * F / phi**2, 1.0)
    v = 1.0 - f + (f / 6.0) * math.log(f)
    t = 1.0 + f / 9.0 - (f / 18.0) * math.log(f)
    return FN_A * F * F / (phi * t * t) * math.exp(-FN_B * phi**1.5 * v / F)


def test_fn_current_density_formula():
    """ベクトル実装が独立スカラー実装と一致し、境界挙動が正しいこと。"""
    fields = np.array([0.0, -1e9, 1e8, 1e9, 5e9, 1e10, 1e11])
    j = fn_current_density(fields, PHI)
    for fi, ji in zip(fields, j):
        assert ji == pytest.approx(_fn_scalar(float(fi), PHI), rel=1e-12)
    # F ≤ 0 は放出なし
    assert j[0] == 0.0 and j[1] == 0.0
    # 単調増加 (F > 0 の範囲)
    assert np.all(np.diff(j[2:]) > 0.0)
    # β スケーリング: J(F, β) = J(βF, 1)
    assert fn_current_density(np.array([1e9]), PHI, beta=5.0)[0] == pytest.approx(
        fn_current_density(np.array([5e9]), PHI, beta=1.0)[0], rel=1e-12
    )
    # 文献オーダー確認: φ=4.5 eV, F=5 GV/m で J ~ 1e9〜1e10 A/m²
    assert 1e9 < fn_current_density(np.array([5e9]), PHI)[0] < 1e10


D = 1e-5   # 平行平板ギャップ [m]
HGT = 2e-5  # 高さ (陰極エッジ長) [m]
VOLT = 1e4  # 電位差 [V] → E = 1e9 V/m
BETA = 10.0  # βE = 1e10 V/m で J が意味のある大きさになる


def _plates_project(v_cathode: float, v_anode: float, fn: dict) -> dict:
    """左辺 (エッジ3) 陰極・右辺 (エッジ1) 陽極の平行平板。"""
    return {
        "geometry": {
            "domain": {"polygon": [[0, 0], [D, 0], [D, HGT], [0, HGT]]},
            "boundaries": [
                {"edges": [3], "type": "dirichlet", "voltage": v_cathode},
                {"edges": [1], "type": "dirichlet", "voltage": v_anode},
            ],
        },
        "mesh": {"size": 2e-6},
        "particles": {"fn": fn, "n_steps": 4000, "save_every": 100},
    }


def test_trace_fn_parallel_plates():
    """一様電界の陰極からの放出: 総電流が解析値と一致し、全粒子が陽極到達。"""
    fn = {"edges": [3], "phi_ev": PHI, "beta": BETA, "n": 40, "init_energy_ev": 0.1}
    project = Project.model_validate(_plates_project(0.0, VOLT, fn))
    mesh = generate_mesh(project)
    sol = solve(project, mesh)
    out = trace(project, mesh, sol)

    e_surf = VOLT / D  # 一様電界 (P1 で厳密)
    i_expected = _fn_scalar(e_surf, PHI, BETA) * HGT  # [A/m]
    assert out.fn_current == pytest.approx(i_expected, rel=1e-6)
    assert out.currents is not None
    assert float(out.currents.sum()) == pytest.approx(i_expected, rel=1e-6)
    assert len(out.currents) == 40

    # 全粒子が吸収され、最終エネルギー ≈ eV + E0 (陽極まで全電位差を走る)
    assert np.all(out.absorbed)
    assert out.final_energy_ev == pytest.approx(
        np.full(40, VOLT + 0.1), rel=2e-2
    )


def test_trace_fn_reversed_field_no_emission():
    """電界が逆向き (陰極が正) なら放出ゼロ。"""
    fn = {"edges": [3], "phi_ev": PHI, "beta": BETA, "n": 40}
    project = Project.model_validate(_plates_project(VOLT, 0.0, fn))
    mesh = generate_mesh(project)
    sol = solve(project, mesh)
    out = trace(project, mesh, sol)
    assert out.fn_current == 0.0
    assert len(out.trajectories) == 0


def test_trace_fn_conductor_region():
    """conductor 領域表面 (fn.regions) からの放出: 全粒子が領域外から出発して吸収。"""
    project = Project.model_validate(
        {
            "geometry": {
                "domain": {"polygon": [[0, 0], [3e-5, 0], [3e-5, 3e-5], [0, 3e-5]]},
                "regions": [
                    {
                        "id": "tip",
                        "type": "conductor",
                        "polygon": [[1.2e-5, 1.2e-5], [1.8e-5, 1.2e-5], [1.8e-5, 1.8e-5], [1.2e-5, 1.8e-5]],
                        "voltage": -VOLT,
                    }
                ],
                "boundaries": [{"edges": [0, 1, 2, 3], "type": "dirichlet", "voltage": 0.0}],
            },
            "mesh": {"size": 2e-6},
            "particles": {
                "fn": {"regions": ["tip"], "phi_ev": PHI, "beta": 30.0, "n": 60},
                "n_steps": 4000,
                "save_every": 100,
            },
        }
    )
    mesh = generate_mesh(project)
    sol = solve(project, mesh)
    out = trace(project, mesh, sol)
    assert out.fn_current is not None and out.fn_current > 0.0
    n = len(out.trajectories)
    assert n == 60
    # 初期位置は conductor 矩形の外側 (真空側へオフセット済み)
    x0 = out.trajectories[:, 0, :]
    inside = (
        (x0[:, 0] > 1.2e-5) & (x0[:, 0] < 1.8e-5)
        & (x0[:, 1] > 1.2e-5) & (x0[:, 1] < 1.8e-5)
    )
    # 陰極表面 (矩形輪郭のすぐ外) から出発するので、厳密内部の点は無い
    # (輪郭上オフセット 1e-3·h の点は inside 判定から外れる場合もあるので緩く)
    assert np.all(out.absorbed)
    assert np.count_nonzero(inside) == 0


def test_pic_fn_emission_count_and_history():
    """PIC の FN 放出: マクロ数が I·t/(e·w) を再現し、履歴に fn_i が乗ること。"""
    w = 1e6  # マクロ重み (実電子数/マクロ)。毎ステップの放出マクロ数が
    # FN_MAX_MACROS_PER_STEP 未満に収まる値にする (上限系のテストは別関数)
    project = Project.model_validate(
        _plates_project(0.0, VOLT, fn={"edges": [3]})  # particles は使わない (下で pic を設定)
        | {
            "pic": {
                "n_macro": 100,
                "dt": 1e-13,
                "n_steps": 50,
                "frame_every": 100,
                "fn": {
                    "edges": [3],
                    "phi_ev": PHI,
                    # β=4 (βE=4e9 V/m) で J ~ 1e8 A/m² — 空間電荷の擾乱が小さく
                    # 電流がほぼ一定に保たれる範囲に抑える
                    "beta": 4.0,
                    "macro_weight": w,
                    "init_energy_ev": 0.1,
                },
            }
        }
    )
    sim = PicSimulation(project)
    for _ in range(50):
        sim.step()

    h = sim.history
    i_tot = np.array(h["fn_i"])
    assert np.all(i_tot > 0.0)
    # 電界は空間電荷が小さければほぼ一定 → I もほぼ一定 (FN は電界に指数的に
    # 敏感なので、わずかな空間電荷遮蔽による低下を見込んで 10% 許容)
    i0 = i_tot[0]
    assert i_tot[-1] == pytest.approx(i0, rel=0.10)
    # 放出マクロ数の合計 = Σ I·dt/(e·w) を端数 ±セグメント数以内で再現
    n_expected = float(np.sum(i_tot) * sim.dt / (QE * w))
    n_seg = len(sim._fn_surf.elem)
    assert abs(sim.fn_events - n_expected) <= n_seg
    assert h["fn_events"][-1] == sim.fn_events
    assert sim.fn_events > 0


def test_pic_fn_requires_weight_without_plasma():
    """初期プラズマ無しで macro_weight 未指定ならエラー。"""
    project = Project.model_validate(
        _plates_project(0.0, VOLT, fn={"edges": [3]})
        | {
            "pic": {
                "n_macro": 100,
                "dt": 1e-13,
                "n_steps": 10,
                "fn": {"edges": [3], "phi_ev": PHI, "beta": BETA},
            }
        }
    )
    with pytest.raises(ValueError, match="macro_weight"):
        PicSimulation(project)


def test_pic_fn_emission_cap_preserves_charge():
    """巨大な放出数 (小さい macro_weight) でもメモリを溢れさせず電荷を保存する。

    β=10 (J ~ 5e12 A/m²) + macro_weight=1 では 1 ステップの実電子数が ~1e13 に
    なる。マクロ数は FN_MAX_MACROS_PER_STEP に抑えられ、実効重みの引き上げで
    総電荷 Σw = ΣI·dt/e (床関数分) が保存されること。
    """
    from es_sim.pic import FN_MAX_MACROS_PER_STEP

    project = Project.model_validate(
        _plates_project(0.0, VOLT, fn={"edges": [3]})
        | {
            "pic": {
                "n_macro": 100,
                "dt": 1e-13,
                "n_steps": 2,
                "frame_every": 100,
                "fn": {
                    "edges": [3],
                    "phi_ev": PHI,
                    "beta": BETA,  # βE = 1e10 V/m → J ~ 5e12 A/m² (莫大な放出)
                    "macro_weight": 1.0,
                },
            }
        }
    )
    sim = PicSimulation(project)
    sim.step()  # MemoryError にならないこと

    el = sim.species["electron"]
    assert len(el.x) == FN_MAX_MACROS_PER_STEP  # 上限で抑えられている
    assert sim.fn_events == FN_MAX_MACROS_PER_STEP
    # 総電荷保存: Σw = このステップの放出実電子数 (床関数適用後の nominal 総数)
    i_step = sim.history["fn_i"][0]
    n_real_nominal = math.floor(i_step * sim.dt / (1.602176634e-19 * 1.0))
    assert float(el.w.sum()) == pytest.approx(n_real_nominal, rel=1e-9)
