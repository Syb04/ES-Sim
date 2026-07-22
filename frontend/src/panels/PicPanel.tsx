import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { CommitNumberInput, CommitTextInput } from "../CommitInput";
import type {
  Emitter,
  InitialPlasma,
  McSettings,
  PicCollectorResult,
  PicCycle,
  PicDiag,
  PicFields,
  PicFrameMsg,
  PicInjection,
  PicSettings,
  PicStartedMsg,
  XsProcess,
} from "../types";

// 周期アニメーションで表示可能なフィールド (すべて節点値)
export type CyclePicField = "phi" | "n_e" | "n_i";

export const CYCLE_FIELD_OPTIONS: { value: CyclePicField; label: string }[] = [
  { value: "phi", label: "電位 [V]" },
  { value: "n_e", label: "電子密度 [m^-3]" },
  { value: "n_i", label: "イオン密度 [m^-3]" },
];

// PIC「結果表示」セレクトの選択肢。"live" はライブ (最終フレーム) 表示、それ以外は
// done メッセージの fields から時間平均フィールドをカラーマップで描画する対象を表す
export type PicResultField = "live" | "phi" | "e_abs" | "n_e" | "n_i" | "te_ev" | "ion_rate";

export const PIC_FIELD_OPTIONS: { value: PicResultField; label: string }[] = [
  { value: "live", label: "ライブ (最終フレーム)" },
  { value: "phi", label: "電位 [V]" },
  { value: "e_abs", label: "|E| [V/m]" },
  { value: "n_e", label: "電子密度 [m^-3]" },
  { value: "n_i", label: "イオン密度 [m^-3]" },
  { value: "te_ev", label: "電子温度 [eV]" },
  { value: "ion_rate", label: "電離レート [m^-3 s^-1]" },
];

// フィールドキーごとの節点/要素の別・単位 (App 側で CadCanvas 用の picFieldView 構築に使う)
export const PIC_FIELD_META: Record<Exclude<PicResultField, "live">, { unit: string; nodeBased: boolean }> = {
  phi: { unit: "V", nodeBased: true },
  e_abs: { unit: "V/m", nodeBased: false },
  n_e: { unit: "m^-3", nodeBased: true },
  n_i: { unit: "m^-3", nodeBased: true },
  te_ev: { unit: "eV", nodeBased: true },
  ion_rate: { unit: "m^-3 s^-1", nodeBased: true },
};

/**
 * PICパネル
 * - 初期プラズマ装荷 / エミッタ定常注入 / マクロ粒子数・積分設定の編集
 * - project.pic として保存/読込対象だが、particles と同様 Undo/Redo 履歴には積まない
 * - 実行制御 (開始/停止・進捗・警告) と診断表示 (数値 + 履歴チャート)
 */

interface Props {
  pic: PicSettings;
  onChange: (next: PicSettings) => void;
  // フェーズ2 (粒子) パネルの現在のエミッタ設定。injection.emitter として共用する
  emitter: Emitter;
  canRun: boolean;
  running: boolean;
  onStart: () => void;
  onStop: () => void;
  started: PicStartedMsg | null;
  frame: PicFrameMsg | null;
  history: PicDiag[];
  error: string | null;
  // done メッセージで受け取った時間平均フィールド一式 (未受信 or 未対応バックエンドでは null)
  fields: PicFields | null;
  // 「結果表示」セレクトの現在値と対数スケールチェックボックスの状態 (App 側で保持・CadCanvas に反映)
  resultField: PicResultField;
  onResultFieldChange: (v: PicResultField) => void;
  logScale: boolean;
  onLogScaleChange: (v: boolean) => void;

  // done で受信した RF 1周期の位相分解データ (RFなし/phase_bins=0 では null)。
  // 新しい実行開始時に App 側で null にリセットされる
  cycle: PicCycle | null;
  cycleField: CyclePicField;
  onCycleFieldChange: (v: CyclePicField) => void;
  cycleLogScale: boolean;
  onCycleLogScaleChange: (v: boolean) => void;
  cyclePlaying: boolean;
  onCyclePlayingChange: (v: boolean) => void;
  cycleBinIndex: number;
  onCycleBinIndexChange: (v: number) => void;
  cycleFps: number;
  onCycleFpsChange: (v: number) => void;
  cycleShowParticles: boolean;
  onCycleShowParticlesChange: (v: boolean) => void;

  // done で受信した IEDF/IADF コレクタの記録結果 (collector 未配置・未受信では null)。
  // 新しい実行開始時に App 側で null にリセットされる
  collectorResult: PicCollectorResult | null;
}

