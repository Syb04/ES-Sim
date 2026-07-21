# サブエージェント指示: 同軸円筒のメッシュ収束検証

対象リポジトリ: `/home/claude/ES-Sim/backend`(依存インストール済み、システムPythonで動く)

ES-Sim の静電場FEMソルバー(P1三角形要素)の精度検証。仕様書 §6 の検証ケース
「同軸円筒(2D断面): V(r) の対数分布(メッシュ収束で確認)」を実施する。
既存コード(schema / meshing / fem)を読んでから着手すること。

## 問題設定

- 中心 (0,0)、内導体半径 a=0.01 m(電位 V1=100 V)、外導体半径 b=0.04 m(電位 0 V)
- 解析解: V(r) = V1 · ln(b/r) / ln(b/a)、静電容量 C = 2πε0 / ln(b/a) [F/m]
- ジオメトリ表現: domain は半径 b の**256角形**(全外周エッジを Dirichlet 0V に)、
  内導体は半径 a の**256角形**の conductor 領域(V1)
  ※多角形近似誤差を FEM 誤差より十分小さくするため分割数は多めにする

## やること

1. **`verification/coax_convergence.py`(新規)**
   - 円ポリゴン生成・プロジェクト構築をコードで行い、メッシュサイズを
     [0.008, 0.004, 0.002, 0.001] と変えて solve
   - 各サイズで以下を算出し表として print:
     - 節点電位の相対 L2 誤差(a ≤ r ≤ b の節点のみ対象)
     - エネルギーから求めた静電容量 C = 2W/V1² と解析値との相対誤差
   - 誤差の収束次数(連続する2ケースの誤差比から log2 で推定)も表示
   - 結果を `verification/coax_results.md` に Markdown 表として書き出す
   - `python verification/coax_convergence.py` で実行できること
2. **`tests/test_coax.py`(新規)**
   - メッシュサイズ 0.002 の1ケースで、相対L2誤差 < 1%、容量の相対誤差 < 1% を assert
   - 実行時間を抑えるためテストは1ケースのみとする
3. `examples/coaxial.json`(新規)— GUI から開ける同サイズの同軸プロジェクト
   (多角形は 64 角形程度に落として良い。mesh size 0.002)。
   coax_convergence.py から json.dump で生成するのがよい

## 制約

- 新しい依存パッケージを追加しない(numpy/scipy/gmsh のみで完結)
- 既存コードは変更しない(必要なら理由を報告に書く)
- コメント・出力は日本語で

## 完了条件

`python verification/coax_convergence.py` が正常終了して coax_results.md が生成され、
`python -m pytest tests/ -q` が全件パスすること。
最後に変更・追加ファイル一覧と収束表の要約のみを報告すること。
