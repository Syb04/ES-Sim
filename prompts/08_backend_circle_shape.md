# サブエージェント指示: 円領域のパラメトリック化(バックエンド)

対象リポジトリ: `/home/claude/ES-Sim/backend`(依存インストール済み)

## 背景

現状、GUI の円ツールは48角形の polygon として領域を保存する。このためメッシュ生成時に
多角形頂点間隔がメッシュサイズの下限になり、粗いメッシュ指定が効かない
(詳細は `verification/coax_convergence.py` 冒頭コメント参照)。
円を「中心+半径」のパラメトリック形状として保持し、**メッシュ生成時に**分割数を決める方式に変える。

## スキーマ契約(フロントと共通。この通りに実装すること)

```jsonc
// Region に shape を追加。polygon / shape はどちらか一方のみ必須
{ "id": "r1", "type": "conductor", "voltage": 0,
  "shape": { "kind": "circle", "center": [0.05, 0.02], "radius": 0.01 } }
```

多角形化規則: 特性長 h = その領域の local_size(あれば)/ なければ mesh.size として
`n = clamp(ceil(2πr / h), 24, 720)` 分割、開始角 0、反時計回り。

## やること

1. **`schema.py`**: `CircleShape(kind: Literal["circle"], center: Point, radius: float > 0)` を追加。
   `Region.polygon` を optional にし、model_validator で「polygon か shape のどちらか一方のみ」を強制
2. **`meshing.py`**: 領域ポリゴン解決ヘルパー `_region_polygon(region, h) -> list[Point]` を導入し、
   circle shape は上記規則で多角形化。既存の polygon 領域は従来通り
3. **`tests/test_circle_shape.py`(新規)**:
   - バリデーション: polygon と shape の両方指定/両方なしで ValidationError
   - 分割数連動: 同じ circle shape 領域(誘電体)で mesh.size を 0.008 と 0.002 にした場合、
     粗い方が総節点数が明確に少ないこと(従来の48角形固定では起きなかった現象)
   - 精度: 同軸円筒(内導体を circle shape、domain は tests/test_coax.py と同様の外周多角形)で
     mesh.size 0.002 の容量が解析値と相対誤差 2% 以内
4. 既存テストを壊さないこと(`python -m pytest tests/ -q` 全件パス)

## 制約

- 新しい依存を追加しない。コメントは日本語。既存の公開関数シグネチャは維持
- server.py の変更は不要のはず(pydantic スキーマ経由で自動対応)

## 完了条件

`python -m pytest tests/ -q` 全件パス。最後に変更ファイル一覧とテスト結果の要約のみを報告。
