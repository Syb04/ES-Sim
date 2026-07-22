# サブエージェント指示: IEDF/IADF のUI(フロントエンド)

対象リポジトリ: `/home/claude/ES-Sim/frontend`(npm install 済み)

バックエンドのスキーマ契約は `/home/claude/ES-Sim/prompts/30_backend_iedf.md` を参照し
型を一致させること。types.ts / App.tsx / canvas/CadCanvas.tsx / panels/PicPanel.tsx /
panels/ProfilePanel.tsx(canvas直描きグラフの既存例)を読んでから着手すること。

## やること

1. **types.ts**: `PicCollector`(p1/p2/tol)を `PicSettings.collector?: PicCollector | null` に、
   `CollectorResult`(count/total_weight/energies_ev/angles_deg/weights/truncated)を
   `PicDoneMsg.collector?: CollectorResult` に追加

2. **コレクタ配置ツール**(CadCanvas): ツール `"collector"` を追加(ツールバーにボタン
   「コレクタ」)。プロファイル線と同じ2点クリックUX。配置済みコレクタは黄系の太めの線分+
   両端マーカーで常時オーバーレイ表示。配置すると PIC 設定の collector が更新され、
   PICタブに切替

3. **PICタブに「IEDF/IADF」セクション**:
   - コレクタの p1/p2 [mm] 数値表示・判定距離 tol [mm](空欄=メッシュサイズ)・クリアボタン
   - done で collector を受信したら、**IEDF**(横軸 エネルギー [eV])と **IADF**
     (横軸 入射角 [deg]、-90〜90)の2つのヒストグラムを canvas 直描きで表示
     (重み付きカウント。ProfilePanel のグラフ実装を参考に、軸目盛り・ホバー値読み付き)
   - ビン数入力(既定 60、変更で再ビニング)。サンプル数・総実イオン数・truncated 警告を表示
   - 「CSV保存」ボタン: energy_ev, angle_deg, weight の生サンプルをダウンロード
   - 新しい実行開始でリセット

4. パネルが縦に伸びすぎないよう、ヒストグラムは高さ ~130px 程度×2段で良い

## 制約

新しい npm 依存なし。日本語コメント。TS strict 維持。既存機能を壊さない。

## 完了条件

`cd /home/claude/ES-Sim/frontend && npx tsc && npx vite build` 成功。
変更ファイル一覧と操作方法の要約のみ報告。
