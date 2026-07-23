"""DSMC (定常ガス流れ) のテスト (prompts/54)。

1. 平衡箱: 密閉断熱箱 (全周拡散壁、壁温 = 初期温度) で n・T・p が初期値を保持し、
   流速 ≈ 0 (統計誤差内)
2. 自由分子流の流出: 左リザーバ → 右真空の無衝突チャネルで、チャネル内密度が
   リザーバの 1/2、平均流速が c̄/2 (半空間 Maxwell の解析値)
3. 圧力駆動チャネル流: p_in > p_out で定常の質量収支 (流入 ≈ 流出) が成り立ち、
   圧力が流れ方向に単調減少する
4. 非一様ガス場の MCC 結合: 定数場は一様指定とビット単位一致、
   密度2倍領域では電子衝突数がほぼ2倍
"""

import math

import numpy as np
import pytest

from es_sim.dsmc import AMU, KB, DsmcSimulation
from es_sim.mcc import GasField, MccModel
from es_sim.pic import PicSimulation
from es_sim.schema import Project

L = 0.02
H = 0.01
M_AR = 39.948 * AMU


def _project(dsmc: dict, mesh: float = 1.5e-3) -> Project:
    return Project.model_validate(
        {
            "geometry": {
                "domain": {"polygon": [[0, 0], [L, 0], [L, H], [0, H]]},
                "boundaries": [],
            },
            "mesh": {"size": mesh},
            "dsmc": dsmc,
        }
    )


def test_dsmc_equilibrium_box():
    """密閉箱 (壁温 = 初期温度 300K、10 Pa): n・T・p を保持し u ≈ 0。"""
    p0, t0 = 10.0, 300.0
    project = _project(
        {
            "init_pressure_pa": p0,
            "init_temperature_k": t0,
            "wall_temperature_k": t0,
            "n_particles": 30000,
            "n_steps": 600,
            "avg_steps": 300,
            "seed": 1,
        }
    )
    sim = DsmcSimulation(project)
    res = sim.run()

    n0 = p0 / (KB * t0)
    area = sim.area
    # 面積重み平均で比較 (セル単位は統計ノイズがある)
    n_mean = float(np.sum(res.n * area) / area.sum())
    t_mean = float(np.sum(res.t * res.n * area) / np.sum(res.n * area))
    p_mean = float(np.sum(res.p * area) / area.sum())
    assert n_mean == pytest.approx(n0, rel=0.03)
    assert t_mean == pytest.approx(t0, rel=0.03)
    assert p_mean == pytest.approx(p0, rel=0.05)
    # 平均流速はほぼゼロ (熱速度 ~350 m/s に対して 2% 未満)
    u_mag = float(np.linalg.norm(np.sum(res.u * (res.n * area)[:, None], axis=0) / np.sum(res.n * area)))
    assert u_mag < 0.02 * math.sqrt(2.0 * KB * t0 / M_AR) + 5.0


def test_dsmc_free_molecular_effusion():
    """無衝突 (d_ref を極小に) チャネル: 左リザーバ p0 → 右真空。

    定常では右向き半空間 Maxwell のビームになり、密度はリザーバの 1/2、
    平均流速 u_x = c̄/2 (c̄ = √(8kT/πm)) が解析値。
    """
    p0, t0 = 1.0, 300.0
    project = _project(
        {
            "gas": {"d_ref_m": 1e-15},  # 衝突を実質無効化
            "boundaries": [
                {"edges": [3], "type": "inlet", "pressure_pa": p0, "temperature_k": t0},
                {"edges": [1], "type": "outlet"},  # 真空
                {"edges": [0], "type": "symmetry"},
                {"edges": [2], "type": "symmetry"},
            ],
            "init_pressure_pa": p0 / 2.0,
            "init_temperature_k": t0,
            "n_particles": 40000,
            "n_steps": 1500,
            "avg_steps": 500,
            "seed": 2,
        }
    )
    sim = DsmcSimulation(project)
    res = sim.run()

    n_res = p0 / (KB * t0)
    area = sim.area
    n_mean = float(np.sum(res.n * area) / area.sum())
    assert n_mean == pytest.approx(0.5 * n_res, rel=0.05)

    c_bar = math.sqrt(8.0 * KB * t0 / (math.pi * M_AR))
    ux_mean = float(np.sum(res.u[:, 0] * res.n * area) / np.sum(res.n * area))
    assert ux_mean == pytest.approx(0.5 * c_bar, rel=0.05)
    # 質量収支: 定常なので流入 ≈ 流出
    assert res.outflow == pytest.approx(res.inflow, rel=0.05)


