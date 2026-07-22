"""誘電体の表面電荷蓄積 + 場フィードバックのテスト (prompts/25)。

1. 保存則: 吸収粒子の Σ(w·q) と Q_surf.sum()・diag の surf_q が一致
2. 場フィードバック (定量): 両端接地の1D相当ストリップで、蓄積後の表面電位が
   解析解 V = σ·a·b/(ε0·(a+b)) と 10% 以内で一致
3. 帯電の単調性: 電子ビーム連続入射で surf_q が単調に負へ蓄積し、φ_min が低下
"""

import math

import numpy as np
import pytest

from es_sim.fem import EPS0
from es_sim.particles import ME, QE, _locate_initial
from es_sim.pic import PicSimulation
from es_sim.schema import Project

L = 0.01   # ストリップ幅 (x) [m]
HGT = 0.01  # ストリップ高さ (y) [m]


def _slab_project(x1: float, x2: float, pic: dict) -> Project:
    """両端接地 (0V/0V)・上下鏡面反射の矩形 + 全高の誘電体スラブ (εr=1 相当)。"""
    return Project.model_validate(
        {
            "geometry": {
                "domain": {"polygon": [[0, 0], [L, 0], [L, HGT], [0, HGT]]},
                "regions": [
                    {
                        "id": "slab",
                        "type": "dielectric",
                        "polygon": [[x1, 0], [x2, 0], [x2, HGT], [x1, HGT]],
                        "eps_r": 1.0,  # εr=1 相当の薄い誘電体 (1D 解析解と直接比較)
                    }
                ],
                "boundaries": [
                    {"edges": [3], "voltage": 0.0},
                    {"edges": [1], "voltage": 0.0},
                ],
            },
            "mesh": {"size": 8e-4},
            "pic": {"reflect_edges": [0, 2], **pic},  # 上下は鏡面反射
        }
    )


def _seed_beam(sim: PicSimulation, n: int, x0: float, vx: float, w: float) -> None:
    """電子ビームを x = x0 の縦線上に等間隔で装荷する (+x 方向の単色ビーム)。"""
    y = (np.arange(n) + 0.5) * HGT / n
    x = np.stack([np.full(n, x0), y], axis=1)
    el = sim.species["electron"]
    el.x = x
    el.v = np.stack([np.full(n, vx), np.zeros(n), np.zeros(n)], axis=1)
    el.w = np.full(n, w)
    el.elem = _locate_initial(sim.coeffs, x)


# ---- 1. 保存則 -----------------------------------------------------------------


def test_surface_charge_conservation():
    """吸収された電子の総電荷 Σ(w·q) = Q_surf.sum() = diag の surf_q (rel 1e-12)。"""
    x_slab = 0.006
    n, w = 200, 1.0
    project = _slab_project(
        x_slab, 0.008,
        {"dt": 1e-9, "n_steps": 60, "n_macro": 10, "frame_every": 60},
    )
    sim = PicSimulation(project)
    _seed_beam(sim, n, x0=0.003, vx=2.0e5, w=w)

    history, frames = sim.run_batch()

    # 全電子がスラブ表面で吸収されている
    assert history["n_e"][-1] == 0
    assert sim.species["electron"].wall_absorbed == n

    expected = n * w * (-QE)  # Σ(w·q) [C/m]
    total = float(sim.q_surf.sum())
    assert total == pytest.approx(expected, rel=1e-12)
    # 診断 (履歴・フレーム) とも一致
    assert history["surf_q"][-1] == pytest.approx(expected, rel=1e-12)
    assert frames[-1]["diag"]["surf_q"] == pytest.approx(expected, rel=1e-12)

    # 電荷はスラブ左面近傍 (進入要素の節点 = 表面から高々1セル) に載る
    charged = np.nonzero(sim.q_surf != 0.0)[0]
    assert len(charged) > 0
    assert np.all(sim.mesh.nodes[charged, 0] >= x_slab - 1e-9)
    assert np.all(sim.mesh.nodes[charged, 0] <= x_slab + 2 * 8e-4)
    assert np.all(sim.q_surf[charged] < 0.0)  # 電子なので全て負


