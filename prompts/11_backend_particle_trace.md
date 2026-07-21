# サブエージェント指示: フェーズ2 粒子軌道トレーサ(バックエンド)

対象リポジトリ: `/home/claude/ES-Sim/backend`(依存インストール済み)

ES-Sim の静電場FEM(P1三角形要素)の解を固定場として、荷電粒子の軌道を追跡する。
仕様書 `/home/claude/ES-Sim/docs/SPEC.md` §8 と、既存の meshing.py / fem.py を読んでから着手すること。

## スキーマ契約(フロントと共通。この通りに実装すること)

`Project` に optional な `particles` を追加:

```jsonc
"particles": {
  "species": { "preset": "electron" },              // "electron" | "proton" | "custom"
  //  custom の場合: { "preset": "custom", "q": -1.6e-19, "m": 9.1e-31 }
  "emitter": {
    "kind": "line",                                  // "line" | "point"
    "p1": [0.01, 0.02], "p2": [0.01, 0.03],          // point の場合は p1 のみ使用
    "n": 100,                                        // 粒子数 (line: 線分上等間隔, point: 全て同位置)
    "energy_ev": 1.0,                                // 初期運動エネルギー [eV]
    "direction_deg": 0.0,                            // 射出方向 (x軸から反時計回り、度)
    "spread_deg": 0.0                                // 方向の一様分布半角 [度] (等間隔に振る。乱数不使用)
  },
  "dt": null,                                        // 秒。null なら自動推定
  "n_steps": 5000,
  "save_every": 10
}
```

`POST /trace`(リクエスト body = Project、particles 必須)のレスポンス:

```jsonc
{
  "trajectories": [ [[x,y], ...], ... ],   // 粒子ごと、save_every ステップごと (初期位置含む)
  "status": [ "absorbed" | "alive", ... ], // absorbed = 電極/外周に到達して停止
  "tof": [ 1.2e-9 | null, ... ],           // absorbed 粒子の飛行時間 [s]
  "final_energy_ev": [ ... ],              // 最終運動エネルギー [eV]
  "dt": 1.0e-12                            // 実際に使った dt
}
```

## 実装方針

1. **schema.py**: 上記の `Species` / `Emitter` / `ParticleSettings` / `TraceResult` を追加。
   `Project.particles: ParticleSettings | None = None`
2. **particles.py**: 本体を実装
   - 前処理: mesh.triangles から**隣接三角形配列**(各要素の3エッジの向こう側、境界は -1)を構築
   - **粒子の所属要素**: 重心座標による walk 探索(前回要素からスタート、負の重心座標の
     エッジを渡って隣へ。全粒子 numpy ベクトル化、walk は上限付き while ループで良い)
   - 初期所属要素は全要素総当たりで決定して良い(初回のみ)
   - **積分**: リープフロッグ。E は所属要素の値(要素内一定)。q/m は species から
   - **吸収**: walk が境界(-1)に出たら absorbed。その粒子は以後更新しない。
     位置は境界を越える直前のものを最終位置とする
   - **dt 自動推定**(dt=null時): 代表速度 v = max(初期速度, sqrt(2·|q|·E_max·h_min/m)) に対し
     dt = 0.3·h_min/v(h_min = 最小要素外接半径程度の長さスケール)。過小/過大にならないよう実装後に
     テストケースで妥当性を確認せよ
   - 乱数は使わない(spread は等間隔割り振り)。再現性を保つ
3. **server.py**: `POST /trace` を追加(mesh 生成 → solve → trace。既存と同じエラーハンドリング)
4. **tests/test_particles.py**(新規):
   - **加速テスト**: 平行平板 100V/0.1m の一様場で電子を陰極から静止発射
     → 陽極到達時の final_energy_ev ≒ 100 eV(相対誤差 <1%)、
     飛行時間が解析解 t=√(2dm/(qE)) と一致(相対誤差 <1%)
   - **放物軌道テスト**: 一様場中に場と直交する初速で発射した電子の軌道が
     解析解の放物線と一致(中間点の位置誤差が数%以内)
   - **吸収テスト**: 電極(円 conductor 領域)に向けて発射した粒子が absorbed になること
5. 既存テストを壊さない(`python -m pytest tests/ -q` 全件パス)

## 制約

- 新しい依存を追加しない(numpy/scipy/gmsh のみ)。コメントは日本語
- ホットループは numpy 一括処理(粒子ループの Python for は不可。walk の反復は可)
- 既存の公開関数シグネチャは維持

## 完了条件

`python -m pytest tests/ -q` 全件パス。最後に変更ファイル一覧・テスト結果・dt自動推定の妥当性の要約のみを報告。
