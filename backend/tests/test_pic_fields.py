"""PIC 結果フィールドの時間平均出力のテスト (prompts/26)。

1. 平行平板 + 初期プラズマ (衝突なし): phi 平均が有限で境界値と整合、
   n_e/n_i が密度アキュムレータと一致、Te が初期温度のオーダー (0.5×〜2×)
2. MCC 電離あり: ion_rate の総和 × 体積 × 時間 ≒ 電離イベント数 × 重み (rel 5%)
3. avg_steps 指定 / None (25% 既定) の両方で動作
"""

import numpy as np

from es_sim.pic import PicSimulation
from es_sim.schema import Project

DENSITY = 1.0e14  # [m^-3]


# ---- 1. 平行平板 + 初期プラズマ (衝突なし) ---------------------------------------


def test_fields_parallel_plates_collisionless():
    te0 = 2.0  # 初期電子温度 [eV]
    # 平均区間は全 40 ステップ。長時間の壁損失後は残留電子が両極性ポテンシャル井戸で
    # 加速され Te (運動論的温度) が物理的に上昇するため、初期温度と比較する本テスト
    # では過渡の浅い短時間平均を使う
    avg_steps = 40
    project = Project.model_validate(
        {
            "geometry": {
                "domain": {"polygon": [[0, 0], [0.02, 0], [0.02, 0.01], [0, 0.01]]},
                "boundaries": [
                    {"edges": [3], "voltage": 0.0},
                    {"edges": [1], "voltage": 0.0},
                ],
            },
            "mesh": {"size": 1.2e-3},
            "pic": {
                "initial_plasma": {
                    "density": DENSITY,
                    "te_ev": te0,
                    "ti_ev": 0.03,
                    "ion_mass_amu": 40.0,
                    "seed": 2,
                },
                "n_macro": 4000,
                "dt": 5e-10,
                "n_steps": 40,
                "frame_every": 40,
                "avg_steps": avg_steps,
            },
        }
    )
    sim = PicSimulation(project)
    sim.run_batch()
    fields = sim.fields

    assert fields is not None
    assert fields["avg_steps"] == avg_steps
    n_nodes, n_elems = sim.n_nodes, len(sim.tris)
    assert len(fields["phi"]) == n_nodes
    assert len(fields["e_abs"]) == n_elems
    for key in ("phi", "e_abs", "n_e", "n_i", "te_ev", "ion_rate"):
        assert np.all(np.isfinite(fields[key])), f"{key} に非有限値"

    # phi 平均は Dirichlet 境界 (0V 固定) と整合する
    fixed = np.fromiter(sim.mesh.dirichlet.keys(), dtype=np.int64)
    assert np.allclose(fields["phi"][fixed], 0.0, atol=1e-12)
    # プラズマがあるので中央電位は正 (シース形成)
    assert np.max(fields["phi"]) > 0.0

    # n_e / n_i は密度アキュムレータと一致 (同じ積算から計算される)
    dens = sim.averaged_density()
    assert np.array_equal(fields["n_e"], dens["electron"])
    assert np.array_equal(fields["n_i"], dens["ion"])
    assert np.max(fields["n_e"]) > 0.0 and np.max(fields["n_i"]) > 0.0

    # Te (重み付き平均) が初期温度のオーダー (0.5×〜2×) にある
    w_node = fields["n_e"] * sim._node_area  # ∝ 積算重み
    te_mean = float(np.sum(fields["te_ev"] * w_node) / np.sum(w_node))
    assert 0.5 * te0 <= te_mean <= 2.0 * te0
    # 粒子なし節点 (あれば) は 0
    assert np.all(fields["te_ev"][fields["n_e"] == 0.0] == 0.0)

    # 衝突なしなので電離レートは全域 0
    assert np.all(fields["ion_rate"] == 0.0)
    assert np.all(fields["e_abs"] >= 0.0) and np.max(fields["e_abs"]) > 0.0


# ---- 2. MCC 電離あり: ion_rate の体積積分 ----------------------------------------


