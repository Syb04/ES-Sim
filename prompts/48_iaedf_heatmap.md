# 48: IAEDF 2Dヒートマップの追加 (フロントエンドのみ)

## 背景

PIC のコレクタ結果 (`PicCollectorResult`) には吸収イオンのサンプル列
`energies_ev[]` / `angles_deg[]` / `weights[]` が届いており、現在
`frontend/src/panels/PicPanel.tsx` の `HistogramChart` で IEDF (エネルギー1D) と
IADF (角度1D) を表示している。これに IAEDF (Ion Angular-Energy Distribution
Function) の 2D ヒートマップを追加する。バックエンド変更は不要。

## やること (PicPanel.tsx)

1. 新コンポーネント `IaedfChart` を PicPanel.tsx 内に追加 (HistogramChart の下辺りID):
   - 横軸: 入射角 [deg]、固定範囲 [-90, 90]
   - 縦軸: エネルギー [eV]、範囲はサンプルの min/max (サンプル0件なら 0〜1)。
     下から上へ増加 (原点は左下)
   - ビニング: `bins × bins` の重み付き2Dカウント (bins は既存の `collectorBins` を共用)
   - カラーマップ: 確率密度 (= ビンの重み付きカウント / 最大値で正規化)。
     viridis 風の連続カラーマップを小さな制御点配列 + 線形補間で実装する
     (例: [68,1,84]→[59,82,139]→[33,145,140]→[94,201,98]→[253,231,37])。
     カウント 0 のビンは背景色 (#0e1116 など、既存ダークテーマに合わせる)
   - canvas 直描き。既存 HistogramChart と同じ描画スタイル (枠 #363c48、
     9px 目盛りフォント、padL≈44) に合わせ、軸目盛り (横: -90/0/90、縦: min/中央/max) を描く
   - 右側か下に細いカラーバー (0〜最大カウント) を描き、最大値を toExponential(2) で表示
   - ホバーで該当ビンの (角度範囲, エネルギー範囲, 重み付きカウント) を
     既存 HistogramChart のホバー表示と同じ流儀で表示
   - 「対数」チェックボックス (コンポーネント内 state) で色を log10 スケールに切替
     (0 ビンは背景色のまま。log時は正の最小値〜最大値で正規化)

2. 表示位置: IADF ヒストグラムの直後に
   `<p className="hint">IAEDF (角度×エネルギー、カラー = 確率密度)</p>` と共に追加。
   高さは 220px 程度 (1Dヒストグラムより大きめの正方形寄り)

3. 既存の IEDF/IADF・CSV保存の挙動は変えない

## 検証

`cd /home/claude/ES-Sim/frontend && npx tsc --noEmit && npx vite build` が通ること。
コミットはしない (呼び出し元が行う)。
