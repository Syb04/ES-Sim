# サブエージェント指示: PIC結果フィールドのプロットUI(フロントエンド)

対象リポジトリ: `/home/claude/ES-Sim/frontend`(npm install 済み)

バックエンドのスキーマ契約は `/home/claude/ES-Sim/prompts/26_backend_pic_fields.md` を参照し、
型を一致させること。types.ts / App.tsx / canvas/CadCanvas.tsx / panels/PicPanel.tsx を
読んでから着手すること。

## やること

1. **types.ts**: `PicFields`(phi / e_abs / n_e / n_i / te_ev / ion_rate / avg_steps)を追加。
   `PicDoneMsg` に `fields?: PicFields` を追加。`PicSettings.avg_steps?: number | null` を追加

2. **PIC設定UI**: 「平均ステップ数(空欄=最後の25%)」入力を計算設定に追加

3. **結果フィールドの選択と描画**:
   - done 受信後、PICタブに「結果表示」セレクトを表示:
     `ライブ(最終フレーム) / 電位 [V] / |E| [V/m] / 電子密度 [m^-3] / イオン密度 [m^-3] / 電子温度 [eV] / 電離レート [m^-3 s^-1]`
   - 選択したフィールドを CadCanvas のカラーマップで描画(既存の viridis / カラーバー経路を再利用。
     phi/n_e/n_i/te_ev/ion_rate は**節点値**(要素は3節点平均で塗る)、e_abs は**要素値**)
   - カラーバーに単位を表示。**対数スケール切替チェックボックス**を追加
     (密度・電離レート向け。値≤0 は最小正値にクランプしてから log。全て≤0 なら線形にフォールバック)
   - 実行中は従来通りライブ表示。新しい実行を開始したら結果フィールド表示はリセット
   - 粒子ドットのオーバーレイは「ライブ」選択時のみ表示

4. **実装の置き場所**: CadCanvas には「表示するフィールド(値配列・節点/要素の別・単位・
   対数フラグ)」を1つの prop(例 `picFieldView`)として渡す形に整理し、描画分岐の散乱を避ける

## 制約

新しい npm 依存なし。日本語コメント。TS strict 維持。既存機能(ライブ表示・Solve結果表示・
プロファイル等)を壊さない。

## 完了条件

`cd /home/claude/ES-Sim/frontend && npx tsc && npx vite build` 成功。
変更ファイル一覧と操作方法の要約のみ報告。
