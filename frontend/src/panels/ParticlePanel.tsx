import { CommitNumberInput } from "../CommitInput";
import { mToMm, mmToM } from "../units";
import type { Emitter, ParticleSettings, Species, TraceResult } from "../types";

/**
 * 粒子パネル
 * - 粒子種 (電子/陽子/カスタム)・エミッタ (line/point)・積分設定の編集
 * - project.particles として保存/読込対象だが、編集操作自体は Undo/Redo 履歴には積まない
 *   (App 側で geometry とは独立な state として管理している)
 * - Trace 実行ボタンと結果サマリの表示
 */

interface Props {
  particles: ParticleSettings;
  onChange: (next: ParticleSettings) => void;
  busy: boolean;
  canRun: boolean;
  onTrace: () => void;
  traceResult: TraceResult | null;
  showTrajectories: boolean;
  onToggleTrajectories: (v: boolean) => void;
}

const ELECTRON: Species = { preset: "electron" };
const PROTON: Species = { preset: "proton" };

export default function ParticlePanel({
  particles,
  onChange,
  busy,
  canRun,
  onTrace,
  traceResult,
  showTrajectories,
  onToggleTrajectories,
}: Props) {
  const { species, emitter } = particles;

  const setSpecies = (next: Species) => onChange({ ...particles, species: next });
  const setEmitter = (patch: Partial<Emitter>) =>
    onChange({ ...particles, emitter: { ...emitter, ...patch } });

  let summary: {
    n: number;
    absorbed: number;
    alive: number;
    avgTof: number | null;
    eMin: number | null;
    eMax: number | null;
  } | null = null;
  if (traceResult) {
    const n = traceResult.status.length;
    const absorbed = traceResult.status.filter((s) => s === "absorbed").length;
    const tofs = traceResult.tof.filter((t): t is number => t !== null);
    const avgTof = tofs.length ? tofs.reduce((a, b) => a + b, 0) / tofs.length : null;
    const energies = traceResult.final_energy_ev;
    const eMin = energies.length ? Math.min(...energies) : null;
    const eMax = energies.length ? Math.max(...energies) : null;
    summary = { n, absorbed, alive: n - absorbed, avgTof, eMin, eMax };
  }

  return (
    <>
      <h2>粒子種</h2>
      <div className="field">
        <span className="label">種類</span>
        <select
          value={species.preset}
          onChange={(e) => {
            const v = e.target.value;
            if (v === "electron") setSpecies(ELECTRON);
            else if (v === "proton") setSpecies(PROTON);
            else setSpecies({ preset: "custom", q: species.q ?? -1.6e-19, m: species.m ?? 9.1e-31 });
          }}
        >
          <option value="electron">電子</option>
          <option value="proton">陽子</option>
          <option value="custom">カスタム</option>
        </select>
      </div>
      {species.preset === "custom" && (
        <>
          <div className="field">
            <span className="label">q [C]</span>
            <CommitNumberInput
              value={species.q ?? 0}
              onCommit={(q) => setSpecies({ preset: "custom", q, m: species.m ?? 9.1e-31 })}
            />
          </div>
          <div className="field">
            <span className="label">m [kg]</span>
            <CommitNumberInput
              value={species.m ?? 0}
              onCommit={(m) => setSpecies({ preset: "custom", q: species.q ?? -1.6e-19, m })}
            />
          </div>
        </>
      )}

      <h2>エミッタ</h2>
      <div className="field">
        <span className="label">種別</span>
        <select value={emitter.kind} onChange={(e) => setEmitter({ kind: e.target.value as Emitter["kind"] })}>
          <option value="line">ライン</option>
          <option value="point">点</option>
        </select>
      </div>
      <div className="field">
        <span className="label">p1 x [mm]</span>
        <CommitNumberInput
          value={mToMm(emitter.p1[0])}
          step="0.1"
          onCommit={(x) => setEmitter({ p1: [mmToM(x), emitter.p1[1]] })}
        />
      </div>
      <div className="field">
        <span className="label">p1 y [mm]</span>
        <CommitNumberInput
          value={mToMm(emitter.p1[1])}
          step="0.1"
          onCommit={(y) => setEmitter({ p1: [emitter.p1[0], mmToM(y)] })}
        />
      </div>
      {emitter.kind === "line" && (
        <>
          <div className="field">
            <span className="label">p2 x [mm]</span>
            <CommitNumberInput
              value={mToMm(emitter.p2[0])}
              step="0.1"
              onCommit={(x) => setEmitter({ p2: [mmToM(x), emitter.p2[1]] })}
            />
          </div>
          <div className="field">
            <span className="label">p2 y [mm]</span>
            <CommitNumberInput
              value={mToMm(emitter.p2[1])}
              step="0.1"
              onCommit={(y) => setEmitter({ p2: [emitter.p2[0], mmToM(y)] })}
            />
          </div>
        </>
      )}
      <div className="field">
        <span className="label">粒子数 n</span>
        <CommitNumberInput value={emitter.n} onCommit={(n) => setEmitter({ n: Math.max(1, Math.round(n)) })} />
      </div>
      <div className="field">
        <span className="label">初期エネルギー [eV]</span>
        <CommitNumberInput value={emitter.energy_ev} onCommit={(v) => setEmitter({ energy_ev: v })} />
      </div>
      <div className="field">
        <span className="label">射出方向 [deg]</span>
        <CommitNumberInput value={emitter.direction_deg} onCommit={(v) => setEmitter({ direction_deg: v })} />
      </div>
      <div className="field">
        <span className="label">広がり半角 [deg]</span>
        <CommitNumberInput value={emitter.spread_deg} onCommit={(v) => setEmitter({ spread_deg: v })} />
      </div>

      <h2>積分設定</h2>
      <div className="field">
        <span className="label">dt [s] (空欄=自動)</span>
        <input
          type="text"
          value={particles.dt === null ? "" : String(particles.dt)}
          placeholder="自動"
          onChange={(e) => {
            const raw = e.target.value;
            if (raw.trim() === "") {
              onChange({ ...particles, dt: null });
              return;
            }
            const n = Number(raw);
            if (Number.isFinite(n)) onChange({ ...particles, dt: n });
          }}
        />
      </div>
      <div className="field">
        <span className="label">ステップ数</span>
        <CommitNumberInput
          value={particles.n_steps}
          onCommit={(v) => onChange({ ...particles, n_steps: Math.max(1, Math.round(v)) })}
        />
      </div>
      <div className="field">
        <span className="label">保存間隔</span>
        <CommitNumberInput
          value={particles.save_every}
          onCommit={(v) => onChange({ ...particles, save_every: Math.max(1, Math.round(v)) })}
        />
      </div>

      <div className="actions">
        <button onClick={onTrace} disabled={busy || !canRun}>
          {busy ? "計算中..." : "Trace"}
        </button>
      </div>

      <label className="snap particle-trace-toggle">
        <input
          type="checkbox"
          checked={showTrajectories}
          onChange={(e) => onToggleTrajectories(e.target.checked)}
        />
        軌道を表示
      </label>

      {summary && (
        <>
          <h2>トレース結果</h2>
          <div className="kv"><span>粒子数</span><span>{summary.n}</span></div>
          <div className="kv"><span>吸収 / 生存</span><span>{summary.absorbed} / {summary.alive}</span></div>
          <div className="kv">
            <span>平均飛行時間</span>
            <span>{summary.avgTof !== null ? summary.avgTof.toExponential(3) : "-"} s</span>
          </div>
          <div className="kv">
            <span>最終エネルギー min/max</span>
            <span>
              {summary.eMin !== null ? summary.eMin.toExponential(3) : "-"} /{" "}
              {summary.eMax !== null ? summary.eMax.toExponential(3) : "-"} eV
            </span>
          </div>
        </>
      )}
    </>
  );
}
