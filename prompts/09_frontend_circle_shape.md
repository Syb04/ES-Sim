# サブエージェント指示: 円領域のパラメトリック化(フロントエンド)

対象リポジトリ: `/home/claude/ES-Sim/frontend`(npm install 済み)

## 背景

現状、円ツールは48角形の polygon として領域を登録している。バックエンドが
「中心+半径」のパラメトリック円(メッシュ生成時にメッシュサイズ連動で多角形化)に対応するため、
フロントも circle shape で保存するよう変更する。必ず現状のコードを読んでから着手すること。

## スキーマ契約(バックエンドと共通)

```ts
// types.ts の Region に追加。polygon / shape はどちらか一方のみ
interface CircleShape { kind: "circle"; center: Point; radius: number; }
interface Region { id: string; type: RegionType; polygon?: Point[]; shape?: CircleShape; ... }
```

## やること

1. **types.ts**: 上記の型変更(`polygon` を optional に、`shape?: CircleShape` 追加)。
   既存コードで `region.polygon` を直接参照している箇所が多いので、
   「表示用ポリゴン」を返すヘルパー(例 `regionOutline(region): Point[]` — circle は64分割の表示用近似)
   を用意して置き換えると安全
2. **円ツール**: 確定時に polygon ではなく shape(中心・半径。グリッドスナップ適用)で領域を追加
   (App の追加ハンドラを拡張。既存の polygon 領域の読込・表示は従来通り動くこと)
3. **CadCanvas の circle 対応**:
   - 描画: `ctx.arc` による真円描画(輪郭色は種別色、選択ハイライトも円で)
   - 選択ヒットテスト: 中心距離 ≤ r+許容 or 円周から6px以内。複数命中時の面積は πr² で比較
   - 移動: ドラッグ/矢印キーで center を平行移動(既存の領域移動と同じ履歴挙動)
   - グリップ: 円周上の1点(角度0°)に半径ハンドルを表示し、ドラッグで半径変更
     (スナップ適用、Esc キャンセル、確定で履歴1エントリ)。頂点/中点ハンドルは円には出さない
4. **サイドパネル**: 選択中領域が circle の場合、中心X/Y・半径の数値入力(既存の CommitInput 方式、
   履歴連動)を表示。polygon 領域は従来通り
5. 保存/読込・Solve・プロファイル・可視化が shape 領域込みで動くこと(リクエストは型通り送るだけ)

## 制約

- 新しい npm 依存を追加しない。コメントは日本語。TS strict 維持
- 既存機能(スケッチ、移動、Undo/Redo、グリップ、プロファイル、ルーラー)を壊さない

## 完了条件

`cd /home/claude/ES-Sim/frontend && npx tsc && npx vite build` 成功。
最後に変更ファイル一覧と操作方法の要約のみを報告。
