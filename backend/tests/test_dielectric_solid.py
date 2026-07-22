"""誘電体領域への粒子侵入防止のテスト (prompts/24)。

領域種別ごとの粒子透過性:
  conductor = 穴 (従来通り吸収)、dielectric = 固体 (表面吸収)、charge = 透過。

1. trace: 誘電体ブロックに向けて発射した粒子が absorbed になり、
   最終位置がブロック輪郭の近傍 (メッシュサイズ程度) にあること
2. trace: charge 領域は従来通り通過すること
3. PIC: 誘電体ブロックありで 100 ステップ実行し、全ステップで誘電体要素内に
   粒子が存在しないこと・壁カウンタに計上されること
4. PIC: 初期装荷が誘電体要素を避けること・重みが装荷可能面積基準であること
"""

import numpy as np

from es_sim.fem import solve
from es_sim.meshing import generate_mesh
from es_sim.particles import _locate_initial, _solid_elements, trace
from es_sim.pic import PicSimulation
from es_sim.schema import Project

D, H, V1 = 0.1, 0.05, 100.0  # 平行平板: 幅 D [m], 高さ H [m], 右側電位 V1 [V]
MESH_SIZE = 0.005
BLOCK = [[0.05, 0.01], [0.07, 0.01], [0.07, 0.04], [0.05, 0.04]]  # 中央のブロック


def _trace_project(region_type: str) -> Project:
    """左 0V・右 V1 の平行平板 + 中央ブロック (dielectric / charge) + 電子ビーム。"""
    return Project.model_validate(
        {
            "geometry": {
                "domain": {"polygon": [[0, 0], [D, 0], [D, H], [0, H]]},
                "regions": [
                    {
                        "id": "block",
                        "type": region_type,
                        "polygon": BLOCK,
                        "eps_r": 4.0,
                    }
                ],
                "boundaries": [
                    {"edges": [3], "voltage": 0.0},
                    {"edges": [1], "voltage": V1},
                ],
            },
            "mesh": {"size": MESH_SIZE},
            "particles": {
                "species": {"preset": "electron"},
                "emitter": {
                    "kind": "point",
                    "p1": [0.01, 0.025],
                    "n": 1,
                    "energy_ev": 100.0,
                    "direction_deg": 0.0,  # ブロックの中心へ向けて +x に直進
                },
                "dt": None,
                "n_steps": 3000,
                "save_every": 5,
            },
        }
    )


# ---- 1. trace: 誘電体ブロックで吸収 --------------------------------------------


def test_trace_absorbed_at_dielectric_surface():
    project = _trace_project("dielectric")
    mesh = generate_mesh(project)
    sol = solve(project, mesh)
    result = trace(project, mesh, sol)

    assert result.absorbed[0]
    assert result.tof[0] is not None and np.isfinite(result.tof[0]) and result.tof[0] > 0

    # 最終位置はブロック左面 (x = 0.05) の近傍 (メッシュサイズ程度の許容)
    x_final, y_final = result.trajectories[0][-1]
    assert abs(x_final - BLOCK[0][0]) <= MESH_SIZE
    assert BLOCK[0][1] - MESH_SIZE <= y_final <= BLOCK[2][1] + MESH_SIZE
    # ブロックを通り抜けていない (右面より奥に到達しない)
    assert x_final < BLOCK[1][0]


# ---- 2. trace: charge 領域は透過 ------------------------------------------------


def test_trace_passes_through_charge_region():
    project = _trace_project("charge")
    mesh = generate_mesh(project)
    sol = solve(project, mesh)
    result = trace(project, mesh, sol)

    # charge 領域は通過し、右壁 (陽極 x = D) で吸収される
    assert result.absorbed[0]
    x_final, _ = result.trajectories[0][-1]
    assert x_final > D - 1e-6


# ---- 3. PIC: 誘電体スラブで全粒子が吸収される -----------------------------------


