"""RF 1周期の位相分解データ出力のテスト (prompts/28)。

1. RF 付き小ケースで cycle が返り、寸法・period_s が正しく、RF 電極近傍節点の
   位相分解 φ がビン間で振動して振幅が RF 振幅のオーダー (0.2×〜1.2×)
2. 位相平均の整合: cycle.phi の全ビン平均が fields.phi と数%以内で一致
3. RF なし・phase_bins=0 では cycle が省略される
"""

import numpy as np

from es_sim.pic import PicSimulation
from es_sim.schema import Project

FREQ = 12.5e6      # RF 周波数 [Hz] (周期 8e-8 s = dt の整数倍になるよう選ぶ)
AMP = 50.0         # RF 振幅 [V]


def _rf_project(pic: dict, with_rf: bool = True) -> Project:
    left_bc: dict = {"edges": [3], "voltage": 0.0}
    if with_rf:
        left_bc["voltage_rf"] = {"amplitude": AMP, "freq_hz": FREQ, "phase_deg": 0.0}
    return Project.model_validate(
        {
            "geometry": {
                "domain": {"polygon": [[0, 0], [0.02, 0], [0.02, 0.01], [0, 0.01]]},
                "boundaries": [left_bc, {"edges": [1], "voltage": 0.0}],
            },
            "mesh": {"size": 1.2e-3},
            "pic": pic,
        }
    )


# ---- 1. 寸法・period_s・φ の位相依存 --------------------------------------------


def test_cycle_shape_and_phase_dependence():
    """RF 電極 (左辺) 節点の位相分解 φ の振幅が RF 振幅のオーダーにあること。

    粒子なしの真空ケース: φ は Dirichlet 境界の V(t) = A sin(2πft) を厳密に追う。
    dt = 1e-9, 周期 = 80 ステップ、平均区間 160 ステップ (ちょうど2周期)。
    """
    bins = 40
    n_steps, avg_steps, dt = 170, 160, 1e-9
    project = _rf_project(
        {
            "dt": dt,
            "n_steps": n_steps,
            "n_macro": 10,
            "frame_every": n_steps,
            "avg_steps": avg_steps,
            "phase_bins": bins,
        }
    )
    sim = PicSimulation(project)
    assert not sim.warnings  # 平均区間 (2周期) は 1 周期以上あるので警告なし
    sim.run_batch()
    cycle = sim.cycle

    assert cycle is not None
    assert cycle["bins"] == bins
    assert cycle["period_s"] == 1.0 / FREQ
    n_nodes = sim.n_nodes
    for key in ("phi", "n_e", "n_i"):
        assert cycle[key].shape == (bins, n_nodes)
        assert np.all(np.isfinite(cycle[key]))
    # 平均区間 = ちょうど 2 周期なので全ビンにステップが割り当てられる
    assert np.all(sim._cycle_count > 0)

    # RF 電極 (左辺 x=0) 上の節点: 位相分解 φ がビン間で振動し、
    # 振幅 (max-min)/2 が RF 振幅のオーダー (0.2×〜1.2×)
    on_rf = np.nonzero(sim.mesh.nodes[:, 0] < 1e-9)[0]
    assert len(on_rf) >= 3
    phi_node = cycle["phi"][:, on_rf[0]]
    amp = 0.5 * (phi_node.max() - phi_node.min())
    assert 0.2 * AMP <= amp <= 1.2 * AMP
    # 正弦波形: ビン平均はほぼ 0 (DC 分なし)
    assert abs(phi_node.mean()) < 0.05 * AMP

    # 粒子スナップショット: bins 個のエントリ (粒子なしなので空)
    for name in ("electron", "ion"):
        assert len(cycle["particles"][name]) == bins
        assert all(len(s) == 0 for s in cycle["particles"][name])


# ---- 2. 位相平均の整合 (プラズマあり) --------------------------------------------


def test_cycle_mean_matches_fields_phi():
    """cycle.phi の全ビン平均が fields.phi と数%以内で一致 (プラズマあり CCP)。

    平均区間 = ちょうど 1 周期 (160 ステップ, 各ビン 4 ステップ) にして
    ビンごとのステップ数を均等にする。
    """
    dt = 5e-10  # 周期 8e-8 s = 160 ステップ
    n_steps, avg_steps = 200, 160
    project = _rf_project(
        {
            "initial_plasma": {
                "density": 1.0e14,
                "te_ev": 2.0,
                "ti_ev": 0.03,
                "ion_mass_amu": 40.0,
                "seed": 2,
            },
            "n_macro": 2000,
            "dt": dt,
            "n_steps": n_steps,
            "frame_every": n_steps,
            "avg_steps": avg_steps,
        }
    )
    sim = PicSimulation(project)
    sim.run_batch()
    fields, cycle = sim.fields, sim.cycle

    assert fields is not None and cycle is not None
    # 各ビンほぼ均等 (4 ステップ ±1: 時刻の浮動小数点丸めでビン境界が僅かにずれ得る)
    assert int(sim._cycle_count.sum()) == avg_steps
    assert np.all(sim._cycle_count >= 3) and np.all(sim._cycle_count <= 5)

    phi_bin_mean = cycle["phi"].mean(axis=0)  # 全ビン平均 (節点ごと)
    ref = np.max(np.abs(fields["phi"]))
    assert ref > 1.0  # プラズマ電位が立っている
    # 全節点で数%以内 (RF 振幅で規格化した最大差)
    assert np.max(np.abs(phi_bin_mean - fields["phi"])) < 0.03 * ref

    # 密度も同様に整合する
    ne_bin_mean = cycle["n_e"].mean(axis=0)
    ne_ref = np.max(fields["n_e"])
    assert ne_ref > 0.0
    assert np.max(np.abs(ne_bin_mean - fields["n_e"])) < 0.03 * ne_ref

    # 最後の1周期の粒子スナップショット: 全ビンに ≤1000 点の位置がある
    for name in ("electron", "ion"):
        snaps = cycle["particles"][name]
        assert len(snaps) == 40
        assert all(0 < len(s) <= 1000 for s in snaps)
        for s in snaps:
            assert np.asarray(s).shape[1] == 2


# ---- 3. RF なし・phase_bins=0 では省略 --------------------------------------------


def test_cycle_disabled_without_rf_or_bins():
    base = {"dt": 1e-9, "n_steps": 20, "n_macro": 10, "frame_every": 20}

    # RF なし → cycle 無効
    sim = PicSimulation(_rf_project(dict(base), with_rf=False))
    sim.run_batch()
    assert sim.cycle is None

    # RF あり + phase_bins=0 → cycle 無効
    sim = PicSimulation(_rf_project({**base, "phase_bins": 0}))
    sim.run_batch()
    assert sim.cycle is None

    # 平均区間 < 1 周期なら started 用の警告が付く (実行前に判定される)
    sim = PicSimulation(_rf_project({**base, "avg_steps": 10}))
    assert any("位相" in w and "周期" in w for w in sim.warnings)
