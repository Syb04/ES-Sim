# サブエージェント指示: バックエンド ラインプロファイルAPI

対象リポジトリ: `/home/claude/ES-Sim/backend`(依存はインストール済み。システムPythonで動く)

## 背景

ES-Sim は 2D静電場FEMアプリ。`es_sim/` に schema(pydantic)/ meshing(gmsh)/ fem(P1要素)/ server(FastAPI) がある。
仕様書 `/home/claude/ES-Sim/docs/SPEC.md` の §7「ラインプロファイル」を実装する。

## やること

1. **`es_sim/postprocess.py` を新規作成**
   - `sample_line(mesh, solution, p1, p2, n) -> (s, v, e_abs)`:
     線分 p1→p2 上を n 点等間隔サンプリングし、弧長 s [m]、電位 v [V]、|E| [V/m] を返す
   - 点の所属三角形の特定は全要素に対する重心座標判定の numpy ベクトル化で良い
     (サンプル数×要素数の総当たり。許容誤差 1e-12 程度のマージンを持たせる)
   - V は P1 形状関数(重心座標)で補間、E は所属要素の値(要素内一定)
   - 領域外(電極の穴の中など)の点は NaN にする
2. **`es_sim/schema.py` に追加**
   - `ProfileRequest(project: Project, p1: Point, p2: Point, n: int = 200)`
   - `ProfileResult(s: list[float], v: list[float | None], e_abs: list[float | None])`
     (NaN は None にして返す)
3. **`es_sim/server.py` に `POST /profile` を追加**
   - mesh 生成 → solve → sample_line。既存エンドポイントと同じエラーハンドリング方針
4. **`tests/test_postprocess.py` を新規作成**
   - 平行平板(既存 test_fem.py の fixture と同じ設定)で x 方向プロファイルをとり、
     v が解析解 V1*x/D と一致(atol=1e-6*V1)、e_abs が V1/D で一定であること
   - 領域外の点が None/NaN になること(domain の外側をサンプリング)

## 制約

- 既存コードのスタイル(日本語コメント、型ヒント、ベクトル化)に合わせる
- 既存ファイルの既存機能は変更しない(server.py への追記は可)
- 新しい依存パッケージを追加しない

## 完了条件

`cd /home/claude/ES-Sim/backend && python -m pytest tests/ -q` が全件パスすること。
最後に変更・追加したファイルの一覧と、テスト結果の要約だけを報告すること。