def test_dsmc_pressure_driven_channel():
    """圧力駆動チャネル (p_in = 20 Pa → p_out = 5 Pa): 質量収支と単調な圧力勾配。"""
    t0 = 300.0
    project = _project(
        {
            "boundaries": [
                {"edges": [3], "type": "inlet", "pressure_pa": 20.0, "temperature_k": t0},
                {"edges": [1], "type": "outlet", "pressure_pa": 5.0, "temperature_k": t0},
            ],
            "init_pressure_pa": 12.0,
            "init_temperature_k": t0,
            "wall_temperature_k": t0,
            "n_particles": 40000,
            "n_steps": 2000,
            "avg_steps": 600,
            "seed": 3,
        }
    )
    sim = DsmcSimulation(project)
    res = sim.run()

    # 定常の質量収支 (流入 ≈ 流出、統計誤差 10%)
    assert res.inflow > 0.0
    assert res.outflow == pytest.approx(res.inflow, rel=0.10)

    # x 方向 4 分割の平均圧力が単調減少し、端の値がリザーバ圧の間にある
    centroids = sim.mesh.nodes[sim.tris].mean(axis=1)
    area = sim.area
    p_slabs = []
    for i in range(4):
        sel = (centroids[:, 0] >= i * L / 4) & (centroids[:, 0] < (i + 1) * L / 4)
        p_slabs.append(float(np.sum(res.p[sel] * area[sel]) / area[sel].sum()))
    assert all(p_slabs[i] > p_slabs[i + 1] for i in range(3)), f"圧力が単調減少していない: {p_slabs}"
    assert 5.0 < p_slabs[-1] < p_slabs[0] < 20.0
    # 流れは +x 方向
    ux_mean = float(np.sum(res.u[:, 0] * res.n * area) / np.sum(res.n * area))
    assert ux_mean > 0.0


# ---- 非一様ガス場の MCC 結合 (Phase A、prompts/54) ------------------------------


def _mcc_project(pressure_pa: float) -> Project:
    """MCC つき小型 CCP (合成弾性断面積)。"""
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
            "pic": {
                "initial_plasma": {
                    "density": 1e14, "te_ev": 2.0, "ti_ev": 0.03,
                    "ion_mass_amu": 40.0, "seed": 5,
                },
                "n_macro": 4000,
                "dt": 5e-11,
                "n_steps": 20,
                "frame_every": 100,
                "mcc": {
                    "gas": {"name": "Ar", "pressure_pa": pressure_pa, "temperature_k": 300.0},
                    "electron_processes": [
                        {
                            "kind": "elastic", "label": "syn", "threshold_ev": 0.0,
                            "mass_ratio": 1.36e-5,
                            "energy_ev": [0.0, 100.0], "sigma_m2": [1e-19, 1e-19],
                        }
                    ],
                    "seed": 7,
                },
            },
        }
    )


def test_gas_field_constant_matches_uniform():
    """定数ガス場は一様指定とビット単位で一致する。"""
    p0 = 10.0
    n0 = p0 / (KB * 300.0)
    proj = _mcc_project(p0)

    sim_a = PicSimulation(proj)
    n_elems = len(sim_a.tris)
    field = GasField(n_g=np.full(n_elems, n0))
    sim_b = PicSimulation(_mcc_project(p0), gas_field=field)
    for _ in range(20):
        sim_a.step()
        sim_b.step()
    for name in ("electron", "ion"):
        assert np.array_equal(sim_a.species[name].x, sim_b.species[name].x)
        assert np.array_equal(sim_a.species[name].v, sim_b.species[name].v)
    assert sim_a.coll_e == sim_b.coll_e


