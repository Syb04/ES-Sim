# 52: 位相分解アニメーションに |E|・電子温度・電離レートを追加

## バックエンド (実装済み・変更しないこと)

WS done の `cycle` に以下のキーが追加された (いずれも float32、位相ビンごと):

- `e_abs: number[][]` — (bins × 要素数) の |E| [V/m]。**要素値** (phi 等の節点値と違う)
- `te_ev: number[][]` — (bins × 節点数) の電子温度 [eV]
- `ion_rate: number[][]` — (bins × 節点数) の電離レート [m^-3 s^-1]

規格化は時間平均フィールド (fields) と同じ規約。古いバックエンドではこれらのキーが
無い場合がある。

## フロントエンド作業

1. **types.ts**: `PicCycle` に `e_abs?: number[][]`、`te_ev?: number[][]`、
   `ion_rate?: number[][]` を追加 (optional、日本語コメントで要素値/節点値の別を明記)

2. **PicPanel.tsx**:
   - `CyclePicField` 型を `"phi" | "n_e" | "n_i" | "e_abs" | "te_ev" | "ion_rate"` に拡張
   - `CYCLE_FIELD_OPTIONS` に「|E| [V/m]」「電子温度 [eV]」「電離レート [m^-3 s^-1]」を追加
   - アニメーションのフィールドセレクトで、cycle データに該当キーが無い場合
     (古いバックエンド) はその選択肢を無効化または非表示にする
     (`cycle && cycle[value] === undefined` で判定)

3. **App.tsx**: `picCycleView` の構築 (cycleFixedRange の計算と
   `picCycle[cycleField][bin]` の参照) が新フィールドでも動くことを確認する。
   `PIC_FIELD_META` には e_abs/te_ev/ion_rate のメタ (単位・nodeBased) が既にあるので
   流用できるはず。`picCycle[cycleField]` が undefined になり得る型になるので、
   undefined ガード (無ければ view を null に) を入れる

4. e_abs は nodeBased=false (要素値) — CadCanvas の picFieldView は既に要素値
   描画に対応している (時間平均の e_abs 表示で実績あり) ので、メタの nodeBased を
   正しく渡せば描画はそのまま動くはず

## 検証

`cd /home/claude/ES-Sim/frontend && npx tsc --noEmit && npx vite build` が通ること。
コミットはしない (呼び出し元が行う)。
