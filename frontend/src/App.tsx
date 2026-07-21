import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import CadCanvas from "./canvas/CadCanvas";
import type { FieldView, Tool } from "./canvas/CadCanvas";
import { CommitNumberInput, CommitTextInput } from "./CommitInput";
import ProfilePanel from "./panels/ProfilePanel";
import { useHistory } from "./useHistory";
import { mToMm, mmToM } from "./units";
import type {
  CircleShape,
  Health,
  MeshResult,
  Point,
  Project,
  Region,
  RegionType,
  SolveResult,
} from "./types";

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

// 矩形 domain の外周エッジ順: 0=下, 1=右, 2=上, 3=左
const EDGE_LABELS = ["下 (y=0)", "右 (x=w)", "上 (y=h)", "左 (x=0)"];

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
  const [fieldView, setFieldView] = useState<FieldView>("v");
  const [showIsolines, setShowIsolines] = useState(false);
  const [showVectors, setShowVectors] = useState(false);
  const [selectedRegionId, setSelectedRegionId] = useState<string | null>(null);
  const [profileLine, setProfileLine] = useState<[Point, Point] | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

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
    setSelectedRegionId((sel) => ensureSelection(prev, sel));
  }, [history, ensureSelection]);

  const doRedo = useCallback(() => {
    const next = history.redo(projectRef.current);
    if (next === null) return;
    projectRef.current = next;
    setProjectState(next);
    setResult(null);
    setMeshResult(null);
    setProfileLine(null);
    setSelectedRegionId((sel) => ensureSelection(next, sel));
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

  // --- 境界条件 (4辺: 0=下,1=右,2=上,3=左) ---
  const edgeState = (edgeIndex: number): { dirichlet: boolean; voltage: number } => {
    const b = project.geometry.boundaries.find((b) => b.edges.includes(edgeIndex));
    return b ? { dirichlet: true, voltage: b.voltage } : { dirichlet: false, voltage: 0 };
  };

  const setEdgeNeumann = (edgeIndex: number) => {
    const p = projectRef.current;
    commitProject({
      ...p,
      geometry: {
        ...p.geometry,
        boundaries: p.geometry.boundaries.filter((b) => !b.edges.includes(edgeIndex)),
      },
    });
  };

  const setEdgeDirichlet = (edgeIndex: number, voltage: number) => {
    const p = projectRef.current;
    const exists = p.geometry.boundaries.some((b) => b.edges.includes(edgeIndex));
    const boundaries = exists
      ? p.geometry.boundaries.map((b) =>
          b.edges.includes(edgeIndex) ? { ...b, voltage } : b,
        )
      : [...p.geometry.boundaries, { edges: [edgeIndex], type: "dirichlet" as const, voltage }];
    commitProject({ ...p, geometry: { ...p.geometry, boundaries } });
  };

  // --- メッシュ ---
  const setMeshSize = (size: number) => {
    if (!(size > 0)) return;
    const p = projectRef.current;
    commitProject({ ...p, mesh: { ...p.mesh, size } });
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
  const saveProject = () => {
    const blob = new Blob([JSON.stringify(project, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "project.json";
    a.click();
    URL.revokeObjectURL(url);
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
        <button className={`tool ${tool === "polyline" ? "active" : ""}`} onClick={() => setTool("polyline")}>
          ポリライン
        </button>
        <button className={`tool ${tool === "rect" ? "active" : ""}`} onClick={() => setTool("rect")}>
          矩形
        </button>
        <button className={`tool ${tool === "circle" ? "active" : ""}`} onClick={() => setTool("circle")}>
          円
        </button>
        <button className={`tool ${tool === "profile" ? "active" : ""}`} onClick={() => setTool("profile")}>
          プロファイル
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
            onSelectRegion={setSelectedRegionId}
            onDeleteRegion={deleteRegion}
            onAddRegion={addRegion}
            onMoveRegion={moveRegion}
            onEditRegionPolygon={editRegionPolygon}
            onEditRegionShape={editRegionShape}
            onProfileLine={(p1, p2) => setProfileLine([p1, p2])}
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
        <div className="side">
          <h2>ジオメトリ (domain)</h2>
          <div className="field">
            <span className="label">幅 [mm]</span>
            <CommitNumberInput
              value={mToMm(domainW)}
              step="0.1"
              onCommit={(w) => setDomainSize(mmToM(w), domainH)}
            />
          </div>
          <div className="field">
            <span className="label">高さ [mm]</span>
            <CommitNumberInput
              value={mToMm(domainH)}
              step="0.1"
              onCommit={(h) => setDomainSize(domainW, mmToM(h))}
            />
          </div>

          <h2>境界条件</h2>
          {EDGE_LABELS.map((label, i) => {
            const st = edgeState(i);
            return (
              <div className="edge-row" key={i}>
                <span className="edge-label">{label}</span>
                <div className="edge-controls">
                  <select
                    value={st.dirichlet ? "dirichlet" : "neumann"}
                    onChange={(e) =>
                      e.target.value === "dirichlet" ? setEdgeDirichlet(i, st.voltage) : setEdgeNeumann(i)
                    }
                  >
                    <option value="neumann">なし (Neumann)</option>
                    <option value="dirichlet">Dirichlet</option>
                  </select>
                  {st.dirichlet && (
                    <CommitNumberInput value={st.voltage} onCommit={(v) => setEdgeDirichlet(i, v)} />
                  )}
                </div>
              </div>
            );
          })}

          <h2>メッシュ</h2>
          <div className="field">
            <span className="label">サイズ [mm]</span>
            <CommitNumberInput
              value={mToMm(project.mesh.size)}
              step="0.01"
              onCommit={(v) => setMeshSize(mmToM(v))}
            />
          </div>
          {meshResult && (
            <>
              <div className="kv"><span>節点数</span><span>{meshResult.nodes.length}</span></div>
              <div className="kv"><span>要素数</span><span>{meshResult.triangles.length}</span></div>
            </>
          )}

          <h2>領域一覧 ({project.geometry.regions.length})</h2>
          <div className="region-list">
            {project.geometry.regions.map((r) => (
              <div
                key={r.id}
                className={`region-item ${selectedRegionId === r.id ? "selected" : ""}`}
                onClick={() => setSelectedRegionId(r.id)}
              >
                <span>{r.id}</span>
                <span className="tag">{r.type}</span>
              </div>
            ))}
            {project.geometry.regions.length === 0 && (
              <div className="muted">(領域なし。ツールバーで作図してください)</div>
            )}
          </div>

          {selected && (
            <div className="region-edit">
              <label>
                ID
                <CommitTextInput
                  value={selected.id}
                  onCommit={(newId) => renameRegion(selected.id, newId)}
                />
              </label>
              <label>
                種別
                <select
                  value={selected.type}
                  onChange={(e) => setRegionType(selected.id, e.target.value as RegionType)}
                >
                  <option value="conductor">電極 (conductor)</option>
                  <option value="dielectric">誘電体 (dielectric)</option>
                  <option value="charge">空間電荷 (charge)</option>
                </select>
              </label>
              {selected.shape && (
                <>
                  <label>
                    中心 X [mm]
                    <CommitNumberInput
                      value={mToMm(selected.shape.center[0])}
                      step="0.1"
                      onCommit={(x) =>
                        editRegionShape(selected.id, {
                          ...selected.shape!,
                          center: [mmToM(x), selected.shape!.center[1]],
                        })
                      }
                    />
                  </label>
                  <label>
                    中心 Y [mm]
                    <CommitNumberInput
                      value={mToMm(selected.shape.center[1])}
                      step="0.1"
                      onCommit={(y) =>
                        editRegionShape(selected.id, {
                          ...selected.shape!,
                          center: [selected.shape!.center[0], mmToM(y)],
                        })
                      }
                    />
                  </label>
                  <label>
                    半径 [mm]
                    <CommitNumberInput
                      value={mToMm(selected.shape.radius)}
                      step="0.1"
                      onCommit={(radius) => editRegionShape(selected.id, { ...selected.shape!, radius: mmToM(radius) })}
                    />
                  </label>
                </>
              )}
              {selected.type === "conductor" && (
                <label>
                  電位 V [V]
                  <CommitNumberInput
                    value={selected.voltage ?? 0}
                    onCommit={(v) => updateRegion(selected.id, { voltage: v })}
                  />
                </label>
              )}
              {selected.type === "dielectric" && (
                <label>
                  比誘電率 εr
                  <CommitNumberInput
                    value={selected.eps_r ?? 1}
                    onCommit={(v) => updateRegion(selected.id, { eps_r: v })}
                  />
                </label>
              )}
              {selected.type === "charge" && (
                <label>
                  電荷密度 ρ [C/m³]
                  <CommitNumberInput
                    value={selected.rho ?? 0}
                    onCommit={(v) => updateRegion(selected.id, { rho: v })}
                  />
                </label>
              )}
              <button className="danger" onClick={() => deleteRegion(selected.id)}>
                削除
              </button>
            </div>
          )}

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

          {result && (
            <>
              <h2>解析結果</h2>
              <div className="kv"><span>節点数</span><span>{result.mesh.nodes.length}</span></div>
              <div className="kv"><span>要素数</span><span>{result.mesh.triangles.length}</span></div>
              <div className="kv"><span>V min/max</span><span>{result.v_min.toFixed(1)} / {result.v_max.toFixed(1)} V</span></div>
              <div className="kv"><span>|E| max</span><span>{result.e_abs_max.toExponential(2)} V/m</span></div>
              <div className="kv"><span>エネルギー</span><span>{result.energy.toExponential(3)} J/m</span></div>
            </>
          )}
          {error && (
            <>
              <h2>エラー</h2>
              <div className="error">{error}</div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
