import type { Health, MeshResult, Point, Project, ProfileResult, SolveResult } from "./types";

const BASE = "http://127.0.0.1:8317";

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(`${path} failed: ${JSON.stringify(detail)}`);
  }
  return res.json();
}

export const api = {
  health: (): Promise<Health> =>
    fetch(`${BASE}/health`).then((r) => r.json()),
  mesh: (project: Project): Promise<MeshResult> => post("/mesh", project),
  solve: (project: Project): Promise<SolveResult> => post("/solve", project),
  profile: (project: Project, p1: Point, p2: Point, n = 200): Promise<ProfileResult> =>
    post("/profile", { project, p1, p2, n }),
};
