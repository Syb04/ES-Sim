"""定常ガス流れの DSMC (Direct Simulation Monte Carlo、prompts/54)。

- セル = 既存の三角形メッシュ要素 (meshing / particles のインフラを再利用)
- 分子モデル: VHS (Variable Hard Sphere)。σ_T(c_r) = π d_ref² (c_ref/c_r)^{2ω−1} 型
  (Bird 1994 の標準形、Γ(5/2−ω) 因子込み)
- 衝突: NTC (No-Time-Counter) 法。セルごとに候補対数
  N_cand = ½ N(N−1) W (σc_r)_max Δt / V を抽選し、σ(c_r)c_r/(σc_r)_max で採択
- 境界: 拡散反射壁 (完全適応)・鏡面反射・圧力リザーバ流入/流出・真空排気。
  壁到達粒子は交点に置き直して境界条件に応じた速度を与える (交点は重心座標 L=0 の
  線形補間、粒子は交点からエッジ高さ×1e-3 だけ内側へ配置)。残余移動時間は
  無視する近似 (Δt がセル通過時間より小さければ誤差は小さい)
- 誘電体 (固体) 要素へ入った粒子は移動を取り消し、壁温の等方 Maxwell で
  再抽選する (質量保存を守る簡易処理)
- 定常判定はユーザ指定の n_steps に委ね、最終 avg_steps の時間平均で
  セルごとの n・u・T (・p = n kB T) を得る。結果は MCC の GasField にそのまま渡せる
- 平面2D (coord="xy") 専用。奥行き 1 m 換算 (セル体積 = 面積 × 1 m)
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .meshing import generate_mesh
from .particles import (
    _adjacency,
    _barycentric_coeffs,
    _pack_coeffs,
    _solid_elements,
    _walk_step,
)
from .schema import DsmcSettings, Project

KB = 1.380649e-23     # ボルツマン定数 [J/K]
AMU = 1.66053906660e-27  # 原子質量単位 [kg]

# 境界タイプの内部コード ((要素, ローカルエッジ) 表で引く)
_B_WALL = 0
_B_SYMMETRY = 1
_B_RESERVOIR = 2  # inlet / outlet (圧力 > 0): 吸収 + リザーバ流入
_B_VACUUM = 3     # outlet (圧力なし): 吸収のみ


@dataclass
class DsmcResult:
    """定常時間平均のガス場 (要素ごと)。"""

    n: np.ndarray        # (M,) 数密度 [m^-3]
    t: np.ndarray        # (M,) 温度 [K]
    u: np.ndarray        # (M, 2) 面内流速 [m/s]
    p: np.ndarray        # (M,) 圧力 [Pa] = n kB T
    n_particles: int     # 最終シミュレーション粒子数
    macro_weight: float  # 実分子数/シミュレーション粒子
    dt: float            # 実際に使った dt [s]
    inflow: float        # 平均区間の流入実分子数 (リザーバ)
    outflow: float       # 平均区間の流出実分子数 (リザーバ + 真空)


class DsmcSimulation:
    """DSMC 本体。run() で n_steps 進めて DsmcResult を返す。"""

    def __init__(self, project: Project):
        if project.dsmc is None:
            raise ValueError("project.dsmc が指定されていません")
        if project.coord != "xy":
            raise ValueError("DSMC は平面2D (coord='xy') のみ対応です")
        self.project = project
        self.s: DsmcSettings = project.dsmc
        gas = self.s.gas
        self.m = gas.mass_amu * AMU
        self.mu = 0.5 * self.m  # 同種2体の換算質量

        # ---- メッシュ (particles.py のインフラを再利用) ----------------------
        self.mesh = generate_mesh(project)
        self.tris = self.mesh.triangles
        self.coeffs = _barycentric_coeffs(self.mesh.nodes, self.tris)
        self._packed = _pack_coeffs(self.coeffs)
        self.adjacency = _adjacency(self.tris)
        det = self.coeffs[3]
        self.area = 0.5 * np.abs(det)
        self._solid = _solid_elements(project, self.mesh)  # 誘電体 (固体) 要素 or None
        gas_area = float(
            self.area.sum() if self._solid is None else self.area[~self._solid].sum()
        )

        # ---- 境界エッジ表 ((要素, ローカルエッジ) で引く) --------------------
        self._build_boundary_tables()

        # ---- マクロ重み・時間刻み --------------------------------------------
        n_init = self.s.init_pressure_pa / (KB * self.s.init_temperature_k)
        res_n = [
            (bc.pressure_pa or 0.0) / (KB * bc.temperature_k)
            for bc in self.s.boundaries
            if bc.type in ("inlet", "outlet")
        ]
        n_ref = max([n_init] + res_n)  # 定常粒子数の目安になる基準密度
        self.w = n_ref * gas_area / self.s.n_particles  # 実分子数/シミュレーション粒子

        t_hot = max(
            [self.s.init_temperature_k, self.s.wall_temperature_k]
            + [bc.temperature_k for bc in self.s.boundaries]
        )
        v_mp = math.sqrt(2.0 * KB * t_hot / self.m)  # 最確速さ
        if self.s.dt is not None:
            self.dt = float(self.s.dt)
        else:
            # セル代表寸法 (最小要素の外接半径相当) を最確速さで割った時間の 1/4
            p = self.mesh.nodes[self.tris]
            edges = (
                np.linalg.norm(p[:, 0] - p[:, 1], axis=1)
                + np.linalg.norm(p[:, 1] - p[:, 2], axis=1)
                + np.linalg.norm(p[:, 2] - p[:, 0], axis=1)
            ) / 3.0
            self.dt = 0.25 * float(edges.min()) / v_mp

        # ---- VHS 断面積 -------------------------------------------------------
        # σ_T(c_r) = π d_ref² · (2 kB T_ref / (μ c_r²))^{ω−1/2} / Γ(5/2 − ω)
        self._sig_coef = (
            math.pi * gas.d_ref_m**2
            / math.gamma(2.5 - gas.omega)
            * (2.0 * KB * gas.t_ref_k / self.mu) ** (gas.omega - 0.5)
        )
        self._sig_pow = 1.0 - 2.0 * gas.omega  # c_r 依存: c_r^{1−2ω} (× c_r で σc_r)
        # (σ c_r)_max のセル別初期値: c_r ~ 2 v_mp で評価 (走行中に実測最大へ更新)
        cr0 = 2.0 * v_mp
        self._sigcr_max = np.full(len(self.tris), self._sigma(np.array([cr0]))[0] * cr0)
        self._coll_frac = np.zeros(len(self.tris))  # NTC 候補数の端数持ち越し

        # ---- 初期充填 (一様 Maxwell) -----------------------------------------
        self.rng = np.random.default_rng(self.s.seed)
        n0 = int(round(n_init * gas_area / self.w))
        loadable = (
            np.arange(len(self.tris))
            if self._solid is None
            else np.nonzero(~self._solid)[0]
        )
        p_elem = self.area[loadable] / self.area[loadable].sum()
        elem0 = loadable[self.rng.choice(len(loadable), size=n0, p=p_elem)]
        r1 = np.sqrt(self.rng.random(n0))
        r2 = self.rng.random(n0)
        pts = self.mesh.nodes[self.tris[elem0]]
        self.x = (
            (1.0 - r1)[:, None] * pts[:, 0]
            + (r1 * (1.0 - r2))[:, None] * pts[:, 1]
            + (r1 * r2)[:, None] * pts[:, 2]
        )
        sig0 = math.sqrt(KB * self.s.init_temperature_k / self.m)
        self.v = self.rng.normal(0.0, sig0, size=(n0, 3))
        self.elem = elem0.astype(np.int64)

        # ---- サンプリング (最終 avg_steps) -----------------------------------
        self._acc_cnt = np.zeros(len(self.tris))
        self._acc_v = np.zeros((len(self.tris), 3))
        self._acc_v2 = np.zeros(len(self.tris))
        self._samples = 0
        self.inflow = 0.0
        self.outflow = 0.0

    # ---- VHS 断面積 -----------------------------------------------------------

    def _sigma(self, c_r: np.ndarray) -> np.ndarray:
        """VHS 全断面積 σ_T(c_r) = coef · c_r^{1−2ω} [m²] (c_r ≤ 0 は 0)。"""
        out = np.zeros_like(c_r)
        pos = c_r > 0.0
        out[pos] = self._sig_coef * c_r[pos] ** self._sig_pow
        return out

    # ---- 境界表 ---------------------------------------------------------------

    def _build_boundary_tables(self) -> None:
        """境界メッシュエッジ (隣接 = -1) の種別・温度・リザーバ密度と幾何を作る。

        domain 外周エッジは DsmcBoundary の指定 (エッジ中点が指定 domain エッジ上に
        あるか) で分類し、未指定エッジと conductor 輪郭は拡散反射壁とする。
        """
        tris = self.tris
        nodes = self.mesh.nodes
        ts, loc = np.nonzero(self.adjacency == -1)
        n1 = tris[ts, (loc + 1) % 3]
        n2 = tris[ts, (loc + 2) % 3]
        n_opp = tris[ts, loc]
        p1, p2, po = nodes[n1], nodes[n2], nodes[n_opp]
        mid = 0.5 * (p1 + p2)
        t_vec = p2 - p1
        length = np.linalg.norm(t_vec, axis=1)
        perp = np.stack([-t_vec[:, 1], t_vec[:, 0]], axis=1)
        sgn = np.where(np.sum(perp * (po - mid), axis=1) >= 0.0, 1.0, -1.0)
        nrm = perp * (sgn / length)[:, None]  # 内向き単位法線
        height = np.abs(np.sum((po - mid) * nrm, axis=1))

        m = len(tris)
        self._b_type = np.full((m, 3), _B_WALL, dtype=np.int8)
        self._b_temp = np.full((m, 3), self.s.wall_temperature_k)
        self._b_nrm = np.zeros((m, 3, 2))
        self._b_tan = np.zeros((m, 3, 2))
        self._b_delta = np.zeros((m, 3))
        self._b_nrm[ts, loc] = nrm
        self._b_tan[ts, loc] = t_vec / length[:, None]
        self._b_delta[ts, loc] = 1e-3 * height

        # domain 外周エッジへの割り当て (エッジ中点が domain エッジ線分上にあるか)
        poly = np.asarray(self.project.geometry.domain.polygon, dtype=np.float64)
        nv = len(poly)
        scale = float(np.max(np.abs(poly)))
        tol = 1e-8 * (scale if scale > 0.0 else 1.0)
        type_code = {"wall": _B_WALL, "symmetry": _B_SYMMETRY}

        # リザーバ流入エッジのリスト (流入計算用)
        self._res_edges: list[dict] = []
        for bc in self.s.boundaries:
            if bc.type in ("inlet", "outlet"):
                code = (
                    _B_RESERVOIR if (bc.pressure_pa and bc.pressure_pa > 0.0) else _B_VACUUM
                )
            else:
                code = type_code[bc.type]
            for e in bc.edges:
                q1 = poly[e % nv]
                q2 = poly[(e + 1) % nv]
                seg = q2 - q1
                seg_len = float(np.hypot(seg[0], seg[1]))
                if seg_len <= 0.0:
                    continue
                d = mid - q1
                dist = np.abs(d[:, 0] * seg[1] - d[:, 1] * seg[0]) / seg_len
                tpar = (d[:, 0] * seg[0] + d[:, 1] * seg[1]) / (seg_len * seg_len)
                on = (dist <= tol) & (tpar >= -1e-9) & (tpar <= 1.0 + 1e-9)
                if not np.any(on):
                    continue
                self._b_type[ts[on], loc[on]] = code
                self._b_temp[ts[on], loc[on]] = bc.temperature_k
                if code == _B_RESERVOIR:
                    n_res = bc.pressure_pa / (KB * bc.temperature_k)
                    for i in np.nonzero(on)[0]:
                        self._res_edges.append(
                            {
                                "elem": int(ts[i]),
                                "loc": int(loc[i]),
                                "p1": p1[i],
                                "p2": p2[i],
                                "nrm": nrm[i],
                                "tan": t_vec[i] / length[i],
                                "len": float(length[i]),
                                "delta": float(1e-3 * height[i]),
                                "n": n_res,
                                "temp": bc.temperature_k,
                                "frac": 0.0,
                            }
                        )

    # ---- 流入 (リザーバ) ------------------------------------------------------

    def _inject(self) -> None:
        """リザーバエッジから平衡流束 Φ = n c̄/4 (c̄ = √(8kT/πm)) で流入させる。

        流入法線速度は流束重み付き Maxwell (v_n = σ√(−2 ln U))、接線・z 成分は
        熱速度の正規分布。端数はエッジごとに持ち越す。
        """
        if not self._res_edges:
            return
        new_x, new_v, new_e = [], [], []
        for ed in self._res_edges:
            sig = math.sqrt(KB * ed["temp"] / self.m)
            flux = ed["n"] * math.sqrt(KB * ed["temp"] / (2.0 * math.pi * self.m))
            quota = flux * ed["len"] * self.dt / self.w + ed["frac"]
            k = int(quota)
            ed["frac"] = quota - k
            if k == 0:
                continue
            u = self.rng.random(k)
            pos = ed["p1"][None, :] + u[:, None] * (ed["p2"] - ed["p1"])[None, :]
            pos = pos + ed["delta"] * ed["nrm"][None, :]
            vn = sig * np.sqrt(-2.0 * np.log(np.maximum(self.rng.random(k), 1e-300)))
            vt = self.rng.normal(0.0, sig, size=k)
            vz = self.rng.normal(0.0, sig, size=k)
            vel = np.empty((k, 3))
            vel[:, :2] = vn[:, None] * ed["nrm"][None, :] + vt[:, None] * ed["tan"][None, :]
            vel[:, 2] = vz
            new_x.append(pos)
            new_v.append(vel)
            new_e.append(np.full(k, ed["elem"], dtype=np.int64))
            self.inflow += k * self.w if self._samples else 0.0
        if new_x:
            self.x = np.concatenate([self.x, *new_x])
            self.v = np.concatenate([self.v, *new_v])
            self.elem = np.concatenate([self.elem, *new_e])

    # ---- 移動と境界 -----------------------------------------------------------

    def _move(self) -> None:
        """自由分子移動 + 境界処理。

        壁/対称/リザーバ/真空のいずれも、交点 (重心座標 L=0 の線形補間) で処理する。
        壁は拡散反射 (壁温 Maxwell 流束)、対称は鏡面反射、リザーバ・真空は吸収。
        再放出/反射した粒子は残余移動時間 (1−frac)·t を完走させる (最大6レグ。
        残余時間を捨てると壁近傍に放出直後の粒子が滞留して温度が数%高く出る)。
        固体要素へ入った粒子は移動を取り消して壁温の等方 Maxwell で再抽選する。
        """
        dt = self.dt
        n = len(self.x)
        x_new = self.x + dt * self.v[:, :2]
        elem_new, absorbed, b_elem, b_loc = _walk_step(
            self.coeffs, self.adjacency, self.elem, x_new, packed=self._packed
        )

        remove = np.zeros(n, dtype=bool)
        t_rem = np.full(n, dt)       # 残余移動時間
        x_from = self.x.copy()       # 現レグの開始位置
        e_from = self.elem.copy()    # 現レグの開始要素
        a_c, b_c, c_c, det_c = self.coeffs
        act = np.nonzero(absorbed)[0]

        for _ in range(6):
            if act.size == 0:
                break
            ea, el = b_elem[act], b_loc[act]
            btype = self._b_type[ea, el]

            # 交点 (境界エッジの重心座標 L=0 を線形補間)
            aa, bb, cc, dd = a_c[ea, el], b_c[ea, el], c_c[ea, el], det_c[ea]
            xp, xn = x_from[act], x_new[act]
            l0 = (aa + bb * xp[:, 0] + cc * xp[:, 1]) / dd
            l1 = (aa + bb * xn[:, 0] + cc * xn[:, 1]) / dd
            denom = np.where(np.abs(l0 - l1) < 1e-300, 1e-300, l0 - l1)
            frac = np.clip(l0 / denom, 0.0, 1.0)
            hit = xp + frac[:, None] * (xn - xp)
            nrm = self._b_nrm[ea, el]
            tan = self._b_tan[ea, el]
            inside = hit + self._b_delta[ea, el][:, None] * nrm
            t_rem[act] = t_rem[act] * (1.0 - frac)

            # 吸収 (リザーバ・真空)
            absorb = (btype == _B_RESERVOIR) | (btype == _B_VACUUM)
            remove[act[absorb]] = True
            if self._samples:
                self.outflow += float(np.count_nonzero(absorb)) * self.w

            # 拡散反射壁: 壁温 Maxwell 流束で内向きに再放出
            wall = btype == _B_WALL
            if np.any(wall):
                k = int(wall.sum())
                w_idx = act[wall]
                sig = np.sqrt(KB * self._b_temp[ea[wall], el[wall]] / self.m)
                vn = sig * np.sqrt(-2.0 * np.log(np.maximum(self.rng.random(k), 1e-300)))
                vt = self.rng.normal(0.0, 1.0, size=k) * sig
                vz = self.rng.normal(0.0, 1.0, size=k) * sig
                self.v[w_idx, 0] = vn * nrm[wall, 0] + vt * tan[wall, 0]
                self.v[w_idx, 1] = vn * nrm[wall, 1] + vt * tan[wall, 1]
                self.v[w_idx, 2] = vz

            # 鏡面反射 (対称境界): 法線速度成分を反転
            sym = btype == _B_SYMMETRY
            if np.any(sym):
                s_idx = act[sym]
                vn_c = self.v[s_idx, 0] * nrm[sym, 0] + self.v[s_idx, 1] * nrm[sym, 1]
                self.v[s_idx, 0] -= 2.0 * np.minimum(vn_c, 0.0) * nrm[sym, 0]
                self.v[s_idx, 1] -= 2.0 * np.minimum(vn_c, 0.0) * nrm[sym, 1]

            # 再放出/反射粒子: 交点内側から残余時間を完走させて再 walk
            cont = wall | sym
            c_idx = act[cont]
            if c_idx.size == 0:
                act = np.zeros(0, dtype=np.int64)
                break
            x_from[c_idx] = inside[cont]
            e_from[c_idx] = ea[cont]
            x_new[c_idx] = inside[cont] + t_rem[c_idx][:, None] * self.v[c_idx, :2]
            e2, a2, be2, bl2 = _walk_step(
                self.coeffs, self.adjacency, ea[cont], x_new[c_idx], packed=self._packed
            )
            elem_new[c_idx] = e2
            b_elem[c_idx] = be2
            b_loc[c_idx] = bl2
            act = c_idx[a2]

        # レグ上限に達しても未解決の粒子 (稀): 直近の交点内側で停止させる
        if act.size:
            x_new[act] = x_from[act]
            elem_new[act] = e_from[act]

        # 固体 (誘電体) 要素へ入った粒子: 移動を取り消し、壁温の等方 Maxwell で再抽選
        if self._solid is not None:
            in_solid = ~remove & self._solid[elem_new]
            if np.any(in_solid):
                s_idx = np.nonzero(in_solid)[0]
                x_new[s_idx] = self.x[s_idx]
                elem_new[s_idx] = self.elem[s_idx]
                sigw = math.sqrt(KB * self.s.wall_temperature_k / self.m)
                self.v[s_idx] = self.rng.normal(0.0, sigw, size=(len(s_idx), 3))

        keep = ~remove
        self.x = x_new[keep]
        self.v = self.v[keep]
        self.elem = elem_new[keep]

    # ---- NTC 衝突 -------------------------------------------------------------

    def _collide(self) -> None:
        """NTC 法のセル内2体衝突 (VHS、COM 系等方散乱)。

        セルごとの候補対数 N_cand = ½ N(N−1) W (σc_r)_max Δt / V を端数持ち越しで
        抽選し、σ(c_r)c_r/(σc_r)_max で採択する。同一粒子が同ステップ内で複数対に
        選ばれた場合は後の衝突が上書きする近似 (候補数が少なければ影響は僅少)。
        """
        n = len(self.x)
        if n < 2:
            return
        counts = np.bincount(self.elem, minlength=len(self.tris))
        order = np.argsort(self.elem, kind="stable")
        starts = np.zeros(len(self.tris) + 1, dtype=np.int64)
        np.cumsum(counts, out=starts[1:])

        vol = self.area  # × 奥行き 1 m
        n_cand_f = (
            0.5 * counts * np.maximum(counts - 1, 0) * self.w
            * self._sigcr_max * self.dt / vol
            + self._coll_frac
        )
        n_cand = n_cand_f.astype(np.int64)
        self._coll_frac = n_cand_f - n_cand
        n_cand = np.where(counts >= 2, n_cand, 0)
        total = int(n_cand.sum())
        if total == 0:
            return

        cell = np.repeat(np.arange(len(self.tris)), n_cand)
        c_cnt = counts[cell]
        r1 = (self.rng.random(total) * c_cnt).astype(np.int64)
        r2 = (self.rng.random(total) * c_cnt).astype(np.int64)
        valid = r1 != r2
        cell, r1, r2 = cell[valid], r1[valid], r2[valid]
        i1 = order[starts[cell] + r1]
        i2 = order[starts[cell] + r2]

        g = self.v[i1] - self.v[i2]
        g_mag = np.sqrt(np.sum(g * g, axis=1))
        sig_cr = self._sigma(g_mag) * g_mag
        # (σc_r)_max の実測更新 (セルごとの最大値)
        np.maximum.at(self._sigcr_max, cell, sig_cr)
        accept = self.rng.random(len(cell)) * self._sigcr_max[cell] < sig_cr
        if not np.any(accept):
            return
        i1, i2 = i1[accept], i2[accept]
        g_mag = g_mag[accept]
        cell_a = cell[accept]

        # 同一粒子を含む複数対の一括更新はエネルギー保存を壊す (古い速度で計算した
        # 相手側更新が上書きされ、分散が湧いて数値加熱する)。各粒子について最初に
        # 現れた対のみ実行し、落とした対は候補として次ステップへ持ち越す
        pos = np.arange(len(i1))
        first = np.full(len(self.x), len(i1), dtype=np.int64)
        np.minimum.at(first, i1, pos)
        np.minimum.at(first, i2, pos)
        keep = (first[i1] == pos) & (first[i2] == pos)
        if not np.all(keep):
            np.add.at(self._coll_frac, cell_a[~keep], 1.0)
            i1, i2 = i1[keep], i2[keep]
            g_mag = g_mag[keep]
        if len(i1) == 0:
            return
        k = len(i1)
        # COM 系で等方散乱 (|g| 保存)
        cos_t = 1.0 - 2.0 * self.rng.random(k)
        sin_t = np.sqrt(np.maximum(1.0 - cos_t * cos_t, 0.0))
        phi = 2.0 * math.pi * self.rng.random(k)
        d_new = np.stack(
            [sin_t * np.cos(phi), sin_t * np.sin(phi), cos_t], axis=1
        )
        v_com = 0.5 * (self.v[i1] + self.v[i2])
        half_g = 0.5 * g_mag[:, None] * d_new
        self.v[i1] = v_com + half_g
        self.v[i2] = v_com - half_g

    # ---- サンプリングと実行 ---------------------------------------------------

    def _sample(self) -> None:
        cnt = np.bincount(self.elem, minlength=len(self.tris)).astype(np.float64)
        self._acc_cnt += cnt
        for c in range(3):
            self._acc_v[:, c] += np.bincount(
                self.elem, weights=self.v[:, c], minlength=len(self.tris)
            )
        v2 = np.sum(self.v * self.v, axis=1)
        self._acc_v2 += np.bincount(self.elem, weights=v2, minlength=len(self.tris))
        self._samples += 1

    def step(self) -> None:
        self._inject()
        self._move()
        self._collide()

    def run(self, callback=None) -> DsmcResult:
        """n_steps 進め、最終 avg_steps の時間平均から DsmcResult を作る。

        callback(step, n_particles) を 200 ステップごとに呼ぶ (進捗表示用)。
        """
        n_steps = self.s.n_steps
        avg_start = max(0, n_steps - self.s.avg_steps)
        for i in range(n_steps):
            if i == avg_start:
                self._samples = 0  # 以降のステップでサンプリング
                self._acc_cnt[:] = 0.0
                self._acc_v[:] = 0.0
                self._acc_v2[:] = 0.0
                self.inflow = 0.0
                self.outflow = 0.0
            self.step()
            if i >= avg_start:
                self._sample()
            if callback is not None and (i + 1) % 200 == 0:
                callback(i + 1, len(self.x))

        cnt = np.maximum(self._acc_cnt, 1e-300)
        n_avg = self._acc_cnt * self.w / (self._samples * self.area)
        u_mean3 = self._acc_v / cnt[:, None]
        v2_mean = self._acc_v2 / cnt
        # T = m/(3k)·(⟨|v|²⟩ − |⟨v⟩|²) (3成分)
        t_avg = np.maximum(
            self.m / (3.0 * KB) * (v2_mean - np.sum(u_mean3 * u_mean3, axis=1)), 0.0
        )
        # サンプルが無いセル (固体・枯渇) は 0 に落とす
        empty = self._acc_cnt <= 0.0
        t_avg[empty] = 0.0
        u_mean3[empty] = 0.0
        return DsmcResult(
            n=n_avg,
            t=t_avg,
            u=u_mean3[:, :2],
            p=n_avg * KB * t_avg,
            n_particles=len(self.x),
            macro_weight=self.w,
            dt=self.dt,
            inflow=self.inflow,
            outflow=self.outflow,
        )
