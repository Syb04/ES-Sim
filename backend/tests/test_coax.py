"""同軸円筒(2D断面)の解析解比較テスト(仕様書 §6 検証ケース)。

実行時間を抑えるためメッシュサイズ 0.002 の1ケースのみで検証する。
詳細なメッシュ収束確認は `verification/coax_convergence.py` を参照。
"""

import numpy as np

from es_sim.fem import solve
from es_sim.meshing import generate_mesh
from verification.coax_convergence import A, B, V1, build_project, c_exact, v_exact

MESH_SIZE = 0.002


def test_coax_convergence_single_case():
    """メッシュサイズ 0.002 で、節点電位のL2誤差と静電容量誤差が1%未満であること。"""
    project = build_project(MESH_SIZE)
    mesh = generate_mesh(project)
    sol = solve(project, mesh)

    r = np.linalg.norm(mesh.nodes, axis=1)
    mask = (r >= A * 0.99) & (r <= B * 1.01)
    v_ana = v_exact(r[mask])
    v_num = sol.v[mask]
    l2_err = np.sqrt(np.sum((v_num - v_ana) ** 2) / np.sum(v_ana ** 2))
    assert l2_err < 0.01

    c_num = 2.0 * sol.energy / V1 ** 2
    c_err = abs(c_num - c_exact()) / c_exact()
    assert c_err < 0.01
