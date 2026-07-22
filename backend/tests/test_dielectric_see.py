"""誘電体の二次電子放出 (SEE) のテスト (prompts/38)。

1. γ=1 の誘電体スラブへイオンビーム: 吸収イオン数 = SEE 電子生成数、
   SEE 電子はプラズマ側 (スラブ外) の要素に生成され速度が入射と逆向き
2. 電荷収支: γ=1 で Q_surf.sum() = Σw·(+q_ion) + Σw·(+e)。γ=0 ではイオン電荷のみ
3. γ=0 (未設定) では SEE なし、電子の誘電体吸収でも SEE なし (イオン誘起のみ)
"""

import numpy as np
import pytest

from es_sim.particles import QE, _locate_initial, _solid_elements
from es_sim.pic import PicSimulation
from es_sim.schema import Project

L = 0.01
X_SLAB = 0.006  # スラブ左面
N_STEPS = 30


def _build(gamma: float | None) -> PicSimulation:
    """左右 0V・上下鏡面反射 + 全高誘電体スラブ (x=0.006..0.008) の PIC。"""
    region = {
        "id": "slab",
        "type": "dielectric",
        "polygon": [[X_SLAB, 0], [0.008, 0], [0.008, L], [X_SLAB, L]],
        "eps_r": 4.0,
    }
    if gamma is not None:
        region["see_gamma"] = gamma
    project = Project.model_validate(
        {
            "geometry": {
                "domain": {"polygon": [[0, 0], [L, 0], [L, L], [0, L]]},
                "regions": [region],
                "boundaries": [
                    {"edges": [3], "voltage": 0.0},
                    {"edges": [1], "voltage": 0.0},
                ],
            },
            "mesh": {"size": 8e-4},
            "pic": {
                "dt": 1e-9,
                "n_steps": N_STEPS,
                "n_macro": 10,
                "frame_every": N_STEPS,
                "reflect_edges": [0, 2],
            },
        }
    )
    return PicSimulation(project)


def _seed_beam(sim: PicSimulation, species: str, n: int = 100) -> None:
    """+x に走る単色ビーム (w=1) を x=0.004 の縦線上に装荷する。"""
    y = np.linspace(0.001, 0.009, n)
    x = np.stack([np.full(n, 0.004), y], axis=1)
    sp = sim.species[species]
    sp.x = x
    sp.v = np.stack([np.full(n, 2.0e5), np.zeros(n), np.zeros(n)], axis=1)
    sp.w = np.ones(n)
    sp.elem = _locate_initial(sim.coeffs, x)


# ---- 1. γ=1: 吸収イオン数 = SEE 生成数、位置と速度の向き --------------------------


def test_dielectric_see_count_position_velocity():
    n = 100
    sim = _build(gamma=1.0)
    solid = _solid_elements(sim.project, sim.mesh)
    _seed_ions = _seed_beam(sim, "ion", n)

    el = sim.species["electron"]
    for _ in range(N_STEPS):
        sim.step()
        if len(el.x):
            # SEE 電子はプラズマ側 (スラブ外) の要素に生成される
            assert not np.any(solid[el.elem])
            # 速度は入射 (+x) と逆向き成分を持つ (この設定では厳密に -x 方向)
            assert np.all(el.v[:, 0] < 0.0)
        el = sim.species["electron"]

    io = sim.species["ion"]
    assert len(io.x) == 0                 # 全イオンがスラブで吸収
    assert io.wall_absorbed == n
    assert sim.see_events == n            # γ=1 なので吸収イオン数 = SEE 生成数
    assert sim.history["see_events"][-1] == n


# ---- 2. 電荷収支 -------------------------------------------------------------------


def test_dielectric_see_surface_charge_balance():
    n = 100

    # γ=1: Q_surf = Σw·(+q_ion) + Σw·(+e) (イオン電荷 + SEE 放出分の正帯電)
    sim = _build(gamma=1.0)
    _seed_beam(sim, "ion", n)
    sim.run_batch()
    assert sim.see_events == n
    expected = n * QE + n * QE  # イオン +e と SEE 放出 +e
    assert float(sim.q_surf.sum()) == pytest.approx(expected, rel=1e-12)

    # γ=0 (明示): 従来通りイオン電荷のみ
    sim0 = _build(gamma=0.0)
    _seed_beam(sim0, "ion", n)
    sim0.run_batch()
    assert sim0.see_events == 0
    assert float(sim0.q_surf.sum()) == pytest.approx(n * QE, rel=1e-12)


# ---- 3. γ 未設定は SEE なし・電子誘起は SEE なし ------------------------------------


def test_no_see_without_gamma_and_for_electrons():
    n = 100

    # γ 未設定 (既定 0): SEE は発生せず電子は一切生成されない (既存挙動不変)
    sim = _build(gamma=None)
    assert sim._solid_gamma is None  # 従来経路と完全一致する分岐
    _seed_beam(sim, "ion", n)
    history, _ = sim.run_batch()
    assert sim.see_events == 0
    assert np.all(np.asarray(history["n_e"]) == 0)
    assert float(sim.q_surf.sum()) == pytest.approx(n * QE, rel=1e-12)

    # γ=1 でも電子の誘電体吸収では SEE を発生させない (イオン誘起のみ)
    sim_e = _build(gamma=1.0)
    _seed_beam(sim_e, "electron", n)
    sim_e.run_batch()
    assert sim_e.see_events == 0
    assert sim_e.species["electron"].wall_absorbed == n
    # 電子吸収の表面電荷は負に蓄積される
    assert float(sim_e.q_surf.sum()) == pytest.approx(-n * QE, rel=1e-12)
