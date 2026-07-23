import { useEffect, useRef } from "react";
import { CommitNumberInput, CommitTextInput } from "../CommitInput";
import type { DsmcBoundary, DsmcBoundaryType, DsmcGas, DsmcResult, DsmcSettings, Project } from "../types";

/**
 * ガスパネル (タブ4): DSMC 定常ガス流れ
 * - DSMC 有効チェック (project.dsmc の有無)
 * - ガス種 (VHS分子モデル) 設定
 * - 境界条件リスト (domain エッジ番号 + タイプ + 温度/圧力、追加/削除)
 * - 初期条件・積分設定
 * - 「ガス流れ計算」ボタン (POST /dsmc) と結果サマリ
 * - 結果フィールド (n/T/|u|/p) 選択 + 対数スケール → App 側で PicFieldView 型に変換して CadCanvas へ渡す
 *
 * project.dsmc は Project 本体のフィールドなので、編集は App 側の commitProject 経由で
 * Undo/Redo 履歴に積まれる (ジオメトリ・メッシュ設定と同じ扱い)。
 */

// 結果表示セレクトの選択肢。"u" は要素ごとの流速ベクトルの大きさ |u| を表示する
export type GasResultField = "n" | "t" | "u" | "p";

export const GAS_FIELD_OPTIONS: { value: GasResultField; label: string }[] = [
  { value: "n", label: "数密度 n [m^-3]" },
  { value: "t", label: "温度 T [K]" },
  { value: "u", label: "流速 |u| [m/s]" },
  { value: "p", label: "圧力 p [Pa]" },
];

// フィールドキーごとの単位 (App 側で CadCanvas 用の PicFieldView 構築に使う)。
// DSMC 結果はすべて要素値 (nodeBased=false)
export const GAS_FIELD_META: Record<GasResultField, { unit: string }> = {
  n: { unit: "m^-3" },
  t: { unit: "K" },
  u: { unit: "m/s" },
  p: { unit: "Pa" },
};

// DsmcResult から表示用の要素値配列を取り出す (u のみ大きさへ変換)
export function gasFieldValues(result: DsmcResult, field: GasResultField): number[] {
  if (field === "u") return result.u.map(([ux, uy]) => Math.hypot(ux, uy));
  return result[field];
}

const DEFAULT_GAS: DsmcGas = {
  name: "Ar",
  mass_amu: 39.948,
  d_ref_m: 4.17e-10,
  omega: 0.81,
  t_ref_k: 273.0,
};

// 有効チェックを一度オフにしても、再度オンにしたときに直前の値を復元できるよう保持する既定値
const DEFAULT_DSMC: DsmcSettings = {
  gas: DEFAULT_GAS,
  boundaries: [],
  wall_temperature_k: 300.0,
  init_pressure_pa: 1.0,
  init_temperature_k: 300.0,
  n_particles: 50000,
  dt: null,
  n_steps: 2000,
  avg_steps: 500,
  seed: 0,
};

const DEFAULT_BOUNDARY: DsmcBoundary = { edges: [], type: "wall", temperature_k: 300.0, pressure_pa: null };

const BOUNDARY_TYPE_LABELS: Record<DsmcBoundaryType, string> = {
  wall: "壁 (拡散反射)",
  symmetry: "対称",
  inlet: "流入 (圧力リザーバ)",
  outlet: "流出 (圧力/真空)",
};

// "0,2,3" のようなカンマ区切りテキストをエッジ番号配列にパースする (不正な値は無視)
function parseEdgesText(text: string): number[] {
  return text
    .split(",")
    .map((s) => s.trim())
    .filter((s) => s !== "")
    .map((s) => Math.round(Number(s)))
    .filter((n) => Number.isFinite(n) && n >= 0);
}

interface Props {
  project: Project;
  dsmc: DsmcSettings | null;
  onChange: (next: DsmcSettings | null) => void;
  canRun: boolean;
  busy: boolean;
  onRun: () => void;
  result: DsmcResult | null;
  error: string | null;
  resultField: GasResultField;
  onResultFieldChange: (v: GasResultField) => void;
  logScale: boolean;
  onLogScaleChange: (v: boolean) => void;
}

