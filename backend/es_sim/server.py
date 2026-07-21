"""FastAPI ローカルサーバー。Tauri フロントエンドから 127.0.0.1:8317 で利用する。

起動:  uvicorn es_sim.server:app --port 8317
"""

from __future__ import annotations

import math

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .backend import gpu_available
from .fem import solve
from .meshing import generate_mesh
from .particles import trace
from .postprocess import sample_line
from .schema import (
    MeshResult,
    Project,
    ProfileRequest,
    ProfileResult,
    SolveResult,
    TraceResult,
)

app = FastAPI(title="ES-Sim backend", version=__version__)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?|tauri://localhost",
    allow_methods=["*"],
    allow_headers=["*"],
)


def _mesh_result(mesh) -> MeshResult:
    return MeshResult(
        nodes=[tuple(p) for p in mesh.nodes.tolist()],
        triangles=[tuple(t) for t in mesh.triangles.tolist()],
        region_of_triangle=mesh.tri_region.tolist(),
    )


@app.get("/health")
def health():
    return {"status": "ok", "version": __version__, "gpu": gpu_available()}


@app.post("/mesh", response_model=MeshResult)
def mesh_endpoint(project: Project) -> MeshResult:
    try:
        return _mesh_result(generate_mesh(project))
    except Exception as exc:  # gmsh 由来の失敗をフロントへ伝える
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/solve", response_model=SolveResult)
def solve_endpoint(project: Project) -> SolveResult:
    try:
        mesh = generate_mesh(project)
        sol = solve(project, mesh)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    e_abs = (sol.e_field[:, 0] ** 2 + sol.e_field[:, 1] ** 2) ** 0.5
    return SolveResult(
        mesh=_mesh_result(mesh),
        v=sol.v.tolist(),
        e_field=[tuple(e) for e in sol.e_field.tolist()],
        v_min=float(sol.v.min()),
        v_max=float(sol.v.max()),
        e_abs_max=float(e_abs.max()),
        energy=sol.energy,
    )


@app.post("/profile", response_model=ProfileResult)
def profile_endpoint(req: ProfileRequest) -> ProfileResult:
    try:
        mesh = generate_mesh(req.project)
        sol = solve(req.project, mesh)
        s, v, e_abs = sample_line(mesh, sol, req.p1, req.p2, req.n)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    def _nan_to_none(arr: np.ndarray) -> list[float | None]:
        return [None if np.isnan(x) else float(x) for x in arr]

    return ProfileResult(
        s=s.tolist(),
        v=_nan_to_none(v),
        e_abs=_nan_to_none(e_abs),
    )


@app.post("/trace", response_model=TraceResult)
def trace_endpoint(project: Project) -> TraceResult:
    if project.particles is None:
        raise HTTPException(status_code=422, detail="project.particles が指定されていません")
    try:
        mesh = generate_mesh(project)
        sol = solve(project, mesh)
        result = trace(project, mesh, sol)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    status = ["absorbed" if a else "alive" for a in result.absorbed.tolist()]
    tof = [None if math.isnan(t) else float(t) for t in result.tof.tolist()]
    return TraceResult(
        trajectories=result.trajectories.tolist(),
        status=status,
        tof=tof,
        final_energy_ev=result.final_energy_ev.tolist(),
        dt=result.dt,
    )
