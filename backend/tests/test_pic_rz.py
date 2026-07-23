"""PIC 軸対称 (rz) モードのテスト (prompts/47)。

1. 中性静穏開始: 電子・イオン同位置装荷で電荷堆積が厳密に相殺し φ ≈ 0
2. 電荷堆積の規約: 一様に置いたイオンリング電荷による軸上電位が
   無限長一様帯電円柱の解析解 φ(r) = ρ(R²−r²)/(4ε0) と一致 (係数 2π の検証)
3. 自由粒子の遠心力・角運動量保存: 無場で vθ を持つ粒子の r(t) が
   解析解 r(t) = √(r0² + (vθ0 t)²) と一致
4. 軸方向プラズマ振動: 冷たい電子の微小 z ドリフトで KE が 2×fpe で振動
"""

import math

import numpy as np

from es_sim.fem import EPS0
from es_sim.particles import ME, QE
from es_sim.pic import PicSimulation
from es_sim.schema import Project

DENSITY = 1.0e14  # [m^-3]


def _wpe(density: float) -> float:
    return math.sqrt(density * QE**2 / (EPS0 * ME))


def _zero_cross_freq(sig: np.ndarray, dt: float) -> float:
    s = sig - sig.mean()
    idx = np.nonzero((s[:-1] < 0) & (s[1:] >= 0))[0]
    assert len(idx) >= 3, "ゼロクロスが少なすぎます"
    tz = idx + s[idx] / (s[idx] - s[idx + 1])
    return (len(tz) - 1) / ((tz[-1] - tz[0]) * dt)


def _cylinder_project(lz: float, rr: float, mesh: float, pic: dict) -> Project:
    """rz (x=z, y=r, 軸 y=0) の円柱。軸以外の3辺を接地する。"""
    return Project.model_validate(
        {
            "coord": "rz",
            "geometry": {
                "domain": {"polygon": [[0, 0], [lz, 0], [lz, rr], [0, rr]]},
                # エッジ0 (y=0) は対称軸 = 自然境界。1: z=lz、2: r=rr、3: z=0
                "boundaries": [{"edges": [1, 2, 3], "type": "dirichlet", "voltage": 0.0}],
            },
            "mesh": {"size": mesh},
            "pic": pic,
        }
    )


# ---- 1. 中性静穏開始 -----------------------------------------------------------


def test_rz_neutral_quiet_start():
    """電子・イオンを同位置に装荷 (quiet start) → 堆積が相殺して φ ≈ 0。"""
    project = _cylinder_project(
        0.02, 0.01, 1.5e-3,
        {
            "initial_plasma": {
                "density": DENSITY, "te_ev": 0.0, "ti_ev": 0.0,
                "ion_mass_amu": 40.0, "immobile_ions": True, "seed": 2,
            },
            "n_macro": 4000,
            "dt": None,
            "n_steps": 3,
            "frame_every": 100,
        },
    )
    sim = PicSimulation(project)
    phi = sim._solve_phi(sim._deposit(), 0.0)
    assert float(np.max(np.abs(phi))) < 1e-9


# ---- 2. 電荷堆積の規約 (一様帯電円柱の解析解) -----------------------------------


def test_rz_deposit_uniform_cylinder():
    """一様密度のイオンリングを要素重心に決定的に配置し、軸上中央の電位を
    無限長一様帯電円柱 φ(r) = ρ(R²−r²)/(4ε0) と比較する (L = 10R で端効果は無視小)。

    リング電荷 Q = n·V_elem·e の P1 射影 f = Q·L_i/(2π) の係数 (2π) と
    節点体積規格化が正しくなければ電位が定数倍ずれるので、この比較で検証できる。
    """
    rr = 0.01
    lz = 0.1
    project = _cylinder_project(
        lz, rr, 1.2e-3,
        {"n_macro": 100, "dt": 1e-9, "n_steps": 3, "frame_every": 100},
    )
    sim = PicSimulation(project)

    # イオンを全要素の重心に配置し、重み = n·(要素体積) で一様密度を表現する
    io = sim.species["ion"]
    m = len(sim.tris)
    centroids = sim.mesh.nodes[sim.tris].mean(axis=1)  # (M, 2)
    io.x = centroids
    io.v = np.zeros((m, 3))
    io.w = DENSITY * sim.elem_vol.copy()
    io.elem = np.arange(m, dtype=np.int64)
    io.bary = None
    io.nidx = None
    io.mobile = False

    phi = sim._solve_phi(sim._deposit(), 0.0)

    rho = DENSITY * QE
    nodes = sim.mesh.nodes
    # 中央付近 (|z - L/2| < L/8) の節点で解析解と比較する
    mid = np.abs(nodes[:, 0] - lz / 2.0) < lz / 8.0
    phi_ana = rho * (rr**2 - nodes[mid, 1] ** 2) / (4.0 * EPS0)
    phi_max = rho * rr**2 / (4.0 * EPS0)
    err = np.max(np.abs(phi[mid] - phi_ana)) / phi_max
    assert err < 0.05, f"相対誤差 {err:.3f}"