def test_gas_field_density_ratio():
    """密度2倍の場では電子衝突数がほぼ2倍になる (統計比較)。"""
    p0 = 10.0
    n0 = p0 / (KB * 300.0)
    results = {}
    for factor in (1.0, 2.0):
        proj = _mcc_project(p0)
        sim = PicSimulation(proj)
        field = GasField(n_g=np.full(len(sim.tris), n0 * factor))
        sim2 = PicSimulation(_mcc_project(p0), gas_field=field)
        for _ in range(20):
            sim2.step()
        results[factor] = sim2.coll_e
    assert results[2.0] == pytest.approx(2.0 * results[1.0], rel=0.15)


# ---- サーバー統合 (/dsmc + use_dsmc_gas) ----------------------------------------


def test_dsmc_endpoint_and_pic_coupling():
    """POST /dsmc が動き、mcc.use_dsmc_gas の PIC がその場を使って起動する。"""
    from starlette.testclient import TestClient

    from es_sim import server as srv

    c = TestClient(srv.app)
    base_geom = {
        "geometry": {
            "domain": {"polygon": [[0, 0], [L, 0], [L, H], [0, H]]},
            "boundaries": [
                {"edges": [3], "type": "dirichlet", "voltage": 0.0},
                {"edges": [1], "type": "dirichlet", "voltage": 0.0},
            ],
        },
        "mesh": {"size": 1.5e-3},
    }
    dsmc_project = base_geom | {
        "dsmc": {
            "boundaries": [
                {"edges": [0], "type": "inlet", "pressure_pa": 10.0},
                {"edges": [2], "type": "outlet", "pressure_pa": 3.0},
            ],
            "init_pressure_pa": 6.0,
            "n_particles": 10000,
            "n_steps": 300,
            "avg_steps": 100,
            "seed": 4,
        }
    }
    r = c.post("/dsmc", json=dsmc_project)
    assert r.status_code == 200, r.text
    d = r.json()
    assert srv._last_dsmc is not None
    assert srv._last_dsmc["n_elems"] == len(d["n"])
    assert all(np.isfinite(d["p"]))

    # use_dsmc_gas の PIC がガス場付きで構築できる (同一 project → 同一メッシュ)
    pic_project = Project.model_validate(
        base_geom
        | {
            "pic": {
                "initial_plasma": {
                    "density": 1e14, "te_ev": 2.0, "ti_ev": 0.03,
                    "ion_mass_amu": 40.0, "seed": 5,
                },
                "n_macro": 2000,
                "dt": 5e-11,
                "n_steps": 5,
                "frame_every": 100,
                "mcc": {
                    "gas": {"name": "Ar", "pressure_pa": 6.0, "temperature_k": 300.0},
                    "electron_processes": [
                        {
                            "kind": "elastic", "label": "syn", "threshold_ev": 0.0,
                            "mass_ratio": 1.36e-5,
                            "energy_ev": [0.0, 100.0], "sigma_m2": [1e-19, 1e-19],
                        }
                    ],
                    "seed": 7,
                    "use_dsmc_gas": True,
                },
            }
        }
    )
    sim = PicSimulation(pic_project, srv._last_dsmc["field"])
    for _ in range(5):
        sim.step()
    assert np.all(np.isfinite(sim.species["electron"].v))


# ---- 線分指定の流入口 + sccm 流量指定 (prompts/55) ------------------------------