const DEFAULT_INITIAL_PLASMA: InitialPlasma = {
  density: 1.0e14,
  te_ev: 2.0,
  ti_ev: 0.03,
  ion_mass_amu: 40.0,
  immobile_ions: false,
  seed: 0,
};

// MCC(背景ガス衝突)設定の既定値。有効チェックを一度オフにしても直前の値を復元できるよう保持する
const DEFAULT_MCC: McSettings = {
  gas: { name: "Ar", pressure_pa: 10.0, temperature_k: 300.0 },
  electron_processes: [],
  ion_processes: [],
  seed: 0,
};

// プロセスラベルは長いことがあるので一覧表示では短縮する (title 属性でフルテキストを見せる)
function shortLabel(label: string, max = 34): string {
  return label.length > max ? `${label.slice(0, max - 1)}…` : label;
}

// LXCatインポート済みの断面積プロセス一覧 (種別・ラベル(短縮)・閾値・点数)
function ProcessList({ processes }: { processes: XsProcess[] }) {
  if (processes.length === 0) return <div className="muted">(未読込)</div>;
  return (
    <div className="mcc-process-list">
      {processes.map((p, i) => (
        <div className="mcc-process-row" key={i} title={p.label}>
          <span className="tag">{p.kind}</span>
          <span className="mcc-process-label">{shortLabel(p.label)}</span>
          <span>{p.threshold_ev.toFixed(2)} eV</span>
          <span>{p.energy_ev.length} pts</span>
        </div>
      ))}
    </div>
  );
}

function emitterSummary(e: Emitter): string {
  if (e.kind === "point") return `点 (${(e.p1[0] * 1000).toFixed(1)}, ${(e.p1[1] * 1000).toFixed(1)} mm), n=${e.n}`;
  return `ライン (${(e.p1[0] * 1000).toFixed(1)}, ${(e.p1[1] * 1000).toFixed(1)}) - (${(e.p2[0] * 1000).toFixed(1)}, ${(e.p2[1] * 1000).toFixed(1)}) mm, n=${e.n}`;
}

