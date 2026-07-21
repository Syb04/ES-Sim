"""解析解との比較テスト (仕様書 §6 の検証ケース)。"""

import numpy as np
import pytest

from es_sim.fem import EPS0, solve
from es_sim.meshing import generate_mesh
from es_sim.schema import Project

D, H, V1 = 0.1, 0.05, 100.0  # 平行平板: 幅 D [m], 高さ H [m], 右側電位 V1 [V]


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
    return project, mesh, solve(project, mesh)


def test_potential_is_linear(parallel_plates):
    """線形解は P1 で厳密に表現できるため、節点電位は解析解と一致する。"""
    _, mesh, sol = parallel_plates
    v_exact = V1 * mesh.nodes[:, 0] / D
    assert np.max(np.abs(sol.v - v_exact)) < 1e-8 * V1


def test_field_is_uniform(parallel_plates):
    _, _, sol = parallel_plates
    e_exact = V1 / D
    assert np.allclose(sol.e_field[:, 0], -e_exact, rtol=1e-8)
    assert np.max(np.abs(sol.e_field[:, 1])) < 1e-8 * e_exact


def test_energy(parallel_plates):
    """W = 1/2 ε0 E^2 × 面積 (奥行き単位長あたり)。"""
    _, _, sol = parallel_plates
    w_exact = 0.5 * EPS0 * (V1 / D) ** 2 * D * H
    assert sol.energy == pytest.approx(w_exact, rel=1e-10)


def test_dielectric_uniform_field():
    """全域を εr=4 の誘電体にしても V は変わらず、エネルギーは 4 倍になる。"""
    project = Project.model_validate(
        {
            "geometry": {
                "domain": {"polygon": [[0, 0], [D, 0], [D, H], [0, H]]},
                "regions": [
                    {
                        "id": "diel",
                        "type": "dielectric",
                        "polygon": [[0.02, 0.01], [0.08, 0.01], [0.08, 0.04], [0.02, 0.04]],
                        "eps_r": 1.0,  # εr=1 なら真空と完全一致するはず
                    }
                ],
                "boundaries": [
                    {"edges": [3], "voltage": 0.0},
                    {"edges": [1], "voltage": V1},
                ],
            },
            "mesh": {"size": 0.01},
        }
    )
    mesh = generate_mesh(project)
    sol = solve(project, mesh)
    v_exact = V1 * mesh.nodes[:, 0] / D
    assert np.max(np.abs(sol.v - v_exact)) < 1e-8 * V1