def test_dsmc_segment_inlet_classification():
    """p1-p2 線分指定で上辺の一部だけが流入口 (リザーバ) に分類される。"""
    from es_sim.dsmc import _B_RESERVOIR

    project = _project(
        {
            "boundaries": [
                # 上辺 (エッジ2) の左 1/4 だけを線分指定で inlet にする
                {"type": "inlet", "p1": [0.0, H], "p2": [L / 4, H], "pressure_pa": 10.0},
            ],
            "init_pressure_pa": 5.0,
            "n_particles": 5000,
            "n_steps": 10,
            "avg_steps": 5,
            "seed": 6,
        }
    )
    sim = DsmcSimulation(project)
    ts, loc = np.nonzero(sim.adjacency == -1)
    types = sim._b_type[ts, loc]
    res_sel = types == _B_RESERVOIR
    assert np.any(res_sel)
    # 分類されたエッジの中点はすべて上辺 y=H かつ x ≤ L/4 (+わずかな許容)
    tris = sim.tris
    nodes = sim.mesh.nodes
    n1 = tris[ts, (loc + 1) % 3]
    n2 = tris[ts, (loc + 2) % 3]
    mids = 0.5 * (nodes[n1] + nodes[n2])
    assert np.all(np.abs(mids[res_sel, 1] - H) < 1e-9)
    assert np.all(mids[res_sel, 0] <= L / 4 + 1e-6)
    # 上辺の右側 (x > L/4) は壁のまま = リザーバに分類されていない
    top_right = (np.abs(mids[:, 1] - H) < 1e-9) & (mids[:, 0] > L / 4 + 1e-6)
    assert not np.any(res_sel & top_right)


def test_dsmc_sccm_flow_inlet_mass_balance():
    """流量指定 (10 sccm) の流入口: 流入レートが換算値に一致し、定常で流出と釣り合う。"""
    from es_sim.dsmc import SCCM_TO_PER_S

    sccm = 10.0
    project = _project(
        {
            "gas": {"d_ref_m": 1e-15},  # 無衝突 (輸送を単純化)
            "boundaries": [
                {"edges": [3], "type": "inlet", "flow_sccm": sccm},
                {"edges": [1], "type": "outlet"},  # 真空排気
                {"edges": [0], "type": "symmetry"},
                {"edges": [2], "type": "symmetry"},
            ],
            "init_pressure_pa": 0.01,
            "init_temperature_k": 300.0,
            "n_particles": 30000,
            "n_steps": 1500,
            "avg_steps": 500,
            "seed": 7,
        }
    )
    sim = DsmcSimulation(project)
    res = sim.run()

    ndot_expected = sccm * SCCM_TO_PER_S  # ≈ 4.478e18 分子/s
    t_avg = 500 * sim.dt
    inflow_rate = res.inflow / t_avg
    # 流入は決定的 (端数持ち越し) なので換算値にほぼ厳密に一致する
    assert inflow_rate == pytest.approx(ndot_expected, rel=0.02)
    # 定常の質量収支 (統計誤差 10%)
    assert res.outflow == pytest.approx(res.inflow, rel=0.10)
    # 流れは +x 方向
    area = sim.area
    ux_mean = float(np.sum(res.u[:, 0] * res.n * area) / np.sum(res.n * area))
    assert ux_mean > 0.0


# ---- 軸対称 (rz、prompts/56) ----------------------------------------------------


def test_dsmc_rz_equilibrium_cylinder():
    """rz 密閉円筒 (軸 = 下辺 y=0、他は壁温 300K): n/T/p を保持し径方向にも一様。"""
    p0, t0 = 10.0, 300.0
    rr = 0.01
    project = Project.model_validate(
        {
            "coord": "rz",
            "geometry": {
                "domain": {"polygon": [[0, 0], [L, 0], [L, rr], [0, rr]]},
                "boundaries": [],
            },
            "mesh": {"size": 1.5e-3},
            "dsmc": {
                "init_pressure_pa": p0,
                "init_temperature_k": t0,
                "wall_temperature_k": t0,
                "n_particles": 30000,
                "n_steps": 600,
                "avg_steps": 300,
                "seed": 8,
            },
        }
    )
    sim = DsmcSimulation(project)
    res = sim.run()

    n0 = p0 / (KB * t0)
    vol = sim.vol
    n_mean = float(np.sum(res.n * vol) / vol.sum())
    t_mean = float(np.sum(res.t * res.n * vol) / np.sum(res.n * vol))
    assert n_mean == pytest.approx(n0, rel=0.03)
    assert t_mean == pytest.approx(t0, rel=0.03)
    # 径方向の一様性 (体積規格化 2πr̄A の検証): 内側半分と外側半分の平均密度が一致
    r_c = sim.mesh.nodes[sim.tris].mean(axis=1)[:, 1]
    inner = r_c < rr / 2
    n_in = float(np.sum(res.n[inner] * vol[inner]) / vol[inner].sum())
    n_out = float(np.sum(res.n[~inner] * vol[~inner]) / vol[~inner].sum())
    assert n_in == pytest.approx(n_out, rel=0.08)
    # 粒子が消えていない (軸は物理境界ではない)
    assert res.n_particles == pytest.approx(30000, rel=0.02)


