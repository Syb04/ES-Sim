# サブエージェント指示: MCC衝突 + LXCatインポート + 二次電子放出(バックエンド)

対象リポジトリ: `/home/claude/ES-Sim/backend`(依存インストール済み)

ES-Sim の FEM-PIC(`es_sim/pic.py` の `PicSimulation`)に、背景中性ガス(Ar等)との
モンテカルロ衝突(MCC, null-collision法)と電極での二次電子放出(SEE)を追加する。
断面積は LXCat 形式ファイルからインポートする。既存の pic.py / particles.py /
schema.py / server.py を熟読してから着手すること。

実サンプル: `tests/data/Ar電子衝突断面積.txt`(Morgan: ELASTIC/EXCITATION×2/IONIZATION、
標準LXCatブロック形式)、`tests/data/Arイオン衝突断面積.txt`(Phelps: Ar+ + Ar の
Backscat/Isotropic、**タイプ行なし**の SPECIES/PROCESS ブロック形式)。
両ファイルは git 管理外(再配布条件のため)。テストは実ファイルがあれば使い
(`pytest.mark.skipif`)、リポジトリには**自作の小さな合成フィクスチャ**
(`tests/data/synthetic_electron.txt` / `synthetic_ion.txt`、両形式を模す)を置いて常時テストする。

## スキーマ契約(フロントと共通。この通りに実装)

```jsonc
// 断面積プロセス (パース済み、プロジェクトJSONに埋め込む)
"XsProcess": {
  "kind": "elastic" | "excitation" | "ionization" | "isotropic" | "backscat",
  "label": "E + Ar -> E + Ar, Elastic",   // PROCESS行等から
  "threshold_ev": 0.0,                     // excitation/ionization のみ >0
  "mass_ratio": 1.36e-5,                   // elastic のみ (m/M)。無ければ 0
  "energy_ev": [...], "sigma_m2": [...]    // 断面積テーブル (同長、energy 昇順)
}

// PicSettings に追加
"mcc": {                                   // null なら MCC 無効
  "gas": { "name": "Ar", "pressure_pa": 10.0, "temperature_k": 300.0 },
  "electron_processes": [XsProcess...],    // elastic/excitation/ionization
  "ion_processes": [XsProcess...],         // isotropic/backscat
  "seed": 0
},
"see_energy_ev": 2.0                       // SEE電子の初期エネルギー

// SEE係数 γ: 電極単位で指定 (0 = 無効)
Region(conductor) に "see_gamma": 0.0 (optional)
BoundaryCondition に "see_gamma": 0.0 (optional)
```

`POST /lxcat/parse` を追加: body `{"text": "<ファイル内容>", "species": "electron"|"ion"}` →
`{"processes": [XsProcess...], "warnings": [...]}`(パース失敗は 422 + 理由)。

## 実装

### 1. `es_sim/lxcat.py`(新規)— パーサー

- 標準形式: `ELASTIC`/`EFFECTIVE`/`EXCITATION`/`IONIZATION`/`ATTACHMENT` 行 → 2行目 種名 →
  3行目 パラメータ(elastic: m/M、excitation/ionization: 閾値eV)→ コメント行(数字で始まらない)→
  `-----` で挟まれた2列テーブル(eV, m²)
- タイプ行なし形式(Phelpsイオン等): `SPECIES:`/`PROCESS:` 行 + テーブルのブロック。
  PROCESS 行の末尾語で判定: `Backscat`→`backscat`、`Isotropic`→`isotropic`
- `EFFECTIVE` は警告付きで elastic として取り込み。`ATTACHMENT` は警告を出してスキップ
- ヘッダ・説明文・`xxxx`/`****` 区切りは読み飛ばす。species="electron" では
  elastic/excitation/ionization のみ、"ion" では isotropic/backscat のみ許可(他は警告スキップ)

### 2. `es_sim/mcc.py`(新規)— null-collision MCC

- 前処理(mcc設定から): 共通エネルギーグリッド上で各プロセスの ν_j(E) = n_g σ_j(E) v(E) を
  テーブル化し、ν_max = max_E Σ_j ν_j を求める(n_g = p/(kB·T_gas))
- 毎ステップ種ごとに: P_coll = 1 − exp(−ν_max·dt) で衝突候補を抽選 →
  候補粒子のエネルギーで ν_j(E)/ν_max により実プロセス or null を選択(numpyベクトル化、
  rng は mcc.seed から)
- 電子プロセス:
  - elastic: 2D等方散乱(速度方向を一様乱数で回し直す)+エネルギー損失 ΔE = 2(m/M)(1−cosχ)E
  - excitation: E ≥ 閾値なら E−閾値 に減速し等方散乱
  - ionization: E ≥ 閾値なら余剰 E−閾値 を一様乱数比で散乱電子/放出電子に分配(両者等方)。
    新電子+新イオン(ガス温度のMaxwell速度)を衝突位置に生成。マクロ重みは入射電子と同じ
- イオンプロセス(energy_ev は実験室系イオンエネルギーとして解釈):
  - isotropic: ガス原子(Maxwell抽選)との等質量弾性衝突、COM等方散乱
  - backscat: 電荷交換 — イオン速度をガス原子のMaxwell速度で置き換える
- 衝突は位置を変えないので所属要素の更新は不要

### 3. SEE(pic.py に統合)

- 初期化時に境界エッジ(隣接=-1)ごとの属性表を構築: エッジ両端節点が
  γ>0 の電極/Dirichlet辺に属するなら γ と内向き法線を記録
- イオンがそのエッジで吸収された際、確率 γ で電子を1個生成:
  位置=吸収位置(境界からわずかに内側)、速度=内向き法線方向に see_energy_ev、
  重み=吸収イオンと同じ。診断に SEE 発生数を追加

### 4. 診断の拡張

`PicDiag`(履歴・フレーム)に累計カウンタを追加: `coll_e`(電子衝突計)、`ion_events`(電離)、
`see_events`。既存フィールドは変更しない(フロントの後方互換のため追加のみ)

### 5. テスト(`tests/test_mcc.py` 新規)

- パーサー: 合成フィクスチャで両形式・全プロセス種のパース(件数・閾値・テーブル長・単調性)。
  実ファイルがあれば追加検証(電子: elastic+excitation×2+ionization、イオン: backscat+isotropic)
- 衝突頻度: 一定断面積σの合成データ・電場なし・単色電子で、測定衝突率が ν = n_g σ v と
  数%以内で一致
- 電離: 一様電場+電離のみで電子数が増加すること。エネルギー閾値未満では電離が起きないこと
- SEE: γ=1 の電極へイオンを打ち込み、吸収数=SEE電子生成数となること
- CCPスモーク: 実ファイル(なければ合成)+RF+初期プラズマで既存CCPスモーク相当が
  MCC有効でも NaN なく完走すること
- 既存テストを壊さない

## 制約

- 新しい依存を追加しない。コメントは日本語。ホットループはnumpyベクトル化
- mcc=null なら従来の無衝突動作と完全一致(既存テストで担保)
- 乱数はすべてシード付き rng(再現性)

## 完了条件

`python -m pytest tests/ -q` 全件パス。最後に変更ファイル一覧・テスト結果・
実ファイルのパース結果概要(プロセス数・閾値)のみを報告。
