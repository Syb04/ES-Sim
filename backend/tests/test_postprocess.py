"""ラインプロファイル (postprocess.sample_line) のテスト。仕様書 §7 参照。"""

import numpy as np
import pytest

from es_sim.fem import solve
from es_sim.meshing import generate_mesh
from es_sim.postprocess import sample_line
from es_sim.schema import Project

D, H, V1 = 0.1, 0.05, 100.0  # 平行平板: 幅 D [m], 高さ H [m], 右側電位 V1 [V] (test_fem.py と同じ設定)


@pytest.fixture(scope="module")
def parallel_plates():
    project = Project.model_validate(
        {
            "geometry": {
                "domain": {"polygon": [[0, 0], [D, 0], [D, H], [0, H]]},
                "regions": [],
                "boundaries": [
                    {"edges": [3], "type": "dirichlet", "voltage": 0.0},   # 左辺
                    {"edges": [1], "type": "dirichlet", "voltage": V1},    # 右辺
                ],
            },
            "mesh": {"size": 0.01},
        }
    )
    mesh = generate_mesh(project)
    return mesh, solve(project, mesh)


def test_profile_matches_analytic(parallel_plates):
    """x 方向プロファイル: v = V1*x/D, |E| = V1/D で一定 (解析解と一致)。"""
    mesh, sol = parallel_plates
    n = 101
    s, v, e_abs = sample_line(mesh, sol, (0.0, H / 2), (D, H / 2), n)

    assert np.allclose(s, np.linspace(0.0, D, n))
    assert not np.any(np.isnan(v))
    assert not np.any(np.isnan(e_abs))

    v_exact = V1 * s / D
    assert np.max(np.abs(v - v_exact)) < 1e-6 * V1

    e_exact = V1 / D
    assert np.allclose(e_abs, e_exact, rtol=1e-6)


def test_profile_outside_domain_is_nan(parallel_plates):
    """domain の外側をサンプリングすると NaN になる。"""
    mesh, sol = parallel_plates
    s, v, e_abs = sample_line(mesh, sol, (-0.05, H / 2), (-0.01, H / 2), 20)

    assert np.all(np.isnan(v))
    assert np.all(np.isnan(e_abs))


def test_profile_partially_outside_domain(parallel_plates):
    """線分の一部が領域外に出る場合、外側の点だけ NaN になる。"""
    mesh, sol = parallel_plates
    n = 101
    s, v, e_abs = sample_line(mesh, sol, (-0.02, H / 2), (D, H / 2), n)

    # 弧長 s=0.02 が domain の左辺 (x=0) に相当する。それより手前 (x<0) は NaN。
    x = -0.02 + s
    outside = x < -1e-9
    inside = x > 1e-9
    assert np.all(np.isnan(v[outside]))
    assert not np.any(np.isnan(v[inside]))
    assert not np.any(np.isnan(e_abs[inside]))