def test_dsmc_rz_axial_effusion():
    """rz 無衝突円筒: 左端面リザーバ → 右真空。密度 = リザーバの 1/2、u_z = c̄/2。"""
    p0, t0 = 1.0, 300.0
    rr = 0.005
    project = Project.model_validate(
        {
            "coord": "rz",
            "geometry": {
                "domain": {"polygon": [[0, 0], [L, 0], [L, rr], [0, rr]]},
                "boundaries": [],
            },
            "mesh": {"size": 1.2e-3},
            "dsmc": {
                "gas": {"d_ref_m": 1e-15},  # 無衝突
                "boundaries": [
                    {"edges": [3], "type": "inlet", "pressure_pa": p0, "temperature_k": t0},
                    {"edges": [1], "type": "outlet"},
                    {"edges": [2], "type": "symmetry"},  # 外周 r=R は鏡面 (1D模擬)
                ],
                "init_pressure_pa": p0 / 2.0,
                "init_temperature_k": t0,
                "n_particles": 40000,
                "n_steps": 1500,
                "avg_steps": 500,
                "seed": 9,
            },
        }
    )
    sim = DsmcSimulation(project)
    res = sim.run()

    n_res = p0 / (KB * t0)
    vol = sim.vol
    n_mean = float(np.sum(res.n * vol) / vol.sum())
    assert n_mean == pytest.approx(0.5 * n_res, rel=0.05)
    c_bar = math.sqrt(8.0 * KB * t0 / (math.pi * M_AR))
    uz_mean = float(np.sum(res.u[:, 0] * res.n * vol) / np.sum(res.n * vol))
    assert uz_mean == pytest.approx(0.5 * c_bar, rel=0.05)
    assert res.outflow == pytest.approx(res.inflow, rel=0.07)


def test_dsmc_ws_progress():
    """/ws/dsmc: started → progress (100ステップごと) → done が届く (prompts/58)。"""
    from starlette.testclient import TestClient

    from es_sim import server as srv

    c = TestClient(srv.app)
    project = {
        "geometry": {
            "domain": {"polygon": [[0, 0], [L, 0], [L, H], [0, H]]},
            "boundaries": [],
        },
        "mesh": {"size": 2e-3},
        "dsmc": {
            "init_pressure_pa": 5.0,
            "n_particles": 5000,
            "n_steps": 350,
            "avg_steps": 100,
            "seed": 11,
        },
    }
    with c.websocket_connect("/ws/dsmc") as ws:
        ws.send_json({"cmd": "start", "project": project})
        started = ws.receive_json()
        assert started["type"] == "started"
        assert started["n_steps"] == 350
        assert started["n_particles"] > 0

        progress = 0
        while True:
            msg = ws.receive_json()
            if msg["type"] == "progress":
                progress += 1
                assert 0 < msg["step"] <= 350
                assert msg["n_particles"] > 0
            elif msg["type"] == "done":
                break
            else:
                raise AssertionError(f"想定外のメッセージ: {msg['type']}")
        assert progress == 3  # 100, 200, 300
        result = msg["result"]
        assert len(result["n"]) > 0
        assert all(np.isfinite(result["p"]))
    # done 後は保持スロットが更新されている
    assert srv._last_dsmc is not None
