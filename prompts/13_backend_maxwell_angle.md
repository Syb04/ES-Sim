# サブエージェント指示: Maxwell分布ソース + 衝突角度の記録(バックエンド)

対象リポジトリ: `/home/claude/ES-Sim/backend`(依存インストール済み)

ES-Sim の粒子軌道トレーサ(`es_sim/particles.py`、`POST /trace`)への機能追加2件。
既存の schema.py / particles.py / tests/test_particles.py を読んでから着手すること。

## スキーマ契約(フロントと共通。この通りに実装すること)

`Emitter` に追加:

```jsonc
"energy_dist": "mono",       // "mono"(既定・従来動作) | "maxwell"
"temperature_ev": 1.0,       // maxwell 時の温度 kT [eV] (>0)
"seed": 0                    // maxwell サンプリングの乱数シード (int、再現性確保)
```

`TraceResult` に追加:

```jsonc
"final_angle_deg": [ ... ]   // 全粒子の最終速度の向き [度] (x軸から反時計回り、-180〜180)。
                             // absorbed 粒子では衝突時の入射方向を意味する
```

## 実装詳細

1. **Maxwell 分布**(`_init_particles` を拡張):
   - `energy_dist == "maxwell"` の場合:
     ドリフト速度(従来通り energy_ev と direction_deg から。spread_deg は無視)に、
     熱速度成分 vx, vy ~ Normal(0, σ)、σ = sqrt(kT·q_e/m) を加算する(2D Maxwell)
   - 乱数は `np.random.default_rng(seed)` を使用(同じ seed で完全再現)
   - `energy_dist == "mono"` は従来動作と完全一致(既存テストが通ること)
2. **衝突角度**: 積分中の最終速度(吸収粒子は衝突時刻に線形補間した速度が既にあればそれ、
   なければ吸収直前ステップの速度で良い)から `atan2(vy, vx)` [度] を全粒子分記録し、
   `TraceOutput` / `TraceResult` / server.py の変換に追加する
3. **テスト追加**(tests/test_particles.py に追記または新ファイル):
   - Maxwell サンプリング: seed 固定・n=2000・ドリフト0で、平均運動エネルギーが
     2D Maxwell の期待値 <E> = kT に対し相対誤差 5% 以内。同じ seed で2回呼ぶと完全一致
   - 角度: 既存の放物軌道テスト設定で、衝突時の角度が解析解 atan2(v_y, v_x) と数度以内で一致
   - mono の従来動作が変わらないこと(既存テストのパスで確認)

## 制約

- 新しい依存を追加しない。コメントは日本語。既存の公開関数シグネチャは維持
- mono モードでは乱数を一切使わない(従来の再現性を維持)

## 完了条件

`python -m pytest tests/ -q` 全件パス。最後に変更ファイル一覧とテスト結果の要約のみを報告。
