"""荷電粒子軌道追跡 (フェーズ2)。仕様書 §8 参照。

- 粒子位置 → 所属三角形の特定: walk 探索 + 前回要素キャッシュ
- E 補間: P1 要素なので要素内一定 (将来、節点平均場の重心座標補間に変更可)
- 積分器: リープフロッグ (kick-drift-kick / velocity-Verlet 形式。静電場のみ。
  磁場を導入する際に Boris 化)
- 全粒子を numpy 一括で進め、backend.get_xp() で CuPy に切り替え可能にする
- 電極・外周到達で吸収し、衝突位置・エネルギーを記録
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .fem import Solution
from .meshing import Mesh
from .schema import Emitter, ParticleSettings, Project, Species

QE = 1.602176634e-19   # 電気素量 [C]
ME = 9.1093837015e-31  # 電子質量 [kg]
MP = 1.67262192369e-27 # 陽子質量 [kg]

# walk 探索の反復上限 (1ステップの移動量が要素サイズに比べて十分小さければ
# ほぼ1〜2回で収束する。安全のため上限を設ける)
_MAX_WALK_ITERS = 64
# 重心座標が「内部」とみなす許容誤差 (数値誤差対策)
_TOL = 1e-9


@dataclass
class TraceOutput:
    """trace() の生データ (numpy)。server.py で TraceResult(pydantic) に変換する。"""

    trajectories: np.ndarray       # (n_particles, n_frames, 2)  初期位置を含む
    absorbed: np.ndarray           # (n_particles,) bool
    tof: np.ndarray                # (n_particles,) float。alive なら nan
    final_energy_ev: np.ndarray    # (n_particles,)
    final_angle_deg: np.ndarray    # (n_particles,) 最終速度の向き [度] (atan2(vy, vx))
    dt: float                      # 実際に使った dt [s]


def _species_qm(species: Species) -> tuple[float, float]:
    """粒子種から (q, m) を決定する。"""
    if species.preset == "electron":
        return -QE, ME
    if species.preset == "proton":
        return QE, MP
    assert species.q is not None and species.m is not None  # schema で保証済み
    return species.q, species.m


# ---- メッシュ前処理 ---------------------------------------------------------


def _barycentric_coeffs(nodes: np.ndarray, tris: np.ndarray):
    """P1 重心座標 L_i(x,y) = (a_i + b_i x + c_i y) / det の係数を全要素一括で返す。

    (a, b, c, det) はいずれも (M,) または (M,3) の配列。
    det は符号付き2倍面積 (三角形の頂点順序に依存)。向きに関わらず
    L_i は分子・分母を同じ符号規約で計算すれば正しい値になる。
    """
    p = nodes[tris]                      # (M, 3, 2)
    x, y = p[:, :, 0], p[:, :, 1]
    b = np.stack([y[:, 1] - y[:, 2], y[:, 2] - y[:, 0], y[:, 0] - y[:, 1]], axis=1)
    c = np.stack([x[:, 2] - x[:, 1], x[:, 0] - x[:, 2], x[:, 1] - x[:, 0]], axis=1)
    a = np.stack([
        x[:, 1] * y[:, 2] - x[:, 2] * y[:, 1],
        x[:, 2] * y[:, 0] - x[:, 0] * y[:, 2],
        x[:, 0] * y[:, 1] - x[:, 1] * y[:, 0],
    ], axis=1)
    det = x[:, 0] * b[:, 0] + x[:, 1] * b[:, 1] + x[:, 2] * b[:, 2]
    return a, b, c, det


def _adjacency(triangles: np.ndarray) -> np.ndarray:
    """隣接三角形配列を構築する。

    adjacency[t, i] = 要素 t の頂点 i の対辺 (頂点 i+1, i+2) を挟んで
    隣接する要素番号。境界 (隣接要素なし) なら -1。
    メッシュ全体で1回だけ行う前処理なので、要素数分の python ループで実装する
    (粒子ループではないので制約に抵触しない)。
    """
    m = len(triangles)
    edge_map: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for t in range(m):
        v0, v1, v2 = int(triangles[t, 0]), int(triangles[t, 1]), int(triangles[t, 2])
        # local i の対辺は (i+1, i+2) 番目の頂点
        local_edges = ((v1, v2), (v2, v0), (v0, v1))
        for i, (u, v) in enumerate(local_edges):
            key = (u, v) if u < v else (v, u)
            edge_map.setdefault(key, []).append((t, i))

    adjacency = np.full((m, 3), -1, dtype=np.int64)
    for lst in edge_map.values():
        if len(lst) == 2:
            (t0, i0), (t1, i1) = lst
            adjacency[t0, i0] = t1
            adjacency[t1, i1] = t0
    return adjacency


def _locate_initial(coeffs, points: np.ndarray) -> np.ndarray:
    """初期所属要素を全要素総当たりで決定する (初回のみ)。"""
    a, b, c, det = coeffs
    x = points[:, 0].reshape(-1, 1, 1)
    y = points[:, 1].reshape(-1, 1, 1)
    # L: (n_particles, n_elements, 3)
    l_all = (a[None, :, :] + b[None, :, :] * x + c[None, :, :] * y) / det[None, :, None]
    inside = np.all(l_all >= -_TOL, axis=2)
    any_inside = inside.any(axis=1)
    elem = np.where(any_inside, np.argmax(inside, axis=1), 0)
    if not np.all(any_inside):
        # 領域外 (エミッタ設定ミス等) のフォールバック: 違反が最小の要素を採用
        violation = np.clip(-l_all, 0.0, None).max(axis=2)
        fallback = np.argmin(violation, axis=1)
        elem = np.where(any_inside, elem, fallback)
    return elem.astype(np.int64)


def _walk_step(coeffs, adjacency: np.ndarray, elem0: np.ndarray, x_new: np.ndarray):
    """現在の要素から x_new へ向けて重心座標 walk を行う。

    戻り値:
        elem: 新しい所属要素 (吸収された粒子は最後にいた要素のまま)
        absorbed: 境界 (adjacency == -1) を越えて出たかどうか
        b_elem, b_loc: absorbed 時に境界を検出した要素・ローカルエッジ番号
                       (tof 補間に使う。absorbed=False の要素では無意味)
    """
    a, b, c, det = coeffs
    n = len(x_new)
    elem = elem0.copy()
    absorbed = np.zeros(n, dtype=bool)
    b_elem = np.zeros(n, dtype=np.int64)
    b_loc = np.zeros(n, dtype=np.int64)
    active = np.ones(n, dtype=bool)

    for _ in range(_MAX_WALK_ITERS):
        idx = np.nonzero(active)[0]
        if idx.size == 0:
            break
        e = elem[idx]
        xp, yp = x_new[idx, 0], x_new[idx, 1]
        l_loc = (a[e] + b[e] * xp[:, None] + c[e] * yp[:, None]) / det[e][:, None]  # (K,3)
        min_loc = np.argmin(l_loc, axis=1)
        min_val = l_loc[np.arange(len(idx)), min_loc]
        outside = min_val < -_TOL

        done = idx[~outside]
        active[done] = False
        if not np.any(outside):
            continue

        o_idx = idx[outside]
        o_elem = elem[o_idx]
        o_loc = min_loc[outside]
        neighbor = adjacency[o_elem, o_loc]
        left = neighbor == -1

        abs_idx = o_idx[left]
        if abs_idx.size:
            absorbed[abs_idx] = True
            b_elem[abs_idx] = o_elem[left]
            b_loc[abs_idx] = o_loc[left]
            active[abs_idx] = False

        cont_idx = o_idx[~left]
        if cont_idx.size:
            elem[cont_idx] = neighbor[~left]
            # active のまま次の反復で再チェック

    return elem, absorbed, b_elem, b_loc


# ---- エミッタ・dt推定 -------------------------------------------------------


def _init_particles(emitter: Emitter, m: float) -> tuple[np.ndarray, np.ndarray]:
    """エミッタ設定から初期位置・初期速度 (n,2) を作る。

    energy_dist == "mono" (既定) の場合は乱数を使わず等間隔割り振り (従来動作)。
    energy_dist == "maxwell" の場合はドリフト速度 (energy_ev, direction_deg から。
    spread_deg は無視) に熱速度成分 (2D Maxwell分布) を加算する。乱数は
    np.random.default_rng(seed) を使い、同じ seed で完全再現する。
    """
    n = emitter.n
    if emitter.kind == "point":
        p1 = np.asarray(emitter.p1, dtype=np.float64)
        pos = np.tile(p1, (n, 1))
    else:
        p1 = np.asarray(emitter.p1, dtype=np.float64)
        p2 = np.asarray(emitter.p2, dtype=np.float64)
        t = np.linspace(0.0, 1.0, n)
        pos = p1[None, :] + t[:, None] * (p2 - p1)[None, :]

    if emitter.energy_dist == "maxwell":
        # ドリフト速度は全粒子共通 (spread_deg は無視)
        angle = math.radians(emitter.direction_deg)
        speed = math.sqrt(2.0 * emitter.energy_ev * QE / m) if emitter.energy_ev > 0 else 0.0
        drift = speed * np.array([math.cos(angle), math.sin(angle)])
        vel = np.tile(drift, (n, 1))

        # 熱速度: vx, vy ~ Normal(0, sigma), sigma = sqrt(kT * q_e / m)
        sigma = math.sqrt(emitter.temperature_ev * QE / m)
        rng = np.random.default_rng(emitter.seed)
        vel = vel + rng.normal(0.0, sigma, size=(n, 2))
        return pos, vel

    if n == 1:
        angles_deg = np.array([emitter.direction_deg])
    else:
        angles_deg = np.linspace(
            emitter.direction_deg - emitter.spread_deg,
            emitter.direction_deg + emitter.spread_deg,
            n,
        )
    angles = np.radians(angles_deg)

    speed = math.sqrt(2.0 * emitter.energy_ev * QE / m) if emitter.energy_ev > 0 else 0.0
    vel = speed * np.stack([np.cos(angles), np.sin(angles)], axis=1)
    return pos, vel


def _estimate_dt(mesh: Mesh, e_field: np.ndarray, v0: np.ndarray, q: float, m: float) -> float:
    """dt 自動推定。

    h_min: 最小要素の外接半径 (= 辺長の積 / (4×面積))。
    v = max(初期速度, sqrt(2|q|E_max h_min / m))、dt = 0.3 h_min / v。
    """
    p = mesh.nodes[mesh.triangles]
    d0 = np.linalg.norm(p[:, 1] - p[:, 2], axis=1)
    d1 = np.linalg.norm(p[:, 2] - p[:, 0], axis=1)
    d2 = np.linalg.norm(p[:, 0] - p[:, 1], axis=1)
    x, y = p[:, :, 0], p[:, :, 1]
    det = x[:, 0] * (y[:, 1] - y[:, 2]) + x[:, 1] * (y[:, 2] - y[:, 0]) + x[:, 2] * (y[:, 0] - y[:, 1])
    area = 0.5 * np.abs(det)
    circum_r = (d0 * d1 * d2) / (4.0 * area)
    h_min = float(circum_r.min())

    e_abs = np.sqrt(np.sum(e_field ** 2, axis=1))
    e_max = float(e_abs.max()) if len(e_abs) else 0.0

    v0_max = float(np.max(np.sqrt(np.sum(v0 ** 2, axis=1)))) if len(v0) else 0.0
    v_th = math.sqrt(2.0 * abs(q) * e_max * h_min / m) if e_max > 0.0 else 0.0
    v_rep = max(v0_max, v_th, 1e-9)  # ゼロ割回避 (静止・無電場の極端なケース)
    return 0.3 * h_min / v_rep


# ---- 本体 -------------------------------------------------------------------


def trace(project: Project, mesh: Mesh, sol: Solution) -> TraceOutput:
    """フェーズ1の解 (固定場) を使って粒子軌道を積分する。"""
    settings: ParticleSettings | None = project.particles
    if settings is None:
        raise ValueError("project.particles が指定されていません")

    q, m = _species_qm(settings.species)

    tris = mesh.triangles
    coeffs = _barycentric_coeffs(mesh.nodes, tris)
    adjacency = _adjacency(tris)
    e_field = sol.e_field  # (M, 2) 要素内一定

    x0, v0 = _init_particles(settings.emitter, m)
    n = len(x0)

    dt = settings.dt
    if dt is None:
        dt = _estimate_dt(mesh, e_field, v0, q, m)
    dt = float(dt)

    n_steps = settings.n_steps
    save_every = settings.save_every

    elem = _locate_initial(coeffs, x0)
    x = x0.copy()
    v = v0.copy()
    alive = np.ones(n, dtype=bool)
    tof = np.full(n, np.nan)

    frames = [x.copy()]
    t_elapsed = 0.0
    qm = q / m

    a_coef, b_coef, c_coef, det_coef = coeffs

    for step in range(1, n_steps + 1):
        idx_active = np.nonzero(alive)[0]
        if idx_active.size:
            e_at = e_field[elem[idx_active]]
            a_cur = qm * e_at
            x_prev = x[idx_active]
            v_half = v[idx_active] + 0.5 * dt * a_cur
            x_new = x_prev + dt * v_half

            new_elem, absorbed_mask, b_elem, b_loc = _walk_step(
                coeffs, adjacency, elem[idx_active], x_new
            )

            cont = ~absorbed_mask
            cont_idx = idx_active[cont]
            if cont_idx.size:
                x[cont_idx] = x_new[cont]
                elem[cont_idx] = new_elem[cont]
                e_new = e_field[elem[cont_idx]]
                a_new = qm * e_new
                v[cont_idx] = v_half[cont] + 0.5 * dt * a_new

            abs_idx = idx_active[absorbed_mask]
            if abs_idx.size:
                # 境界を検出したエッジの重心座標 L を x_prev, x_new で評価し、
                # L=0 (境界線) を通過する時刻を線形補間する。
                ea = b_elem[absorbed_mask]
                eloc = b_loc[absorbed_mask]
                bb = b_coef[ea, eloc]
                cc = c_coef[ea, eloc]
                aa = a_coef[ea, eloc]
                dd = det_coef[ea]
                xp_a = x_prev[absorbed_mask]
                xn_a = x_new[absorbed_mask]
                l0 = (aa + bb * xp_a[:, 0] + cc * xp_a[:, 1]) / dd
                l1 = (aa + bb * xn_a[:, 0] + cc * xn_a[:, 1]) / dd
                denom = l0 - l1
                denom = np.where(np.abs(denom) < 1e-300, 1e-300, denom)
                frac = np.clip(l0 / denom, 0.0, 1.0)

                x[abs_idx] = xp_a + frac[:, None] * (xn_a - xp_a)
                v[abs_idx] = v[abs_idx] + frac[:, None] * dt * a_cur[absorbed_mask]
                tof[abs_idx] = t_elapsed + frac * dt
                alive[abs_idx] = False

        t_elapsed += dt
        if step % save_every == 0:
            frames.append(x.copy())

    trajectories = np.stack(frames, axis=1)  # (n, n_frames, 2)
    speed2 = np.sum(v * v, axis=1)
    final_energy_ev = 0.5 * m * speed2 / QE
    absorbed = ~alive
    # 衝突角度: absorbed 粒子は衝突時刻に線形補間した速度 (v[abs_idx] を参照)、
    # alive 粒子は最終ステップの速度から向きを求める
    final_angle_deg = np.degrees(np.arctan2(v[:, 1], v[:, 0]))

    return TraceOutput(
        trajectories=trajectories,
        absorbed=absorbed,
        tof=tof,
        final_energy_ev=final_energy_ev,
        final_angle_deg=final_angle_deg,
        dt=dt,
    )
