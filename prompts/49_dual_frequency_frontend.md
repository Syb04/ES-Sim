# 49: デュアル周波数 RF 電圧のフロントエンド UI

## 背景

バックエンドは `voltage_rf` (BoundaryCondition と conductor Region) に
**単一 `VoltageRF` オブジェクトまたはそのリスト** を受け付けるようになった
(V(t) = V_dc + Σ_k A_k sin(2π f_k t + φ_k)、デュアル周波数 CCP 用)。
位相分解アニメーションの基本周波数は全成分の最小周波数になる。
フロントエンドの RF 編集 UI を複数成分対応にする。バックエンドは変更しないこと。

## 現状 (対象ファイル)

- `frontend/src/types.ts`: `VoltageRf` 型、`Region.voltage_rf?: VoltageRf`、
  `DirichletBC.voltage_rf?: VoltageRf`
- `frontend/src/panels/FieldPanel.tsx`: 境界エッジの BC 編集 (RF有効チェック +
  振幅/周波数/位相の3入力、`setEdgeVoltageRf`) と conductor 領域の RF 編集
  (`updateRegion` 経由)。既定値 `DEFAULT_VOLTAGE_RF = {amplitude:100, freq_hz:13.56e6, phase_deg:0}`
- `frontend/src/App.tsx`: `edgeState()` が `voltageRf?: VoltageRf` を返し、
  `setEdgeVoltageRf(edgeIndex, voltage_rf | undefined)` が BC を更新

## やること

1. **types.ts**:
   - `Region.voltage_rf?: VoltageRf | VoltageRf[]`、`DirichletBC.voltage_rf?: VoltageRf | VoltageRf[]` に変更
   - 正規化ヘルパを追加してエクスポート:
     ```ts
     export function rfComponents(rf: VoltageRf | VoltageRf[] | null | undefined): VoltageRf[] {
       if (!rf) return [];
       return Array.isArray(rf) ? rf : [rf];
     }
     ```

2. **FieldPanel.tsx** (境界エッジと conductor 領域の両方):
   - RF有効チェックはそのまま (オンで成分1個から開始)
   - 成分ごとに「成分k」見出し + 振幅[V]/周波数[Hz]/位相[deg] の入力行 + 成分削除ボタン (×)
   - 「+ RF成分を追加」ボタンで成分追加 (追加時の既定は {amplitude:100, freq_hz:13.56e6, phase_deg:0}。
     2成分目以降の追加時は周波数を変えた例として freq_hz: 2e6 を既定にすると親切)
   - 成分が1個になったら削除ボタンで RF ごと無効化してよい (または最後の1個は削除でチェックオフと同じ挙動)
   - 保存形式: 常に配列で持ってよい (バックエンドは単一/配列どちらも受ける。
     旧ファイル読込時は rfComponents() で正規化)
   - 編集は既存の `setEdgeVoltageRf` / `updateRegion` の型を `VoltageRf[] | undefined` を渡せるように
     広げる (App.tsx 側の型も合わせて変更)

3. **App.tsx**: `edgeState` / `setEdgeVoltageRf` の型を `VoltageRf | VoltageRf[]` 対応に。
   既存の読込正規化 (loadProject) は素通しで良い (rfComponents で UI 側が吸収)

4. 表示崩れしないよう既存の `.field` 行スタイルを流用。コメントは日本語

## 検証

`cd /home/claude/ES-Sim/frontend && npx tsc --noEmit && npx vite build` が通ること。
コミットはしない (呼び出し元が行う)。