# ---- 2. 場フィードバック (定量) --------------------------------------------------


def test_surface_potential_matches_1d_analytic():
    """位置 d の表面に σ を蓄積させたとき、表面電位が 1D 解析解
    V = σ·a·b/(ε0·(a+b)) と 10% 以内で一致する (a, b は両接地面までの距離)。"""
    a = 0.004          # 左接地面 (x=0) からスラブ表面までの距離
    b = L - a          # スラブ表面から右接地面 (x=L) までの距離
    n = 400
    v_target = 30.0    # 蓄積後の表面電位の目安 [V]
    # V = (n·w·QE/h)·a·b/(ε0(a+b)) から逆算したマクロ重み
    w = v_target * HGT * EPS0 * (a + b) / (QE * a * b) / n
    vx = math.sqrt(2.0 * 100.0 * QE / ME)  # 100 eV (障壁 ~30 V を越えて到達する)

    project = _slab_project(
        a, a + 8e-4,  # 1セル厚の薄いスラブ (εr=1)
        {"dt": 2e-11, "n_steps": 100, "n_macro": 10, "frame_every": 100},
    )
    sim = PicSimulation(project)
    _seed_beam(sim, n, x0=0.003, vx=vx, w=w)

    # 吸収が完了するまで進め、完了後の φ (表面電荷のみの場) を取得する
    phi = None
    for _ in range(100):
        phi = sim.step()
        if len(sim.species["electron"].x) == 0:
            phi = sim.step()  # 吸収完了後の場を1ステップ分解き直す
            break
    assert len(sim.species["electron"].x) == 0, "ビームが吸収しきれていません"

    # 実際に蓄積された電荷から面密度 σ を求める (保存則も同時に確認)
    q_total = float(sim.q_surf.sum())
    assert q_total == pytest.approx(n * w * (-QE), rel=1e-12)
    sigma = q_total / HGT  # [C/m^2]
    v_analytic = sigma * a * b / (EPS0 * (a + b))

    # スラブ左面 (x = a) 上の節点電位の平均と比較
    on_surface = np.abs(sim.mesh.nodes[:, 0] - a) < 1e-9
    assert np.count_nonzero(on_surface) >= 3
    v_measured = float(phi[on_surface].mean())

    assert v_analytic < 0.0  # 電子なので負に帯電
    assert v_measured == pytest.approx(v_analytic, rel=0.10)


# ---- 3. 帯電の単調性 --------------------------------------------------------------


def test_continuous_beam_charges_monotonically():
    """電子ビーム連続入射で surf_q が単調に負へ蓄積し、φ_min が低下する。"""
    n_steps = 200
    project = _slab_project(
        0.004, 0.0048,
        {
            "dt": 2e-11,
            "n_steps": n_steps,
            "n_macro": 10,
            "frame_every": n_steps,
            "injection": {
                "emitter": {
                    "kind": "line",
                    "p1": [0.002, 0.001],
                    "p2": [0.002, 0.009],
                    "n": 10,
                    "energy_ev": 100.0,
                    "direction_deg": 0.0,  # スラブへ向けて +x
                },
                "species": "electron",
                "current_a_per_m": 1e-3,
            },
        },
    )
    sim = PicSimulation(project)
    history, _ = sim.run_batch()

    sq = np.asarray(history["surf_q"])
    # 到達前は 0、以後は単調非増加 (電子なので負へ蓄積)
    assert sq[0] == 0.0
    assert np.all(np.diff(sq) <= 1e-30)
    assert sq[-1] < 0.0
    # 定常入射なので後半も蓄積が続く (途中で止まらない)
    assert sq[-1] < sq[n_steps // 2] < 0.0

    # 表面帯電により φ_min が低下する (ビームが定常になった後の比較)
    phi_min = np.asarray(history["phi_min"])
    assert phi_min[-1] < phi_min[n_steps // 4]
    assert phi_min[-1] < 0.0