def test_pic_dielectric_blocks_particles_and_counts_wall():
    """+x に走る電子ビームが誘電体スラブ (x = 0.006..0.008) で全て吸収され、
    全ステップで誘電体要素内に粒子が存在しないこと。"""
    h = 0.01
    x_slab = 0.006
    project = Project.model_validate(
        {
            "geometry": {
                "domain": {"polygon": [[0, 0], [0.01, 0], [0.01, h], [0, h]]},
                "regions": [
                    {
                        "id": "slab",
                        "type": "dielectric",
                        # 上下の外枠に接する全高スラブ (OCC 化で扱える形状)
                        "polygon": [[x_slab, 0], [0.008, 0], [0.008, h], [x_slab, h]],
                        "eps_r": 4.0,
                    }
                ],
                "boundaries": [
                    {"edges": [3], "voltage": 0.0},
                    {"edges": [1], "voltage": 0.0},
                ],
            },
            "mesh": {"size": 8e-4},
            "pic": {
                "dt": 1e-9,
                "n_steps": 100,
                "n_macro": 10,
                "frame_every": 100,
                "reflect_edges": [0, 2],  # 上下は鏡面反射 (吸収は左右壁とスラブのみ)
            },
        }
    )
    sim = PicSimulation(project)
    solid = _solid_elements(project, sim.mesh)
    assert solid is not None and np.any(solid)

    # 電子を左側に装荷し、+x の速度でスラブへ向かわせる (壁には向かわない)
    n = 200
    rng = np.random.default_rng(7)
    x = np.stack([rng.uniform(0.001, 0.004, n), rng.uniform(0.002, 0.008, n)], axis=1)
    el = sim.species["electron"]
    el.x = x
    el.v = np.stack([np.full(n, 2.0e5), np.zeros(n), np.zeros(n)], axis=1)
    el.w = np.ones(n)  # 実電子1個分 → 空間電荷は無視できる
    el.elem = _locate_initial(sim.coeffs, x)

    for _ in range(project.pic.n_steps):
        sim.step()
        for sp in sim.species.values():
            if len(sp.x):
                # 誘電体要素内に粒子が存在しない
                assert not np.any(solid[sp.elem])
                # スラブを通り抜けた粒子もいない (表面 + 1ステップ分より奥に無い)
                assert np.all(sp.x[:, 0] < x_slab + 2.0e5 * 1e-9 + 1e-9)

    # 全粒子がスラブ表面で吸収され、壁カウンタに計上される
    assert len(el.x) == 0
    assert el.wall_absorbed == n
    assert sim.history["wall_e"][-1] == n
    assert sim.history["n_e"][-1] == 0


# ---- 4. PIC: 初期装荷が誘電体を避け、重みが装荷可能面積基準 -----------------------


def test_pic_initial_plasma_avoids_dielectric_and_weight():
    density = 1.0e14
    n_macro = 3000
    lx = 0.01
    b1, b2 = 0.004, 0.008  # ブロック [0.004, 0.008]^2 (面積 1.6e-5 m^2)
    project = Project.model_validate(
        {
            "geometry": {
                "domain": {"polygon": [[0, 0], [lx, 0], [lx, lx], [0, lx]]},
                "regions": [
                    {
                        "id": "block",
                        "type": "dielectric",
                        "polygon": [[b1, b1], [b2, b1], [b2, b2], [b1, b2]],
                        "eps_r": 4.0,
                    }
                ],
                "boundaries": [{"edges": [0, 1, 2, 3], "voltage": 0.0}],
            },
            "mesh": {"size": 8e-4},
            "pic": {
                "initial_plasma": {
                    "density": density,
                    "te_ev": 2.0,
                    "ti_ev": 0.03,
                    "ion_mass_amu": 40.0,
                    "seed": 3,
                },
                "n_macro": n_macro,
                "dt": 1e-9,
                "n_steps": 1,
                "frame_every": 1,
            },
        }
    )
    sim = PicSimulation(project)
    solid = _solid_elements(project, sim.mesh)
    assert solid is not None

    for sp in sim.species.values():
        assert len(sp.x) == n_macro
        # 装荷直後の所属要素が誘電体要素でない
        assert not np.any(solid[sp.elem])
        # 位置もブロックの内部に無い
        inside = (
            (sp.x[:, 0] > b1 + 1e-12) & (sp.x[:, 0] < b2 - 1e-12)
            & (sp.x[:, 1] > b1 + 1e-12) & (sp.x[:, 1] < b2 - 1e-12)
        )
        assert not np.any(inside)

    # 装荷可能面積 = domain 面積 - ブロック面積 (メッシュは多角形を厳密に埋める)
    area_load = float(sim.area[~solid].sum())
    area_expected = lx * lx - (b2 - b1) ** 2
    assert abs(area_load - area_expected) < 1e-9 * area_expected

    # マクロ重み w = density × 装荷可能面積 / n_macro (誘電体面積を含めない)
    w_expected = density * area_load / n_macro
    for sp in sim.species.values():
        assert np.allclose(sp.w, w_expected, rtol=1e-12)
    # 従来式 (全面積基準) より小さいこと
    assert w_expected < density * lx * lx / n_macro
