"""PIC 性能ベンチマーク (prompts/50)。

CCP 類似ケース (RF 平行平板 + 初期プラズマ) で ms/step を測る。
イオンサブサイクリング (--sub) と粒子チャンク並列 (--threads) の効果確認用。

使い方:
    python scripts/bench_pic.py                     # 既定 (sub=1, threads=1)
    python scripts/bench_pic.py --sub 10 --threads 8
    python scripts/bench_pic.py --n-macro 100000 --steps 200
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from es_sim.pic import PicSimulation  # noqa: E402
from es_sim.schema import Project  # noqa: E402


def build_project(n_macro: int, sub: int, threads: int, steps: int) -> Project:
    return Project.model_validate(
        {
            "geometry": {
                "domain": {"polygon": [[0, 0], [0.02, 0], [0.02, 0.01], [0, 0.01]]},
                "boundaries": [
                    {
                        "edges": [3], "type": "dirichlet", "voltage": 0.0,
                        "voltage_rf": {"amplitude": 100.0, "freq_hz": 13.56e6},
                    },
                    {"edges": [1], "type": "dirichlet", "voltage": 0.0},
                ],
            },
            "mesh": {"size": 8e-4},
            "pic": {
                "initial_plasma": {
                    "density": 1e15, "te_ev": 2.0, "ti_ev": 0.03,
                    "ion_mass_amu": 40.0, "seed": 7,
                },
                "n_macro": n_macro,
                "dt": None,
                "n_steps": steps,
                "frame_every": 10**9,
                "ion_subcycle": sub,
                "threads": threads,
            },
        }
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-macro", type=int, default=40000)
    ap.add_argument("--steps", type=int, default=100)
    ap.add_argument("--sub", type=int, default=1)
    ap.add_argument("--threads", type=int, default=1)
    args = ap.parse_args()

    sim = PicSimulation(build_project(args.n_macro, args.sub, args.threads, args.steps))
    # ウォームアップ (キャッシュ・スレッドプール初期化)
    for _ in range(5):
        sim.step()
    n0 = len(sim.species["electron"].x) + len(sim.species["ion"].x)
    t0 = time.perf_counter()
    for _ in range(args.steps):
        sim.step()
    elapsed = time.perf_counter() - t0
    ms = elapsed / args.steps * 1e3
    print(
        f"n_macro={args.n_macro} particles≈{n0} sub={args.sub} threads={args.threads}: "
        f"{ms:.2f} ms/step ({args.steps} steps, {elapsed:.2f} s)"
    )


if __name__ == "__main__":
    main()
