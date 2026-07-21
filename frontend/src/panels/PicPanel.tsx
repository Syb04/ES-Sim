import { useEffect, useRef } from "react";
import { CommitNumberInput } from "../CommitInput";
import type { Emitter, InitialPlasma, PicDiag, PicFrameMsg, PicInjection, PicSettings, PicStartedMsg } from "../types";

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
}

const DEFAULT_INITIAL_PLASMA: InitialPlasma = {
  density: 1.0e14,
  te_ev: 2.0,
  ti_ev: 0.03,
  ion_mass_amu: 40.0,
  immobile_ions: false,
  seed: 0,
};

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

  const progressPct = started && started.n_steps > 0 ? Math.min(100, ((frame?.step ?? 0) / started.n_steps) * 100) : 0;

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
          <PicHistoryChart history={history} />
        </>
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

    if (history.length < 2) return;

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
