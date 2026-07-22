"""FastAPI ローカルサーバー。Tauri フロントエンドから 127.0.0.1:8317 で利用する。

起動:  uvicorn es_sim.server:app --port 8317
"""

from __future__ import annotations

import asyncio
import json
import math
import threading

import numpy as np
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .backend import gpu_available
from .fem import solve
from .lxcat import parse_lxcat
from .meshing import generate_mesh
from .particles import trace
from .pic import PicSimulation
from .postprocess import sample_line
from .schema import (
    LxcatParseRequest,
    LxcatParseResult,
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
        final_angle_deg=result.final_angle_deg.tolist(),
        dt=result.dt,
    )


@app.post("/lxcat/parse", response_model=LxcatParseResult)
def lxcat_parse_endpoint(req: LxcatParseRequest) -> LxcatParseResult:
    """LXCat 形式テキストをパースして断面積プロセス一覧を返す (prompts/19)。"""
    try:
        processes, warnings = parse_lxcat(req.text, req.species)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return LxcatParseResult(processes=processes, warnings=warnings)


# ---- PIC WebSocket ストリーミング (フェーズ3、仕様書 §9) ----------------------


async def _run_pic_session(ws: WebSocket, project_dict: dict) -> None:
    """1回の PIC 実行。計算はワーカースレッドで行い、フレームをキュー経由で送出する。"""
    loop = asyncio.get_running_loop()
    stop = threading.Event()
    queue: asyncio.Queue = asyncio.Queue()

    try:
        project = Project.model_validate(project_dict)
        # メッシュ生成・行列組み立ても重いのでスレッドで実行
        sim = await asyncio.to_thread(PicSimulation, project)
    except Exception as exc:
        await ws.send_json({"type": "error", "detail": str(exc)})
        return

    await ws.send_json(
        {
            "type": "started",
            "dt": sim.dt,
            "n_steps": sim.pic.n_steps,
            "warnings": sim.warnings,
            "mesh": {
                "nodes": sim.mesh.nodes.tolist(),
                "triangles": sim.mesh.triangles.tolist(),
            },
        }
    )

    def on_frame(frame: dict) -> None:
        # ワーカースレッドからイベントループへ安全に渡す (ブロックしない)
        loop.call_soon_threadsafe(queue.put_nowait, frame)

    run_task = asyncio.create_task(
        asyncio.to_thread(sim.run_batch, on_frame, stop.is_set)
    )

    async def watch_stop() -> None:
        # 実行中の stop コマンド (または切断) を監視する
        while True:
            try:
                msg = json.loads(await ws.receive_text())
            except (WebSocketDisconnect, RuntimeError):
                stop.set()
                return
            if msg.get("cmd") == "stop":
                stop.set()
                return

    stop_task = asyncio.create_task(watch_stop())
    try:
        while True:
            if run_task.done() and queue.empty():
                break
            try:
                frame = await asyncio.wait_for(queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                continue
            await ws.send_json(frame)
        history, _ = await run_task
        done_msg: dict = {"type": "done", "history": history}
        # 時間平均フィールド (prompts/26)。平均区間を積算できていれば添付する
        if sim.fields is not None:
            done_msg["fields"] = {
                k: (v.tolist() if isinstance(v, np.ndarray) else v)
                for k, v in sim.fields.items()
            }
        await ws.send_json(done_msg)
    except Exception as exc:
        try:
            await ws.send_json({"type": "error", "detail": str(exc)})
        except Exception:
            pass
    finally:
        stop.set()
        stop_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)


@app.websocket("/ws/pic")
async def ws_pic(ws: WebSocket) -> None:
    """PIC 実行の WebSocket。start コマンドで開始、stop で中断できる。"""
    await ws.accept()
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            cmd = msg.get("cmd")
            if cmd == "start":
                await _run_pic_session(ws, msg.get("project", {}))
            elif cmd == "stop":
                continue  # 実行中でなければ無視
            else:
                await ws.send_json({"type": "error", "detail": f"不明なコマンド: {cmd}"})
    except WebSocketDisconnect:
        pass
