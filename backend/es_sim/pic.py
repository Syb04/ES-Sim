"""FEM-PIC (フェーズ3)。仕様書 §9 参照。

サイクル (PicSimulation.step):
  1. 電荷堆積: P1 形状関数 (重心座標) の重みで粒子電荷を節点荷重ベクトルへ散布
  2. ポアソン求解: 剛性行列は固定なので splu を初回のみ実行し、右辺のみ更新。
     Dirichlet 値は V(t) = V_dc + A sin(2πft + φ) で毎ステップ更新 (RF 電極対応)
  3. E 補間 (P1 なので所属要素の一定値) → 4. リープフロッグでプッシュ →
  5. walk 更新・境界吸収 (壁到達粒子は除去、種別ごとに集計) → 6. 注入

- 粒子種は常に electron / ion の2種を管理する
- リープフロッグの速度は半整数ステップに置く。装荷時・注入時に初期半ステップ
  後退キック v(-dt/2) = v(0) - (q/m) E(x) dt/2 を適用する
- 診断は毎ステップ記録。運動エネルギーは v(n-1/2)·v(n+1/2) の時刻中心化で評価し、
  場のエネルギー (整数ステップ) と整合させる
- 安定性チェック: 開始時に ωpe·dt とセルサイズ/デバイ長を確認して警告文字列を返す
- ホットループは numpy ベクトル化 (粒子 for ループなし)。walk 探索・隣接配列・
  重心座標係数は particles.py の実装を再利用する
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import scipy.sparse.linalg as spla

from .fem import EPS0, _material_arrays, assemble
from .mcc import MccModel
from .meshing import generate_mesh
from .particles import (
    ME,
    MP,
    QE,
    _adjacency,
    _barycentric_coeffs,
    _init_particles,
    _locate_initial,
    _walk_step,
)
from .schema import PicSettings, Project

# フレーム送出時の種ごとの最大粒子数 (間引き)
MAX_FRAME_PARTICLES = 2000


@dataclass
class PicSpecies:
    """マクロ粒子種。状態はすべて numpy 配列で保持する。"""

    name: str
    q: float               # 電荷 [C]
    m: float               # 質量 [kg]
    x: np.ndarray          # (n, 2) 位置 [m]
    v: np.ndarray          # (n, 2) 速度 [m/s] (リープフロッグの半整数ステップ)
    w: np.ndarray          # (n,) マクロ重み (実粒子数/マクロ粒子)
    elem: np.ndarray       # (n,) 所属要素番号
    mobile: bool = True    # False ならプッシュしない (immobile_ions)
    wall_absorbed: int = 0  # 壁吸収の累計 (マクロ粒子数)


class PicSimulation:
    """FEM-PIC シミュレーション本体。

    __init__ でメッシュ生成・FEM 行列組み立て・K_ff の LU 前分解 (1回のみ) を行い、
    step() ごとに右辺のみ更新して解く。
    """

    def __init__(self, project: Project):
        if project.pic is None:
            raise ValueError("project.pic が指定されていません")
        self.project = project
        self.pic: PicSettings = project.pic

        # ---- メッシュ・幾何前処理 (particles.py の実装を再利用) --------------
        self.mesh = generate_mesh(project)
        mesh = self.mesh
        self.n_nodes = len(mesh.nodes)
        self.tris = mesh.triangles
        self.coeffs = _barycentric_coeffs(mesh.nodes, self.tris)  # (a, b, c, det)
        self.adjacency = _adjacency(self.tris)
        det = self.coeffs[3]
        self.area = 0.5 * np.abs(det)          # (M,) 要素面積
        self.eps_elem, _ = _material_arrays(project, mesh)  # (M,) 要素ごとの ε

        # ---- FEM 行列: K_ff を splu で1回だけ前分解 --------------------------
        k, self.f_static = assemble(project, mesh)  # 静的 charge 領域の右辺を含む
        items = sorted(mesh.dirichlet.items())      # 節点順に固定して決定的に
        self.fixed = np.array([i for i, _ in items], dtype=np.int64)
        self.v_dc = np.array([v for _, v in items], dtype=np.float64)
        rf = mesh.dirichlet_rf
        self.rf_amp = np.array([rf.get(i, (0.0, 0.0, 0.0))[0] for i, _ in items])
        self.rf_omega = np.array(
            [2.0 * math.pi * rf.get(i, (0.0, 0.0, 0.0))[1] for i, _ in items]
        )
        self.rf_phase = np.array(
            [math.radians(rf.get(i, (0.0, 0.0, 0.0))[2]) for i, _ in items]
        )
        self.free = np.setdiff1d(np.arange(self.n_nodes), self.fixed)
        if len(self.free) == 0:
            raise ValueError("自由節点がありません (全節点が Dirichlet)")
        self.k_fd = k[self.free][:, self.fixed].tocsr()
        self.lu = spla.splu(k[self.free][:, self.free].tocsc())

        # ---- dt とプラズマパラメータ -----------------------------------------
        ip = self.pic.initial_plasma
        amu = ip.ion_mass_amu if ip is not None else 40.0
        self.m_ion = amu * MP
        wpe = 0.0
        if ip is not None:
            wpe = math.sqrt(ip.density * QE**2 / (EPS0 * ME))
        if self.pic.dt is not None:
            self.dt = float(self.pic.dt)
        elif wpe > 0.0:
            self.dt = 0.1 / wpe  # 既定: ωpe·dt = 0.1
        else:
            raise ValueError("pic.dt を指定してください (初期密度が無いため自動決定できません)")

        # ---- 安定性チェック (警告のみ、実行は継続) ---------------------------
        self.warnings: list[str] = []
        if wpe > 0.0:
            if wpe * self.dt > 0.3:
                self.warnings.append(
                    f"ωpe·dt = {wpe * self.dt:.3g} > 0.3: 時間刻みが粗すぎます (数値不安定の恐れ)"
                )
            if ip.te_ev > 0.0:
                lam_d = math.sqrt(EPS0 * ip.te_ev * QE / (ip.density * QE**2))
                p = mesh.nodes[self.tris]
                edges = (
                    np.linalg.norm(p[:, 0] - p[:, 1], axis=1)
                    + np.linalg.norm(p[:, 1] - p[:, 2], axis=1)
                    + np.linalg.norm(p[:, 2] - p[:, 0], axis=1)
                ) / 3.0
                h_mean = float(edges.mean())
                if h_mean > 3.0 * lam_d:
                    self.warnings.append(
                        f"平均セルサイズ {h_mean:.3g} m > 3×デバイ長 {lam_d:.3g} m: "
                        "メッシュがデバイ長を解像していません"
                    )

        # ---- 初期プラズマ装荷 -------------------------------------------------
        # 電子・イオンを同一位置に装荷して初期の厳密な電気的中性を保つ (quiet start)
        self.species: dict[str, PicSpecies] = {}
        if ip is not None:
            rng = np.random.default_rng(ip.seed)
            n_macro = self.pic.n_macro
            area_total = float(self.area.sum())
            w0 = ip.density * area_total / n_macro  # マクロ重み (奥行き1m換算)
            x0, elem0 = self._sample_uniform(rng, n_macro)
            for name, q, m, t_ev, mobile in (
                ("electron", -QE, ME, ip.te_ev, True),
                ("ion", QE, self.m_ion, ip.ti_ev, not ip.immobile_ions),
            ):
                sigma = math.sqrt(t_ev * QE / m) if t_ev > 0.0 else 0.0
                v = (
                    rng.normal(0.0, sigma, size=(n_macro, 2))
                    if sigma > 0.0
                    else np.zeros((n_macro, 2))
                )
                self.species[name] = PicSpecies(
                    name, q, m, x0.copy(), v, np.full(n_macro, w0), elem0.copy(), mobile
                )
        else:
            for name, q, m in (("electron", -QE, ME), ("ion", QE, self.m_ion)):
                self.species[name] = PicSpecies(
                    name, q, m,
                    np.zeros((0, 2)), np.zeros((0, 2)),
                    np.zeros(0), np.zeros(0, dtype=np.int64),
                )

        # ---- 注入の前計算 (エミッタ形状は固定なので所属要素をキャッシュ) ------
        inj = self.pic.injection
        if inj is not None:
            sp = self.species[inj.species]
            pos, vel = _init_particles(inj.emitter, sp.m)
            self._inj_pos = pos
            self._inj_vel_base = vel  # mono の場合の決定的な速度
            self._inj_elem = _locate_initial(self.coeffs, pos)
            self._inj_rng = np.random.default_rng(inj.emitter.seed)
            # 毎ステップの実電荷 I·dt を n 個のマクロ粒子へ等分
            self._inj_w = inj.current_a_per_m * self.dt / (QE * inj.emitter.n)

        # ---- MCC (モンテカルロ衝突、prompts/19) ------------------------------
        # mcc=null なら無効 (従来の無衝突動作と完全一致)
        self.mcc = MccModel(self.pic.mcc, self.m_ion) if self.pic.mcc is not None else None

        # ---- SEE (二次電子放出) の境界エッジ属性表 ----------------------------
        mcc_seed = self.pic.mcc.seed if self.pic.mcc is not None else 0
        self._see_rng = np.random.default_rng(mcc_seed + 12345)
        self._see_speed = math.sqrt(2.0 * self.pic.see_energy_ev * QE / ME)
        self._build_see_edges()

        # ---- 診断・時刻 -------------------------------------------------------
        self.t = 0.0
        self.step_count = 0
        # 累計カウンタ (既存フィールドは変更せず追加のみ: フロントの後方互換)
        self.coll_e = 0      # 電子衝突の累計
        self.ion_events = 0  # 電離の累計
        self.see_events = 0  # SEE 発生の累計
        self.history: dict[str, list[float]] = {
            k: []
            for k in (
                "t", "ke_e", "ke_i", "fe", "n_e", "n_i",
                "wall_e", "wall_i", "phi_min", "phi_max",
                "coll_e", "ion_events", "see_events",
            )
        }
        self._f_immobile: dict[str, np.ndarray] = {}  # 不動種の堆積キャッシュ

        # ---- 初期半ステップ後退キック (t=0 の場で v を -dt/2 へ) --------------
        phi0 = self._solve_phi(self._deposit(), 0.0)
        ex, ey = self._e_field(phi0)
        for sp in self.species.values():
            if sp.mobile and len(sp.x):
                e_at = np.stack([ex[sp.elem], ey[sp.elem]], axis=1)
                sp.v -= 0.5 * self.dt * (sp.q / sp.m) * e_at

    # ---- 内部処理 -----------------------------------------------------------

    def _build_see_edges(self) -> None:
        """境界エッジ (隣接 = -1) ごとの SEE 属性表を構築する。

        エッジ両端の節点がともに γ>0 の電極/Dirichlet 辺に属する場合に、
        γ (両端の最小値)・内向き単位法線・境界からわずかに内側へ置く
        オフセット量を (要素, ローカルエッジ) で引ける配列に記録する。
        """
        self._edge_gamma: np.ndarray | None = None
        gm_dict = self.mesh.see_gamma
        if not gm_dict:
            return
        gm = np.zeros(self.n_nodes)
        gm[np.fromiter(gm_dict.keys(), dtype=np.int64)] = np.fromiter(
            gm_dict.values(), dtype=np.float64
        )
        # 境界エッジ: adjacency[t, i] == -1 (頂点 i の対辺)
        ts, loc = np.nonzero(self.adjacency == -1)
        n1 = self.tris[ts, (loc + 1) % 3]
        n2 = self.tris[ts, (loc + 2) % 3]
        n_opp = self.tris[ts, loc]
        g_edge = np.minimum(gm[n1], gm[n2])  # 両端とも γ>0 のときのみ >0
        if not np.any(g_edge > 0.0):
            return
        nodes = self.mesh.nodes
        p1, p2, po = nodes[n1], nodes[n2], nodes[n_opp]
        mid = 0.5 * (p1 + p2)
        t_vec = p2 - p1
        perp = np.stack([-t_vec[:, 1], t_vec[:, 0]], axis=1)
        # 内向き = 対頂点の側
        sgn = np.where(np.sum(perp * (po - mid), axis=1) >= 0.0, 1.0, -1.0)
        nrm = perp * (sgn / np.linalg.norm(perp, axis=1))[:, None]
        h = np.abs(np.sum((po - mid) * nrm, axis=1))  # エッジから対頂点までの高さ

        m = len(self.tris)
        self._edge_gamma = np.zeros((m, 3))
        self._edge_normal = np.zeros((m, 3, 2))
        self._edge_delta = np.zeros((m, 3))
        self._edge_gamma[ts, loc] = g_edge
        self._edge_normal[ts, loc] = nrm
        self._edge_delta[ts, loc] = 1e-3 * h  # 境界からわずかに内側

    def _emit_see(
        self,
        sp: PicSpecies,
        x_new: np.ndarray,
        b_elem: np.ndarray,
        b_loc: np.ndarray,
        absorbed: np.ndarray,
    ) -> None:
        """γ>0 の電極エッジに吸収されたイオンから確率 γ で二次電子を放出する。

        位置 = 吸収位置 (境界エッジとの交点をわずかに内側へ)、
        速度 = 内向き法線方向に see_energy_ev、重み = 吸収イオンと同じ。
        sp.x は更新前 (プッシュ前) の位置であることを前提とする。
        """
        idx = np.nonzero(absorbed)[0]
        ea = b_elem[idx]
        eloc = b_loc[idx]
        gam = self._edge_gamma[ea, eloc]
        cand = gam > 0.0
        if not np.any(cand):
            return
        c_idx = idx[cand]
        ea, eloc = ea[cand], eloc[cand]
        accept = self._see_rng.random(len(c_idx)) < gam[cand]
        if not np.any(accept):
            return
        c_idx, ea, eloc = c_idx[accept], ea[accept], eloc[accept]

        # 吸収位置: 越えたエッジの重心座標 L=0 を x_prev → x_new で線形補間
        a, b, c, det = self.coeffs
        aa, bb, cc, dd = a[ea, eloc], b[ea, eloc], c[ea, eloc], det[ea]
        xp, xn = sp.x[c_idx], x_new[c_idx]
        l0 = (aa + bb * xp[:, 0] + cc * xp[:, 1]) / dd
        l1 = (aa + bb * xn[:, 0] + cc * xn[:, 1]) / dd
        denom = l0 - l1
        denom = np.where(np.abs(denom) < 1e-300, 1e-300, denom)
        frac = np.clip(l0 / denom, 0.0, 1.0)
        x_hit = xp + frac[:, None] * (xn - xp)

        nrm = self._edge_normal[ea, eloc]
        pos = x_hit + self._edge_delta[ea, eloc][:, None] * nrm
        el = self.species["electron"]
        el.x = np.concatenate([el.x, pos])
        el.v = np.concatenate([el.v, self._see_speed * nrm])
        el.w = np.concatenate([el.w, sp.w[c_idx]])
        el.elem = np.concatenate([el.elem, ea])
        self.see_events += len(c_idx)

    def _sample_uniform(self, rng: np.random.Generator, n: int):
        """ドメイン内 (メッシュ要素上 = 電極領域を除く) の一様分布サンプリング。

        要素を面積比例で選び、要素内は重心座標の一様分布で配置する。
        所属要素が同時に確定するので walk 初期化が不要。
        """
        p_elem = self.area / self.area.sum()
        elem = rng.choice(len(self.tris), size=n, p=p_elem).astype(np.int64)
        r1 = np.sqrt(rng.random(n))
        r2 = rng.random(n)
        pts = self.mesh.nodes[self.tris[elem]]  # (n, 3, 2)
        x = (
            (1.0 - r1)[:, None] * pts[:, 0]
            + (r1 * (1.0 - r2))[:, None] * pts[:, 1]
            + (r1 * r2)[:, None] * pts[:, 2]
        )
        return x, elem

    def _deposit_species(self, sp: PicSpecies) -> np.ndarray:
        """1種の電荷を P1 形状関数 (重心座標) の重みで節点へ散布する。

        f_i = Σ_p w_p q_p L_i(x_p)。散布は np.add.at と等価だが高速な
        np.bincount で行う。
        """
        a, b, c, det = self.coeffs
        e = sp.elem
        l = (a[e] + b[e] * sp.x[:, 0:1] + c[e] * sp.x[:, 1:2]) / det[e][:, None]  # (n,3)
        contrib = (sp.q * sp.w)[:, None] * l
        return np.bincount(
            self.tris[e].ravel(), weights=contrib.ravel(), minlength=self.n_nodes
        )

    def _deposit(self) -> np.ndarray:
        """全種の電荷堆積 (不動種はキャッシュを再利用)。"""
        f = np.zeros(self.n_nodes)
        for sp in self.species.values():
            if len(sp.x) == 0:
                continue
            if not sp.mobile:
                if sp.name not in self._f_immobile:
                    self._f_immobile[sp.name] = self._deposit_species(sp)
                f += self._f_immobile[sp.name]
            else:
                f += self._deposit_species(sp)
        return f

    def _dirichlet_values(self, t: float) -> np.ndarray:
        """時刻 t の Dirichlet 値 V(t) = V_dc + A sin(ωt + φ)。"""
        return self.v_dc + self.rf_amp * np.sin(self.rf_omega * t + self.rf_phase)

    def _solve_phi(self, f_dep: np.ndarray, t: float) -> np.ndarray:
        """ポアソン求解。前分解済み LU で右辺のみ更新して解く (再分解しない)。"""
        v = np.zeros(self.n_nodes)
        vd = self._dirichlet_values(t)
        v[self.fixed] = vd
        f = self.f_static + f_dep
        rhs = f[self.free] - self.k_fd @ vd
        v[self.free] = self.lu.solve(rhs)
        return v

    def _e_field(self, phi: np.ndarray):
        """要素ごとの E = -∇φ (P1 なので要素内一定)。"""
        _, b, c, det = self.coeffs
        vt = phi[self.tris]  # (M, 3)
        ex = -np.sum(vt * b, axis=1) / det
        ey = -np.sum(vt * c, axis=1) / det
        return ex, ey

    def _injection_velocities(self) -> np.ndarray:
        """注入粒子の速度。maxwell は持続 rng でステップごとに独立にサンプルする。"""
        inj = self.pic.injection
        em = inj.emitter
        sp = self.species[inj.species]
        if em.energy_dist == "maxwell":
            angle = math.radians(em.direction_deg)
            speed = math.sqrt(2.0 * em.energy_ev * QE / sp.m) if em.energy_ev > 0 else 0.0
            drift = speed * np.array([math.cos(angle), math.sin(angle)])
            sigma = math.sqrt(em.temperature_ev * QE / sp.m)
            return drift[None, :] + self._inj_rng.normal(0.0, sigma, size=(em.n, 2))
        return self._inj_vel_base.copy()

    def _inject(self, ex: np.ndarray, ey: np.ndarray) -> None:
        """エミッタ定常注入。初期半ステップ後退キックを適用して追加する。"""
        inj = self.pic.injection
        sp = self.species[inj.species]
        elem = self._inj_elem
        v = self._injection_velocities()
        e_at = np.stack([ex[elem], ey[elem]], axis=1)
        v -= 0.5 * self.dt * (sp.q / sp.m) * e_at
        n = len(elem)
        sp.x = np.concatenate([sp.x, self._inj_pos])
        sp.v = np.concatenate([sp.v, v])
        sp.w = np.concatenate([sp.w, np.full(n, self._inj_w)])
        sp.elem = np.concatenate([sp.elem, elem])

    # ---- 1ステップ -----------------------------------------------------------

    def step(self) -> np.ndarray:
        """PIC 1サイクル。時刻 t_n の場を解き、粒子を t_{n+1} へ進める。

        戻り値: 時刻 t_n の節点電位 φ (フレーム生成に使う)。
        """
        dt = self.dt
        t = self.t

        # 1. 電荷堆積 → 2. ポアソン求解 (RF 含む V(t) で Dirichlet 更新)
        phi = self._solve_phi(self._deposit(), t)
        # 3. E 補間の準備 (要素ごとの一定値)
        ex, ey = self._e_field(phi)
        fe = float(np.sum(0.5 * self.eps_elem * (ex**2 + ey**2) * self.area))

        # 4. リープフロッグでプッシュ → 5. walk 更新・境界吸収
        ke: dict[str, float] = {}
        for sp in self.species.values():
            if len(sp.x) == 0:
                ke[sp.name] = 0.0
                continue
            if not sp.mobile:
                # 不動種: 運動エネルギーのみ評価
                ke[sp.name] = 0.5 * sp.m * float(np.sum(sp.w * np.sum(sp.v**2, axis=1)))
                continue
            e_at = np.stack([ex[sp.elem], ey[sp.elem]], axis=1)
            v_new = sp.v + (sp.q / sp.m) * dt * e_at
            # 時刻中心化した運動エネルギー: KE(t_n) ≈ ½ m Σ w v(n-1/2)·v(n+1/2)
            ke[sp.name] = 0.5 * sp.m * float(np.sum(sp.w * np.sum(sp.v * v_new, axis=1)))
            x_new = sp.x + dt * v_new
            elem_new, absorbed, b_elem, b_loc = _walk_step(
                self.coeffs, self.adjacency, sp.elem, x_new
            )
            n_abs = int(absorbed.sum())
            if n_abs:
                sp.wall_absorbed += n_abs
                # SEE: γ>0 電極へのイオン吸収で二次電子を生成 (sp.x は更新前の位置)
                if sp.name == "ion" and self._edge_gamma is not None:
                    self._emit_see(sp, x_new, b_elem, b_loc, absorbed)
                keep = ~absorbed
                sp.x = x_new[keep]
                sp.v = v_new[keep]
                sp.w = sp.w[keep]
                sp.elem = elem_new[keep]
            else:
                sp.x = x_new
                sp.v = v_new
                sp.elem = elem_new

        # 5.5. MCC 衝突 (衝突は位置を変えないので所属要素の更新は不要)
        if self.mcc is not None:
            el = self.species["electron"]
            io = self.species["ion"]
            if len(el.x):
                res = self.mcc.collide_electrons(el.x, el.v, el.w, el.elem, dt)
                self.coll_e += res.n_coll
                self.ion_events += res.n_ionization
                if res.new_x is not None:
                    # 電離: 衝突位置に新電子 + 新イオン (ガス温度 Maxwell) を生成
                    el.x = np.concatenate([el.x, res.new_x])
                    el.v = np.concatenate([el.v, res.new_v_e])
                    el.w = np.concatenate([el.w, res.new_w])
                    el.elem = np.concatenate([el.elem, res.new_elem])
                    io.x = np.concatenate([io.x, res.new_x.copy()])
                    io.v = np.concatenate([io.v, res.new_v_i])
                    io.w = np.concatenate([io.w, res.new_w.copy()])
                    io.elem = np.concatenate([io.elem, res.new_elem.copy()])
                    # 不動イオンに追加した場合は堆積キャッシュを無効化
                    self._f_immobile.pop("ion", None)
            if io.mobile and len(io.x):
                self.mcc.collide_ions(io.v, dt)

        # 6. 注入
        if self.pic.injection is not None:
            self._inject(ex, ey)

        self.t = t + dt
        self.step_count += 1

        # 診断記録 (毎ステップ)
        el, io = self.species["electron"], self.species["ion"]
        h = self.history
        h["t"].append(t)
        h["ke_e"].append(ke["electron"])
        h["ke_i"].append(ke["ion"])
        h["fe"].append(fe)
        h["n_e"].append(len(el.x))
        h["n_i"].append(len(io.x))
        h["wall_e"].append(el.wall_absorbed)
        h["wall_i"].append(io.wall_absorbed)
        h["phi_min"].append(float(phi.min()))
        h["phi_max"].append(float(phi.max()))
        h["coll_e"].append(self.coll_e)
        h["ion_events"].append(self.ion_events)
        h["see_events"].append(self.see_events)
        return phi

    # ---- フレーム・実行 -------------------------------------------------------

    def _make_frame(self, phi: np.ndarray) -> dict:
        """WS 送出用フレーム (JSON 化可能な dict)。粒子は種ごと最大2000点に間引く。"""
        particles = {}
        for name, sp in self.species.items():
            n = len(sp.x)
            if n > MAX_FRAME_PARTICLES:
                stride = int(math.ceil(n / MAX_FRAME_PARTICLES))
                pts = sp.x[::stride]
            else:
                pts = sp.x
            particles[name] = pts.tolist()
        diag = {k: v[-1] for k, v in self.history.items()}
        return {
            "type": "frame",
            "step": self.step_count,
            "t": self.t,
            "phi": phi.tolist(),
            "particles": particles,
            "diag": diag,
        }

    def run_batch(self, callback=None, should_stop=None):
        """n_steps 回実行して (診断履歴, フレーム列) を返す (テスト用同期 API)。

        callback(frame) は frame_every ステップごとに呼ばれる。
        should_stop() が True を返したら中断する (WS の stop コマンド用)。
        """
        frames: list[dict] = []
        for _ in range(self.pic.n_steps):
            if should_stop is not None and should_stop():
                break
            phi = self.step()
            if self.step_count % self.pic.frame_every == 0:
                frame = self._make_frame(phi)
                frames.append(frame)
                if callback is not None:
                    callback(frame)
        return self.history, frames
