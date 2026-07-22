# サブエージェント指示: 構造格子メッシュモード(バックエンド)

対象リポジトリ: `/home/claude/ES-Sim/backend`(meshing.py の最新実装が前提)

矩形 domain 向けに、等間隔の構造格子メッシュ(三角形2分割)で切るモードを追加する。
gmsh transfinite は内部領域とのT字交差に弱いため、**numpy による直接生成**で実装する。
FEM・PIC 側は三角形前提のまま無変更で動くこと。

## スキーマ契約(フロントと共通)

- `MeshSettings` に `mode: "unstructured" | "structured" = "unstructured"` を追加

## 実装(`generate_mesh` の分岐で `_generate_structured(project)` を新設)

- **前提検査**: domain が軸平行の矩形(4頂点、辺が x/y 軸平行)であること。
  そうでなければ日本語の明確な ValueError
- 格子: nx = max(1, round(W/size))、ny = max(1, round(H/size))。節点は等間隔格子。
  各セルを対角線で2三角形に分割(向きは市松に交互=等方性向上。反時計回りの頂点順)
- **領域割り当て**: 要素中心の点内包判定(polygon は ray casting、circle は中心距離)で
  tri_region を決定(曲線境界は階段近似。domain 外へのはみ出しは自然にクリップ)
- **conductor**: 内包要素をメッシュから除去(穴)。Dirichlet 節点 = conductor 領域に
  内包(境界上含む、許容誤差 1e-12 相対)される節点のうち、残存要素から参照されるもの。
  voltage / voltage_rf / see_gamma は既存の Mesh フィールド
  (dirichlet / dirichlet_rf / see_gamma)と同じ形式で設定
- **外周BC**: 辺0(y=0)/1(x=W)/2(y=H)/3(x=0)上の節点に既存と同じ規則で
  Dirichlet/RF/γ を割り当て(電極優先の上書き順も既存と同じ)。symmetry/periodic 対応:
  periodic は対辺の節点が格子で完全一致するので座標対応で periodic_map を構築
- 未参照節点(conductor 内部)は除去して再番号付け(既存OCC実装と同じ後処理)
- local_sizes は構造格子では非対応(指定されていたら警告的に無視、docstringに明記)

## テスト(`tests/test_structured_mesh.py` 新規)

1. 平行平板(構造格子)で解析解テストと同水準の一致(V線形 <1e-8)。要素数 = 2·nx·ny
2. 矩形 conductor 領域(格子に整合する座標)で穴と Dirichlet 節点が正しいこと、
   /solve が妥当な V 範囲
3. circle conductor(階段近似)で同軸類似ケースの容量が解析値と 5% 以内
   (b/a が小さめの太い同軸で良い。domain は矩形+circle 電極、外周 Dirichlet)
4. periodic(上下)の構造格子で対辺節点の電位一致・x 線形解
5. PIC スモーク: 構造格子メッシュで 100 ステップ正常動作(粒子数保存系のチェック)
6. 既存68テストを壊さない(unstructured 経路は不変)

## 制約

新しい依存なし。日本語コメント。スキーマは追加のみ(後方互換)。

## 完了条件

`python -m pytest tests/ -q` 全件パス。変更ファイル一覧とテスト結果のみ報告。
