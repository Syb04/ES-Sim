# サブエージェント指示: 軸対称 (r-z) モードのUI(フロントエンド)

対象リポジトリ: `/home/claude/ES-Sim/frontend`(npm install 済み)

バックエンドの契約は `/home/claude/ES-Sim/prompts/39_backend_axisymmetric.md` を参照
(coord: "xy"|"rz"、rz では x=z・y=r・下辺 y=0 が対称軸、PIC は未対応)。
types.ts / App.tsx / panels/FieldPanel.tsx / canvas/CadCanvas.tsx を読んでから着手すること。

## やること

1. **types.ts**: `Project.coord?: "xy" | "rz"` を追加

2. **FieldPanel ジオメトリセクション**: 「座標系」セレクト(平面2D / 軸対称 r-z)。
   切替は commitProject 経由(Undo対象・結果破棄)。rz 選択時:
   - 幅/高さのラベルを「長さ z [mm]」「半径 r [mm]」に変更
   - 境界条件の辺ラベルを rz 用に変更(下 = 「対称軸 (r=0)」として**セレクトを無効化**し
     固定表示。上 = r=R、左/右 = z=0 / z=L)。下辺に既存のBC設定があれば座標系切替時に除去
   - ヒント「軸対称モードでは下辺が対称軸になります。PICは未対応です」

3. **CadCanvas**: rz モードでは座標表示・ルーラーのラベルを z / r 表記に
   (例 左下の座標表示を「z: .. mm  r: .. mm」)。対称軸(下辺)を一点鎖線風の
   見た目(細い破線+シアン系)でオーバーレイ表示

4. **App**: rz のとき PIC タブに「軸対称モードでは PIC は利用できません」の注記を出し、
   PIC開始/続き実行ボタンを無効化。静電場の解析結果サマリのエネルギー単位を
   coord に応じて [J/m] / [J] と表示切替

## 制約

新しい npm 依存なし。日本語コメント。TS strict 維持。既存機能(xyモード)を壊さない。

## 完了条件

`cd /home/claude/ES-Sim/frontend && npx tsc && npx vite build` 成功。
変更ファイル一覧と操作方法の要約のみ報告。
