# 62: 長さ表示単位の切替 (mm ⇔ µm)

## 背景

現在、長さの入出力・表示はすべて mm 固定 (内部データ project は m 単位)。
FN電界放出の検証では µm スケールの形状を扱うため、**UI 全体の長さ単位を
mm / µm で切り替えられるようにしたい** (ユーザー要望)。

## 方針

- 内部データ (project) は従来通り **m のまま**。変換は表示・入力の境界のみ。
- App に表示単位 state `lengthUnit: "mm" | "um"` を追加。切替 select は
  **上部バーの「座標系」の隣**に置く (ラベル「単位」、選択肢 mm / µm)。
- 選択は localStorage (`es-sim-length-unit`) に保存し、起動時に復元する
  (プロジェクトファイルには含めない。backend スキーマは触らない)。
- 単位を切り替えても project の値は変わらない (表示・入力の解釈だけが変わる)。

## units.ts の拡張 (frontend/src/units.ts)

```ts
export type LengthUnit = "mm" | "um";
// 表示ラベル (µ は U+00B5)
export const LENGTH_UNIT_LABEL: Record<LengthUnit, string> = { mm: "mm", um: "µm" };
const FACTOR: Record<LengthUnit, number> = { mm: 1e3, um: 1e6 };
// m -> 表示単位 (mToMm と同じ toPrecision(10) 丸め)
export function mToUnit(m: number, unit: LengthUnit): number;
// 表示単位 -> m
export function unitToM(v: number, unit: LengthUnit): number;
```

既存の `mToMm`/`mmToM` は全呼び出し箇所を mToUnit/unitToM へ移行して**削除**する
(残すと単位切替に追従しない入力欄の混入バグの温床になるため)。

## 変更対象 (「mm」ハードコードの全面置換)

`grep -rn "mm" frontend/src --include="*.tsx" --include="*.ts"` で網羅確認すること。
把握している箇所:

1. **App.tsx** — lengthUnit state (+localStorage 復元/保存 useEffect)、上部バーの単位 select、
   domainW/domainH まわりの mToMm 使用箇所、各パネル・CadCanvas・ProfilePanel への
   `lengthUnit` prop 受け渡し。
2. **FieldPanel.tsx** — ドメイン寸法 幅/高さ [mm]、メッシュサイズ [mm]、領域ローカル
   メッシュサイズ、円領域の中心/半径 [mm] などのラベルと変換。
   ラベルは `[${LENGTH_UNIT_LABEL[lengthUnit]}]` の形に。
3. **ParticlePanel.tsx** — エミッタ p1/p2 [mm]。
4. **GasPanel.tsx** — DSMC 流入境界の線分 p1/p2 [mm]。
5. **PicPanel.tsx** — コレクタ tol など長さ入力があれば同様に (grep で確認)。
6. **ProjectTree.tsx** — メッシュノードの要約 (「4.00mm」表示) を単位追従に。
7. **canvas/CadCanvas.tsx** — `lengthUnit` prop を追加:
   - カーソル座標の読み出し表示 (`(cursor[0] * 1000).toFixed(2)} mm` → 単位追従。
     µm 時は係数 1e6、桁が大きくなるので toFixed(2) のままで良い)
   - ルーラー目盛りラベル (mm 換算で描いている箇所を単位追従に)
   - グリッド自動選択のコメント/ラベル (ステップ選択ロジック自体は 10 の冪で
     単位非依存のはずなので、ラベル表示のみ追従させる)
8. **ProfilePanel.tsx** — 横軸 "s [mm]" とホバー表示を単位追従に (`lengthUnit` prop 追加)。

表示専用の固定文言 (例: CSS の px、ヒント文中の物理説明) は対象外。

## 表示の注意

- mToUnit の丸めは mToMm と同じ `toPrecision(10)`。CommitNumberInput の
  formatNumber と組み合わせて、µm 表示時に 20 mm 域の値が 20000 のような
  表示になるのは許容 (formatNumber が 1e5 以上を指数表記にするので破綻しない)。
- 単位切替時、フォーカス外の入力欄は CommitNumberInput の value 同期
  (useEffect) で自動的に新単位の値へ更新される — 追加対応不要のはずだが確認する。

## 検証

- `cd frontend && npx tsc --noEmit && npx vite build` が通ること。
- `grep -rn "mToMm\|mmToM" frontend/src` が 0 件になること。
- 残存する「mm」ハードコード表示がないこと (grep で確認、CSS 等は除く)。

## 注意

- コメントは日本語で「なぜ」を書く既存スタイル。
- backend には一切触れない。