def test_ion_rate_volume_integral_matches_event_count():
    """Σ(ion_rate × 節点集中面積) × 平均時間 = 電離イベント数 × マクロ重み (rel 5%)。"""
    n_macro = 2000
    n_steps = 60
    project = Project.model_validate(
        {
            "geometry": {
                "domain": {"polygon": [[0, 0], [0.01, 0], [0.01, 0.01], [0, 0.01]]},
                "boundaries": [{"edges": [0, 1, 2, 3], "voltage": 0.0}],
            },
            "mesh": {"size": 8e-4},
            "pic": {
                "initial_plasma": {
                    "density": DENSITY,
                    "te_ev": 10.0,  # 閾値 5 eV を超える電子を十分含む
                    "ti_ev": 0.03,
                    "ion_mass_amu": 40.0,
                    "seed": 5,
                },
                "n_macro": n_macro,
                "dt": 5e-10,
                "n_steps": n_steps,
                "frame_every": n_steps,
                "avg_steps": n_steps,  # 全ステップを平均区間にする (イベント数と直接比較)
                "mcc": {
                    "gas": {"name": "Ar", "pressure_pa": 100.0, "temperature_k": 300.0},
                    "electron_processes": [
                        {
                            "kind": "ionization",
                            "label": "synthetic ionization",
                            "threshold_ev": 5.0,
                            "energy_ev": [5.0, 5.0 + 1e-6, 1000.0],
                            "sigma_m2": [0.0, 2.0e-20, 2.0e-20],
                        }
                    ],
                    "ion_processes": [],
                    "seed": 9,
                },
            },
        }
    )
    sim = PicSimulation(project)
    history, _ = sim.run_batch()
    fields = sim.fields

    events = int(history["ion_events"][-1])  # 平均区間 = 全ステップなので累計と一致
    assert events > 100, "電離イベントが少なすぎます"
    assert fields is not None and fields["avg_steps"] == n_steps

    # 電離で生まれた粒子の重みは親電子と同じ = 初期一様重み w0
    w0 = DENSITY * float(sim.area.sum()) / n_macro
    expected = events * w0

    avg_time = fields["avg_steps"] * sim.dt
    measured = float(np.sum(fields["ion_rate"] * sim._node_area)) * avg_time
    assert abs(measured - expected) / expected < 0.05
    assert np.max(fields["ion_rate"]) > 0.0


# ---- 3. avg_steps 指定 / None (25% 既定) ------------------------------------------


def _empty_pic_project(n_steps: int, avg_steps: int | None) -> Project:
    pic: dict = {
        "dt": 1e-9,
        "n_steps": n_steps,
        "n_macro": 10,
        "frame_every": n_steps,
    }
    if avg_steps is not None:
        pic["avg_steps"] = avg_steps
    return Project.model_validate(
        {
            "geometry": {
                "domain": {"polygon": [[0, 0], [0.01, 0], [0.01, 0.01], [0, 0.01]]},
                "boundaries": [{"edges": [0, 1, 2, 3], "voltage": 0.0}],
            },
            "mesh": {"size": 1e-3},
            "pic": pic,
        }
    )


def test_avg_steps_default_is_last_quarter():
    """avg_steps=None なら全ステップの最後の 25% を平均する。"""
    sim = PicSimulation(_empty_pic_project(n_steps=40, avg_steps=None))
    sim.run_batch()
    assert sim.fields is not None
    assert sim.fields["avg_steps"] == 10  # 40 // 4
    # 粒子なしなので全フィールドはゼロ
    assert np.all(sim.fields["phi"] == 0.0)
    assert np.all(sim.fields["n_e"] == 0.0)
    assert np.all(sim.fields["te_ev"] == 0.0)
    assert np.all(sim.fields["ion_rate"] == 0.0)


def test_avg_steps_explicit():
    """avg_steps を明示指定した場合はそのステップ数だけ平均する。"""
    sim = PicSimulation(_empty_pic_project(n_steps=40, avg_steps=15))
    sim.run_batch()
    assert sim.fields is not None
    assert sim.fields["avg_steps"] == 15
