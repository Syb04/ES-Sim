"""プロジェクト JSON のスキーマ (pydantic)。仕様書 §10 参照。

このモデルがプロジェクトファイルの唯一の正。
フロントエンドの TypeScript 型 (src/types.ts) はこれと手動同期する。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

Point = tuple[float, float]


class Domain(BaseModel):
    polygon: list[Point] = Field(..., min_length=3, description="解析領域の外周 (閉ポリゴン、反時計回り)")


class CircleShape(BaseModel):
    """円領域のパラメトリック形状。メッシュ生成時に多角形化する (meshing._region_polygon 参照)。"""

    kind: Literal["circle"] = "circle"
    center: Point
    radius: float = Field(..., gt=0)


class VoltageRF(BaseModel):
    """RF 電圧成分 (フェーズ3)。V(t) = voltage + amplitude * sin(2π f t + phase)。

    静電ソルブ (/solve) は従来通り直流分 voltage のみを使い、PIC のみが V(t) を使う。
    """

    amplitude: float
    freq_hz: float = Field(..., gt=0)
    phase_deg: float = 0.0


class Region(BaseModel):
    id: str
    type: Literal["conductor", "dielectric", "charge"]
    polygon: list[Point] | None = Field(None, min_length=3)
    shape: CircleShape | None = None
    voltage: float | None = None  # conductor: 電位 [V] (直流分)
    voltage_rf: VoltageRF | None = None  # conductor: RF 成分 (PIC のみ使用)
    eps_r: float = 1.0            # dielectric: 比誘電率
    rho: float = 0.0              # charge: 電荷密度 [C/m^3]
    see_gamma: float = Field(0.0, ge=0, description="conductor: 二次電子放出係数 γ (0 = 無効、PIC のみ使用)")

    @model_validator(mode="after")
    def _check_polygon_xor_shape(self) -> "Region":
        if (self.polygon is None) == (self.shape is None):
            raise ValueError("Region には polygon か shape のどちらか一方のみを指定してください")
        return self


class BoundaryCondition(BaseModel):
    """domain 外周のエッジ単位の境界条件。

    edges: 外周ポリゴンのエッジ番号 (i 番目のエッジは頂点 i → i+1)。
    未指定のエッジは自然境界 (Neumann, dV/dn = 0)。

    type (prompts/22、フロントと共通のスキーマ契約):
      - "dirichlet": 固定電位。voltage / voltage_rf / see_gamma は dirichlet のみ有効
      - "symmetry":  対称境界。場は自然境界 (Neumann)、粒子 (trace / PIC) は鏡面反射
      - "periodic":  周期境界。edges にちょうど2本の対辺 (平行・同長) を指定する。
                     場は対辺の節点 DOF を同一視して解き、粒子は反対側へラップする
    """

    edges: list[int]
    type: Literal["dirichlet", "symmetry", "periodic"] = "dirichlet"
    voltage: float = 0.0
    voltage_rf: VoltageRF | None = None  # RF 成分 (PIC のみ使用)
    see_gamma: float = Field(0.0, ge=0, description="二次電子放出係数 γ (0 = 無効、PIC のみ使用)")

    @model_validator(mode="after")
    def _check_periodic_edge_count(self) -> "BoundaryCondition":
        if self.type == "periodic":
            if len(self.edges) != 2 or self.edges[0] == self.edges[1]:
                raise ValueError("periodic 境界には異なるエッジをちょうど2本指定してください")
        return self


class Geometry(BaseModel):
    domain: Domain
    regions: list[Region] = []
    boundaries: list[BoundaryCondition] = []

    @model_validator(mode="after")
    def _check_periodic_pairs(self) -> "Geometry":
        """periodic 境界の2辺が domain の平行・同長の対辺であることを検査する。"""
        poly = self.domain.polygon
        n = len(poly)
        for bc in self.boundaries:
            if bc.type != "periodic":
                continue
            for e in bc.edges:
                if not (0 <= e < n):
                    raise ValueError(f"periodic 境界のエッジ番号 {e} が範囲外です (0..{n - 1})")
            e1, e2 = bc.edges
            d1 = (poly[(e1 + 1) % n][0] - poly[e1][0], poly[(e1 + 1) % n][1] - poly[e1][1])
            d2 = (poly[(e2 + 1) % n][0] - poly[e2][0], poly[(e2 + 1) % n][1] - poly[e2][1])
            l1 = (d1[0] ** 2 + d1[1] ** 2) ** 0.5
            l2 = (d2[0] ** 2 + d2[1] ** 2) ** 0.5
            if l1 <= 0.0 or l2 <= 0.0:
                raise ValueError("periodic 境界のエッジが退化しています (長さ 0)")
            cross = d1[0] * d2[1] - d1[1] * d2[0]
            if abs(cross) > 1e-6 * l1 * l2 or abs(l1 - l2) > 1e-6 * max(l1, l2):
                raise ValueError(
                    f"periodic 境界のエッジ {e1}, {e2} は平行かつ同じ長さの対辺である必要があります"
                )
        return self


class LocalSize(BaseModel):
    region: str
    size: float


class MeshSettings(BaseModel):
    size: float = Field(..., gt=0, description="全体特性長 [m]")
    local_sizes: list[LocalSize] = []


class SolverSettings(BaseModel):
    backend: Literal["numpy", "cupy", "auto"] = "numpy"


# ---- 粒子軌道追跡 (フェーズ2、仕様書 §8) --------------------------------------


class Species(BaseModel):
    """粒子種。electron/proton プリセット、または custom で q・m を直接指定する。"""

    preset: Literal["electron", "proton", "custom"] = "electron"
    q: float | None = None  # custom 時の電荷 [C]
    m: float | None = None  # custom 時の質量 [kg]

    @model_validator(mode="after")
    def _check_custom_qm(self) -> "Species":
        if self.preset == "custom" and (self.q is None or self.m is None):
            raise ValueError("preset='custom' には q と m の指定が必要です")
        return self


class Emitter(BaseModel):
    """粒子源。

    line: p1-p2 の線分上に n 個を等間隔配置。point: p1 に全粒子を配置 (p2 は無視)。
    direction_deg は x 軸から反時計回りの射出方向 [度]、spread_deg はその一様分布
    半角 [度] (乱数は使わず、n 個に等間隔で振り分ける)。
    """

    kind: Literal["line", "point"] = "line"
    p1: Point
    p2: Point | None = None
    n: int = Field(..., gt=0)
    energy_ev: float = 0.0
    direction_deg: float = 0.0
    spread_deg: float = 0.0
    energy_dist: Literal["mono", "maxwell"] = "mono"  # "mono": 従来動作 / "maxwell": 熱速度成分を付加
    temperature_ev: float = Field(1.0, gt=0, description="maxwell 時の温度 kT [eV]")
    seed: int = 0  # maxwell サンプリングの乱数シード (再現性確保)

    @model_validator(mode="after")
    def _check_line_needs_p2(self) -> "Emitter":
        if self.kind == "line" and self.p2 is None:
            raise ValueError("kind='line' には p2 の指定が必要です")
        return self


class ParticleSettings(BaseModel):
    species: Species = Species()
    emitter: Emitter
    dt: float | None = None  # 秒。None なら自動推定 (particles.py 参照)
    n_steps: int = Field(5000, gt=0)
    save_every: int = Field(10, gt=0)


# ---- PIC (フェーズ3、仕様書 §9) ----------------------------------------------


class InitialPlasma(BaseModel):
    """初期プラズマの一様装荷。null なら初期装荷なし。"""

    density: float = Field(..., gt=0, description="数密度 [m^-3] (奥行き1m換算)")
    te_ev: float = Field(2.0, ge=0, description="電子温度 kTe [eV]")
    ti_ev: float = Field(0.03, ge=0, description="イオン温度 kTi [eV]")
    ion_mass_amu: float = Field(40.0, gt=0, description="イオン質量 [amu] (Ar+ = 40)")
    immobile_ions: bool = False  # true でイオン固定 (検証用)
    seed: int = 0


class PicInjection(BaseModel):
    """エミッタからの定常注入。電流 [A/m] を毎ステップの実電荷として等分注入する。"""

    emitter: Emitter
    species: Literal["electron", "ion"] = "electron"
    current_a_per_m: float = Field(..., gt=0)


# ---- MCC 衝突 (prompts/19、フロントと共通のスキーマ契約) ------------------------


class XsProcess(BaseModel):
    """LXCat 由来の衝突断面積プロセス (パース済み、プロジェクト JSON に埋め込む)。"""

    kind: Literal["elastic", "excitation", "ionization", "isotropic", "backscat"]
    label: str = ""                # PROCESS 行等から
    threshold_ev: float = 0.0      # excitation/ionization のみ >0
    mass_ratio: float = 0.0        # elastic のみ (m/M)。無ければ 0
    energy_ev: list[float]         # 断面積テーブルのエネルギー [eV] (昇順)
    sigma_m2: list[float]          # 断面積 [m^2] (energy_ev と同長)

    @model_validator(mode="after")
    def _check_table(self) -> "XsProcess":
        if len(self.energy_ev) != len(self.sigma_m2):
            raise ValueError("energy_ev と sigma_m2 は同じ長さが必要です")
        if len(self.energy_ev) == 0:
            raise ValueError("断面積テーブルが空です")
        return self


class MccGas(BaseModel):
    """背景中性ガスの状態。数密度は n_g = p/(kB·T) で決まる。"""

    name: str = "Ar"
    pressure_pa: float = Field(..., gt=0, description="ガス圧 [Pa]")
    temperature_k: float = Field(300.0, gt=0, description="ガス温度 [K]")


class MccSettings(BaseModel):
    """MCC 設定。null なら MCC 無効 (従来の無衝突動作)。"""

    gas: MccGas
    electron_processes: list[XsProcess] = []  # elastic/excitation/ionization
    ion_processes: list[XsProcess] = []       # isotropic/backscat
    seed: int = 0
    # 電離の余剰エネルギー分配: "half" = 散乱電子と生成電子で等分 (Turner ベンチマーク互換)、
    # "random" = 一様乱数比で分配 (従来動作)
    ionization_split: Literal["half", "random"] = "half"
    # イオン断面積テーブルの参照エネルギー系: "lab" = 実験室系イオンエネルギー (従来動作)、
    # "com" = 重心系エネルギー E = ½μg² (μ = m_i·m_g/(m_i+m_g)、Turner の He+/He データ用)
    ion_energy_frame: Literal["com", "lab"] = "lab"


class Collector(BaseModel):
    """IEDF/IADF コレクタ線分 (prompts/30)。null なら無効。

    平均区間中にコレクタ線分の近傍 (距離 tol 以内・線分区間内) で吸収された
    イオンのエネルギー・入射角・重みを記録する (ウエハ面の IEDF/IADF 取得用)。
    """

    p1: Point
    p2: Point
    tol: float | None = Field(None, gt=0, description="判定距離 [m]。None なら mesh.size と同値")


class PicSettings(BaseModel):
    initial_plasma: InitialPlasma | None = None
    injection: PicInjection | None = None
    n_macro: int = Field(20000, gt=0, description="種ごとの初期マクロ粒子数の目安")
    dt: float | None = Field(None, description="秒。None なら 0.1/ωpe (初期密度から)")
    n_steps: int = Field(2000, gt=0)
    frame_every: int = Field(20, gt=0, description="フレーム送出間隔 (ステップ)")
    mcc: MccSettings | None = None  # null なら MCC 無効
    see_energy_ev: float = Field(2.0, ge=0, description="SEE 電子の初期エネルギー [eV]")
    # 完了時に返す時間平均フィールドの平均ステップ数 (最終 N ステップ、prompts/26)。
    # None なら全ステップの最後の 25% を平均する
    avg_steps: int | None = Field(None, gt=0)
    # RF 1周期の位相分解データ (アニメーション用) の位相ビン数 (prompts/28)。
    # 0 で無効。RF (voltage_rf) が未設定の場合も無効
    phase_bins: int = Field(40, ge=0)
    # IEDF/IADF コレクタ線分 (prompts/30)。null なら無効
    collector: Collector | None = None
    # 鏡面反射する domain 外周エッジ番号のリスト (エッジ i は頂点 i → i+1)。
    # 到達粒子は吸収せず法線速度成分を反転して境界内へ折り返す (壁カウンタに含めない)。
    # 当該エッジは境界条件なし (Neumann) を想定。2D ストリップで 1D 問題を模擬する用途
    reflect_edges: list[int] = Field(default_factory=list)


class Project(BaseModel):
    version: int = 1
    unit: Literal["m", "mm"] = "m"
    geometry: Geometry
    mesh: MeshSettings
    solver: SolverSettings = SolverSettings()
    particles: ParticleSettings | None = None
    pic: PicSettings | None = None


# ---- API レスポンス ----------------------------------------------------------


class MeshResult(BaseModel):
    nodes: list[Point]                  # 節点座標 [m]
    triangles: list[tuple[int, int, int]]  # 要素 → 節点番号
    region_of_triangle: list[int]       # 要素 → regions のインデックス (-1: 背景=真空)


class SolveResult(BaseModel):
    mesh: MeshResult
    v: list[float]                      # 節点電位 [V]
    e_field: list[tuple[float, float]]  # 要素ごとの E = -∇V [V/m]
    v_min: float
    v_max: float
    e_abs_max: float
    energy: float                       # 蓄積エネルギー W = 1/2 ∫ ε|E|^2 dΩ [J/m (奥行き単位)]


class ProfileRequest(BaseModel):
    project: Project
    p1: Point
    p2: Point
    n: int = 200


class ProfileResult(BaseModel):
    s: list[float]                # 弧長 (p1 からの距離) [m]
    v: list[float | None]         # 電位 [V] (領域外は None)
    e_abs: list[float | None]     # |E| [V/m] (領域外は None)


class LxcatParseRequest(BaseModel):
    """POST /lxcat/parse のリクエスト。"""

    text: str
    species: Literal["electron", "ion"]


class LxcatParseResult(BaseModel):
    processes: list[XsProcess]
    warnings: list[str]


class TraceResult(BaseModel):
    trajectories: list[list[Point]]            # 粒子ごと、save_every ステップごと (初期位置含む)
    status: list[Literal["absorbed", "alive"]]
    tof: list[float | None]                    # absorbed 粒子の飛行時間 [s]
    final_energy_ev: list[float]
    final_angle_deg: list[float]                # 最終速度の向き [度] (x軸から反時計回り, -180〜180)
    dt: float                                  # 実際に使った dt [s]
