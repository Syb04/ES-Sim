# サブエージェント指示: 対称/周期境界のUI(フロントエンド)

対象リポジトリ: `/home/claude/ES-Sim/frontend`(npm install 済み)

バックエンドのスキーマ契約は `/home/claude/ES-Sim/prompts/22_backend_bc_overlap.md` §A を参照し
型を一致させること。現状の types.ts / panels/FieldPanel.tsx / App.tsx / canvas/CadCanvas.tsx を
読んでから着手すること。

## やること

1. **types.ts**: `BoundaryCondition.type` を `"dirichlet" | "symmetry" | "periodic"` に拡張

2. **FieldPanel の境界条件UI**: 各辺(下/右/上/左)のセレクトを4択に:
   `なし(Neumann) / Dirichlet / 対称(粒子反射) / 周期`
   - Dirichlet 選択時のみ電圧・RF・γ入力を表示(従来通り)
   - **周期**を選ぶと**対辺**(下↔上、左↔右)も自動的に周期になり、スキーマ上は
     `{ edges: [i, 対辺], type: "periodic" }` の1エントリにまとめる。
     どちらかを別タイプへ変えたら両方解除。対辺が Dirichlet 等で使用中なら上書き確認は不要
     (単純に置き換えで良いが、状態が矛盾しないよう App 側のハンドラで一元管理する)
   - 対称・周期では電圧等の入力は非表示

3. **キャンバスのBC可視化**: domain 外周の各辺を BCタイプ別の色でオーバーレイ描画:
   Dirichlet=オレンジ実線(既存の輪郭より太め)、対称=緑破線、周期=紫破線(対辺で同色)、
   なし=現状のまま。ツールバー付近かキャンバス隅に小さな凡例(色と名称)を表示

4. 矩形/ポリライン/円ツールで**外枠に重なる・はみ出す図形も描けること**を確認
   (フロント側にバリデーションがあれば「domain外にはみ出した部分は解析時にクリップされます」の
   ヒント表示に変える。作図自体は妨げない)

## 制約

- 新しい npm 依存を追加しない。コメントは日本語。TS strict 維持。既存機能を壊さない
- 旧形式プロジェクト(type:"dirichlet" のみ)の読込互換を維持

## 完了条件

`cd /home/claude/ES-Sim/frontend && npx tsc && npx vite build` 成功。
最後に変更ファイル一覧と操作方法の要約のみを報告。