export default function PicPanel({
  pic,
  onChange,
  emitter,
  canRun,
  running,
  onStart,
  onStop,
  started,
  frame,
  history,
  error,
  fields,
  resultField,
  onResultFieldChange,
  logScale,
  onLogScaleChange,
  cycle,
  cycleField,
  onCycleFieldChange,
  cycleLogScale,
  onCycleLogScaleChange,
  cyclePlaying,
  onCyclePlayingChange,
  cycleBinIndex,
  onCycleBinIndexChange,
  cycleFps,
  onCycleFpsChange,
  cycleShowParticles,
  onCycleShowParticlesChange,
  collectorResult,
}: Props) {
  // 有効チェックを一度オフにしても、再度オンにしたときに直前の値を復元できるよう保持する
  const plasmaDefaultsRef = useRef<InitialPlasma>(pic.initial_plasma ?? DEFAULT_INITIAL_PLASMA);
  useEffect(() => {
    if (pic.initial_plasma) plasmaDefaultsRef.current = pic.initial_plasma;
  }, [pic.initial_plasma]);

  const injectionDefaultsRef = useRef<{ species: "electron" | "ion"; current_a_per_m: number }>({
    species: pic.injection?.species ?? "electron",
    current_a_per_m: pic.injection?.current_a_per_m ?? 1e-4,
  });
  useEffect(() => {
    if (pic.injection) {
      injectionDefaultsRef.current = {
        species: pic.injection.species,
        current_a_per_m: pic.injection.current_a_per_m,
      };
    }
  }, [pic.injection]);

  const updatePlasma = (patch: Partial<InitialPlasma>) => {
    if (!pic.initial_plasma) return;
    onChange({ ...pic, initial_plasma: { ...pic.initial_plasma, ...patch } });
  };

  const updateInjection = (patch: Partial<PicInjection>) => {
    if (!pic.injection) return;
    onChange({ ...pic, injection: { ...pic.injection, ...patch } });
  };

  // MCC設定。有効チェックを一度オフにしても、再度オンにしたときに直前の値を復元できるよう保持する
  const mccDefaultsRef = useRef<McSettings>(pic.mcc ?? DEFAULT_MCC);
  useEffect(() => {
    if (pic.mcc) mccDefaultsRef.current = pic.mcc;
  }, [pic.mcc]);

  const updateMcc = (patch: Partial<McSettings>) => {
    if (!pic.mcc) return;
    onChange({ ...pic, mcc: { ...pic.mcc, ...patch } });
  };
  const updateGas = (patch: Partial<McSettings["gas"]>) => {
    if (!pic.mcc) return;
    onChange({ ...pic, mcc: { ...pic.mcc, gas: { ...pic.mcc.gas, ...patch } } });
  };

  // LXCatインポート (電子/イオン共通)。ファイルテキストを api.lxcatParse に送り、
  // 成功したら該当プロセス列を置換する。失敗時はエラー文言を表示する
  const [lxcatWarnings, setLxcatWarnings] = useState<string[]>([]);
  const [lxcatError, setLxcatError] = useState<string | null>(null);
  const electronFileRef = useRef<HTMLInputElement>(null);
  const ionFileRef = useRef<HTMLInputElement>(null);

  const importLxcat = (species: "electron" | "ion", file: File) => {
    const reader = new FileReader();
    reader.onload = () => {
      const text = String(reader.result ?? "");
      api
        .lxcatParse(text, species)
        .then((res) => {
          setLxcatError(null);
          setLxcatWarnings(res.warnings);
          if (species === "electron") updateMcc({ electron_processes: res.processes });
          else updateMcc({ ion_processes: res.processes });
        })
        .catch((e) => setLxcatError(String(e)));
    };
    reader.readAsText(file);
  };

  const progressPct = started && started.n_steps > 0 ? Math.min(100, ((frame?.step ?? 0) / started.n_steps) * 100) : 0;

  // IEDF/IADF ヒストグラムのビン数 (既定60、変更で再ビニング。コレクタ設定自体ではないので project 保存対象外)
  const [collectorBins, setCollectorBins] = useState(60);

  // コレクタ生サンプル (energy_ev, angle_deg, weight) をCSVでダウンロードする
  const downloadCollectorCsv = () => {
    if (!collectorResult) return;
    const lines = ["energy_ev,angle_deg,weight"];
    for (let i = 0; i < collectorResult.energies_ev.length; i++) {
      lines.push(`${collectorResult.energies_ev[i]},${collectorResult.angles_deg[i]},${collectorResult.weights[i]}`);
    }
    const blob = new Blob([lines.join("\n")], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "iedf_iadf.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <>
      <h2>PIC: 初期プラズマ</h2>
      <div className="field">
        <span className="label">有効</span>
        <input
          type="checkbox"
          checked={pic.initial_plasma !== null}
          onChange={(e) =>
            onChange({ ...pic, initial_plasma: e.target.checked ? plasmaDefaultsRef.current : null })
          }
        />
      </div>
      {pic.initial_plasma && (
        <>
          <div className="field">
            <span className="label">密度 [m^-3]</span>
            <CommitNumberInput value={pic.initial_plasma.density} onCommit={(v) => updatePlasma({ density: v })} />
          </div>
          <div className="field">
            <span className="label">Te [eV]</span>
            <CommitNumberInput value={pic.initial_plasma.te_ev} onCommit={(v) => updatePlasma({ te_ev: v })} />
          </div>
          <div className="field">
            <span className="label">Ti [eV]</span>
            <CommitNumberInput value={pic.initial_plasma.ti_ev} onCommit={(v) => updatePlasma({ ti_ev: v })} />
          </div>
          <div className="field">
            <span className="label">イオン質量 [amu]</span>
            <CommitNumberInput
              value={pic.initial_plasma.ion_mass_amu}
              onCommit={(v) => updatePlasma({ ion_mass_amu: v })}
            />
          </div>
          <div className="field">
            <span className="label">イオン固定</span>
            <input
              type="checkbox"
              checked={pic.initial_plasma.immobile_ions}
              onChange={(e) => updatePlasma({ immobile_ions: e.target.checked })}
            />
          </div>
          <div className="field">
            <span className="label">乱数シード</span>
            <CommitNumberInput
              value={pic.initial_plasma.seed}
              onCommit={(v) => updatePlasma({ seed: Math.round(v) })}
            />
          </div>
        </>
      )}

      <h2>PIC: 注入</h2>
      <div className="field">
        <span className="label">有効</span>
        <input
          type="checkbox"
          checked={pic.injection !== null}
          onChange={(e) =>
            onChange({
              ...pic,
              injection: e.target.checked
                ? {
                    emitter,
                    species: injectionDefaultsRef.current.species,
                    current_a_per_m: injectionDefaultsRef.current.current_a_per_m,
                  }
                : null,
            })
          }
        />
      </div>
      {pic.injection && (
        <>
          <p className="hint">
            エミッタはフェーズ2(粒子)パネルの設定を共用します: {emitterSummary(emitter)}
          </p>
          <div className="field">
            <span className="label">種</span>
            <select
              value={pic.injection.species}
              onChange={(e) => updateInjection({ species: e.target.value as "electron" | "ion" })}
            >
              <option value="electron">電子</option>
              <option value="ion">イオン</option>
            </select>
          </div>
          <div className="field">
            <span className="label">電流 [A/m]</span>
            <CommitNumberInput
              value={pic.injection.current_a_per_m}
              onCommit={(v) => updateInjection({ current_a_per_m: v })}
            />
          </div>
        </>
      )}

      <h2>PIC: MCC(衝突)</h2>
      <div className="field">
        <span className="label">有効</span>
        <input
          type="checkbox"
          checked={pic.mcc !== null}
          onChange={(e) => onChange({ ...pic, mcc: e.target.checked ? mccDefaultsRef.current : null })}
        />
      </div>
      {pic.mcc && (
        <>
          <div className="field">
            <span className="label">ガス名</span>
            <CommitTextInput value={pic.mcc.gas.name} onCommit={(v) => updateGas({ name: v })} />
          </div>
          <div className="field">
            <span className="label">圧力 [Pa]</span>
            <CommitNumberInput value={pic.mcc.gas.pressure_pa} onCommit={(v) => updateGas({ pressure_pa: v })} />
          </div>
          <div className="field">
            <span className="label">ガス温度 [K]</span>
            <CommitNumberInput
              value={pic.mcc.gas.temperature_k}
              onCommit={(v) => updateGas({ temperature_k: v })}
            />
          </div>

          <div className="actions">
            <button className="secondary" onClick={() => electronFileRef.current?.click()}>
              電子断面積を読込
            </button>
            <button className="secondary" onClick={() => ionFileRef.current?.click()}>
              イオン断面積を読込
            </button>
            <input
              ref={electronFileRef}
              type="file"
              accept=".txt,text/plain"
              className="file-input"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) importLxcat("electron", f);
                e.target.value = "";
              }}
            />
            <input
              ref={ionFileRef}
              type="file"
              accept=".txt,text/plain"
              className="file-input"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) importLxcat("ion", f);
                e.target.value = "";
              }}
            />
          </div>

          {lxcatError && <div className="error">{lxcatError}</div>}
          {lxcatWarnings.length > 0 && (
            <div className="pic-warnings">
              {lxcatWarnings.map((w, i) => (
                <div key={i}>警告: {w}</div>
              ))}
            </div>
          )}

          <p className="hint">電子プロセス ({pic.mcc.electron_processes.length})</p>
          <ProcessList processes={pic.mcc.electron_processes} />
          <div className="actions">
            <button className="secondary" onClick={() => updateMcc({ electron_processes: [] })}>
              電子プロセスをクリア
            </button>
          </div>

          <p className="hint">イオンプロセス ({pic.mcc.ion_processes.length})</p>
          <ProcessList processes={pic.mcc.ion_processes} />
          <div className="actions">
            <button className="secondary" onClick={() => updateMcc({ ion_processes: [] })}>
              イオンプロセスをクリア
            </button>
          </div>

          <div className="field">
            <span className="label">乱数シード</span>
            <CommitNumberInput value={pic.mcc.seed} onCommit={(v) => updateMcc({ seed: Math.round(v) })} />
          </div>
        </>
      )}
      <div className="field">
        <span className="label">SEE初期エネルギー [eV]</span>
        <CommitNumberInput
          value={pic.see_energy_ev}
          onCommit={(v) => onChange({ ...pic, see_energy_ev: v })}
        />
      </div>

      <h2>PIC: 計算設定</h2>
      <div className="field">
        <span className="label">マクロ粒子数</span>
        <CommitNumberInput
          value={pic.n_macro}
          onCommit={(v) => onChange({ ...pic, n_macro: Math.max(1, Math.round(v)) })}
        />
      </div>
      <div className="field">
        <span className="label">dt [s] (空欄=自動)</span>
        <input
          type="text"
          value={pic.dt === null ? "" : String(pic.dt)}
          placeholder="自動"
          onChange={(e) => {
            const raw = e.target.value;
            if (raw.trim() === "") {
              onChange({ ...pic, dt: null });
              return;
            }
            const n = Number(raw);
            if (Number.isFinite(n)) onChange({ ...pic, dt: n });
          }}
        />
      </div>
      <div className="field">
        <span className="label">ステップ数</span>
        <CommitNumberInput
          value={pic.n_steps}
          onCommit={(v) => onChange({ ...pic, n_steps: Math.max(1, Math.round(v)) })}
        />
      </div>
      <div className="field">
        <span className="label">フレーム間隔</span>
        <CommitNumberInput
          value={pic.frame_every}
          onCommit={(v) => onChange({ ...pic, frame_every: Math.max(1, Math.round(v)) })}
        />
      </div>
      <div className="field">
        <span className="label">平均ステップ数 (空欄=最後の25%)</span>
        <input
          type="text"
          value={pic.avg_steps === null || pic.avg_steps === undefined ? "" : String(pic.avg_steps)}
          placeholder="最後の25%"
          onChange={(e) => {
            const raw = e.target.value;
            if (raw.trim() === "") {
              onChange({ ...pic, avg_steps: null });
              return;
            }
            const n = Number(raw);
            if (Number.isFinite(n)) onChange({ ...pic, avg_steps: Math.max(1, Math.round(n)) });
          }}
        />
      </div>
      <div className="field">
        <span className="label">位相ビン数 (周期アニメ用、0=無効)</span>
        <CommitNumberInput
          value={pic.phase_bins ?? 40}
          onCommit={(v) => onChange({ ...pic, phase_bins: Math.max(0, Math.round(v)) })}
        />
      </div>

      <h2>PIC: IEDF/IADF (コレクタ)</h2>
      <p className="hint">
        キャンバスの「コレクタ」ツールでウエハ面上に2点クリックして線分を配置します。
      </p>
      <div className="kv">
        <span>p1 [mm]</span>
        <span>
          {pic.collector
            ? `(${(pic.collector.p1[0] * 1000).toFixed(2)}, ${(pic.collector.p1[1] * 1000).toFixed(2)})`
            : "未配置"}
        </span>
      </div>
      <div className="kv">
        <span>p2 [mm]</span>
        <span>
          {pic.collector
            ? `(${(pic.collector.p2[0] * 1000).toFixed(2)}, ${(pic.collector.p2[1] * 1000).toFixed(2)})`
            : "未配置"}
        </span>
      </div>
      <div className="field">
        <span className="label">判定距離 tol [mm] (空欄=メッシュサイズ)</span>
        <input
          type="text"
          disabled={!pic.collector}
          value={pic.collector?.tol == null ? "" : String(pic.collector.tol * 1000)}
          placeholder="メッシュサイズ"
          onChange={(e) => {
            if (!pic.collector) return;
            const raw = e.target.value;
            if (raw.trim() === "") {
              onChange({ ...pic, collector: { ...pic.collector, tol: null } });
              return;
            }
            const n = Number(raw);
            if (Number.isFinite(n)) onChange({ ...pic, collector: { ...pic.collector, tol: n / 1000 } });
          }}
        />
      </div>
      <div className="actions">
        <button className="secondary" onClick={() => onChange({ ...pic, collector: null })} disabled={!pic.collector}>
          コレクタをクリア
        </button>
      </div>

      {collectorResult && (
        <>
          <div className="kv">
            <span>記録サンプル数</span>
            <span>{collectorResult.count}</span>
          </div>
          <div className="kv">
            <span>総実イオン数 [1/m]</span>
            <span>{collectorResult.total_weight.toExponential(3)}</span>
          </div>
          {collectorResult.truncated && (
            <div className="pic-warnings">
              警告: サンプル数上限に達したため、以降は個数のみ集計しています (ヒストグラムは記録分のみ反映)
            </div>
          )}
          <div className="field">
            <span className="label">ビン数</span>
            <CommitNumberInput
              value={collectorBins}
              onCommit={(v) => setCollectorBins(Math.max(1, Math.round(v)))}
            />
          </div>
          <p className="hint">IEDF (入射エネルギー分布、横軸 eV)</p>
          <HistogramChart
            values={collectorResult.energies_ev}
            weights={collectorResult.weights}
            bins={collectorBins}
            unit="eV"
            color="#4da3ff"
          />
          <p className="hint">IADF (入射角分布、横軸 deg、-90〜90)</p>
          <HistogramChart
            values={collectorResult.angles_deg}
            weights={collectorResult.weights}
            bins={collectorBins}
            unit="deg"
            color="#ffb84d"
            fixedRange={[-90, 90]}
          />
          <div className="actions">
            <button className="secondary" onClick={downloadCollectorCsv}>
              CSV保存
            </button>
          </div>
        </>
      )}

      <div className="actions">
        <button onClick={onStart} disabled={!canRun || running}>
          {running ? "実行中..." : "PIC開始"}
        </button>
        <button className="secondary" onClick={onStop} disabled={!running}>
          停止
        </button>
      </div>

      {started && (
        <>
          <div className="pic-progress">
            <div className="pic-progress-bar" style={{ width: `${progressPct}%` }} />
          </div>
          <div className="kv">
            <span>進捗</span>
            <span>{frame?.step ?? 0} / {started.n_steps}</span>
          </div>
          {started.warnings.length > 0 && (
            <div className="pic-warnings">
              {started.warnings.map((w, i) => (
                <div key={i}>警告: {w}</div>
              ))}
            </div>
          )}
        </>
      )}

      {frame && (
        <>
          <h2>PIC: 診断</h2>
          <div className="kv">
            <span>粒子数 (電子/イオン)</span>
            <span>{frame.diag.n_e} / {frame.diag.n_i}</span>
          </div>
          <div className="kv">
            <span>φ min/max</span>
            <span>{frame.diag.phi_min.toFixed(2)} / {frame.diag.phi_max.toFixed(2)} V</span>
          </div>
          <div className="kv">
            <span>壁吸収 (電子/イオン)</span>
            <span>{frame.diag.wall_e} / {frame.diag.wall_i}</span>
          </div>
          <div className="kv">
            <span>衝突/電離/SEE (累計)</span>
            <span>
              {frame.diag.coll_e ?? "-"} / {frame.diag.ion_events ?? "-"} / {frame.diag.see_events ?? "-"}
            </span>
          </div>
          <div className="kv">
            <span>誘電体表面電荷 [C/m]</span>
            <span>{frame.diag.surf_q !== undefined ? frame.diag.surf_q.toExponential(3) : "-"}</span>
          </div>
          <PicHistoryChart history={history} />
        </>
      )}

      {fields && (
        <>
          <h2>PIC: 結果フィールド</h2>
          <p className="hint">時間平均ステップ数: {fields.avg_steps}</p>
          <div className="field">
            <span className="label">結果表示</span>
            <select
              value={resultField}
              onChange={(e) => onResultFieldChange(e.target.value as PicResultField)}
            >
              {PIC_FIELD_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>
          {resultField !== "live" && (
            <div className="field">
              <span className="label">対数スケール</span>
              <input
                type="checkbox"
                checked={logScale}
                onChange={(e) => onLogScaleChange(e.target.checked)}
              />
            </div>
          )}
        </>
      )}

      {cycle && (
        <PicCyclePlayer
          cycle={cycle}
          field={cycleField}
          onFieldChange={onCycleFieldChange}
          logScale={cycleLogScale}
          onLogScaleChange={onCycleLogScaleChange}
          playing={cyclePlaying}
          onPlayingChange={onCyclePlayingChange}
          binIndex={cycleBinIndex}
          onBinIndexChange={onCycleBinIndexChange}
          fps={cycleFps}
          onFpsChange={onCycleFpsChange}
          showParticles={cycleShowParticles}
          onShowParticlesChange={onCycleShowParticlesChange}
        />
      )}

      {error && (
        <>
          <h2>PICエラー</h2>
          <div className="error">{error}</div>
        </>
      )}
    </>
  );
}

