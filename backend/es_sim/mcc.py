"""モンテカルロ衝突 (MCC, null-collision 法)。prompts/19 参照。

- 前処理: 全プロセステーブルの最大エネルギー (安全率 2 倍) までの共通グリッドで
  ν_tot(E) = Σ_j n_g σ_j(E) v(E) を評価し、ν_max = max_E ν_tot を求める
  (n_g = p/(kB·T_gas))
- 毎ステップ種ごとに: P_coll = 1 − exp(−ν_max·dt) で衝突候補を抽選し、
  候補粒子のエネルギーでの ν_j(E)/ν_max により実プロセス or null を選択する
- 断面積の評価はテーブルの np.interp (範囲外は端点値でクランプ)。
  excitation/ionization はテーブルが閾値から σ=0 で始まるので閾値未満は自然に 0
- 衝突は位置を変えないので所属要素の更新は不要
- 乱数はすべて mcc.seed からのシード付き rng (再現性)
- ホットループは numpy ベクトル化 (粒子 for ループなし。プロセス数分の
  小さなループのみ)
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .particles import ME, QE
from .schema import MccSettings, XsProcess

KB = 1.380649e-23  # ボルツマン定数 [J/K]

# ν_max 評価用エネルギーグリッドの点数
_NU_GRID_N = 4096
# グリッド上限のテーブル最大エネルギーに対する安全率 (範囲外クランプ σ でも
# v(E) が伸びる分を吸収する)
_NU_GRID_MARGIN = 2.0


@dataclass
class _Proc:
    """前処理済みプロセステーブル (numpy 配列)。"""

    kind: str
    threshold_ev: float
    mass_ratio: float
    e: np.ndarray  # (K,) エネルギー [eV] (昇順)
    s: np.ndarray  # (K,) 断面積 [m^2]


@dataclass
class ElectronCollisionResult:
    """collide_electrons の結果。速度は in-place 更新し、生成粒子のみ返す。"""

    n_coll: int = 0              # 実衝突数 (elastic + excitation + ionization)
    n_ionization: int = 0        # 電離数
    new_x: np.ndarray | None = None     # 電離位置 (新電子・新イオン共通)
    new_elem: np.ndarray | None = None  # 所属要素 (入射電子と同じ)
    new_w: np.ndarray | None = None     # マクロ重み (入射電子と同じ)
    new_v_e: np.ndarray | None = None   # 放出電子の速度
    new_v_i: np.ndarray | None = None   # 新イオンの速度 (ガス温度 Maxwell)


class MccModel:
    """null-collision MCC。PicSimulation から毎ステップ呼ばれる。"""

    def __init__(self, settings: MccSettings, m_ion: float):
        gas = settings.gas
        self.n_gas = gas.pressure_pa / (KB * gas.temperature_k)  # 中性ガス数密度 [m^-3]
        self.m_ion = m_ion
        # ガス原子の Maxwell 速度分布の成分ごとの標準偏差 (ガス原子質量 = イオン質量とみなす)
        self.vth_gas = math.sqrt(KB * gas.temperature_k / m_ion)
        self.rng = np.random.default_rng(settings.seed)

        self.e_procs = [
            self._conv(p, ("elastic", "excitation", "ionization"))
            for p in settings.electron_processes
        ]
        self.i_procs = [
            self._conv(p, ("isotropic", "backscat")) for p in settings.ion_processes
        ]
        self.numax_e = self._nu_max(self.e_procs, ME)
        self.numax_i = self._nu_max(self.i_procs, m_ion)

    # ---- 前処理 --------------------------------------------------------------

    @staticmethod
    def _conv(p: XsProcess, allowed: tuple[str, ...]) -> _Proc:
        if p.kind not in allowed:
            raise ValueError(f"このプロセスリストでは kind='{p.kind}' は使えません ({p.label})")
        e = np.asarray(p.energy_ev, dtype=np.float64)
        s = np.asarray(p.sigma_m2, dtype=np.float64)
        if np.any(np.diff(e) < 0.0):
            raise ValueError(f"エネルギー列が昇順ではありません: {p.label}")
        return _Proc(p.kind, p.threshold_ev, p.mass_ratio, e, s)

    def _nu_max(self, procs: list[_Proc], m: float) -> float:
        """共通エネルギーグリッド上の ν_tot(E) の最大値。プロセスが無ければ 0。"""
        if not procs:
            return 0.0
        e_cap = _NU_GRID_MARGIN * max(float(p.e[-1]) for p in procs)
        grid = np.linspace(0.0, e_cap, _NU_GRID_N)
        v = np.sqrt(2.0 * grid * QE / m)
        nu = np.zeros_like(grid)
        for p in procs:
            nu += self.n_gas * np.interp(grid, p.e, p.s) * v
        return float(nu.max())

    # ---- 共通: 候補抽選とプロセス選択 -----------------------------------------

    def _select(self, v: np.ndarray, m: float, numax: float, procs: list[_Proc], dt: float):
        """衝突候補の抽選と実プロセスの選択。

        戻り値: (cand, proc_idx, e_ev, speed)。cand は候補粒子のインデックス、
        proc_idx は選ばれたプロセス番号 (-1 = null 衝突)。
        """
        n = len(v)
        p_coll = 1.0 - math.exp(-numax * dt)
        cand = np.nonzero(self.rng.random(n) < p_coll)[0]
        if cand.size == 0:
            return cand, None, None, None
        vv = v[cand]
        speed = np.sqrt(np.sum(vv * vv, axis=1))
        e_ev = 0.5 * m * speed * speed / QE
        nu = np.empty((cand.size, len(procs)))
        for j, p in enumerate(procs):
            nu[:, j] = self.n_gas * np.interp(e_ev, p.e, p.s) * speed
        cum = np.cumsum(nu, axis=1)
        u = self.rng.random(cand.size) * numax
        hit = u < cum[:, -1]
        proc_idx = np.where(hit, np.argmax(u[:, None] < cum, axis=1), -1)
        return cand, proc_idx, e_ev, speed

    def _iso_dir(self, k: int) -> np.ndarray:
        """2D 等方な単位方向ベクトルを k 個サンプルする。"""
        th = self.rng.random(k) * (2.0 * np.pi)
        return np.stack([np.cos(th), np.sin(th)], axis=1)

    # ---- 電子衝突 -------------------------------------------------------------

    def collide_electrons(
        self,
        x: np.ndarray,
        v: np.ndarray,
        w: np.ndarray,
        elem: np.ndarray,
        dt: float,
    ) -> ElectronCollisionResult:
        """電子の MCC。v を in-place 更新し、電離の生成粒子を結果で返す。"""
        res = ElectronCollisionResult()
        if len(v) == 0 or self.numax_e <= 0.0:
            return res
        cand, proc_idx, e_ev, speed = self._select(v, ME, self.numax_e, self.e_procs, dt)
        if cand.size == 0:
            return res

        new_x: list[np.ndarray] = []
        new_elem: list[np.ndarray] = []
        new_w: list[np.ndarray] = []
        new_ve: list[np.ndarray] = []
        new_vi: list[np.ndarray] = []

        for j, p in enumerate(self.e_procs):
            mask = proc_idx == j
            if p.kind in ("excitation", "ionization"):
                mask &= e_ev >= p.threshold_ev  # 閾値未満は null 扱い (通常 σ=0 で選ばれない)
            k = int(mask.sum())
            if k == 0:
                continue
            sub = cand[mask]
            d_new = self._iso_dir(k)  # 2D 等方散乱: 速度方向を一様乱数で回し直す
            if p.kind == "elastic":
                # 散乱角 χ = 旧方向と新方向のなす角。ΔE = 2(m/M)(1−cosχ)E
                d_old = v[sub] / speed[mask][:, None]
                cos_chi = np.sum(d_old * d_new, axis=1)
                e_new = np.maximum(
                    e_ev[mask] * (1.0 - 2.0 * p.mass_ratio * (1.0 - cos_chi)), 0.0
                )
                v[sub] = np.sqrt(2.0 * e_new * QE / ME)[:, None] * d_new
            elif p.kind == "excitation":
                # E − 閾値 に減速して等方散乱
                e_new = e_ev[mask] - p.threshold_ev
                v[sub] = np.sqrt(2.0 * e_new * QE / ME)[:, None] * d_new
            else:  # ionization
                # 余剰 E − 閾値 を一様乱数比で散乱電子/放出電子に分配 (両者等方)
                excess = e_ev[mask] - p.threshold_ev
                r = self.rng.random(k)
                e_scat = r * excess
                e_eject = excess - e_scat
                v[sub] = np.sqrt(2.0 * e_scat * QE / ME)[:, None] * d_new
                new_ve.append(np.sqrt(2.0 * e_eject * QE / ME)[:, None] * self._iso_dir(k))
                # 新イオンはガス温度の Maxwell 速度
                new_vi.append(self.rng.normal(0.0, self.vth_gas, size=(k, 2)))
                new_x.append(x[sub].copy())
                new_elem.append(elem[sub].copy())
                new_w.append(w[sub].copy())  # マクロ重みは入射電子と同じ
                res.n_ionization += k
            res.n_coll += k

        if new_x:
            res.new_x = np.concatenate(new_x)
            res.new_elem = np.concatenate(new_elem)
            res.new_w = np.concatenate(new_w)
            res.new_v_e = np.concatenate(new_ve)
            res.new_v_i = np.concatenate(new_vi)
        return res

    # ---- イオン衝突 -----------------------------------------------------------

    def collide_ions(self, v: np.ndarray, dt: float) -> int:
        """イオンの MCC。v を in-place 更新し、実衝突数を返す。

        断面積テーブルの energy_ev は実験室系イオンエネルギーとして解釈する。
        """
        if len(v) == 0 or self.numax_i <= 0.0:
            return 0
        cand, proc_idx, _, _ = self._select(v, self.m_ion, self.numax_i, self.i_procs, dt)
        if cand.size == 0:
            return 0
        n_coll = 0
        for j, p in enumerate(self.i_procs):
            mask = proc_idx == j
            k = int(mask.sum())
            if k == 0:
                continue
            sub = cand[mask]
            vg = self.rng.normal(0.0, self.vth_gas, size=(k, 2))  # ガス原子の Maxwell 速度
            if p.kind == "backscat":
                # 電荷交換: イオン速度をガス原子の速度で置き換える
                v[sub] = vg
            else:  # isotropic: 等質量弾性衝突、COM 等方散乱 (|g| 保存)
                g = v[sub] - vg
                g_mag = np.sqrt(np.sum(g * g, axis=1))
                v_com = 0.5 * (v[sub] + vg)
                v[sub] = v_com + 0.5 * g_mag[:, None] * self._iso_dir(k)
            n_coll += k
        return n_coll
