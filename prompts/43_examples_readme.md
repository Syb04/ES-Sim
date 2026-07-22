# サブエージェント指示: サンプルプロジェクト追加 + README最新化

対象リポジトリ: `/home/claude/ES-Sim`(バックエンド依存インストール済み)

## A. サンプルプロジェクト(examples/ に追加)

すべて**実際に API で実行して動作確認**してから納品すること
(TestClient で /solve、/trace、PIC は run_batch 短縮実行)。

1. **`ccp_demo.json`** — 平面2DのRF CCPデモ(PIC一式のショーケース):
   - 20mm ギャップ相当の矩形 domain、左辺 RF (±150V/13.56MHz)・右辺 GND、上下は対称境界
   - 初期プラズマ (Ar+, 1e14 m^-3, Te 2eV)、MCC 有効
   - **断面積は tests/data/synthetic_electron.txt / synthetic_ion.txt をパースして埋め込む**
     (LXCat実データは再配布不可のため。プロジェクト内の mcc.gas.name を "Ar(合成断面積デモ)" とし、
     README にも「実計算では LXCat からダウンロードした実データを読み込むこと」と明記)
   - 両電極にコレクタ2本 (C1/C2)、phase_bins 40、n_steps 2000 程度の現実的な設定
2. **`egun_rz.json`** — 軸対称 (rz: 下辺が軸) の簡易電子銃デモ:
   - カソード(-2kV相当の電位配置でも、接地カソード+正の陽極でも良い。物理的に妥当な構成)
   - 集束電極っぽい形状を1つ入れ、エミッタ(軸近傍から電子を発射)で /trace すると
     ビームが加速・集束される様子が見えること(実行して軌道が陽極側へ到達することを確認)
3. 既存の parallel_plates.json / coaxial.json はそのまま

## B. README.md の最新化

現状の README は進捗記載がフェーズ3途中で止まっている。全面的に整理:

- 冒頭: 一段落の説明+主要機能の要約(CAD/静電場FEM/軌道追跡/PIC-MCC/軸対称/構造格子/
  IEDF-IADF/周期アニメ/続き実行/検証済み: Turnerベンチマーク2%以内)
- セットアップ手順を最新化(dialog/fs プラグイン導入後の npm install 必須を明記)
- examples/ の各サンプルの説明(何が見られるか、どう開くか)
- 検証について docs/VALIDATION.md と docs/validation_report.html への参照
- 機能一覧はチェックリストの羅列をやめ、カテゴリごとの簡潔な表または箇条書きに再構成
- prompts/ ディレクトリの説明(開発時のサブエージェント指示書)
- 既知の制約(PICは軸対称未対応、構造格子は矩形domainのみ、無衝突では放電が減衰、など)
- ロードマップ(残: Turner ケース2-4、CuPy、DXFインポート等)

## 完了条件

- 3サンプルすべての動作確認ログ(実行結果の要約)
- README が現状と矛盾しないこと
- `python -m pytest tests/ -q` 既存全件パス(コード変更はしないはずだが確認)
変更ファイル一覧と動作確認結果のみ報告。
