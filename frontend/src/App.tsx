import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import CadCanvas from "./canvas/CadCanvas";
import type { FieldView, PicFieldView, Tool } from "./canvas/CadCanvas";
import ProfilePanel from "./panels/ProfilePanel";
import FieldPanel from "./panels/FieldPanel";
import ParticlePanel from "./panels/ParticlePanel";
import PicPanel, { PIC_FIELD_META } from "./panels/PicPanel";
import type { CyclePicField, PicResultField } from "./panels/PicPanel";
import { PicClient } from "./picClient";
import type { PicClientCallbacks } from "./picClient";
import { useHistory } from "./useHistory";
import { saveTextFile } from "./saveFile";
import { toDiagArray } from "./types";
import { mToMm, mmToM } from "./units";
import type {
  BoundaryCondition,
  CircleShape,
  EdgeBcType,
  Health,
  MeshResult,
  ParticleSettings,
  PicCollectorResult,
  PicCycle,
  PicDiag,
  PicFields,
  PicFrameMsg,
  PicLiveFrame,
  PicSettings,
  PicStartedMsg,
  Point,
  Project,
  Region,
  RegionType,
  SolveResult,
  TraceResult,
  VoltageRf,
} from "./types";

// 粒子パネルの既定値 (project.particles が未設定の場合の初期表示に使う)
const DEFAULT_PARTICLES: ParticleSettings = {
  species: { preset: "electron" },
  emitter: {
    kind: "line",
    p1: [0.02, 0.02],
    p2: [0.02, 0.03],
    n: 50,
    energy_ev: 1.0,
    direction_deg: 0,
    spread_deg: 0,
  },
  dt: null,
  n_steps: 2000,
  save_every: 10,
};

// PIC設定の既定値 (project.pic が未設定の場合の初期表示に使う)
const DEFAULT_PIC: PicSettings = {
  initial_plasma: null,
  injection: null,
  n_macro: 20000,
  dt: null,
  n_steps: 2000,
  frame_every: 20,
  mcc: null,
  see_energy_ev: 2.0,
  avg_steps: null,
  phase_bins: 40,
};

// pic.injection.emitter は常にフェーズ2 (粒子) パネルの現在のエミッタ設定で上書きしてから
// 保存/送信する (PicPanel 側では編集用の複製を持たず、都度ここで同期する)
function withInjectionEmitter(pic: PicSettings, emitter: ParticleSettings["emitter"]): PicSettings {
  if (!pic.injection) return pic;
  return { ...pic, injection: { ...pic.injection, emitter } };
}

// フェーズ0 のサンプル (examples/parallel_plates.json と同内容)。
// これを初期値として、以降は project state を編集していく。
const SAMPLE: Project = {
  version: 1,
  unit: "m",
  geometry: {
    domain: { polygon: [[0, 0], [0.1, 0], [0.1, 0.05], [0, 0.05]] },
    regions: [
      {
        id: "diel1",
        type: "dielectric",
        polygon: [[0.04, 0.01], [0.06, 0.01], [0.06, 0.04], [0.04, 0.04]],
        eps_r: 4.0,
      },
    ],
    boundaries: [
      { edges: [3], type: "dirichlet", voltage: 0.0 },
      { edges: [1], type: "dirichlet", voltage: 100.0 },
    ],
  },
  mesh: { size: 0.004 },
  solver: { backend: "numpy" },
};

