import type { Health, MeshResult, Point, Project, ProfileResult, SolveResult, TraceResult, XsProcess } from "./types";
import { getPort } from "./backendPort";

// リクエストの都度ポート番号を組み立てる (GUIでの変更を即座に反映するため、定数 BASE は使わない)
function base(): string {
  return `http://127.0.0.1:${getPort()}`;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${base()}${path}`, {
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
    fetch(`${base()}/health`).then((r) => r.json()),
  mesh: (project: Project): Promise<MeshResult> => post("/mesh", project),
  solve: (project: Project): Promise<SolveResult> => post("/solve", project),
  profile: (project: Project, p1: Point, p2: Point, n = 200): Promise<ProfileResult> =>
    post("/profile", { project, p1, p2, n }),
  trace: (project: Project): Promise<TraceResult> => post("/trace", project),
  // LXCat形式テキストを断面積プロセス列にパースする (MCC設定のインポート用)
  lxcatParse: (text: string, species: "electron" | "ion"): Promise<{ processes: XsProcess[]; warnings: string[] }> =>
    post("/lxcat/parse", { text, species }),
};