// 小さな履歴チャート: 横軸=時刻、縦軸は 運動E・場E・全E・粒子数 の4系列を
// それぞれ独立に 0〜1 正規化して重ね描きする (canvas 直描き、依存追加なし)
function PicHistoryChart({ history }: { history: PicDiag[] }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const el = canvasRef.current;
    if (!el) return;
    const dpr = window.devicePixelRatio || 1;
    const rect = el.getBoundingClientRect();
    el.width = rect.width * dpr;
    el.height = rect.height * dpr;
    const ctx = el.getContext("2d")!;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, rect.width, rect.height);

    // 防御: 想定外の形式 (配列でない等) が渡っても例外で画面全体を落とさない
    if (!Array.isArray(history) || history.length < 2) return;

    const ts = history.map((h) => h.t);
    const ke = history.map((h) => h.ke_e + h.ke_i);
    const fe = history.map((h) => h.fe);
    const total = ke.map((v, i) => v + fe[i]);
    const nParticles = history.map((h) => h.n_e + h.n_i);

    const tMin = ts[0];
    const tMax = ts[ts.length - 1];
    const tRange = tMax - tMin || 1;
    const xOf = (t: number) => ((t - tMin) / tRange) * rect.width;

    const padY = 3;
    const drawSeries = (values: number[], color: string) => {
      const vMin = Math.min(...values);
      const vMax = Math.max(...values);
      const range = vMax - vMin || 1;
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.3;
      ctx.beginPath();
      values.forEach((v, i) => {
        const x = xOf(ts[i]);
        const y = rect.height - padY - ((v - vMin) / range) * (rect.height - 2 * padY);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();
    };

    drawSeries(ke, "#4da3ff");
    drawSeries(fe, "#ffb84d");
    drawSeries(total, "#6fd08c");
    drawSeries(nParticles, "#d8dce4");
  }, [history]);

  return (
    <>
      <canvas ref={canvasRef} className="pic-chart" />
      <div className="pic-chart-legend">
        <span><span className="swatch" style={{ background: "#4da3ff" }} />運動E</span>
        <span><span className="swatch" style={{ background: "#ffb84d" }} />場E</span>
        <span><span className="swatch" style={{ background: "#6fd08c" }} />全E</span>
        <span><span className="swatch" style={{ background: "#d8dce4" }} />粒子数</span>
      </div>
    </>
  );
}

