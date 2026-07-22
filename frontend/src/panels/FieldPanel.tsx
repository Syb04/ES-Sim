import { CommitNumberInput, CommitTextInput } from "../CommitInput";
import { mToMm, mmToM } from "../units";
import type {
  CircleShape,
  EdgeBcType,
  MeshResult,
  Project,
  Region,
  RegionType,
  SolveResult,
  VoltageRf,
} from "../types";

/**
 * 静電場パネル (タブ1)
 * - ジオメトリ (domain 幅/高さ)・境界条件 (4辺、RF含む)・メッシュ (サイズ)
 * - 領域一覧 + 選択中領域のプロパティ編集
 * - 解析結果サマリ (節点数・V範囲・エネルギー等)・メッシュ結果サマリ
 * 編集操作自体は App 側の commitProject 経由で Undo/Redo 履歴に積まれる
 */

// RF重畳電圧の既定値 (13.56MHz の CCP を想定)
const DEFAULT_VOLTAGE_RF: VoltageRf = { amplitude: 100.0, freq_hz: 13.56e6, phase_deg: 0.0 };

// 矩形 domain の外周エッジ順: 0=下, 1=右, 2=上, 3=左
const EDGE_LABELS = ["下 (y=0)", "右 (x=w)", "上 (y=h)", "左 (x=0)"];

interface Props {
  project: Project;
  domainW: number;
  domainH: number;
  setDomainSize: (w: number, h: number) => void;
  edgeState: (edgeIndex: number) => { type: EdgeBcType; voltage: number; voltageRf?: VoltageRf; seeGamma: number };
  setEdgeType: (edgeIndex: number, type: EdgeBcType) => void;
  setEdgeVoltage: (edgeIndex: number, voltage: number) => void;
  setEdgeVoltageRf: (edgeIndex: number, voltage_rf: VoltageRf | undefined) => void;
  setEdgeSeeGamma: (edgeIndex: number, see_gamma: number) => void;
  setMeshSize: (size: number) => void;
  meshResult: MeshResult | null;
  selectedRegionId: string | null;
  onSelectRegion: (id: string) => void;
  selected: Region | null;
  renameRegion: (oldId: string, newId: string) => void;
  setRegionType: (id: string, type: RegionType) => void;
  editRegionShape: (id: string, shape: CircleShape) => void;
  updateRegion: (id: string, patch: Partial<Region>) => void;
  deleteRegion: (id: string) => void;
  result: SolveResult | null;
}

export default function FieldPanel({
  project,
  domainW,
  domainH,
  setDomainSize,
  edgeState,
  setEdgeType,
  setEdgeVoltage,
  setEdgeVoltageRf,
  setEdgeSeeGamma,
  setMeshSize,
  meshResult,
  selectedRegionId,
  onSelectRegion,
  selected,
  renameRegion,
  setRegionType,
  editRegionShape,
  updateRegion,
  deleteRegion,
  result,
}: Props) {
  return (
    <>
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
                value={st.type}
                onChange={(e) => setEdgeType(i, e.target.value as EdgeBcType)}
              >
                <option value="neumann">なし (Neumann)</option>
                <option value="dirichlet">Dirichlet</option>
                <option value="symmetry">対称 (粒子反射)</option>
                <option value="periodic">周期</option>
              </select>
              {st.type === "dirichlet" && (
                <>
                  <CommitNumberInput value={st.voltage} onCommit={(v) => setEdgeVoltage(i, v)} />
                  <label className="rf-check-inline">
                    <input
                      type="checkbox"
                      checked={!!st.voltageRf}
                      onChange={(e) =>
                        setEdgeVoltageRf(i, e.target.checked ? st.voltageRf ?? DEFAULT_VOLTAGE_RF : undefined)
                      }
                    />
                    RF
                  </label>
                  <label className="rf-check-inline" title="二次電子放出係数 γ">
                    γ
                    <CommitNumberInput
                      className="rf-compact"
                      value={st.seeGamma}
                      onCommit={(v) => setEdgeSeeGamma(i, v)}
                    />
                  </label>
                </>
              )}
            </div>
            {st.type === "dirichlet" && st.voltageRf && (
              <div className="edge-rf-row">
                <CommitNumberInput
                  className="rf-compact"
                  value={st.voltageRf.amplitude}
                  onCommit={(v) => setEdgeVoltageRf(i, { ...st.voltageRf!, amplitude: v })}
                />
                <CommitNumberInput
                  className="rf-compact"
                  value={st.voltageRf.freq_hz}
                  onCommit={(v) => setEdgeVoltageRf(i, { ...st.voltageRf!, freq_hz: v })}
                />
                <CommitNumberInput
                  className="rf-compact"
                  value={st.voltageRf.phase_deg}
                  onCommit={(v) => setEdgeVoltageRf(i, { ...st.voltageRf!, phase_deg: v })}
                />
              </div>
            )}
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
            onClick={() => onSelectRegion(r.id)}
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
            <>
              <label>
                電位 V [V]
                <CommitNumberInput
                  value={selected.voltage ?? 0}
                  onCommit={(v) => updateRegion(selected.id, { voltage: v })}
                />
              </label>
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={!!selected.voltage_rf}
                  onChange={(e) =>
                    updateRegion(selected.id, {
                      voltage_rf: e.target.checked ? selected.voltage_rf ?? DEFAULT_VOLTAGE_RF : undefined,
                    })
                  }
                />
                RF重畳
              </label>
              {selected.voltage_rf && (
                <>
                  <label>
                    振幅 [V]
                    <CommitNumberInput
                      value={selected.voltage_rf.amplitude}
                      onCommit={(v) =>
                        updateRegion(selected.id, { voltage_rf: { ...selected.voltage_rf!, amplitude: v } })
                      }
                    />
                  </label>
                  <label>
                    周波数 [Hz]
                    <CommitNumberInput
                      value={selected.voltage_rf.freq_hz}
                      onCommit={(v) =>
                        updateRegion(selected.id, { voltage_rf: { ...selected.voltage_rf!, freq_hz: v } })
                      }
                    />
                  </label>
                  <label>
                    位相 [deg]
                    <CommitNumberInput
                      value={selected.voltage_rf.phase_deg}
                      onCommit={(v) =>
                        updateRegion(selected.id, { voltage_rf: { ...selected.voltage_rf!, phase_deg: v } })
                      }
                    />
                  </label>
                </>
              )}
              <label>
                二次電子放出係数 γ
                <CommitNumberInput
                  value={selected.see_gamma ?? 0}
                  onCommit={(v) => updateRegion(selected.id, { see_gamma: v })}
                />
              </label>
            </>
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
    </>
  );
}
