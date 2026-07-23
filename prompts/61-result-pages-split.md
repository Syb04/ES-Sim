# 61: 結果ノードのインスペクタを「結果専用ページ」に分離

## 背景

prompts/60 の3カラム化で、結果セクションの「PIC 結果」「ガス流れ結果」「粒子軌道」
ノードはスタディノードと同じインスペクタページを共有しており、設定UIまで表示されて
しまっている (ユーザー指摘)。結果ノードにはシミュレーション結果だけを表示したい:

> PIC結果の中にもPICの設定が入っています。ここにはシミュレーション結果
> (電位、電場、電子密度、イオン密度、電子温度、電離レートの時間平均とアニメーション) を入れてほしい

## 方針

ParticlePanel / PicPanel / GasPanel に `mode?: "all" | "setup" | "results"` prop を追加
(既定 "all" = 従来通り全表示で後方互換)。App.tsx では各パネルを2インスタンス mount する:

- スタディノード (study-trace / study-pic / study-gas) → `mode="setup"`
- 結果ノード (result-trace / result-pic / result-gas) → `mode="results"`

どちらも display:none 切替で mount したままにする (WebSocket・チャート履歴は App 側
state なので2インスタンスでも共有される。パネル内ローカル state はモードごとに独立で問題ない)。

## PicPanel の分割 (frontend/src/panels/PicPanel.tsx)

- **setup**: PIC: 初期プラズマ / PIC: 注入 / PIC: MCC(衝突) / FN電界放出 /
  PIC: 計算設定 / PIC: IEDF/IADF コレクタの**一覧編集部分** (追加ヒント・一覧・削除) /
  実行ボタン群 (PIC開始・停止・続きから実行 + 説明文) / started の警告 /
  PIC: 診断 (+ 履歴チャート — 実行監視なのでスタディ側) / PICエラー
- **results**: PIC: 結果フィールド (時間平均の 結果表示 select = 電位φ/電場|E|/電子密度/
  イオン密度/電子温度/電離レート/ライブ + 対数スケール) / PIC: 周期アニメーション
  (PicCyclePlayer) / コレクタの**結果表示部分** (表示コレクタ select・記録サンプル数・
  IEDF/IADF ヒストグラム・IAEDF・CSV保存) / PICエラー
- results モードで `fields` も `cycle` も無い (未実行) 場合は
  「PIC計算が未実行です。スタディ「PIC-MCC」から実行してください。」の hint を表示。
- 「PIC: IEDF/IADF」セクションは一覧編集 (setup) と結果表示 (results) にまたがるので、
  h2 見出しは両モードで出し、中身をモードで出し分ける。

## GasPanel の分割 (frontend/src/panels/GasPanel.tsx)

- **setup**: ガス流れ (DSMC) 有効化 / ガス種 (VHS) / 境界条件 (domain 外周) /
  初期条件・計算設定 / 実行・停止ボタン / 進捗 / エラー
- **results**: 結果サマリ + 結果表示 select (n/T/|u|/p) + 対数スケール / エラー
- results モードで result が無い場合は
  「DSMC計算が未実行です。スタディ「ガス流れ DSMC」から実行してください。」の hint。

## ParticlePanel の分割 (frontend/src/panels/ParticlePanel.tsx)

- **setup**: 粒子種 / エミッタ / FN電界放出 / 積分設定 / Trace ボタン
- **results**: 「軌道を表示」チェック + トレース結果サマリ (+ FN総放出電流)
- results モードで traceResult が無い場合は
  「トレースが未実行です。スタディ「粒子軌道追跡」から実行してください。」の hint。

## App.tsx の変更

- showParticlePage / showPicPage / showGasPage を study 用と result 用に分離
  (例: showPicSetupPage = activeNode==="study-pic"、showPicResultsPage = activeNode==="result-pic")。
- 各パネルを mode="setup" と mode="results" の2インスタンスで mount
  (props は同一のものを渡す。コールバックも共有)。
- gasFieldView の表示条件 (study-gas || result-gas) は現状のまま。

## 検証

`cd frontend && npx tsc --noEmit && npx vite build` が通ること。
分割後も setup+results を合わせると従来の全機能・全表示が揃っていること
(欠落・重複置き忘れがないか、旧レンダリング内容と突き合わせて確認する)。

## 注意

- ロジック (state・ハンドラ) は一切変えない。JSX の出し分けのみ。
- コメントは日本語で「なぜ」を書く既存スタイル。mode 出し分けには
  `const show = (m: "setup" | "results") => mode === "all" || mode === m` のような
  小さいヘルパを各パネル内に置くと差分が読みやすい。
