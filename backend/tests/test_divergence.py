"""数値発散の検出と警告のテスト (prompts/57)。

発散した値 (NaN/Inf) をフレームに載せて送ると JSON として不正になり
フロントの解析が落ちるため、run_batch が明確な ValueError で止まること、
および衝突候補率・ガス場スパイクの事前警告を検証する。
"""

import math

import numpy as np
import pytest

from es_sim.mcc import GasField
from es_sim.pic import PicSimulation
from es_sim.schema import Project

L = 0.02
H = 0.01


def _project(pic_extra: dict | None = None, mcc: dict | None = None) -> Project:
    pic = {
        "initial_plasma": {
            "density": 1e14, "te_ev": 2.0, "ti_ev": 0.03,
            "ion_mass_amu": 40.0, "seed": 0,
        },
        "n_macro": 2000,
        "dt": 5e-11,
        "n_steps": 20,
        "frame_every": 100,
    } | (pic_extra or {})
    if mcc is not None:
        pic["mcc"] = mcc
    return Project.model_validate(
        {
            "geometry": {
                "domain": {"polygon": [[0, 0], [L, 0], [L, H], [0, H]]},
                "boundaries": [
                    {"edges": [3], "type": "dirichlet", "voltage": 0.0},
                    {"edges": [1], "type": "dirichlet", "voltage": 0.0},
                ],
            },
            "mesh": {"size": 1.5e-3},
            "pic": pic,
        }
    )


def test_run_batch_detects_nonfinite():
    """粒子状態に NaN が混入したら run_batch が明確なエラーで止まる。"""
    sim = PicSimulation(_project())
    for _ in range(3):
        sim.step()
    sim.species["electron"].v[0, 0] = np.nan  # 発散のシミュレート
    with pytest.raises(ValueError, match="数値発散"):
        sim.run_batch()


_SYN_ELASTIC = {
    "kind": "elastic", "label": "syn", "threshold_ev": 0.0,
    "mass_ratio": 1.36e-5,
    "energy_ev": [0.0, 100.0], "sigma_m2": [1e-19, 1e-19],
}


def test_warning_high_collision_probability():
    """衝突候補率 > 0.5 (高圧 + 粗い dt) で警告が付く。"""
    mcc = {
        "gas": {"name": "Ar", "pressure_pa": 5000.0, "temperature_k": 300.0},
        "electron_processes": [_SYN_ELASTIC],
        "seed": 0,
    }
    sim = PicSimulation(_project({"dt": 1e-9}, mcc=mcc))
    assert any("衝突候補率" in w for w in sim.warnings)
    # 通常条件では警告なし
    mcc_low = mcc | {"gas": {"name": "Ar", "pressure_pa": 5.0, "temperature_k": 300.0}}
    sim2 = PicSimulation(_project(mcc=mcc_low))
    assert not any("衝突候補率" in w for w in sim2.warnings)


def test_warning_gas_field_spike():
    """ガス場の最大密度が中央値の100倍を超えると警告が付く。"""
    mcc = {
        "gas": {"name": "Ar", "pressure_pa": 5.0, "temperature_k": 300.0},
        "electron_processes": [_SYN_ELASTIC],
        "seed": 0,
    }
    base = PicSimulation(_project(mcc=mcc))
    n_elems = len(base.tris)
    n_g = np.full(n_elems, 1e20)
    n_g[0] = 5e22  # スパイク (500倍)
    sim = PicSimulation(_project(mcc=mcc), gas_field=GasField(n_g=n_g))
    assert any("最大密度" in w for w in sim.warnings)
