# サブエージェント指示: フェーズ3 FEM-PICコア + WebSocketストリーミング(バックエンド)

対象リポジトリ: `/home/claude/ES-Sim/backend`(依存インストール済み)

ES-Sim に FEM-PIC(非構造三角形メッシュ上のPIC)を実装する。代表ターゲットは
**低温プラズマ(CCP: RF電極駆動の容量結合プラズマ、第1弾は無衝突)**。
仕様書 `/home/claude/ES-Sim/docs/SPEC.md` §9 と、既存の meshing.py / fem.py /
particles.py(walk探索・隣接配列・リープフロッグが再利用できる)を熟読してから着手すること。

## スキーマ契約(フロントと共通。この通りに実装すること)

### RF電圧(既存スキーマの拡張)

`Region`(conductor)と `BoundaryCondition` に optional で追加:

```jsonc
"voltage_rf": { "amplitude": 100.0, "freq_hz": 13.56e6, "phase_deg": 0.0 }
// V(t) = voltage + amplitude * sin(2π f t + phase)。未指定なら従来の直流のみ
```

静電ソルブ(/solve)は従来通り `voltage`(直流分)のみを使う。PIC のみ V(t) を使う。

### PIC設定(`Project.pic`、optional)

```jsonc
"pic": {
  "initial_plasma": {                       // null なら初期装荷なし
    "density": 1.0e14,                      // [m^-3] (奥行き1m換算)
    "te_ev": 2.0,                           // 電子温度
    "ti_ev": 0.03,                          // イオン温度
    "ion_mass_amu": 40.0,                   // Ar+ = 40
    "immobile_ions": false,                 // true でイオン固定 (検証用)
    "seed": 0
  },
  "injection": null,                        // null なら注入なし。エミッタ定常注入:
  // { "emitter": <既存Emitterと同型>, "species": "electron"|"ion",
  //   "current_a_per_m": 1e-4 }            // 電流 [A/m] → 毎ステップの実電荷を等分注入
  "n_macro": 20000,                         // 種ごとの初期マクロ粒子数の目安
  "dt": null,                               // null = 0.1/ωpe (初期密度から。密度0なら要指定)
  "n_steps": 2000,
  "frame_every": 20                         // フレーム送出間隔 (ステップ)
}
```

- 粒子はドメイン内(電極領域を除く)に一様配置(乱数は `default_rng(seed)`、速度はMaxwell)。
  マクロ重み w = density × 装荷面積 / n_macro
- 電子は preset electron、イオンは質量 amu×MP・電荷 +e の2種を常に管理する

## 実装方針

### `pic.py` — `PicSimulation` クラス

- `__init__(project)`: メッシュ生成 → FEM行列組み立て → **K_ff を splu で1回だけ前分解**。
  particles.py の隣接配列・重心座標係数・walk探索を再利用(必要なら particles.py の関数を
  import して使う。コピペ実装はしない)
- `step()`: 1ステップ =
  1. **電荷堆積**: 全粒子の電荷を P1形状関数(重心座標)の重みで節点荷重ベクトルへ散布
     f_i = Σ_p w_p q_p L_i(x_p)(numpy: np.add.at)。静的 charge 領域の寄与(既存fem)にも加算
  2. **ポアソン求解**: Dirichlet 値は V(t)(RF含む)で毎ステップ更新。
     rhs = f_free − K_fd·v_d(t) を前分解済みLUで解く(再分解しない)
  3. E補間(所属要素の値)→ 4. リープフロッグでプッシュ(種ごとにq/m)→
  5. walk更新・境界吸収(壁到達粒子は除去、種別ごとに壁吸収数を集計)→ 6. 注入
- 初速の反跳: リープフロッグの初期半ステップ後退キックを装荷時・注入時に適用
- **診断**(毎ステップ記録): 時刻、運動エネルギー(種別)、場のエネルギー ½∫ε|E|²、
  粒子数(種別)、壁吸収の累計(種別)、φのmin/max
- **安定性チェック**: 開始時に ωpe·dt と デバイ長/セルサイズ を計算し、
  ωpe·dt > 0.3 または セル > 3λD なら警告文字列を返す(実行は継続)
- `run_batch(callback=None)`: n_steps 回して診断履歴とフレーム列を返す(テスト用同期API)

### `server.py` — `WS /ws/pic`

プロトコル(すべてJSONテキスト):

- client→server: `{"cmd": "start", "project": {...}}` / `{"cmd": "stop"}`
- server→client:
  - `{"type": "started", "dt": ..., "n_steps": ..., "warnings": [...], "mesh": {nodes, triangles}}`
  - `{"type": "frame", "step": k, "t": ..., "phi": [節点値], 
     "particles": {"electron": [[x,y],...], "ion": [[x,y],...]},   // 種ごと最大2000点に間引き
     "diag": {"t": ..., "ke_e": ..., "ke_i": ..., "fe": ..., "n_e": ..., "n_i": ...,
              "wall_e": ..., "wall_i": ..., "phi_min": ..., "phi_max": ...}}`
  - `{"type": "done", "history": {全ステップの診断履歴(配列)}}` / `{"type": "error", "detail": "..."}`
- 計算は `asyncio.to_thread` 等でイベントループを塞がず実行し、stop コマンドで中断可能にする
- frame_every ごとに frame を送出。送信が追いつかない場合もブロックしない程度の設計で良い

### テスト(`tests/test_pic.py` 新規)

WSではなく `PicSimulation.run_batch` の同期APIで検証する:

1. **プラズマ振動**: 矩形ドメイン、immobile_ions=true、電子に微小一様変位(または微小ドリフト)を
   与えた冷たいプラズマ(te→ほぼ0)で、運動エネルギー振動の周波数が 2×fpe と 10%以内で一致
   (fpe = ωpe/2π を初期密度から計算。FFTまたはゼロクロスで周波数推定)
2. **エネルギー保存**: 同上設定(ωpe·dt≈0.1)で、(運動+場)エネルギーのドリフトが
   初期全エネルギー比 5% 以内
3. **CCPスモーク**: 平行平板(片側 RF ±50V/13.56MHz、対向 GND)+初期プラズマ装荷で
   200ステップ実行 → NaNなし・粒子数単調非増加・RF1周期平均の中央電位が両壁より高い
   (シース形成の定性確認)
4. 既存テストを壊さない

## 制約

- 新しい依存を追加しない。コメントは日本語。ホットループはnumpyベクトル化(粒子forループ不可)
- 既存の /solve /trace の動作を変えない(スキーマ追加は後方互換に)
- 数万マクロ粒子×数千ステップが実用時間(数十秒〜数分)で回る性能を意識する

## 完了条件

`python -m pytest tests/ -q` 全件パス(PICテストが遅い場合は粒子数・ステップ数を調整して
1テスト30秒以内を目安に)。最後に変更ファイル一覧・テスト結果・性能実測
(粒子数×ステップ数と所要時間)の要約のみを報告。