interface HistogramChartProps {
  values: number[];   // サンプル値 (energies_ev または angles_deg)
  weights: number[];  // 同数、重み付きカウントに使う (values と同じインデックス対応)
  bins: number;       // ビン数
  unit: string;       // 横軸の単位表示
  color: string;      // バーの色
  // 指定時はこの範囲でビニングする (未指定時は values の min/max を使う)。IADFは常に固定 [-90, 90]
  fixedRange?: [number, number];
}

// IEDF/IADF 用のヒストグラム (重み付きカウント、canvas 直描き)。
// ProfilePanel のグラフ実装を参考に、軸目盛り・ホバーでのビン範囲/カウント読み取りを持たせる
function HistogramChart({ values, weights, bins, unit, color, fixedRange }: HistogramChartProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const scaleRef = useRef<{ padL: number; binW: number; n: number } | null>(null);

  // 重み付きカウントのビニング (values/weights が変わるか bins/range が変わるたびに再計算)
  const { counts, lo, hi } = useMemo(() => {
    const n = Math.max(1, Math.round(bins));
    let rangeLo: number;
    let rangeHi: number;
    if (fixedRange) {
      [rangeLo, rangeHi] = fixedRange;
    } else if (values.length === 0) {
      rangeLo = 0;
      rangeHi = 1;
    } else {
      rangeLo = Math.min(...values);
      rangeHi = Math.max(...values);
      if (!(rangeHi > rangeLo)) rangeHi = rangeLo + 1;
    }
    const counts = new Array(n).fill(0) as number[];
    const range = rangeHi - rangeLo || 1;
    for (let i = 0; i < values.length; i++) {
      const v = values[i];
      let idx = Math.floor(((v - rangeLo) / range) * n);
      if (idx < 0) idx = 0;
      if (idx >= n) idx = n - 1;
      counts[idx] += weights[i] ?? 1;
    }
    return { counts, lo: rangeLo, hi: rangeHi };
  }, [values, weights, bins, fixedRange]);

  useEffect(() => {
    const el = canvasRef.current;
    if (!el) return;
    const dpr = window.devicePixelRatio || 1;
    const rect = el.getBoundingClientRect();
    el.width = rect.width * dpr;
    el.height = rect.height * dpr;
    const ctx = el.getContext("2d")!;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, rect.width, rect.height);

    const padL = 44;
    const padR = 6;
    const padT = 6;
    const padB = 16;
    const plotW = rect.width - padL - padR;
    const plotH = rect.height - padT - padB;
    const n = counts.length;
    const binW = plotW / n;
    scaleRef.current = { padL, binW, n };

    const maxCount = Math.max(...counts, 1e-30);

    // 枠
    ctx.strokeStyle = "#363c48";
    ctx.lineWidth = 1;
    ctx.strokeRect(padL, padT, plotW, plotH);

    // バー
    ctx.fillStyle = color;
    for (let i = 0; i < n; i++) {
      const h = (counts[i] / maxCount) * plotH;
      const x = padL + i * binW;
      const y = padT + plotH - h;
      ctx.fillRect(x + 0.5, y, Math.max(1, binW - 1), h);
    }

    // 横軸目盛り (最小/中央/最大)
    ctx.font = "9px system-ui, sans-serif";
    ctx.fillStyle = "#8a919e";
    ctx.textBaseline = "top";
    ctx.textAlign = "left";
    ctx.fillText(lo.toFixed(1), padL, padT + plotH + 3);
    ctx.textAlign = "center";
    ctx.fillText(((lo + hi) / 2).toFixed(1), padL + plotW / 2, padT + plotH + 3);
    ctx.textAlign = "right";
    ctx.fillText(hi.toFixed(1), padL + plotW, padT + plotH + 3);

    // 縦軸目盛り (0 / 最大カウント)
    ctx.textAlign = "right";
    ctx.textBaseline = "top";
    ctx.fillText(maxCount.toExponential(1), padL - 4, padT);
    ctx.textBaseline = "bottom";
    ctx.fillText("0", padL - 4, padT + plotH);

    // ホバー中のビンを枠で強調
    if (hoverIdx !== null && hoverIdx >= 0 && hoverIdx < n) {
      ctx.strokeStyle = "rgba(255,255,255,0.6)";
      ctx.lineWidth = 1;
      ctx.strokeRect(padL + hoverIdx * binW, padT, binW, plotH);
    }
  }, [counts, lo, hi, hoverIdx, color]);

  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const el = canvasRef.current;
    const sc = scaleRef.current;
    if (!el || !sc) return;
    const rect = el.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const idx = Math.floor((x - sc.padL) / sc.binW);
    setHoverIdx(idx >= 0 && idx < sc.n ? idx : null);
  };

  const n = counts.length;
  const range = hi - lo || 1;
  const hoverBinLo = hoverIdx !== null ? lo + (range * hoverIdx) / n : null;
  const hoverBinHi = hoverIdx !== null ? lo + (range * (hoverIdx + 1)) / n : null;

  return (
    <div className="iedf-hist-wrap">
      <canvas
        ref={canvasRef}
        className="iedf-hist"
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setHoverIdx(null)}
      />
      <div className="hint iedf-hist-hover">
        {hoverIdx !== null && hoverBinLo !== null && hoverBinHi !== null
          ? `${hoverBinLo.toFixed(2)} 〜 ${hoverBinHi.toFixed(2)} ${unit}: ${counts[hoverIdx].toExponential(3)}`
          : " "}
      </div>
    </div>
  );
}

