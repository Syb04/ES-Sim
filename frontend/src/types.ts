// backend/es_sim/schema.py と手動同期 (将来 openapi.json から自動生成に移行)

export type Point = [number, number];

export type RegionType = "conductor" | "dielectric" | "charge";

// 円領域のパラメトリック形状 (中心+半径)。メッシュ生成時にバックエンド側で多角形化する
export interface CircleShape {
  kind: "circle";
  center: Point;
  radius: number;
}

// RF重畳電圧。V(t) = voltage(直流分) + amplitude * sin(2π f t + phase) (PICのみで使用。/solve は voltage のみ)
export interface VoltageRf {
  amplitude: number;  // [V]
  freq_hz: number;    // [Hz]
  phase_deg: number;  // [deg]
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
  voltage_rf?: VoltageRf; // conductor: RF重畳 (未指定なら直流のみ)
  see_gamma?: number; // conductor: 二次電子放出係数 γ (未指定/0 で無効)
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

// Dirichlet境界: 電圧を固定する (voltage/voltage_rf/see_gamma はこのタイプのみ有効)
export interface DirichletBC {
  edges: number[];
  type: "dirichlet";
  voltage: number;
  voltage_rf?: VoltageRf; // RF重畳 (未指定なら直流のみ)
  see_gamma?: number; // 二次電子放出係数 γ (未指定/0 で無効)
}

// 対称境界 (Neumann + 粒子鏡面反射): 場は自然境界、粒子はこの辺で反射する
export interface SymmetryBC {
  edges: number[];
  type: "symmetry";
}

// 周期境界: edges はちょうど2本 (平行・同長の対辺) を指定する。
// 場は対辺の節点を同一視して解き、粒子は対辺を越えたら反対側へラップする
export interface PeriodicBC {
  edges: number[];
  type: "periodic";
}

export type BoundaryCondition = DirichletBC | SymmetryBC | PeriodicBC;

// 境界条件セレクトの4択 (フロント内部の表示用タイプ。schema上の type と概ね対応するが
// "neumann" はBCエントリが無い状態=自然境界を表す仮想的な値)
export type EdgeBcType = "neumann" | "dirichlet" | "symmetry" | "periodic";

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

// ---- FEM-PIC (フェーズ3、backend/es_sim/schema.py 予定分と手動同期) ----------------

// 初期プラズマ装荷設定。null なら初期装荷なし
export interface InitialPlasma {
  density: number;        // [m^-3] (奥行き1m換算)
  te_ev: number;           // 電子温度 [eV]
  ti_ev: number;           // イオン温度 [eV]
  ion_mass_amu: number;    // イオン質量 [amu] (Ar+ = 40 など)
  immobile_ions: boolean;  // true でイオン固定 (検証用)
  seed: number;            // 乱数シード
}

// エミッタ定常注入。emitter はフェーズ2の ParticleSettings.emitter と同型 (共用する)
export interface PicInjection {
  emitter: Emitter;
  species: "electron" | "ion";
  current_a_per_m: number; // 電流 [A/m] → 毎ステップの実電荷を等分注入
}

// 断面積プロセスの種別。elastic/excitation/ionization は電子用、isotropic/backscat はイオン用
export type XsKind = "elastic" | "excitation" | "ionization" | "isotropic" | "backscat";

// LXCat形式からパース済みの断面積プロセス (プロジェクトJSONにそのまま埋め込む)
export interface XsProcess {
  kind: XsKind;
  label: string;         // PROCESS行等から取得した表示用ラベル
  threshold_ev: number;  // excitation/ionization のみ >0 (elastic/isotropic/backscat は 0)
  mass_ratio: number;    // elastic のみ m/M。無ければ 0
  energy_ev: number[];   // 断面積テーブルのエネルギー軸 [eV] (昇順)
  sigma_m2: number[];    // 断面積テーブル [m^2] (energy_ev と同長)
}

// MCC(モンテカルロ衝突)用の背景ガス設定
export interface McGas {
  name: string;          // 表示用ガス名 (例: "Ar")
  pressure_pa: number;   // 圧力 [Pa]
  temperature_k: number; // ガス温度 [K]
}

// MCC設定。PicSettings.mcc が null なら MCC 無効
export interface McSettings {
  gas: McGas;
  electron_processes: XsProcess[]; // elastic/excitation/ionization
  ion_processes: XsProcess[];      // isotropic/backscat
  seed: number;                    // 乱数シード
}

export interface PicSettings {
  initial_plasma: InitialPlasma | null;
  injection: PicInjection | null;
  n_macro: number;      // 種ごとの初期マクロ粒子数の目安
  dt: number | null;    // 秒。null = 0.1/ωpe (初期密度から自動)
  n_steps: number;
  frame_every: number;  // フレーム送出間隔 (ステップ)
  mcc: McSettings | null;   // null なら MCC(背景ガス衝突) 無効
  see_energy_ev: number;    // SEE(二次電子放出)電子の初期エネルギー [eV]
  // 完了時の時間平均フィールドの平均ステップ数 (最終Nステップ)。null/省略 = 最後の25%
  avg_steps?: number | null;
}

// PIC診断 (1ステップ分)
export interface PicDiag {
  t: number;
  ke_e: number;
  ke_i: number;
  fe: number;
  n_e: number;
  n_i: number;
  wall_e: number;
  wall_i: number;
  phi_min: number;
  phi_max: number;
  // MCC/SEE 累計カウンタ。undefined = 未対応バックエンド (後方互換のため optional)
  coll_e?: number;      // 電子衝突数 (累計)
  ion_events?: number;  // 電離数 (累計)
  see_events?: number;  // SEE発生数 (累計)
  surf_q?: number;      // 誘電体の累計表面電荷 [C/m] (全誘電体合計)
}

// PIC診断履歴 (done メッセージの形式)。バックエンド (pic.py) は列ごとの辞書
// { t: [...], ke_e: [...], ... } で全ステップの履歴を返すため、フロントでは
// toDiagArray() で PicDiag[] (行ごと) に変換して使う
export type PicHistoryDict = { [K in keyof PicDiag]: number[] };

// 列ごとの辞書 → 行ごとの PicDiag[] 変換。形式が想定外でも例外を投げず空配列を返す
export function toDiagArray(h: PicHistoryDict | PicDiag[] | null | undefined): PicDiag[] {
  if (Array.isArray(h)) return h; // 将来サーバーが行形式になっても許容
  if (!h || !Array.isArray(h.t)) return [];
  const n = h.t.length;
  const col = (a: number[] | undefined, i: number) => (a && Number.isFinite(a[i]) ? a[i] : 0);
  // MCC/SEE カウンタは optional (未対応バックエンドでは配列自体が無い) なので、
  // 値が取れない場合は 0 ではなく undefined のままにして「-」表示に委ねる
  const colOpt = (a: number[] | undefined, i: number): number | undefined =>
    a && Number.isFinite(a[i]) ? a[i] : undefined;
  const out: PicDiag[] = new Array(n);
  for (let i = 0; i < n; i++) {
    out[i] = {
      t: col(h.t, i), ke_e: col(h.ke_e, i), ke_i: col(h.ke_i, i), fe: col(h.fe, i),
      n_e: col(h.n_e, i), n_i: col(h.n_i, i), wall_e: col(h.wall_e, i), wall_i: col(h.wall_i, i),
      phi_min: col(h.phi_min, i), phi_max: col(h.phi_max, i),
      coll_e: colOpt(h.coll_e, i), ion_events: colOpt(h.ion_events, i), see_events: colOpt(h.see_events, i),
      surf_q: colOpt(h.surf_q, i),
    };
  }
  return out;
}

// ---- PIC WebSocket プロトコル (server→client, /ws/pic) ------------------------

export interface PicStartedMsg {
  type: "started";
  dt: number;
  n_steps: number;
  warnings: string[];
  mesh: MeshResult;
}

export interface PicFrameMsg {
  type: "frame";
  step: number;
  t: number;
  phi: number[]; // 節点値
  particles: { electron: Point[]; ion: Point[] }; // 種ごと最大2000点に間引き済み
  diag: PicDiag;
}

// PIC完了時の時間平均2Dフィールド一式 (done メッセージの fields)
export interface PicFields {
  phi: number[];       // 節点、時間平均電位 [V]
  e_abs: number[];     // 要素、時間平均 |E| [V/m] (Eベクトルを平均してから絶対値)
  n_e: number[];       // 節点、電子密度 [m^-3]
  n_i: number[];       // 節点、イオン密度 [m^-3]
  te_ev: number[];     // 節点、電子温度 [eV] (粒子なし節点は 0)
  ion_rate: number[];  // 節点、電離レート [m^-3 s^-1]
  avg_steps: number;   // 実際に平均したステップ数
}

export interface PicDoneMsg {
  type: "done";
  history: PicHistoryDict; // 列ごとの辞書 (toDiagArray で PicDiag[] に変換して使う)
  fields?: PicFields;      // 時間平均フィールド (未対応バックエンドでは省略)
}

export interface PicErrorMsg {
  type: "error";
  detail: string;
}

export type PicServerMessage = PicStartedMsg | PicFrameMsg | PicDoneMsg | PicErrorMsg;

// client→server コマンド
export type PicClientCommand = { cmd: "start"; project: Project } | { cmd: "stop" };

// CadCanvas でのライブ描画用にまとめたビュー (started の mesh + 最新 frame)
export interface PicLiveFrame {
  mesh: MeshResult;
  phi: number[];
  particles: { electron: Point[]; ion: Point[] };
}

export interface Project {
  version: number;
  unit: "m" | "mm";
  geometry: Geometry;
  mesh: { size: number; local_sizes?: { region: string; size: number }[] };
  solver?: { backend: "numpy" | "cupy" | "auto" };
  particles?: ParticleSettings;
  pic?: PicSettings;
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
