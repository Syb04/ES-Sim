# 54: DSMC 定常ガス流れ + 非一様背景ガスの PIC 結合

## バックエンド設計 (実装済み — 本体モデルが直接実装。以下は記録)

### Phase A: MCC の非一様背景ガス対応 (受け側)

- `mcc.GasField {n_g (M,), t_g (M,)|None, u_g (M,2)|None}` — 要素ごとのガス場
- null-collision の ν_max は最大密度 n_max で評価し、採択時に局所密度比
  n_g(x)/n_max を掛ける (非一様でも null-collision は厳密)
- イオン衝突・電離生成イオンの背景 Maxwell は局所温度 t_g・局所流速 u_g を使う
- `PicSimulation(project, gas_field)` で注入。要素数不一致は起動時エラー
- 定数場 (rel ≡ 1) は一様指定とビット単位で一致 (テストで検証済み)

### Phase B: DSMC ソルバー (es_sim/dsmc.py)

- セル = 既存三角形メッシュ。NTC 法 + VHS 分子モデル (Bird 標準形、Γ(5/2−ω) 込み)
- 境界: 拡散反射壁 (壁温 Maxwell 流束)・鏡面 (symmetry)・圧力リザーバ
  (inlet/outlet: 平衡流束 n c̄/4 の流入 + 流出吸収)・真空排気 (outlet 圧力なし)
- 数値加熱を防ぐ2つの要点 (デバッグで判明):
  1. 衝突対のベクトル一括更新で同一粒子が複数対に現れると分散が湧いて加熱する
     → 粒子ごとに最初の対のみ実行、落とした対は候補として次ステップへ持ち越し
  2. 壁再放出後の残余移動時間を捨てると壁近傍に放出直後 (流束 Maxwell = 2kT) の
     粒子が滞留して温度が +2% 程度高く出る → 残余時間を完走 (最大6レグ)
- 検証: 平衡箱で n/T/p 保持 (3%以内)、無衝突チャネルで密度 = リザーバの 1/2・
  流速 = c̄/2 (半空間 Maxwell の解析値、5%以内)、圧力駆動流の質量収支 (10%以内)
  と単調圧力勾配

### サーバー統合

- `POST /dsmc` (project.dsmc 必須) → DsmcResultModel {mesh, n, t, u, p, 統計}。
  結果はプロセス内 `_last_dsmc` に保持
- PIC start で `pic.mcc.use_dsmc_gas: true` なら保持中のガス場を注入
  (未実行ならエラー、要素数不一致もエラー)

## フロントエンド作業 (サブエージェント向け指示)

1. **types.ts**: `DsmcGas`/`DsmcBoundary`/`DsmcSettings`/`DsmcResult` 型を
   backend/es_sim/schema.py と同期して追加。`Project.dsmc?: DsmcSettings | null`、
   `McSettings.use_dsmc_gas?: boolean`。api.ts に `dsmc(project): Promise<DsmcResult>` を追加

2. **新パネル GasPanel.tsx** (サイドバーに4つ目のタブ「ガス」を追加):
   - DSMC 有効チェック (project.dsmc の有無)
   - ガス種設定: name, mass_amu, d_ref_m, omega, t_ref_k (既定 Ar)
   - 境界条件リスト: domain エッジ番号選択 + type (壁/対称/流入/流出) +
     温度 + 圧力 (inlet/outlet)。エッジの追加/削除
   - 初期圧力・初期温度・壁温・粒子数・ステップ数・平均ステップ数・seed
   - 「ガス流れ計算」ボタン → POST /dsmc (実行中は busy 表示)。
     完了後に結果サマリ (粒子数、流入/流出) を表示
   - 結果フィールドセレクト (数密度 n [m^-3] / 温度 T [K] / 流速 |u| [m/s] /
     圧力 p [Pa]) + 対数チェック → CadCanvas に要素値カラーマップ表示
     (App の picFieldView と同じ PicFieldView 型を流用: nodeBased=false)
   - タブ構成は App.tsx の activeTab ("field" | "particle" | "pic") に "gas" を追加

3. **PicPanel.tsx**: MCC セクションに「DSMCガス場を使用」チェックボックス
   (mcc.use_dsmc_gas)。ヒント: 「直前に実行したガス流れ (DSMC) の n・T・u を
   背景ガスとして使う (圧力・温度の一様指定は無視される)」

4. **App.tsx**: dsmc 設定 state (project.dsmc として保存/読込対象、Undo/Redo 外で
   particles/pic と同じ扱いにするか project 内で良いかは既存構造に合わせて判断。
   project.dsmc として素直に project state に置くのが簡単)、ガス場表示用 state
   (DsmcResult 保持、フィールド選択で CadCanvas へ)

## 検証

`cd /home/claude/ES-Sim/frontend && npx tsc --noEmit && npx vite build` が通ること。
コミットはしない (呼び出し元が行う)。