export default function GasPanel({
  project,
  dsmc,
  onChange,
  canRun,
  busy,
  onRun,
  result,
  error,
  resultField,
  onResultFieldChange,
  logScale,
  onLogScaleChange,
}: Props) {
  const dsmcDefaultsRef = useRef<DsmcSettings>(dsmc ?? DEFAULT_DSMC);
  useEffect(() => {
    if (dsmc) dsmcDefaultsRef.current = dsmc;
  }, [dsmc]);

  const updateGas = (patch: Partial<DsmcGas>) => {
    if (!dsmc) return;
    onChange({ ...dsmc, gas: { ...dsmc.gas, ...patch } });
  };

  const addBoundary = () => {
    if (!dsmc) return;
    onChange({ ...dsmc, boundaries: [...dsmc.boundaries, { ...DEFAULT_BOUNDARY }] });
  };

  const updateBoundary = (i: number, patch: Partial<DsmcBoundary>) => {
    if (!dsmc) return;
    const next = dsmc.boundaries.slice();
    next[i] = { ...next[i], ...patch };
    onChange({ ...dsmc, boundaries: next });
  };

  const removeBoundary = (i: number) => {
    if (!dsmc) return;
    onChange({ ...dsmc, boundaries: dsmc.boundaries.filter((_, idx) => idx !== i) });
  };

  const domainEdgeCount = project.geometry.domain.polygon.length;

  return (
    <>
      <h2>ガス流れ (DSMC)</h2>
      <div className="field">
        <span className="label">有効</span>
        <input
          type="checkbox"
          checked={dsmc !== null}
          onChange={(e) => onChange(e.target.checked ? dsmcDefaultsRef.current : null)}
        />
      </div>
      <p className="hint">
        NTC 法 + VHS 分子モデルによる定常ガス流れ解析。既存の三角形メッシュをセルとして使う
        (平面2Dのみ対応)。結果は PIC の MCC で「DSMCガス場を使用」を有効にすると背景ガスとして使える。
      </p>

      {dsmc && (
        <>
          <h2>ガス種 (VHS)</h2>
          <div className="field">
            <span className="label">ガス名</span>
            <CommitTextInput value={dsmc.gas.name} onCommit={(v) => updateGas({ name: v })} />
          </div>
          <div className="field">
            <span className="label">分子質量 [amu]</span>
            <CommitNumberInput value={dsmc.gas.mass_amu} onCommit={(v) => updateGas({ mass_amu: v })} />
          </div>
          <div className="field">
            <span className="label">VHS基準直径 [m]</span>
            <CommitNumberInput value={dsmc.gas.d_ref_m} onCommit={(v) => updateGas({ d_ref_m: v })} />
          </div>
          <div className="field">
            <span className="label">粘性温度指数 ω</span>
            <CommitNumberInput value={dsmc.gas.omega} onCommit={(v) => updateGas({ omega: v })} />
          </div>
          <div className="field">
            <span className="label">基準温度 [K]</span>
            <CommitNumberInput value={dsmc.gas.t_ref_k} onCommit={(v) => updateGas({ t_ref_k: v })} />
          </div>

          <h2>境界条件 (domain 外周)</h2>
          <p className="hint">
            domain 外周のエッジ番号 (カンマ区切り、0-indexed、現在 {domainEdgeCount} 辺) を指定します。
            未指定のエッジは壁 (拡散反射) になります。
          </p>
          <div className="collector-list">
            {dsmc.boundaries.length === 0 && <div className="muted">(未指定。すべて壁境界として扱われます)</div>}
            {dsmc.boundaries.map((b, i) => (
              <div className="dsmc-boundary-row" key={i}>
                <div className="dsmc-boundary-row-main">
                  <CommitTextInput
                    className="dsmc-edges-input"
                    value={b.edges.join(",")}
                    onCommit={(v) => updateBoundary(i, { edges: parseEdgesText(v) })}
                  />
                  <select
                    value={b.type}
                    onChange={(e) => updateBoundary(i, { type: e.target.value as DsmcBoundaryType })}
                  >
                    {(Object.keys(BOUNDARY_TYPE_LABELS) as DsmcBoundaryType[]).map((t) => (
                      <option key={t} value={t}>
                        {BOUNDARY_TYPE_LABELS[t]}
                      </option>
                    ))}
                  </select>
                  <button className="danger collector-delete" onClick={() => removeBoundary(i)} title="この境界を削除">
                    ×
                  </button>
                </div>
                <div className="dsmc-boundary-row-sub">
                  <label className="rf-compact-label" title="温度 [K]">
                    T
                    <CommitNumberInput
                      className="rf-compact"
                      value={b.temperature_k}
                      onCommit={(v) => updateBoundary(i, { temperature_k: v })}
                    />
                  </label>
                  {(b.type === "inlet" || b.type === "outlet") && (
                    <label className="rf-compact-label" title="圧力 [Pa] (outlet は空欄/0で真空排気)">
                      p
                      <input
                        type="text"
                        inputMode="decimal"
                        className="rf-compact"
                        value={b.pressure_pa == null ? "" : String(b.pressure_pa)}
                        placeholder={b.type === "outlet" ? "真空" : ""}
                        onChange={(e) => {
                          const raw = e.target.value;
                          if (raw.trim() === "") {
                            updateBoundary(i, { pressure_pa: null });
                            return;
                          }
                          const n = Number(raw);
                          if (Number.isFinite(n)) updateBoundary(i, { pressure_pa: n });
                        }}
                      />
                    </label>
                  )}
                </div>
              </div>
            ))}
          </div>
          <div className="actions">
            <button className="secondary" onClick={addBoundary}>
              境界を追加
            </button>
          </div>

          <h2>初期条件・計算設定</h2>
          <div className="field">
            <span className="label">壁温 (未指定エッジ) [K]</span>
            <CommitNumberInput
              value={dsmc.wall_temperature_k}
              onCommit={(v) => onChange({ ...dsmc, wall_temperature_k: v })}
            />
          </div>
          <div className="field">
            <span className="label">初期充填圧 [Pa]</span>
            <CommitNumberInput
              value={dsmc.init_pressure_pa}
              onCommit={(v) => onChange({ ...dsmc, init_pressure_pa: v })}
            />
          </div>
          <div className="field">
            <span className="label">初期温度 [K]</span>
            <CommitNumberInput
              value={dsmc.init_temperature_k}
              onCommit={(v) => onChange({ ...dsmc, init_temperature_k: v })}
            />
          </div>
          <div className="field">
            <span className="label">目標粒子数</span>
            <CommitNumberInput
              value={dsmc.n_particles}
              onCommit={(v) => onChange({ ...dsmc, n_particles: Math.max(1, Math.round(v)) })}
            />
          </div>
          <div className="field">
            <span className="label">dt [s] (空欄=自動)</span>
            <input
              type="text"
              value={dsmc.dt === null ? "" : String(dsmc.dt)}
              placeholder="自動"
              onChange={(e) => {
                const raw = e.target.value;
                if (raw.trim() === "") {
                  onChange({ ...dsmc, dt: null });
                  return;
                }
                const n = Number(raw);
                if (Number.isFinite(n)) onChange({ ...dsmc, dt: n });
              }}
            />
          </div>
          <div className="field">
            <span className="label">ステップ数</span>
            <CommitNumberInput
              value={dsmc.n_steps}
              onCommit={(v) => onChange({ ...dsmc, n_steps: Math.max(1, Math.round(v)) })}
            />
          </div>
          <div className="field">
            <span className="label">平均ステップ数</span>
            <CommitNumberInput
              value={dsmc.avg_steps}
              onCommit={(v) => onChange({ ...dsmc, avg_steps: Math.max(1, Math.round(v)) })}
            />
          </div>
          <div className="field">
            <span className="label">乱数シード</span>
            <CommitNumberInput value={dsmc.seed} onCommit={(v) => onChange({ ...dsmc, seed: Math.round(v) })} />
          </div>

          <div className="actions">
            <button onClick={onRun} disabled={!canRun || busy}>
              {busy ? "計算中..." : "ガス流れ計算"}
            </button>
          </div>

          {error && (
            <>
              <h2>エラー</h2>
              <div className="error">{error}</div>
            </>
          )}

          {result && (
            <>
              <h2>結果</h2>
              <div className="kv">
                <span>シミュレーション粒子数</span>
                <span>{result.n_particles}</span>
              </div>
              <div className="kv">
                <span>マクロ重み (実分子数/粒子)</span>
                <span>{result.macro_weight.toExponential(3)}</span>
              </div>
              <div className="kv">
                <span>実際に使った dt [s]</span>
                <span>{result.dt.toExponential(3)}</span>
              </div>
              <div className="kv">
                <span>流入 (平均区間、実分子数)</span>
                <span>{result.inflow.toExponential(3)}</span>
              </div>
              <div className="kv">
                <span>流出 (平均区間、実分子数)</span>
                <span>{result.outflow.toExponential(3)}</span>
              </div>

              <div className="field">
                <span className="label">結果表示</span>
                <select value={resultField} onChange={(e) => onResultFieldChange(e.target.value as GasResultField)}>
                  {GAS_FIELD_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <span className="label">対数スケール</span>
                <input type="checkbox" checked={logScale} onChange={(e) => onLogScaleChange(e.target.checked)} />
              </div>
            </>
          )}
        </>
      )}
    </>
  );
}
