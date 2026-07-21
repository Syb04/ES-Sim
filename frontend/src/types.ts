// backend/es_sim/schema.py と手動同期 (将来 openapi.json から自動生成に移行)

export type Point = [number, number];

export type RegionType = "conductor" | "dielectric" | "charge";

// 円領域のパラメトリック形状 (中心+半径)。メッシュ生成時にバックエンド側で多角形化する
export interface CircleShape {
  kind: "circle";
  center: Point;
  radius: number;
}

export interface Region {
  id: string;
  type: RegionType;
  // polygon / shape はどちらか一方のみ指定する
  polygon?: Point[];
  shape?: CircleShape;
  voltage?: number; // conductor
  eps_r?: number;   // dielectric
  rho?: number;     // charge
}

// 表示/ヒットテスト用の輪郭ポリゴンを返す。
// polygon 領域はそのまま、circle (shape) 領域は64分割の近似ポリゴンを返す。
// (実際の描画・ヒットテストは真円で行うべき箇所も多いが、
//  「とりあえず輪郭が欲しい」用途 — 例: 初期表示のフィット計算等 — で安全に使えるヘルパー)
export function regionOutline(region: Region): Point[] {
  if (region.shape) {
    const { center, radius } = region.shape;
    const n = 64;
    return Array.from({ length: n }, (_, i) => {
      const a = (i / n) * Math.PI * 2;
      return [center[0] + radius * Math.cos(a), center[1] + radius * Math.sin(a)] as Point;
    });
  }
  return region.polygon ?? [];
}

export interface BoundaryCondition {
  edges: number[];
  type: "dirichlet";
  voltage: number;
}

export interface Geometry {
  domain: { polygon: Point[] };
  regions: Region[];
  boundaries: BoundaryCondition[];
}

// 粒子種。custom の場合のみ q [C] / m [kg] を持つ
export interface Species {
  preset: "electron" | "proton" | "custom";
  q?: number; // custom時のみ [C]
  m?: number; // custom時のみ [kg]
}

// 粒子エミッタ。line: p1-p2 線分上に等間隔配置、point: p1 のみ使用 (全粒子同位置)
export interface Emitter {
  kind: "line" | "point";
  p1: Point;
  p2: Point; // point の場合は未使用 (p1 のみ使用)
  n: number;             // 粒子数
  energy_ev: number;     // 初期運動エネルギー [eV] (ドリフトエネルギー。maxwell 時もドリフト成分として有効)
  direction_deg: number; // 射出方向 (x軸から反時計回り、度)
  spread_deg: number;    // 方向の一様分布半角 [度] (等間隔割り振り、乱数不使用。maxwell 時は無視される)
  energy_dist?: "mono" | "maxwell"; // エネルギー分布。未指定は "mono" (従来動作)
  temperature_ev?: number; // maxwell 時の温度 kT [eV] (>0)
  seed?: number;           // maxwell サンプリングの乱数シード (再現性確保)
}

export interface ParticleSettings {
  species: Species;
  emitter: Emitter;
  dt: number | null; // 秒。null なら自動推定
  n_steps: number;
  save_every: number;
}

export interface Project {
  version: number;
  unit: "m" | "mm";
  geometry: Geometry;
  mesh: { size: number; local_sizes?: { region: string; size: number }[] };
  solver?: { backend: "numpy" | "cupy" | "auto" };
  particles?: ParticleSettings;
}

export interface TraceResult {
  trajectories: Point[][];               // 粒子ごと、save_every ステップごと (初期位置含む)
  status: ("absorbed" | "alive")[];      // absorbed = 電極/外周に到達して停止
  tof: (number | null)[];                // absorbed 粒子の飛行時間 [s]
  final_energy_ev: number[];             // 最終運動エネルギー [eV]
  final_angle_deg: number[];             // 最終速度の向き [度] (x軸から反時計回り、-180〜180)。absorbed 粒子では衝突時の入射方向
  dt: number;                            // 実際に使った dt
}

export interface MeshResult {
  nodes: Point[];
  triangles: [number, number, number][];
  region_of_triangle: number[];
}

export interface SolveResult {
  mesh: MeshResult;
  v: number[];
  e_field: Point[];
  v_min: number;
  v_max: number;
  e_abs_max: number;
  energy: number;
}

export interface Health {
  status: string;
  version: string;
  gpu: boolean;
}

export interface ProfileResult {
  s: number[];               // 弧長 (p1 からの距離) [m]
  v: (number | null)[];      // 電位 [V] (領域外は null)
  e_abs: (number | null)[];  // |E| [V/m] (領域外は null)
}
