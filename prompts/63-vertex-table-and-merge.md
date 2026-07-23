# 63: 領域の頂点座標テーブル編集 + 隣接領域のマージ

## 背景 (ユーザー要望)

1. 矩形 (ポリゴン) 領域の編集は現在キャンバス上のドラッグのみ。**頂点座標を表形式で
   表示し、表の値を書き換えたら形状に反映される**ようにしたい。
2. **矩形領域を複数隣接させているとき、領域をマージ (結合) したい。**

## 1. 頂点座標テーブル (FieldPanel の選択領域プロパティ内)

- 対象: polygon を持つ領域 (circle shape 領域は従来の中心/半径入力のまま)。
- 場所: FieldPanel の regions セクション、選択領域のプロパティ (種別・電圧等) の下に
  `<h2>` ではなく小見出し (「頂点座標 [{unit}]」) + テーブル。
- 各行: `#i` / x の CommitNumberInput / y の CommitNumberInput (表示単位は lengthUnit、
  mToUnit/unitToM で変換)。値を確定するとその頂点だけ更新した polygon で
  `editRegionPolygon(id, polygon)` を呼ぶ (App の既存ハンドラ。Undo/Redo 対象になる)。
- 行の追加/削除は不要 (キャンバスの中点グリップ/頂点削除が既にある)。
- App.tsx: FieldPanel へ `editRegionPolygon` を props 追加で渡す。
- スタイル: style.css に頂点テーブル用の小さい CSS (`.vertex-table` 等、
  2列の入力が横に並ぶ compact な行) を追加。入力幅は狭め (~80px)。

## 2. 領域マージ

### ライブラリ

`polygon-clipping@0.15.7` (union のブーリアン演算、型定義同梱) を
frontend に `npm install polygon-clipping` で追加する。

### App.tsx にマージハンドラ

```ts
// 領域 otherId を targetId へマージする (union)。成功時は target の polygon を
// union 結果へ差し替え、other を削除する (プロパティは target 側を維持)。
// 失敗時 (非隣接で1つにならない / 穴ができる) はエラーメッセージ文字列を返す
const mergeRegions = (targetId: string, otherId: string): string | null => { ... }
```

- polygon 取得: 両領域とも polygon を持つこと (circle は「多角形領域のみマージできます」)。
- `union([targetPolygon], [otherPolygon])` → MultiPolygon。
  - 結果が2ポリゴン以上 → 「領域が隣接していないためマージできません」を返す。
  - 結果ポリゴンにリング2本以上 (穴) → 「マージ結果に穴ができるためマージできません」。
- union 結果の外周リングから **共線頂点を除去** する (隣接矩形の辺共有で
  できる余分な中間点を掃除。外積の絶対値 < 1e-12 × スケール^2 程度で判定。
  また polygon-clipping は先頭点を末尾に複製して返すので閉じ点を除去する)。
- commitProject で: target の polygon 差し替え + other 削除 +
  mesh.local_sizes から other の参照を掃除 (deleteRegion と同じ扱い)。
- 選択は target のまま維持。

### UI (FieldPanel の選択領域プロパティ内)

- 頂点座標テーブルの下に「マージ」小見出し。
- 他の polygon 領域 (自分以外) の select + 「この領域とマージ」ボタン。
  対象領域が無ければ非表示。type が異なる領域を選んだ場合もマージ自体は許可するが、
  「※ プロパティ (種別・電圧等) はこの領域側の設定が使われます」のヒントを常時表示。
- 失敗時は返ってきたメッセージを赤字で表示 (ローカル state)。

## 検証

- `cd frontend && npx tsc --noEmit && npx vite build` が通る。
- 手元での動作確認の代わりに、union+共線除去ロジックは小さい単体検証を
  node で一時スクリプト実行して確認する (例: [[0,0],[1,0],[1,1],[0,1]] と
  [[1,0],[2,0],[2,1],[1,1]] の union が 4頂点 [[0,0],[2,0],[2,1],[0,1]] になる、
  離れた矩形はエラー、L字型もOK、など)。検証後スクリプトは削除。

## 注意

- backend には触れない。project スキーマも変更なし (polygon の中身が変わるだけ)。
- コメントは日本語で「なぜ」を書く既存スタイル。
- git commit はしない。
- package.json / package-lock.json の変更もコミット対象になる旨を最終報告に含める。