interface PicCyclePlayerProps {
  cycle: PicCycle;
  field: CyclePicField;
  onFieldChange: (v: CyclePicField) => void;
  logScale: boolean;
  onLogScaleChange: (v: boolean) => void;
  playing: boolean;
  onPlayingChange: (v: boolean) => void;
  binIndex: number;
  onBinIndexChange: (v: number) => void;
  fps: number;
  onFpsChange: (v: number) => void;
  showParticles: boolean;
  onShowParticlesChange: (v: boolean) => void;
}

// PIC: 周期アニメーションプレイヤー。RF 1周期分の位相分解データ (cycle) を
// 再生/一時停止・位相スライダー・再生速度で辿る UI (実際のビン送り・描画は App/CadCanvas 側で行う)。
// このコンポーネントは選択状態の表示・入力のみを担う
function PicCyclePlayer({
  cycle,
  field,
  onFieldChange,
  logScale,
  onLogScaleChange,
  playing,
  onPlayingChange,
  binIndex,
  onBinIndexChange,
  fps,
  onFpsChange,
  showParticles,
  onShowParticlesChange,
}: PicCyclePlayerProps) {
  const bin = Math.min(binIndex, cycle.bins - 1);
  const phaseDeg = (bin / cycle.bins) * 360;
  const tInBin = (bin / cycle.bins) * cycle.period_s;

  return (
    <>
      <h2>PIC: 周期アニメーション</h2>
      <div className="field">
        <span className="label">表示フィールド</span>
        <select value={field} onChange={(e) => onFieldChange(e.target.value as CyclePicField)}>
          {CYCLE_FIELD_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </div>
      <div className="field">
        <span className="label">対数スケール</span>
        <input
          type="checkbox"
          checked={logScale}
          onChange={(e) => onLogScaleChange(e.target.checked)}
        />
      </div>
      <div className="field">
        <span className="label">粒子スナップショット表示</span>
        <input
          type="checkbox"
          checked={showParticles}
          onChange={(e) => onShowParticlesChange(e.target.checked)}
        />
      </div>

      <div className="actions">
        <button className="secondary" onClick={() => onPlayingChange(!playing)}>
          {playing ? "一時停止" : "再生"}
        </button>
        <select value={fps} onChange={(e) => onFpsChange(Number(e.target.value))}>
          <option value={5}>5 fps</option>
          <option value={10}>10 fps</option>
          <option value={20}>20 fps</option>
        </select>
      </div>

      <div className="field">
        <span className="label">位相 (bin {bin + 1}/{cycle.bins})</span>
        <input
          type="range"
          min={0}
          max={cycle.bins - 1}
          step={1}
          value={bin}
          onChange={(e) => {
            onPlayingChange(false); // スライダー操作で明示的に位相を選んだら再生は止める
            onBinIndexChange(Number(e.target.value));
          }}
        />
      </div>
      <p className="hint">
        位相角 {phaseDeg.toFixed(1)}° / ビン内時刻 {(tInBin * 1e9).toFixed(2)} ns
        (周期 {(cycle.period_s * 1e9).toFixed(2)} ns)
      </p>
    </>
  );
}
