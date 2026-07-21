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


class Region(BaseModel):
    id: str
    type: Literal["conductor", "dielectric", "charge"]
    polygon: list[Point] | None = Field(None, min_length=3)
    shape: CircleShape | None = None
    voltage: float | None = None  # conductor: 電位 [V]
    eps_r: float = 1.0            # dielectric: 比誘電率
    rho: float = 0.0              # charge: 電荷密度 [C/m^3]

    @model_validator(mode="after")
    def _check_polygon_xor_shape(self) -> "Region":
        if (self.polygon is None) == (self.shape is None):
            raise ValueError("Region には polygon か shape のどちらか一方のみを指定してください")
        return self


class BoundaryCondition(BaseModel):
    """domain 外周のエッジ単位の境界条件。

    edges: 外周ポリゴンのエッジ番号 (i 番目のエッジは頂点 i → i+1)。
    未指定のエッジは自然境界 (Neumann, dV/dn = 0)。
    """

    edges: list[int]
    type: Literal["dirichlet"] = "dirichlet"
    voltage: float = 0.0


class Geometry(BaseModel):
    domain: Domain
    regions: list[Region] = []
    boundaries: list[BoundaryCondition] = []


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


class Project(BaseModel):
    version: int = 1
    unit: Literal["m", "mm"] = "m"
    geometry: Geometry
    mesh: MeshSettings
    solver: SolverSettings = SolverSettings()
    particles: ParticleSettings | None = None


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


class TraceResult(BaseModel):
    trajectories: list[list[Point]]            # 粒子ごと、save_every ステップごと (初期位置含む)
    status: list[Literal["absorbed", "alive"]]
    tof: list[float | None]                    # absorbed 粒子の飛行時間 [s]
    final_energy_ev: list[float]
    dt: float                                  # 実際に使った dt [s]
