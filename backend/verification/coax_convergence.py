"""同軸円筒(2D断面)のメッシュ収束検証。仕様書 §6 検証ケース。

内導体半径 a=0.01 m (V1=100V, conductor)、外導体半径 b=0.04 m (0V, domain外周)
の同軸構造を解き、解析解

    V(r) = V1 * ln(b/r) / ln(b/a)
    C    = 2 pi eps0 / ln(b/a)   [F/m]

とメッシュサイズを変えながら比較して収束を確認する。
domain / 内導体は円ではなく多角形しか表現できないジオメトリ制約への対処として
多角形近似する(仕様書の指示では256角形を想定)。

【多角形分割数についての注記】
実装時に確認したところ、本リポジトリの `meshing.generate_mesh` は
domain外周・内導体それぞれの頂点列をそのまま gmsh の Point/Line として
渡すため、頂点間隔(多角形の1辺の長さ)が要求メッシュサイズ mesh.size より
十分小さい場合、生成される三角形メッシュ全体の粗さが mesh.size ではなく
その頂点間隔に引きずられてしまう(=粗いメッシュサイズを指定しても
実際には細かいメッシュのまま変化しない)ことが確認された。
そのため本スクリプトでは、多角形分割数を「256」に固定するのではなく、
各メッシュサイズ h に対して 1辺の長さが概ね h/4 になるよう分割数を
都度計算する(`polygon_count`)。これにより
  - 多角形近似誤差は常に FEM 誤差より十分小さく保たれる
  - mesh.size (h) が実際のメッシュ解像度を支配し、収束確認が意味を持つ
の両方を満たす。仕様書の「256角形」という数値そのものではなく、
その目的(多角形近似誤差の十分な低減)を満たす分割数を採用する。

実行方法:
    python verification/coax_convergence.py
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

# `python verification/coax_convergence.py` のように backend/ 以外の cwd から
# 直接実行しても es_sim パッケージ(backend/es_sim)を解決できるようにする。
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from es_sim.fem import EPS0, solve
from es_sim.meshing import generate_mesh
from es_sim.schema import Project

# ---- 問題設定 --------------------------------------------------------------

A = 0.01     # 内導体半径 [m]
B = 0.04     # 外導体(domain外周)半径 [m]
V1 = 100.0   # 内導体電位 [V] (外導体は 0V)

MESH_SIZES = [0.008, 0.004, 0.002, 0.001]  # 収束確認に使うメッシュサイズ [m]

SEGMENT_FACTOR = 4   # 多角形の1辺の長さ ≒ mesh_size / SEGMENT_FACTOR
MIN_POLYGON_N = 32   # 多角形分割数の下限(粗いメッシュでも円形状を保つため)

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent  # ES-Sim/ (backend/ の親)


def circle_polygon(radius: float, n: int) -> list[list[float]]:
    """半径 radius・分割数 n の正n角形頂点列(反時計回り)を返す。"""
    theta = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False)
    return [[radius * math.cos(t), radius * math.sin(t)] for t in theta]


def polygon_count(radius: float, mesh_size: float) -> int:
    """1辺の長さが概ね mesh_size/SEGMENT_FACTOR になる分割数を計算する。"""
    target_segment = mesh_size / SEGMENT_FACTOR
    n = round(2.0 * math.pi * radius / target_segment)
    return max(MIN_POLYGON_N, n)


def build_project(mesh_size: float, n_outer: int | None = None, n_inner: int | None = None) -> Project:
    """同軸円筒プロジェクトを構築する。

    domain外周(半径b)は全エッジをDirichlet 0Vとし、
    内導体(半径a)はconductor領域としてV1を与える。
    n_outer / n_inner を省略した場合は mesh_size から自動計算する
    (多角形近似誤差を FEM 誤差より十分小さく保つため)。
    """
    if n_outer is None:
        n_outer = polygon_count(B, mesh_size)
    if n_inner is None:
        n_inner = polygon_count(A, mesh_size)
    outer = circle_polygon(B, n_outer)
    inner = circle_polygon(A, n_inner)
    data = {
        "version": 1,
        "unit": "m",
        "geometry": {
            "domain": {"polygon": outer},
            "regions": [
                {
                    "id": "inner_conductor",
                    "type": "conductor",
                    "polygon": inner,
                    "voltage": V1,
                }
            ],
            "boundaries": [
                {"edges": list(range(n_outer)), "type": "dirichlet", "voltage": 0.0},
            ],
        },
        "mesh": {"size": mesh_size},
    }
    return Project.model_validate(data)


def v_exact(r: np.ndarray) -> np.ndarray:
    """解析解 V(r) = V1 ln(b/r) / ln(b/a)。"""
    return V1 * np.log(B / r) / np.log(B / A)


def c_exact() -> float:
    """解析解の静電容量 C = 2 pi eps0 / ln(b/a) [F/m]。"""
    return 2.0 * math.pi * EPS0 / math.log(B / A)


def run_case(mesh_size: float) -> dict:
    """1つのメッシュサイズについて解いて誤差指標を計算する。"""
    project = build_project(mesh_size)
    mesh = generate_mesh(project)
    sol = solve(project, mesh)

    r = np.linalg.norm(mesh.nodes, axis=1)
    # 多角形近似の丸め誤差を考慮し a <= r <= b の節点のみを対象とする
    mask = (r >= A * 0.99) & (r <= B * 1.01)
    v_ana = v_exact(r[mask])
    v_num = sol.v[mask]
    l2_err = float(np.sqrt(np.sum((v_num - v_ana) ** 2) / np.sum(v_ana ** 2)))

    c_num = 2.0 * sol.energy / V1 ** 2
    c_ana = c_exact()
    c_err = abs(c_num - c_ana) / c_ana

    return {
        "mesh_size": mesh_size,
        "n_nodes": len(mesh.nodes),
        "l2_err": l2_err,
        "c_num": c_num,
        "c_err": c_err,
    }


def _order(prev_err: float, err: float) -> float:
    """連続する2ケースの誤差比から収束次数を log2 で推定する。"""
    return math.log2(prev_err / err)


def main() -> None:
    results = [run_case(h) for h in MESH_SIZES]

    print("同軸円筒メッシュ収束検証")
    print(f"  a={A} m, b={B} m, V1={V1} V")
    print(f"  解析解 C = {c_exact():.6e} F/m")
    print()

    header = (
        f"{'size[m]':>10} {'節点数':>8} {'相対L2誤差':>14} {'収束次数':>8} "
        f"{'C[F/m]':>14} {'C相対誤差':>12} {'収束次数':>8}"
    )
    print(header)
    for i, res in enumerate(results):
        if i == 0:
            order_l2 = order_c = float("nan")
        else:
            prev = results[i - 1]
            order_l2 = _order(prev["l2_err"], res["l2_err"])
            order_c = _order(prev["c_err"], res["c_err"])
        print(
            f"{res['mesh_size']:>10.4f} {res['n_nodes']:>8d} {res['l2_err']:>14.4e} "
            f"{order_l2:>8.2f} {res['c_num']:>14.6e} {res['c_err']:>12.4e} {order_c:>8.2f}"
        )

    # ---- Markdown 表として書き出し -----------------------------------------
    lines = [
        "# 同軸円筒メッシュ収束検証結果",
        "",
        "仕様書 §6 の検証ケース「同軸円筒(2D断面): V(r) の対数分布」の収束確認結果。",
        "",
        f"- 内導体半径 a = {A} m (V1 = {V1} V)",
        f"- 外導体半径 b = {B} m (0 V)",
        f"- 解析解 V(r) = V1 * ln(b/r) / ln(b/a)",
        f"- 解析解 C = 2 pi eps0 / ln(b/a) = {c_exact():.6e} F/m",
        "- domain外周・内導体は多角形近似(1辺の長さ ≒ mesh size / "
        f"{SEGMENT_FACTOR} となるよう分割数を各メッシュサイズごとに自動決定。"
        "gmshの挙動上、多角形分割数を固定すると mesh size の変更が"
        "メッシュ解像度に反映されないため、分割数を可変にしている)",
        "",
        "| mesh size [m] | 節点数 | 相対L2誤差 | 収束次数 | C [F/m] | C相対誤差 | 収束次数 |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for i, res in enumerate(results):
        if i == 0:
            order_l2_s = order_c_s = "-"
        else:
            prev = results[i - 1]
            order_l2_s = f"{_order(prev['l2_err'], res['l2_err']):.2f}"
            order_c_s = f"{_order(prev['c_err'], res['c_err']):.2f}"
        lines.append(
            f"| {res['mesh_size']:.4f} | {res['n_nodes']} | {res['l2_err']:.4e} | {order_l2_s} "
            f"| {res['c_num']:.6e} | {res['c_err']:.4e} | {order_c_s} |"
        )
    results_path = HERE / "coax_results.md"
    results_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print()
    print(f"結果を {results_path} に書き出しました。")

    # ---- GUIサンプル用プロジェクト (64角形, mesh size 0.002) ---------------
    example_project = build_project(0.002, n_outer=64, n_inner=64)
    example_path = REPO_ROOT / "examples" / "coaxial.json"
    example_path.write_text(
        json.dumps(example_project.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"サンプルプロジェクトを {example_path} に書き出しました。")


if __name__ == "__main__":
    main()