export default function App() {
  const [project, setProjectState] = useState<Project>(SAMPLE);
  // project state の最新値を同期的に参照するための ref。
  // イベントハンドラ内で複数回連続して編集操作が呼ばれても
  // (例: 矢印キーの連続入力) 常に最新の状態を土台にできるようにする。
  const projectRef = useRef<Project>(SAMPLE);
  const history = useHistory<Project>();

  const [health, setHealth] = useState<Health | null>(null);
  const [result, setResult] = useState<SolveResult | null>(null);
  // Mesh ボタン (解析なしでメッシュ生成のみ) の結果。Solve 結果とは独立に保持する
  const [meshResult, setMeshResult] = useState<MeshResult | null>(null);
  const [showMesh, setShowMesh] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [tool, setTool] = useState<Tool>("select");
  const [gridSnap, setGridSnap] = useState(true);
  // ルーラー目盛りラベルのフォントサイズ (px)。プロジェクトファイルには保存しない表示設定
  const [rulerFontSize, setRulerFontSize] = useState(11);
  // サイドパネル幅 (px)。リサイザのドラッグで変更する表示設定 (保存対象外)
  const [sideWidth, setSideWidth] = useState(280);
  const [fieldView, setFieldView] = useState<FieldView>("v");
  const [showIsolines, setShowIsolines] = useState(false);
  const [showVectors, setShowVectors] = useState(false);
  const [selectedRegionId, setSelectedRegionId] = useState<string | null>(null);
  const [profileLine, setProfileLine] = useState<[Point, Point] | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // サイドパネルのタブ (静電場/粒子追跡/PIC)。タブ切替は表示の切替のみで、
  // 各タブの編集状態・実行状態 (PIC の WS 接続やチャート履歴など) はアンマウントされずに保持される
  const [activeTab, setActiveTab] = useState<"field" | "particle" | "pic">("field");

  // 粒子設定 (エミッタ・積分パラメータ)。ジオメトリ編集とは独立に管理し、
  // 既存の Undo/Redo 履歴 (history) には積まない。保存/読込 (project.particles) の対象ではある
  const [particles, setParticles] = useState<ParticleSettings>(DEFAULT_PARTICLES);
  const [traceResult, setTraceResult] = useState<TraceResult | null>(null);
  const [showTrajectories, setShowTrajectories] = useState(true);

  // PIC設定 (particles と同様、Undo/Redo履歴には積まない。保存/読込 (project.pic) の対象ではある)
  const [pic, setPic] = useState<PicSettings>(DEFAULT_PIC);
  const [picRunning, setPicRunning] = useState(false);
  const [picStarted, setPicStarted] = useState<PicStartedMsg | null>(null);
  const [picFrame, setPicFrame] = useState<PicFrameMsg | null>(null);
  const [picHistory, setPicHistory] = useState<PicDiag[]>([]);
  const [picError, setPicError] = useState<string | null>(null);
  // done メッセージで受け取った時間平均フィールド一式。新規実行開始時にリセットする
  const [picFields, setPicFields] = useState<PicFields | null>(null);
  // 「結果表示」セレクトの選択と対数スケールチェックボックス。新規実行開始時に既定 (ライブ/線形) へ戻す
  const [picResultField, setPicResultField] = useState<PicResultField>("live");
  const [picLogScale, setPicLogScale] = useState(false);
  const picClientRef = useRef<PicClient | null>(null);
  // 「続きから実行」ボタンの有効条件その1: 直前の実行が done (または stop) 済みで、
  // 現在実行中でないこと。start/continue 開始時に false、done 受信時に true にする
  const [picContinueReady, setPicContinueReady] = useState(false);
  // 「続きから実行」ボタンの有効条件その2: 前回の PIC 実行以降にジオメトリが編集 (commitProject /
  // Undo / Redo) されていないこと。サーバー側が保持する状態 (メッシュ・境界条件等) と食い違うため、
  // 編集されたら続き実行を無効化する。新しい start を送るとサーバー状態も同期し直されるので false に戻す
  const [picProjectChangedSinceRun, setPicProjectChangedSinceRun] = useState(false);

  // done メッセージで受け取った IEDF/IADF コレクタの記録結果。新規実行開始時にリセットする
  const [picCollector, setPicCollector] = useState<PicCollectorResult | null>(null);

  // RF 1周期の位相分解データ (done で受信、RFなし/phase_bins=0 では null)。
  // 周期アニメーションプレイヤー (PicPanel) の状態一式も新規実行開始時にリセットする
  const [picCycle, setPicCycle] = useState<PicCycle | null>(null);
  const [cycleField, setCycleField] = useState<CyclePicField>("phi");
  const [cycleLogScale, setCycleLogScale] = useState(false);
  const [cyclePlaying, setCyclePlaying] = useState(false);
  const [cycleBinIndex, setCycleBinIndex] = useState(0);
  const [cycleFps, setCycleFps] = useState(10);
  const [cycleShowParticles, setCycleShowParticles] = useState(true);

  // 周期アニメーション再生ループ: playing 中は fps に応じた間隔でビンを1つずつ順送りし、
  // 最後まで行ったら先頭へループする (setInterval + 関数更新で古いクロージャの影響を避ける)
  useEffect(() => {
    if (!cyclePlaying || !picCycle || picCycle.bins <= 0) return;
    const bins = picCycle.bins;
    const id = setInterval(() => {
      setCycleBinIndex((i) => (i + 1) % bins);
    }, 1000 / cycleFps);
    return () => clearInterval(id);
  }, [cyclePlaying, cycleFps, picCycle]);

  // アンマウント時に WebSocket 接続を確実に閉じる
  useEffect(() => {
    return () => picClientRef.current?.close();
  }, []);

  useEffect(() => {
    const check = () => api.health().then(setHealth).catch(() => setHealth(null));
    check();
    const t = setInterval(check, 5000);
    return () => clearInterval(t);
  }, []);

  // 選択中領域が project から消えていたら選択解除する
  const ensureSelection = useCallback((p: Project, sel: string | null): string | null => {
    if (sel === null) return null;
    return p.geometry.regions.some((r) => r.id === sel) ? sel : null;
  }, []);

  // 編集操作の確定: 直前の状態を履歴へ積み、新しい状態を反映する。
  // 解析結果は state が変わったら破棄する (プロファイルパネルも連動して閉じる)。
  const commitProject = useCallback((next: Project) => {
    history.push(projectRef.current);
    projectRef.current = next;
    setProjectState(next);
    setResult(null);
    setMeshResult(null);
    setProfileLine(null);
    setTraceResult(null); // ジオメトリ変更で解析結果とともに trace 結果も破棄する
    setPicProjectChangedSinceRun(true); // PIC続き実行はサーバー状態と食い違うため無効化する
  }, [history]);

  // --- Undo/Redo ---
  const doUndo = useCallback(() => {
    const prev = history.undo(projectRef.current);
    if (prev === null) return;
    projectRef.current = prev;
    setProjectState(prev);
    setResult(null);
    setMeshResult(null);
    setProfileLine(null);
    setTraceResult(null);
    setSelectedRegionId((sel) => ensureSelection(prev, sel));
    setPicProjectChangedSinceRun(true); // PIC続き実行はサーバー状態と食い違うため無効化する
  }, [history, ensureSelection]);

  const doRedo = useCallback(() => {
    const next = history.redo(projectRef.current);
    if (next === null) return;
    projectRef.current = next;
    setProjectState(next);
    setResult(null);
    setMeshResult(null);
    setProfileLine(null);
    setTraceResult(null);
    setSelectedRegionId((sel) => ensureSelection(next, sel));
    setPicProjectChangedSinceRun(true); // PIC続き実行はサーバー状態と食い違うため無効化する
  }, [history, ensureSelection]);

  // キーボードショートカット: Ctrl+Z (Undo) / Ctrl+Y, Ctrl+Shift+Z (Redo)
  // テキスト入力中は素通しする (native な編集を邪魔しないため)
  useEffect(() => {
    const isEditable = (t: EventTarget | null) =>
      t instanceof HTMLElement && ["INPUT", "SELECT", "TEXTAREA"].includes(t.tagName);
    const onKeyDown = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      if (isEditable(e.target)) return;
      const key = e.key.toLowerCase();
      if (key === "z") {
        e.preventDefault();
        if (e.shiftKey) doRedo();
        else doUndo();
      } else if (key === "y") {
        e.preventDefault();
        doRedo();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [doUndo, doRedo]);

  const runSolve = async () => {
    setBusy(true);
    setError(null);
    setMeshResult(null); // Solve 実行時は Mesh のみの結果を破棄し、Solve 側の表示を優先する
    try {
      setResult(await api.solve(project));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  // メッシュ生成のみ (解析は行わない)
  const runMesh = async () => {
    setBusy(true);
    setError(null);
    try {
      setMeshResult(await api.mesh(project));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  // 粒子軌道トレース実行 (project.particles として送信する)
  const runTrace = async () => {
    setBusy(true);
    setError(null);
    try {
      setTraceResult(await api.trace({ ...project, particles }));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  // PIC実行中のコールバック生成 (start/continue で共通化)。isContinue が true のときは
  // done 受信時に history を「置き換え」ではなく既存へ「連結」する (それ以外の挙動は同じ:
  // 新しい実行区間の started/frame でライブ表示は自然に切り替わり、fields/cycle/collector は
  // 新しい done の内容で置き換わる)
  const makePicCallbacks = (isContinue: boolean): PicClientCallbacks => ({
    onStarted: (msg) => {
      setPicStarted(msg);
      setPicFrame(null); // ライブ表示を新しい実行区間の内容に自然に切り替える
    },
    onFrame: (msg) => {
      setPicFrame(msg);
      setPicHistory((h) => [...h, msg.diag]);
    },
    onDone: (msg) => {
      // バックエンドの history は列ごとの辞書形式なので行ごとの PicDiag[] に変換する
      // (形式不一致のまま描画するとチャートが例外を投げて画面全体が落ちるため必ず変換を通す)
      const added = toDiagArray(msg.history);
      setPicHistory((h) => (isContinue ? [...h, ...added] : added));
      setPicFields(msg.fields ?? null);
      setPicCycle(msg.cycle ?? null);
      setPicCollector(msg.collector ?? null);
      setPicRunning(false);
      setPicContinueReady(true); // done (stop 済みも含む) したので続き実行が可能になる
    },
    onError: (detail) => {
      setPicError(detail);
      setPicRunning(false);
      setPicContinueReady(false); // エラー後の状態は不定なので続き実行は無効のままにする
    },
    onClose: () => setPicRunning(false),
  });

  // PIC開始: WebSocket接続を張り、project.pic (エミッタはフェーズ2の設定と同期) を送信する
  const runPicStart = () => {
    setPicError(null);
    setPicStarted(null);
    setPicFrame(null);
    setPicHistory([]);
    setPicRunning(true);
    setPicContinueReady(false);
    // 新しい実行を開始したら結果フィールド表示 (前回 done の残骸) をリセットする
    setPicFields(null);
    setPicResultField("live");
    setPicLogScale(false);
    // 周期アニメーションの状態も新規実行開始時にリセットする (前回 done の cycle・再生状態を破棄)
    setPicCycle(null);
    setCycleField("phi");
    setCycleLogScale(false);
    setCyclePlaying(false);
    setCycleBinIndex(0);
    setCycleShowParticles(true);
    // IEDF/IADF コレクタ結果も新規実行開始時にリセットする (前回 done の残骸を消す)
    setPicCollector(null);
    const client = new PicClient(makePicCallbacks(false));
    picClientRef.current = client;
    // 現在のプロジェクト状態をサーバーへ送るので、続き実行の食い違いフラグをここで解消する
    setPicProjectChangedSinceRun(false);
    client.start({ ...project, pic: withInjectionEmitter(pic, particles.emitter) });
  };

  // PIC続きから実行: 保持中のシミュレーション状態 (粒子・表面電荷・時刻・乱数) を維持したまま
  // 現在の計算設定 (n_steps/frame_every/avg_steps/phase_bins) で追加実行する。
  // ジオメトリ・プラズマ設定などプロジェクト側の変更はサーバーへは送らないため反映されない。
  // picHistory はクリアせず、既存の履歴 (フル実行分) の末尾へ追加区間分を連結する
  const runPicContinue = () => {
    if (!picClientRef.current || picRunning || !picContinueReady || picProjectChangedSinceRun) return;
    setPicError(null);
    setPicRunning(true);
    setPicContinueReady(false);
    picClientRef.current.setCallbacks(makePicCallbacks(true));
    picClientRef.current.continueRun({
      n_steps: pic.n_steps,
      frame_every: pic.frame_every,
      avg_steps: pic.avg_steps ?? null,
      phase_bins: pic.phase_bins ?? null,
    });
  };

  const runPicStop = () => {
    picClientRef.current?.stop();
  };

  // エミッタ配置ツール (CadCanvas) からの確定通知。kind/n 等はそのまま維持し p1/p2 のみ更新する。
  // 線を確定したら「粒子追跡」タブに切替え、プロパティがすぐ見えるようにする
  const setEmitterPoints = (p1: Point, p2: Point) => {
    setParticles((prev) => ({ ...prev, emitter: { ...prev.emitter, p1, p2 } }));
    setActiveTab("particle");
  };

  // コレクタ配置ツール (CadCanvas) からの確定通知。tol は既存設定があれば維持する。
  // 配置したら PIC 設定の collector を更新し、PIC タブへ切替える
  const setCollectorPoints = (p1: Point, p2: Point) => {
    setPic((prev) => ({ ...prev, collector: { p1, p2, tol: prev.collector?.tol ?? null } }));
    setActiveTab("pic");
  };

  // キャンバス上で領域を選択したら「静電場」タブに切替える (選択解除時はタブ切替しない)
  const selectRegionFromCanvas = (id: string | null) => {
    setSelectedRegionId(id);
    if (id !== null) setActiveTab("field");
  };

  // --- domain ---
  const domainW = Math.max(...project.geometry.domain.polygon.map((p) => p[0]));
  const domainH = Math.max(...project.geometry.domain.polygon.map((p) => p[1]));

  const setDomainSize = (w: number, h: number) => {
    if (!(w > 0) || !(h > 0)) return;
    const p = projectRef.current;
    commitProject({
      ...p,
      geometry: {
        ...p.geometry,
        domain: { polygon: [[0, 0], [w, 0], [w, h], [0, h]] },
      },
    });
  };

  // --- 境界条件 (4辺: 0=下,1=右,2=上,3=左)。矩形domain前提で対辺は (i+2)%4 ---
  const oppositeEdge = (edgeIndex: number) => (edgeIndex + 2) % 4;

  // 指定エッジを含むBCエントリを取り除く。periodicエントリは2辺セットで消えるため、
  // 対辺も道連れで自然境界(Neumann)に戻る
  const removeEdgeBoundary = (boundaries: BoundaryCondition[], edgeIndex: number): BoundaryCondition[] =>
    boundaries.filter((b) => !b.edges.includes(edgeIndex));

  const edgeState = (
    edgeIndex: number,
  ): { type: EdgeBcType; voltage: number; voltageRf?: VoltageRf; seeGamma: number } => {
    const b = project.geometry.boundaries.find((b) => b.edges.includes(edgeIndex));
    if (!b) return { type: "neumann", voltage: 0, seeGamma: 0 };
    if (b.type === "dirichlet") {
      return { type: "dirichlet", voltage: b.voltage, voltageRf: b.voltage_rf, seeGamma: b.see_gamma ?? 0 };
    }
    return { type: b.type, voltage: 0, seeGamma: 0 };
  };

  // 境界条件タイプの一元切替ハンドラ。周期を選ぶと対辺も自動的に周期エントリへまとめ、
  // 対辺が別タイプ(Dirichlet等)で使用中でも単純に上書きする。他タイプへ切替えた場合、
  // 元が周期エントリであれば removeEdgeBoundary により対辺も道連れで解除される
  const setEdgeType = (edgeIndex: number, type: EdgeBcType) => {
    const p = projectRef.current;
    let boundaries = removeEdgeBoundary(p.geometry.boundaries, edgeIndex);
    if (type === "dirichlet") {
      boundaries = [...boundaries, { edges: [edgeIndex], type: "dirichlet" as const, voltage: 0 }];
    } else if (type === "symmetry") {
      boundaries = [...boundaries, { edges: [edgeIndex], type: "symmetry" as const }];
    } else if (type === "periodic") {
      const opposite = oppositeEdge(edgeIndex);
      boundaries = [
        ...removeEdgeBoundary(boundaries, opposite),
        { edges: [edgeIndex, opposite], type: "periodic" as const },
      ];
    }
    commitProject({ ...p, geometry: { ...p.geometry, boundaries } });
  };

  // Dirichlet辺の電圧値のみ更新 (まだDirichletでなければ新規作成する)
  const setEdgeVoltage = (edgeIndex: number, voltage: number) => {
    const p = projectRef.current;
    const cur = p.geometry.boundaries.find((b) => b.edges.includes(edgeIndex));
    const boundaries =
      cur && cur.type === "dirichlet"
        ? p.geometry.boundaries.map((b) => (b === cur ? { ...b, voltage } : b))
        : [...removeEdgeBoundary(p.geometry.boundaries, edgeIndex), { edges: [edgeIndex], type: "dirichlet" as const, voltage }];
    commitProject({ ...p, geometry: { ...p.geometry, boundaries } });
  };

  // 境界条件のRF重畳設定 (対象エッジが Dirichlet でない場合は何もしない)
  const setEdgeVoltageRf = (edgeIndex: number, voltage_rf: VoltageRf | undefined) => {
    const p = projectRef.current;
    commitProject({
      ...p,
      geometry: {
        ...p.geometry,
        boundaries: p.geometry.boundaries.map((b) =>
          b.type === "dirichlet" && b.edges.includes(edgeIndex) ? { ...b, voltage_rf } : b,
        ),
      },
    });
  };

  // 境界条件の二次電子放出係数 γ (対象エッジが Dirichlet でない場合は何もしない)
  const setEdgeSeeGamma = (edgeIndex: number, see_gamma: number) => {
    const p = projectRef.current;
    commitProject({
      ...p,
      geometry: {
        ...p.geometry,
        boundaries: p.geometry.boundaries.map((b) =>
          b.type === "dirichlet" && b.edges.includes(edgeIndex) ? { ...b, see_gamma } : b,
        ),
      },
    });
  };

  // --- メッシュ ---
  const setMeshSize = (size: number) => {
    if (!(size > 0)) return;
    const p = projectRef.current;
    commitProject({ ...p, mesh: { ...p.mesh, size } });
  };

  // メッシュモード (非構造 gmsh / 構造格子)。構造格子は矩形 domain のみ対応
  const setMeshMode = (mode: "unstructured" | "structured") => {
    const p = projectRef.current;
    commitProject({ ...p, mesh: { ...p.mesh, mode } });
  };

  // --- 領域 ---
  // ポリゴン (ポリライン/矩形ツール) または circle shape (円ツール) のどちらでも領域を追加できる
  const addRegion = (geom: Point[] | CircleShape) => {
    const p = projectRef.current;
    const ids = new Set(p.geometry.regions.map((r) => r.id));
    let n = p.geometry.regions.length + 1;
    let id = `region${n}`;
    while (ids.has(id)) { n += 1; id = `region${n}`; }
    const region: Region = Array.isArray(geom)
      ? { id, type: "conductor", polygon: geom, voltage: 0 }
      : { id, type: "conductor", shape: geom, voltage: 0 };
    commitProject({ ...p, geometry: { ...p.geometry, regions: [...p.geometry.regions, region] } });
  };

  const updateRegion = (id: string, patch: Partial<Region>) => {
    const p = projectRef.current;
    commitProject({
      ...p,
      geometry: {
        ...p.geometry,
        regions: p.geometry.regions.map((r) => (r.id === id ? { ...r, ...patch } : r)),
      },
    });
  };

  const renameRegion = (oldId: string, newId: string) => {
    if (!newId || newId === oldId) return;
    const p = projectRef.current;
    if (p.geometry.regions.some((r) => r.id === newId)) return; // ID 重複は不可
    commitProject({
      ...p,
      geometry: {
        ...p.geometry,
        regions: p.geometry.regions.map((r) => (r.id === oldId ? { ...r, id: newId } : r)),
      },
    });
    setSelectedRegionId(newId);
  };

  const setRegionType = (id: string, type: RegionType) => {
    const p = projectRef.current;
    commitProject({
      ...p,
      geometry: {
        ...p.geometry,
        regions: p.geometry.regions.map((r) => {
          if (r.id !== id) return r;
          // shape (circle) 領域はそのまま shape を維持し、polygon 領域は polygon を維持する
          const base = r.shape
            ? { id: r.id, type, shape: r.shape }
            : { id: r.id, type, polygon: r.polygon ?? [] };
          if (type === "conductor") return { ...base, voltage: r.voltage ?? 0 };
          if (type === "dielectric") return { ...base, eps_r: r.eps_r ?? 1 };
          return { ...base, rho: r.rho ?? 0 };
        }),
      },
    });
  };

  const deleteRegion = (id: string) => {
    const p = projectRef.current;
    commitProject({
      ...p,
      geometry: { ...p.geometry, regions: p.geometry.regions.filter((r) => r.id !== id) },
    });
    setSelectedRegionId((sel) => (sel === id ? null : sel));
  };

  // --- 図形の移動 (CadCanvas からのドラッグ確定 / 矢印キー微動) ---
  // polygon 領域は各頂点を、circle (shape) 領域は中心を平行移動する
  const moveRegion = (id: string, dx: number, dy: number) => {
    if (dx === 0 && dy === 0) return;
    const p = projectRef.current;
    if (!p.geometry.regions.some((r) => r.id === id)) return;
    commitProject({
      ...p,
      geometry: {
        ...p.geometry,
        regions: p.geometry.regions.map((r) => {
          if (r.id !== id) return r;
          if (r.shape) {
            return {
              ...r,
              shape: { ...r.shape, center: [r.shape.center[0] + dx, r.shape.center[1] + dy] },
            };
          }
          return { ...r, polygon: (r.polygon ?? []).map(([x, y]) => [x + dx, y + dy] as Point) };
        }),
      },
    });
  };

  // --- 領域の多角形編集 (CadCanvas からの頂点/中点グリップ操作の確定) ---
  const editRegionPolygon = (id: string, polygon: Point[]) => {
    if (polygon.length < 3) return;
    const p = projectRef.current;
    if (!p.geometry.regions.some((r) => r.id === id)) return;
    commitProject({
      ...p,
      geometry: {
        ...p.geometry,
        regions: p.geometry.regions.map((r) => (r.id === id ? { ...r, polygon } : r)),
      },
    });
  };

  // --- circle 領域の shape 編集 (CadCanvas からの半径グリップ操作の確定、サイドパネルの数値入力共通) ---
  const editRegionShape = (id: string, shape: CircleShape) => {
    if (!(shape.radius > 0)) return;
    const p = projectRef.current;
    if (!p.geometry.regions.some((r) => r.id === id)) return;
    commitProject({
      ...p,
      geometry: {
        ...p.geometry,
        regions: p.geometry.regions.map((r) => (r.id === id ? { ...r, shape } : r)),
      },
    });
  };

  // --- 保存/読込 ---
  // particles / pic は history 管理外の別 state のため、保存時にここで project へ合成する
  const saveProject = () => {
    const toSave: Project = { ...project, particles, pic: withInjectionEmitter(pic, particles.emitter) };
    saveTextFile("project.json", JSON.stringify(toSave, null, 2), "JSON", ["json"]).catch((err) => {
      setError(String(err));
    });
  };

  const loadProject = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const obj = JSON.parse(String(reader.result));
        if (!obj || typeof obj !== "object" || !("geometry" in obj)) {
          throw new Error("不正なプロジェクトファイルです (geometry がありません)");
        }
        // 型はバックエンドが信頼できるものを書き出す前提で信用する
        commitProject(obj as Project);
        // particles / pic は独立管理の state なので、読込んだファイルにあれば反映し、なければ既定値に戻す
        const loadedParticles = (obj as Project).particles;
        setParticles(loadedParticles ?? DEFAULT_PARTICLES);
        const loadedPic = (obj as Project).pic;
        // mcc/see_energy_ev が無い旧形式のファイルでも安全に読み込めるよう、既定値をベースに合成する
        setPic(loadedPic ? { ...DEFAULT_PIC, ...loadedPic } : DEFAULT_PIC);
        setSelectedRegionId(null);
        setError(null);
      } catch (err) {
        setError(String(err));
      }
    };
    reader.readAsText(file);
    e.target.value = ""; // 同じファイルを連続で読み込めるようにする
  };

  const selected = project.geometry.regions.find((r) => r.id === selectedRegionId) ?? null;

  // 「続きから実行」ボタンの有効条件: 直前の実行が done/stop 済みで現在実行中でなく、
  // かつ前回実行以降にジオメトリが編集されていないこと (health 未接続時も不可)
  const picCanContinue = !!health && picContinueReady && !picRunning && !picProjectChangedSinceRun;

  // 配置済み IEDF/IADF コレクタ線分 (CadCanvas への常時オーバーレイ表示用)
  const collectorLine: [Point, Point] | null = pic.collector
    ? [pic.collector.p1, pic.collector.p2]
    : null;

  // PICライブ描画用ビュー (started の mesh + 最新 frame)。実行中〜done後の最終フレームまで保持する
  const picLiveFrame: PicLiveFrame | null =
    picStarted && picFrame
      ? { mesh: picStarted.mesh, phi: picFrame.phi, particles: picFrame.particles }
      : null;

  // PIC結果フィールド表示用ビュー (「結果表示」セレクトでライブ以外を選び、fields がある場合のみ)。
  // CadCanvas へは値配列・節点/要素の別・単位・対数フラグを1つの prop にまとめて渡す
  const picFieldView: PicFieldView | null =
    picResultField !== "live" && picFields && picStarted
      ? {
          mesh: picStarted.mesh,
          values: picFields[picResultField],
          nodeBased: PIC_FIELD_META[picResultField].nodeBased,
          unit: PIC_FIELD_META[picResultField].unit,
          log: picLogScale,
        }
      : null;

  // 周期アニメーション用のカラースケール固定範囲 (全ビンの min/max)。
  // フレーム(ビン)が変わるたびに色が暴れないよう、選択フィールドが変わったときだけ再計算する
  const cycleFixedRange = useMemo(() => {
    if (!picCycle) return null;
    const rows = picCycle[cycleField];
    let min = Infinity;
    let max = -Infinity;
    let minPositive = Infinity;
    for (const row of rows) {
      for (const v of row) {
        if (v < min) min = v;
        if (v > max) max = v;
        if (v > 0 && v < minPositive) minPositive = v;
      }
    }
    if (!Number.isFinite(min)) { min = 0; max = 0; }
    return { min, max, minPositive };
  }, [picCycle, cycleField]);

  // 周期アニメーション表示用ビュー (done で cycle を受信している間のみ非null)。
  // 現在の位相ビンの値+固定min/max+粒子スナップショットを picFieldView と同形にまとめて渡す
  const picCycleView: PicFieldView | null =
    picCycle && picStarted && cycleFixedRange
      ? (() => {
          const bin = Math.min(cycleBinIndex, picCycle.bins - 1);
          const meta = PIC_FIELD_META[cycleField];
          return {
            mesh: picStarted.mesh,
            values: picCycle[cycleField][bin],
            nodeBased: meta.nodeBased,
            unit: meta.unit,
            log: cycleLogScale,
            fixedRange: cycleFixedRange,
            particles: cycleShowParticles
              ? {
                  electron: picCycle.particles.electron[bin] ?? [],
                  ion: picCycle.particles.ion[bin] ?? [],
                }
              : undefined,
          };
        })()
      : null;

  // 描画優先順位: 周期アニメーション > 結果フィールド表示 (> ライブ表示 > Solve結果、CadCanvas側で処理)。
  // CadCanvas へは既存の picFieldView prop をそのまま使い回す (新規propは増やさない)
  const finalPicFieldView = picCycleView ?? picFieldView;

  return (
    <div className="app">
      <div className="toolbar">
        <h1>ES-Sim</h1>
        <button className="secondary" onClick={runMesh} disabled={busy || !health}>
          {busy ? "計算中..." : "Mesh"}
        </button>
        <button onClick={runSolve} disabled={busy || !health}>
          {busy ? "計算中..." : "Solve"}
        </button>
        <button className="secondary" onClick={() => setShowMesh(!showMesh)}>
          メッシュ {showMesh ? "非表示" : "表示"}
        </button>
        <div className="sep" />
        <button className="secondary" onClick={doUndo} disabled={!history.canUndo} title="Undo (Ctrl+Z)">
          ↶ Undo
        </button>
        <button
          className="secondary"
          onClick={doRedo}
          disabled={!history.canRedo}
          title="Redo (Ctrl+Y / Ctrl+Shift+Z)"
        >
          ↷ Redo
        </button>
        <div className="spacer" />
        <div className={`status ${health ? "ok" : "ng"}`}>
          {health
            ? `backend v${health.version} ${health.gpu ? "(GPU)" : "(CPU)"}`
            : "backend 未接続 — uvicorn es_sim.server:app --port 8317 を起動してください"}
        </div>
      </div>

      <div className="tool-toolbar">
        <button className={`tool ${tool === "select" ? "active" : ""}`} onClick={() => setTool("select")}>
          選択
        </button>
        <button
          className={`tool ${tool === "polyline" ? "active" : ""}`}
          onClick={() => setTool("polyline")}
          title="domain外にはみ出した部分は解析時にクリップされます"
        >
          ポリライン
        </button>
        <button
          className={`tool ${tool === "rect" ? "active" : ""}`}
          onClick={() => setTool("rect")}
          title="domain外にはみ出した部分は解析時にクリップされます"
        >
          矩形
        </button>
        <button
          className={`tool ${tool === "circle" ? "active" : ""}`}
          onClick={() => setTool("circle")}
          title="domain外にはみ出した部分は解析時にクリップされます"
        >
          円
        </button>
        <button className={`tool ${tool === "profile" ? "active" : ""}`} onClick={() => setTool("profile")}>
          プロファイル
        </button>
        <button className={`tool ${tool === "emitter" ? "active" : ""}`} onClick={() => setTool("emitter")}>
          エミッタ
        </button>
        <button className={`tool ${tool === "collector" ? "active" : ""}`} onClick={() => setTool("collector")}>
          コレクタ
        </button>
        <div className="sep" />
        <label className="snap">
          <input
            type="checkbox"
            checked={gridSnap}
            onChange={(e) => setGridSnap(e.target.checked)}
          />
          グリッドスナップ
        </label>
        <label className="snap">
          ルーラー文字
          <select
            className="ruler-font-select"
            value={rulerFontSize}
            onChange={(e) => setRulerFontSize(Number(e.target.value))}
          >
            <option value={9}>小</option>
            <option value={11}>中</option>
            <option value={14}>大</option>
          </select>
        </label>
        <div className="sep" />
        <span className="field-view-label">表示</span>
        <select
          className="field-view-select"
          value={fieldView}
          onChange={(e) => setFieldView(e.target.value as FieldView)}
        >
          <option value="v">電位 V</option>
          <option value="e_abs">|E|</option>
        </select>
        <label className="snap">
          <input
            type="checkbox"
            checked={showIsolines}
            onChange={(e) => setShowIsolines(e.target.checked)}
          />
          等電位線
        </label>
        <label className="snap">
          <input
            type="checkbox"
            checked={showVectors}
            onChange={(e) => setShowVectors(e.target.checked)}
          />
          ベクトル
        </label>
      </div>

      <div className="main">
        <div className="canvas-col">
          <CadCanvas
            project={project}
            result={result}
            meshResult={meshResult}
            showMesh={showMesh}
            tool={tool}
            gridSnap={gridSnap}
            rulerFontSize={rulerFontSize}
            selectedRegionId={selectedRegionId}
            fieldView={fieldView}
            showIsolines={showIsolines}
            showVectors={showVectors}
            profileLine={profileLine}
            collectorLine={collectorLine}
            emitter={particles.emitter}
            traceResult={traceResult}
            showTrajectories={showTrajectories}
            picFrame={picLiveFrame}
            picFieldView={finalPicFieldView}
            onSelectRegion={selectRegionFromCanvas}
            onDeleteRegion={deleteRegion}
            onAddRegion={addRegion}
            onMoveRegion={moveRegion}
            onEditRegionPolygon={editRegionPolygon}
            onEditRegionShape={editRegionShape}
            onProfileLine={(p1, p2) => setProfileLine([p1, p2])}
            onSetEmitter={setEmitterPoints}
            onSetCollector={setCollectorPoints}
          />
          {profileLine && (
            <ProfilePanel
              project={project}
              p1={profileLine[0]}
              p2={profileLine[1]}
              onClose={() => setProfileLine(null)}
            />
          )}
        </div>
        {/* サイドパネル幅のリサイザ (ドラッグで変更、ダブルクリックで既定幅に戻す) */}
        <div
          className="side-resizer"
          onMouseDown={(e) => {
            e.preventDefault();
            const startX = e.clientX;
            const startW = sideWidth;
            const onMove = (ev: MouseEvent) => {
              const w = startW + (startX - ev.clientX);
              setSideWidth(Math.min(560, Math.max(220, w)));
            };
            const onUp = () => {
              window.removeEventListener("mousemove", onMove);
              window.removeEventListener("mouseup", onUp);
              document.body.style.cursor = "";
            };
            document.body.style.cursor = "col-resize";
            window.addEventListener("mousemove", onMove);
            window.addEventListener("mouseup", onUp);
          }}
          onDoubleClick={() => setSideWidth(280)}
          title="ドラッグで幅を変更 / ダブルクリックで既定幅"
        />
        <div className="side" style={{ width: sideWidth }}>
          <div className="side-top">
            <div className="actions">
              <button className="secondary" onClick={saveProject}>保存</button>
              <button className="secondary" onClick={() => fileInputRef.current?.click()}>読込</button>
              <input
                ref={fileInputRef}
                type="file"
                accept="application/json"
                className="file-input"
                onChange={loadProject}
              />
            </div>
          </div>

          <div className="side-tabbar">
            <button
              className={`side-tab ${activeTab === "field" ? "active" : ""}`}
              onClick={() => setActiveTab("field")}
            >
              静電場
            </button>
            <button
              className={`side-tab ${activeTab === "particle" ? "active" : ""}`}
              onClick={() => setActiveTab("particle")}
            >
              粒子追跡
            </button>
            <button
              className={`side-tab ${activeTab === "pic" ? "active" : ""}`}
              onClick={() => setActiveTab("pic")}
            >
              PIC
            </button>
          </div>

          <div className="side-tab-content">
            {/* 各タブは display:none で非表示化するのみでアンマウントしない。
                これにより PIC 実行中の WebSocket 接続やチャート履歴、他タブの編集状態が
                タブ切替をまたいで保持される */}
            <div style={{ display: activeTab === "field" ? "block" : "none" }}>
              <FieldPanel
                project={project}
                domainW={domainW}
                domainH={domainH}
                setDomainSize={setDomainSize}
                edgeState={edgeState}
                setEdgeType={setEdgeType}
                setEdgeVoltage={setEdgeVoltage}
                setEdgeVoltageRf={setEdgeVoltageRf}
                setEdgeSeeGamma={setEdgeSeeGamma}
                setMeshSize={setMeshSize}
                setMeshMode={setMeshMode}
                meshResult={meshResult}
                selectedRegionId={selectedRegionId}
                onSelectRegion={setSelectedRegionId}
                selected={selected}
                renameRegion={renameRegion}
                setRegionType={setRegionType}
                editRegionShape={editRegionShape}
                updateRegion={updateRegion}
                deleteRegion={deleteRegion}
                result={result}
              />
            </div>

            <div style={{ display: activeTab === "particle" ? "block" : "none" }}>
              <ParticlePanel
                particles={particles}
                onChange={setParticles}
                busy={busy}
                canRun={!!health}
                onTrace={runTrace}
                traceResult={traceResult}
                showTrajectories={showTrajectories}
                onToggleTrajectories={setShowTrajectories}
              />
            </div>

            <div style={{ display: activeTab === "pic" ? "block" : "none" }}>
              <PicPanel
                pic={pic}
                onChange={setPic}
                emitter={particles.emitter}
                canRun={!!health}
                running={picRunning}
                onStart={runPicStart}
                onStop={runPicStop}
                canContinue={picCanContinue}
                onContinue={runPicContinue}
                continueDisabledByProjectChange={picProjectChangedSinceRun}
                started={picStarted}
                frame={picFrame}
                history={picHistory}
                error={picError}
                fields={picFields}
                resultField={picResultField}
                onResultFieldChange={setPicResultField}
                logScale={picLogScale}
                onLogScaleChange={setPicLogScale}
                cycle={picCycle}
                cycleField={cycleField}
                onCycleFieldChange={setCycleField}
                cycleLogScale={cycleLogScale}
                onCycleLogScaleChange={setCycleLogScale}
                cyclePlaying={cyclePlaying}
                onCyclePlayingChange={setCyclePlaying}
                cycleBinIndex={cycleBinIndex}
                onCycleBinIndexChange={setCycleBinIndex}
                cycleFps={cycleFps}
                onCycleFpsChange={setCycleFps}
                cycleShowParticles={cycleShowParticles}
                onCycleShowParticlesChange={setCycleShowParticles}
                collectorResult={picCollector}
              />
            </div>

            {error && (
              <>
                <h2>エラー</h2>
                <div className="error">{error}</div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
