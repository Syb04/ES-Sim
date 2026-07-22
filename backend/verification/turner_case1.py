"""Turner CCP ベンチマーク ケース1 (He) 検証スクリプト (prompts/21)。

Turner et al., Phys. Plasmas 20, 013507 (2013) のケース1 (He CCP) を
薄い 2D ストリップ (L×2mm、上下エッジ鏡面反射) で 1D 模擬し、
時間平均密度プロファイルを基準解 Benchmark_A.csv と定量比較する。

使い方:
    python verification/turner_case1.py                # 本番 (512000 ステップ)
    python verification/turner_case1.py --steps 4000   # スモーク (数分)

出力:
    verification/turner_case1_result.md   比較指標のまとめ
    verification/turner_case1_result.json 再解析用の生データ
    verification/turner_case1.png         密度プロファイル比較プロット
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from es_sim.mcc import KB  # noqa: E402
from es_sim.particles import ME, MP, QE, _locate_initial  # noqa: E402
from es_sim.pic import PicSimulation  # noqa: E402
from es_sim.schema import Project  # noqa: E402

DATA = Path(__file__).parent / "data" / "turner"
OUT = Path(__file__).parent

# ---- ケース1 パラメータ (Turner Table 1) ----------------------------------------
L = 6.7e-2                     # ギャップ [m]
H = 2.0e-3                     # ストリップ高さ (y 方向) [m]
FREQ = 13.56e6                 # RF 周波数 [Hz]
V_RF = 450.0                   # V(t) = 450·sin(2πft) [V] (片側、対向 GND)
N_GAS = 9.64e20                # He ガス数密度 [m^-3]
T_GAS = 300.0                  # ガス温度 [K]
N0 = 2.56e14                   # 初期プラズマ密度 [m^-3]
TE_K = 30000.0                 # 初期電子温度 [K]
TI_K = 300.0                   # 初期イオン温度 [K]
M_HE = 6.67e-27                # He+ 質量 [kg]
STEPS_PER_CYCLE = 400          # dt = 1/(400f)
DT = 1.0 / (STEPS_PER_CYCLE * FREQ)
AVG_CYCLES = 32                # 密度の時間平均区間 (最後の 32 周期 = 12800 ステップ)
MESH_SIZE = L / 128.0          # ≈ 0.523 mm (文献の Δx = L/128 に対応)


def _read_xs_csv(name: str) -> tuple[list[float], list[float]]:
    """`;` 区切りの (energy_eV; sigma_m2) CSV を読む。"""
    arr = np.loadtxt(DATA / name, delimiter=";")
    return arr[:, 0].tolist(), arr[:, 1].tolist()


def _xs(kind: str, name: str, label: str, threshold: float = 0.0, mass_ratio: float = 0.0) -> dict:
    """CSV を XsProcess 形式の dict に変換する。"""
    e, s = _read_xs_csv(name)
    return {
        "kind": kind,
        "label": label,
        "threshold_ev": threshold,
        "mass_ratio": mass_ratio,
        "energy_ev": e,
        "sigma_m2": s,
    }


def _build_project(steps: int, n_macro: int, seed: int) -> Project:
    """ケース1 の Project を構築する。"""
    # 電子/He (Biagi 7.1)。弾性の質量比 m_e/M_He
    e_procs = [
        _xs("elastic", "Elastic_He.csv", "e + He elastic", mass_ratio=ME / M_HE),
        _xs("excitation", "Excitation1_He.csv", "e + He excitation (19.82 eV)", threshold=19.82),
        _xs("excitation", "Excitation2_He.csv", "e + He excitation (20.61 eV)", threshold=20.61),
        _xs("ionization", "Ionization_He.csv", "e + He ionization (24.59 eV)", threshold=24.59),
    ]
    # He+/He (Phelps、重心系エネルギー参照)
    i_procs = [
        _xs("isotropic", "Isotropic_He.csv", "He+ + He isotropic"),
        _xs("backscat", "Backscattering_He.csv", "He+ + He backscattering"),
    ]
    return Project.model_validate(
        {
            "geometry": {
                "domain": {"polygon": [[0, 0], [L, 0], [L, H], [0, H]]},
                "boundaries": [
                    {
                        "edges": [3],  # 左辺 x=0: RF 電極 V(t) = 450 sin(2πft)
                        "voltage": 0.0,
                        "voltage_rf": {"amplitude": V_RF, "freq_hz": FREQ, "phase_deg": 0.0},
                    },
                    {"edges": [1], "voltage": 0.0},  # 右辺 x=L: GND
                ],
            },
            "mesh": {"size": MESH_SIZE},
            "pic": {
                "initial_plasma": {
                    "density": N0,
                    "te_ev": TE_K * KB / QE,   # 30000 K → ≈ 2.585 eV
                    "ti_ev": TI_K * KB / QE,   # 300 K → ≈ 0.0259 eV
                    "ion_mass_amu": M_HE / MP,  # 6.67e-27 kg を正確に指定
                    "immobile_ions": False,
                    "seed": seed,
                },
                "n_macro": n_macro,
                "dt": DT,
                "n_steps": steps,
                "frame_every": 10**9,  # フレームは使わない
                "reflect_edges": [0, 2],  # 下辺・上辺: 鏡面反射 (1D 模擬)
                "mcc": {
                    "gas": {
                        "name": "He",
                        "pressure_pa": N_GAS * KB * T_GAS,  # n_g = p/(kB T) → p ≈ 3.99 Pa
                        "temperature_k": T_GAS,
                    },
                    "electron_processes": e_procs,
                    "ion_processes": i_procs,
                    "seed": seed + 1,
                    "ionization_split": "half",   # 電離余剰は散乱/生成電子で等分
                    "ion_energy_frame": "com",    # He+/He テーブルは重心系エネルギー
                },
                # SEE・電子反射なし (壁は完全吸収): see_gamma 未指定で既定 0
            },
        }
    )


def _eval_nodal(sim: PicSimulation, nodal: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """節点値 nodal を P1 補間で任意点 pts (n,2) に評価する。"""
    elem = _locate_initial(sim.coeffs, pts)
    a, b, c, det = sim.coeffs
    l = (a[elem] + b[elem] * pts[:, 0:1] + c[elem] * pts[:, 1:2]) / det[elem][:, None]
    return np.sum(nodal[sim.tris[elem]] * l, axis=1)


def _profile_1d(sim: PicSimulation, nodal: np.ndarray, x_grid: np.ndarray) -> np.ndarray:
    """x_grid の各点で y 方向 (反射エッジを避けた内側) を平均して 1D プロファイル化。"""
    y_vals = np.linspace(0.15 * H, 0.85 * H, 8)
    eps = 1e-9
    xc = np.clip(x_grid, eps, L - eps)
    xx, yy = np.meshgrid(xc, y_vals, indexing="ij")  # (nx, ny)
    pts = np.stack([xx.ravel(), yy.ravel()], axis=1)
    vals = _eval_nodal(sim, nodal, pts).reshape(len(x_grid), len(y_vals))
    return vals.mean(axis=1)


def _rel(a: float, b: float) -> float:
    return (a - b) / b


def _ensure_matplotlib():
    """matplotlib を import する (無ければ pip でインストール)。"""
    try:
        import matplotlib  # noqa: F401
    except ImportError:
        print("matplotlib が無いためインストールします...", flush=True)
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--break-system-packages", "matplotlib"],
            check=True,
        )
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def main() -> None:
    ap = argparse.ArgumentParser(description="Turner ケース1 (He CCP) ベンチマーク検証")
    ap.add_argument("--steps", type=int, default=512000,
                    help="総ステップ数 (既定 512000 = 1280 RF 周期。スモークは 4000 など)")
    ap.add_argument("--n-macro", type=int, default=65536,
                    help="種ごとの初期マクロ粒子数 (既定 65536 ≈ 512個/x セル)")
    ap.add_argument("--seed", type=int, default=1, help="乱数シード")
    args = ap.parse_args()

    steps = args.steps
    n_cycles = steps / STEPS_PER_CYCLE
    print(f"Turner ケース1: L={L} m, He n_g={N_GAS:.3g} m^-3, "
          f"V_RF={V_RF} V @ {FREQ / 1e6:.2f} MHz, dt={DT:.4g} s")
    print(f"steps={steps} ({n_cycles:.1f} RF 周期), n_macro={args.n_macro}, "
          f"mesh size={MESH_SIZE * 1e3:.3f} mm, ストリップ高さ={H * 1e3:.1f} mm")

    project = _build_project(steps, args.n_macro, args.seed)
    t_setup = time.perf_counter()
    sim = PicSimulation(project)
    for w in sim.warnings:
        print(f"[warning] {w}")
    print(f"メッシュ: 節点 {sim.n_nodes}, 要素 {len(sim.tris)} "
          f"(構築 {time.perf_counter() - t_setup:.1f} s)", flush=True)

    # 密度の時間平均: 最後の AVG_CYCLES 周期 (足りなければ後半半分)
    avg_steps = min(AVG_CYCLES * STEPS_PER_CYCLE, max(1, steps // 2))
    accum_start = steps - avg_steps + 1
    sim.enable_density_accum(accum_start)
    print(f"密度時間平均: ステップ {accum_start}〜{steps} ({avg_steps} ステップ)")

    # ---- メインループ (進捗を RF 周期ごとに表示) --------------------------------
    t0 = time.perf_counter()
    report_every = STEPS_PER_CYCLE if n_cycles <= 100 else 10 * STEPS_PER_CYCLE
    for i in range(1, steps + 1):
        sim.step()
        if i % report_every == 0 or i == steps:
            el = sim.species["electron"]
            io = sim.species["ion"]
            print(f"cycle {i / STEPS_PER_CYCLE:8.1f}/{n_cycles:.0f}  "
                  f"n_e={len(el.x):7d}  n_i={len(io.x):7d}  "
                  f"elapsed={time.perf_counter() - t0:8.1f} s", flush=True)
    elapsed = time.perf_counter() - t0
    print(f"実行完了: {elapsed:.1f} s ({elapsed / steps * 1e3:.2f} ms/step)")

    # ---- 密度プロファイルの抽出と比較 -------------------------------------------
    bench = np.loadtxt(DATA / "Benchmark_A.csv")
    x_ref = bench[:, 0]        # 0〜0.067 m の 129 点
    ne_ref = bench[:, 1]       # 電子密度 [m^-3]
    ni_ref = bench[:, 4]       # イオン密度 [m^-3]

    dens = sim.averaged_density()
    ne_sim = _profile_1d(sim, dens["electron"], x_ref)
    ni_sim = _profile_1d(sim, dens["ion"], x_ref)

    i_c = len(x_ref) // 2  # 中心 (x = L/2)
    metrics = {}
    for name, sim_p, ref_p in (("n_e", ne_sim, ne_ref), ("n_i", ni_sim, ni_ref)):
        metrics[name] = {
            "center_sim": float(sim_p[i_c]),
            "center_ref": float(ref_p[i_c]),
            "center_rel_diff": float(_rel(sim_p[i_c], ref_p[i_c])),
            "peak_sim": float(sim_p.max()),
            "peak_ref": float(ref_p.max()),
            "peak_rel_diff": float(_rel(sim_p.max(), ref_p.max())),
            "rel_l2": float(np.linalg.norm(sim_p - ref_p) / np.linalg.norm(ref_p)),
        }

    print("\n==== Benchmark_A.csv との比較 ====")
    for name, m in metrics.items():
        print(f"{name}: 中心密度 sim={m['center_sim']:.4g} ref={m['center_ref']:.4g} "
              f"(相対差 {m['center_rel_diff'] * 100:+.2f}%)")
        print(f"{name}: ピーク密度 sim={m['peak_sim']:.4g} ref={m['peak_ref']:.4g} "
              f"(相対差 {m['peak_rel_diff'] * 100:+.2f}%)")
        print(f"{name}: プロファイル相対 L2 偏差 = {m['rel_l2']:.4f}")

    full_run = steps >= 512000
    if not full_run:
        print(f"\n[注意] steps={steps} は短縮実行です。基準解 (512000 ステップの定常状態) "
              "との定量一致は本番実行でのみ意味を持ちます。")

    # ---- JSON 保存 (再解析用) ----------------------------------------------------
    result = {
        "params": {
            "steps": steps, "n_macro": args.n_macro, "seed": args.seed,
            "dt": DT, "mesh_size": MESH_SIZE, "strip_height": H,
            "avg_steps": avg_steps, "elapsed_s": elapsed,
        },
        "history_last": {
            "n_e": int(sim.history["n_e"][-1]),
            "n_i": int(sim.history["n_i"][-1]),
            "wall_e": int(sim.history["wall_e"][-1]),
            "wall_i": int(sim.history["wall_i"][-1]),
            "coll_e": int(sim.history["coll_e"][-1]),
            "ion_events": int(sim.history["ion_events"][-1]),
        },
        "x": x_ref.tolist(),
        "ne_sim": ne_sim.tolist(),
        "ni_sim": ni_sim.tolist(),
        "ne_ref": ne_ref.tolist(),
        "ni_ref": ni_ref.tolist(),
        "metrics": metrics,
    }
    json_path = OUT / "turner_case1_result.json"
    json_path.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(f"\nJSON 保存: {json_path}")

    # ---- プロット ----------------------------------------------------------------
    plt = _ensure_matplotlib()
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(x_ref * 1e2, ne_ref, "k-", lw=1.5, label="$n_e$ Turner Benchmark A")
    ax.plot(x_ref * 1e2, ni_ref, "k--", lw=1.5, label="$n_i$ Turner Benchmark A")
    ax.plot(x_ref * 1e2, ne_sim, "C0-", lw=1.2, label="$n_e$ ES-Sim")
    ax.plot(x_ref * 1e2, ni_sim, "C3--", lw=1.2, label="$n_i$ ES-Sim")
    ax.set_xlabel("x [cm]")
    ax.set_ylabel(r"density [m$^{-3}$]")
    title = f"Turner case 1 (He CCP): {steps} steps ({n_cycles:.0f} RF cycles)"
    if not full_run:
        title += " — SMOKE RUN (not converged)"
    ax.set_title(title)
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    png_path = OUT / "turner_case1.png"
    fig.savefig(png_path, dpi=150)
    print(f"プロット保存: {png_path}")

    # ---- Markdown 保存 -------------------------------------------------------------
    md = [
        "# Turner ケース1 (He CCP) ベンチマーク比較",
        "",
        f"- 実行: steps={steps} ({n_cycles:.1f} RF 周期), n_macro={args.n_macro}, "
        f"dt={DT:.4g} s, メッシュ {MESH_SIZE * 1e3:.3f} mm, ストリップ {H * 1e3:.1f} mm "
        f"(上下エッジ鏡面反射)",
        f"- 時間平均: 最後の {avg_steps} ステップ ({avg_steps / STEPS_PER_CYCLE:.1f} 周期)",
        f"- 実行時間: {elapsed:.1f} s",
        f"- 最終粒子数: n_e={result['history_last']['n_e']}, n_i={result['history_last']['n_i']}",
        "",
        "| 指標 | n_e | n_i |",
        "|---|---|---|",
        f"| 中心密度 sim [m^-3] | {metrics['n_e']['center_sim']:.4g} | {metrics['n_i']['center_sim']:.4g} |",
        f"| 中心密度 ref [m^-3] | {metrics['n_e']['center_ref']:.4g} | {metrics['n_i']['center_ref']:.4g} |",
        f"| 中心密度 相対差 | {metrics['n_e']['center_rel_diff'] * 100:+.2f}% | {metrics['n_i']['center_rel_diff'] * 100:+.2f}% |",
        f"| ピーク密度 sim [m^-3] | {metrics['n_e']['peak_sim']:.4g} | {metrics['n_i']['peak_sim']:.4g} |",
        f"| ピーク密度 ref [m^-3] | {metrics['n_e']['peak_ref']:.4g} | {metrics['n_i']['peak_ref']:.4g} |",
        f"| ピーク密度 相対差 | {metrics['n_e']['peak_rel_diff'] * 100:+.2f}% | {metrics['n_i']['peak_rel_diff'] * 100:+.2f}% |",
        f"| プロファイル相対 L2 偏差 | {metrics['n_e']['rel_l2']:.4f} | {metrics['n_i']['rel_l2']:.4f} |",
        "",
        "比較プロット: `turner_case1.png` / 生データ: `turner_case1_result.json`",
    ]
    if not full_run:
        md.append("")
        md.append(f"**注意**: steps={steps} の短縮実行 (スモーク)。定常状態に達していないため"
                  "基準解との定量比較は参考値。本番は `--steps 512000`。")
    md_path = OUT / "turner_case1_result.md"
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"Markdown 保存: {md_path}")


if __name__ == "__main__":
    main()
