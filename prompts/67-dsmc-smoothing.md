# 67: DSMC 結果の平滑化 (隣接セル拡散、保存的)

## 背景 (ユーザー要望)

DSMC の圧力・数密度など統計ノイズの平滑化。方針は相談済みで以下に確定:

- **生モーメント (Σ個数, Σv, Σv²) を平滑化してから n/u/T/p を導出**する
  (導出後の場を別々に均すと p = n k T の整合が崩れ、負温度等の人工値が出るため)。
- 平滑化は**隣接セル間の対称拡散**: 体積重みで厳密に総量保存・正値保証。
- 適用先は**結果 (DsmcResult の n/t/u/p) と PIC 連成 (GasField)** の両方。
- 回数 (passes) を DSMC 設定で指定。0 = 無効 (既定、従来と完全一致)。

## アルゴリズム

要素 i の体積を V_i (xy: 面積×奥行1m、rz: 2πr̄A = 既存の self.vol)、
隣接要素集合を adjacency (walk 用の既存テーブル、境界は -1) とする。
セル密度的な中間量 q_i = acc_i / V_i (acc は蓄積モーメントの各成分) に対し、1パス:

```
q_i' = q_i + θ · Σ_{j∈adj(i), j≥0, 非固体} (W_ij / V_i) · (q_j − q_i)
W_ij = min(V_i, V_j)   (対称)
θ = 0.25
```

- W_ij が対称なので Σ_i V_i q_i (= Σ acc) は**厳密に保存**される
  (ペアごとの交換が相殺するため)。
- q_i' は凸結合: 係数 1 − θ·Σ W_ij/V_i ≥ 1 − 0.25×3 = 0.25 > 0 なので
  **非負性が保たれる** (W_ij ≤ V_i、隣接は最大3)。
- 固体 (誘電体) 要素はガスが存在しないため交換対象から除外する
  (self._solid が非Noneの場合。固体セルの acc は元々0のはず)。
- passes 回反復。実装は全成分まとめてベクトル化
  (acc_cnt / acc_v(3成分) / acc_v2 の5成分を (n_elem, 5) に並べて一括更新可)。

## backend

### es_sim/schema.py

- `DsmcSettings.smoothing_passes: int = Field(0, ge=0, le=20)` を追加。
  コメント: 隣接セル拡散による統計ノイズ平滑化の回数 (0=無効)。

### es_sim/dsmc.py

- `_smooth_moments()` (または相当のヘルパ) を追加し、結果組み立て
  (n/t/u/p を _acc_* から導出している箇所) の**直前**に
  smoothing_passes > 0 なら _acc_cnt / _acc_v / _acc_v2 を上記拡散で平滑化する。
- 蓄積配列そのものを書き換えるのではなくコピーに対して行う
  (途中停止→再開等で二重適用しないよう、導出時のみ適用)。
  ※ 現在 run() は1回きりなので実害はないが、導出パスで完結させるのが安全。
- adjacency の形状 (要素×3、-1=境界) を確認して利用。固体隣接も除外。

### PIC 連成 (server.py / pic.py)

- GasField が DsmcResult の n/t/u から作られていることを確認する。
  そうであれば結果側の平滑化が自動で連成にも効くので追加実装不要。
  もし生の蓄積から別経路で作っていれば、同じ平滑化済みモーメントを通す。

## frontend

- `types.ts`: DsmcSettings に `smoothing_passes: number` を追加。
- `GasPanel.tsx`: 「初期条件・計算設定」に「平滑化回数」入力
  (CommitNumberInput、整数 0〜20、既定 0、`dsmc.smoothing_passes ?? 0` で表示)。
  ヒント: 「隣接セル拡散による統計ノイズの平滑化。0=無効。総量 (質量・運動量・
  エネルギー) は保存され、結果表示と PIC 連成の両方に適用されます。目安 1〜5」。
  DEFAULT_DSMC にも 0 を追加。

## テスト (backend/tests/test_dsmc.py に追加)

1. **保存性**: 小ケースを smoothing_passes=3 で実行し、Σ V_i·n_i (総粒子数相当) が
   passes=0 の場合と相対誤差 1e-10 以下で一致すること。
2. **正値性**: n ≥ 0、t ≥ 0 (全要素)。
3. **ノイズ低減**: 一様平衡箱 (全辺壁、流入なし) で n の空間分散
   (var(n)/mean(n)²) が passes=5 で passes=0 より小さくなること。
4. **無効時の完全一致**: smoothing_passes=0 (既定) の結果が従来と同一
   (既存テストが全件通ることで担保。明示テストは不要)。

`python -m pytest tests/ -q` 全件パス (現在 135 passed)。

## 検証

- backend: pytest 全件。
- frontend: `npx tsc --noEmit && npx vite build`。

## 注意

- コメントは日本語で「なぜ」を書く既存スタイル (保存性・正値性の理由を書く)。
- docs/DSMC.md に平滑化の節 (アルゴリズム・保存性・θ=0.25 の根拠) を追記する。
- git commit はしない。
