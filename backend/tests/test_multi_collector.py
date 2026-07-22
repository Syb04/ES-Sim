"""複数コレクタ対応のテスト (prompts/36)。

1. 決定的ケース (test_iedf と同じ) を2コレクタで実行し、全面側は全イオン・
   中央半分側は対応するイオンのみ記録 (単数時代と同値)
2. 後方互換: 旧単数形 collector が collectors=[1個] に正規化され、
   done に単数キーも出ること (WS)
3. 9個指定で ValidationError
"""

import json

import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import es_sim.server as server
from es_sim.particles import _locate_initial
from es_sim.pic import PicSimulation
from es_sim.schema import Project

L = 0.01
HGT = 0.01
V_CATHODE = -100.0
X0 = 0.002
E_EXPECTED = (V_CATHODE * X0 / L) - V_CATHODE  # = 80 eV


def _project(pic_extra: dict) -> Project:
    n_steps = 500
    pic = {
        "dt": 2e-9,
        "n_steps": n_steps,
        "n_macro": 10,
        "frame_every": n_steps,
        "avg_steps": n_steps,
        **pic_extra,
    }
    return Project.model_validate(
        {
            "geometry": {
                "domain": {"polygon": [[0, 0], [L, 0], [L, HGT], [0, HGT]]},
                "boundaries": [
                    {"edges": [3], "voltage": 0.0},
                    {"edges": [1], "voltage": V_CATHODE},
                    {"edges": [0, 2], "type": "symmetry"},
                ],
            },
            "mesh": {"size": 8e-4},
            "pic": pic,
        }
    )


def _seed_ions(sim: PicSimulation, y: np.ndarray) -> None:
    n = len(y)
    x = np.stack([np.full(n, X0), y], axis=1)
    io = sim.species["ion"]
    io.x = x
    io.v = np.zeros((n, 3))
    io.w = np.ones(n)
    io.elem = _locate_initial(sim.coeffs, x)


# ---- 1. 2コレクタ (陰極全面 + 中央半分) -------------------------------------------


def test_two_collectors_full_and_center_half():
    n = 10
    y = np.linspace(0.001, 0.009, n)
    y1, y2 = 0.25 * HGT, 0.75 * HGT
    sim = PicSimulation(
        _project(
            {
                "collectors": [
                    {"p1": [L, 0.0], "p2": [L, HGT], "label": "full"},
                    {"p1": [L, y1], "p2": [L, y2], "label": "half"},
                ]
            }
        )
    )
    _seed_ions(sim, y)
    sim.run_batch()

    results = sim.collector_results
    assert results is not None and len(results) == 2
    full, half = results

    # 全面側: 全イオンが記録され、エネルギー・角度は単数時代と同値
    assert full["count"] == n
    assert not full["truncated"]
    assert np.allclose(full["energies_ev"], E_EXPECTED, rtol=0.03)
    assert np.all(np.abs(full["angles_deg"]) < 5.0)
    assert full["total_weight"] == pytest.approx(float(n), rel=1e-12)

    # 中央半分側: 線分区間内の y のイオンのみ (同時該当は両方に記録される)
    expected_half = int(np.count_nonzero((y >= y1) & (y <= y2)))
    assert 0 < expected_half < n
    assert half["count"] == expected_half
    assert np.allclose(half["energies_ev"], E_EXPECTED, rtol=0.03)
    assert half["total_weight"] == pytest.approx(float(expected_half), rel=1e-12)

    # 旧属性 collector_result は先頭コレクタのエイリアス
    assert sim.collector_result is results[0]


# ---- 2. 後方互換 (旧単数形の正規化 + WS done の単数キー) ---------------------------


def test_single_collector_normalized_and_ws_done_keys():
    # スキーマ正規化: collector (単数) → collectors=[1個]、collector は None
    project = _project({"collector": {"p1": [L, 0.0], "p2": [L, HGT]}})
    assert project.pic.collector is None
    assert len(project.pic.collectors) == 1
    assert project.pic.collectors[0].p1 == (L, 0.0)

    # WS done: collectors (1個) と互換の単数キー collector の両方が出る
    server._last_sim = None
    client = TestClient(server.app)
    ws_project = Project.model_validate(
        {
            "geometry": {
                "domain": {"polygon": [[0, 0], [L, 0], [L, HGT], [0, HGT]]},
                "boundaries": [{"edges": [0, 1, 2, 3], "voltage": 0.0}],
            },
            "mesh": {"size": 1e-3},
            "pic": {
                "dt": 1e-9,
                "n_steps": 10,
                "n_macro": 10,
                "frame_every": 10,
                "collector": {"p1": [L, 0.0], "p2": [L, HGT]},
            },
        }
    )
    with client.websocket_connect("/ws/pic") as ws:
        ws.send_text(json.dumps({"cmd": "start", "project": ws_project.model_dump(mode="json")}))
        while True:
            msg = ws.receive_json()
            assert msg["type"] != "error", msg.get("detail")
            if msg["type"] == "done":
                break
    assert "collectors" in msg and len(msg["collectors"]) == 1
    assert "collector" in msg  # 1個のときのみ互換キーが併記される
    assert msg["collector"] == msg["collectors"][0]
    assert msg["collector"]["count"] == 0  # 粒子なしなので記録 0
    server._last_sim = None


# ---- 3. 最大数の検査 ---------------------------------------------------------------


def test_more_than_eight_collectors_rejected():
    cols = [{"p1": [L, 0.0], "p2": [L, HGT]} for _ in range(9)]
    with pytest.raises(ValidationError, match="8"):
        _project({"collectors": cols})
    # 8個ちょうどは通る
    project = _project({"collectors": cols[:8]})
    assert len(project.pic.collectors) == 8