# ---- 3. 自由粒子の遠心力・角運動量保存 ------------------------------------------


def test_rz_free_particle_centrifugal():
    """無場・無電荷で vθ を持つ電子の r(t) が解析解 √(r0² + (vθ t)²) と一致。"""
    r0 = 4e-3
    vth0 = 1.0e5  # vθ [m/s]
    dt = 1e-9
    n_steps = 100
    project = _cylinder_project(
        0.02, 0.02, 2e-3,
        {"n_macro": 100, "dt": dt, "n_steps": n_steps, "frame_every": 1000},
    )
    sim = PicSimulation(project)

    el = sim.species["electron"]
    el.x = np.array([[0.01, r0]])
    el.v = np.array([[0.0, 0.0, vth0]])
    el.w = np.array([1.0])  # 実質無電荷 (1個のリング電子)
    el.elem = np.array([int(np.argmin(np.sum((sim.mesh.nodes[sim.tris].mean(axis=1) - [0.01, r0]) ** 2, axis=1)))])
    # 位置が所属要素内に無い可能性があるため walk で正す (locate 相当)
    from es_sim.particles import _locate_initial
    el.elem = _locate_initial(sim.coeffs, el.x)
    el.bary = None
    el.nidx = None

    for _ in range(n_steps):
        sim.step()

    t = n_steps * dt
    r_ana = math.sqrt(r0**2 + (vth0 * t) ** 2)
    assert len(el.x) == 1  # 吸収されていない
    r_num = float(el.x[0, 1])
    assert abs(r_num - r_ana) / r_ana < 0.01
    # 角運動量 L = r·vθ の保存
    l_num = r_num * float(el.v[0, 2])
    assert abs(l_num - r0 * vth0) / (r0 * vth0) < 0.01
    # 運動エネルギー保存 (無場なので |v| 一定)
    v2 = float(np.sum(el.v[0] ** 2))
    assert abs(v2 - vth0**2) / vth0**2 < 0.01


# ---- 4. 軸方向プラズマ振動 -------------------------------------------------------


def test_rz_axial_plasma_oscillation():
    """冷たい電子に z 方向の正弦モードドリフトを与え、KE が 2×fpe で振動する。"""
    lz = 0.01
    project = _cylinder_project(
        lz, 0.03, 8e-4,
        {
            "initial_plasma": {
                "density": DENSITY, "te_ev": 0.0, "ti_ev": 0.0,
                "ion_mass_amu": 40.0, "immobile_ions": True, "seed": 1,
            },
            "n_macro": 9000,
            "dt": None,  # 0.1/ωpe
            "n_steps": 400,
            "frame_every": 200,
        },
    )
    sim = PicSimulation(project)
    assert abs(sim.dt * _wpe(DENSITY) - 0.1) < 1e-12

    el = sim.species["electron"]
    el.v[:, 0] += 3.0e3 * np.sin(2.0 * np.pi * el.x[:, 0] / lz)
    history, _ = sim.run_batch()

    ke = np.asarray(history["ke_e"])
    f_measured = _zero_cross_freq(ke, sim.dt)
    f_expected = 2.0 * _wpe(DENSITY) / (2.0 * math.pi)
    assert abs(f_measured - f_expected) / f_expected < 0.10
