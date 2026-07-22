# サブエージェント指示: Turner CCPベンチマーク検証の準備(2d3v化・鏡面反射・検証スクリプト)

対象リポジトリ: `/home/claude/ES-Sim/backend`(依存インストール済み)

ES-Sim の FEM-PIC を、PIC-MCC の標準ベンチマーク **Turner et al., Phys. Plasmas 20, 013507 (2013)**
のケース1(He CCP)と定量比較できるようにする。pic.py / mcc.py / particles.py / schema.py を
熟読してから着手すること。基準データと断面積は取得済み:
`verification/data/turner/`(lase-unb/ccp-benchmark 由来)

- `Elastic_He.csv` `Excitation1_He.csv`(閾値19.82eV)`Excitation2_He.csv`(20.61eV)
  `Ionization_He.csv`(24.59eV)— 電子/He、Biagi 7.1、`;`区切り (energy_eV; sigma_m2)
- `Isotropic_He.csv` `Backscattering_He.csv` — He+/He、Phelps、**重心系エネルギー**参照
- `Benchmark_A.csv` — ケース1の基準解。空白区切り129行×7列。列0: x[m](0〜0.067)、
  列1: 電子密度[m^-3](ピーク1.363e14)、列4: イオン密度[m^-3](ピーク1.405e14)。時間平均プロファイル

## ケース1のパラメータ(Turner Table 1)

ギャップ L=6.7e-2 m、He 300K、ガス密度 n_g=9.64e20 m^-3、V(t)=450·sin(2πft) V(片側、対向GND)、
f=13.56 MHz、初期プラズマ密度 n0=2.56e14 m^-3(電子Te=30000K、イオンTi=300K、He+ 質量 6.67e-27 kg)、
セル 128(Δx=L/128)、dt=1/(400f)、総ステップ 512000(1280 RF周期)、
密度は最後の12800ステップ(32周期)の時間平均。SEE・電子反射なし(壁は完全吸収)。
電離後の余剰エネルギーは**散乱電子と生成電子で等分**。電子散乱は等方。

## やること

### 1. PIC の速度3成分化(2d3v)

文献は 1d3v。現在の2成分速度では衝突後のエネルギー分配が合わないため、
**PicSimulation の粒子速度を (n,3) に拡張**する(位置は2Dのまま。E は vx, vy のみに作用)。

- 装荷・注入時の Maxwell 速度は3成分で抽選
- 運動エネルギー・診断は3成分で評価
- mcc.py の散乱を**3D等方散乱**に変更(cosχ一様、方位角一様)。電子弾性の
  エネルギー損失 ΔE = 2(m/M)(1−cosχ)E、励起・電離も3Dで
- イオンの等方散乱(COM系3D等方)・電荷交換も3成分で
- SEE 電子の放出は法線方向+接線2成分0で良い
- **フェーズ2の particles.py(/trace)は変更しない**(2Vのまま)。pic.py が particles.py の
  幾何ユーティリティ(walk等)を再利用している部分は位置(2D)のみなので影響しないはず

### 2. 横方向境界の鏡面反射

2Dストリップで1D問題を模擬するため、`PicSettings` に `reflect_edges: list[int] = []` を追加。
指定した外周エッジ(domain矩形のエッジ番号)に粒子が到達したら吸収せず**鏡面反射**
(法線速度成分を反転し、位置を境界内へ折り返す)。当該エッジは境界条件なし(Neumann)想定。
壁カウンタには含めない。

### 3. MCC のベンチマーク互換オプション(`MccSettings` に追加)

- `ionization_split: "half" | "random" = "half"`(既定を等分に変更。既存テストが
  分配方式に依存していれば修正)
- `ion_energy_frame: "com" | "lab" = "lab"`(イオン断面積参照エネルギー。
  Turner用データは "com": E = ½μg²、μ=m_i·m_g/(m_i+m_g))

### 4. 密度プロファイルの時間平均出力

`PicSimulation` に節点密度アキュムレータを追加: `enable_density_accum(start_step)` 以後、
毎ステップ種ごとに P1 重みで節点へ重みを散布し、`averaged_density()` で
[m^-3](節点集中面積 = Σ隣接要素面積/3 で割る)を返す。

### 5. 検証スクリプト `verification/turner_case1.py`

- CSVから断面積を読み(XsProcess 形式に変換)、薄いストリップ(L×2mm、メッシュサイズ
  ~0.52mm、上下エッジ reflect)でケース1を構築し、`--steps` 引数(既定512000)で実行
- 最後の32周期で密度を時間平均 → y方向を平均して x の1Dプロファイル化 →
  `Benchmark_A.csv` の列1(n_e)・列4(n_i)と比較:
  中心密度・ピーク密度の相対差、プロファイル全体の相対L2偏差を print し、
  `verification/turner_case1_result.md` と比較プロット `turner_case1.png`(matplotlib、
  なければ pip install)に保存。`--steps` を短くしたスモーク実行もできること
- 進捗を定期的に print(周期番号、粒子数、経過秒)。結果はJSONでも保存(再解析用)

### 6. テスト

- 既存テスト全件パス(3成分化に伴う修正は許可: 例 プラズマ振動テストの初期条件)
- 追加: 鏡面反射(反射エッジで粒子数が保存される)、電離等分配(2電子のエネルギー和=残余)、
  COMエネルギー参照の単体テスト
- `python verification/turner_case1.py --steps 4000` のスモークが数分で正常終了すること

## 制約

- 新しい依存を追加しない(matplotlib は検証スクリプト内でのみ使用可、要インストールなら
  pip install --break-system-packages)。コメントは日本語。numpyベクトル化維持
- フロントとのWSプロトコル・既存スキーマの後方互換を保つ(追加のみ)

## 完了条件

`python -m pytest tests/ -q` 全件パス + スモーク実行成功。
最後に変更ファイル一覧・テスト結果・スモーク実行の観察(密度が維持/成長しているか)のみを報告。
