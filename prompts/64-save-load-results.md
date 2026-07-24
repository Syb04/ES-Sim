# 64: 計算結果の保存・読込

## 背景 (ユーザー要望)

「計算結果を保存・読込する機能を追加してほしい」。
現在の保存/読込はプロジェクト (設定・ジオメトリ) のみで、計算結果
(静電場FEM / 粒子トレース / PIC / DSMC) はアプリを閉じると失われる。

## 方針

- **結果はプロジェクトと同じ1ファイルに同梱**する (「結果付き保存」)。
  結果はジオメトリ・設定と整合していないと意味がないため、別ファイルにしない。
- 既存の「保存」(設定のみ) はそのまま残し、上部バーに **「結果付き保存」** ボタンを追加。
- 「読込」は両形式を自動判別: `results` キーがあれば結果も復元する。
- backend には触れない (`results` はフロント専用フィールド。solve/trace 等の API へ
  送る project には含めない — 送信時は現状どおり project state を使うので自然に含まれない。
  ただし保存された結果付きファイルを読み込んだ project state に `results` が
  紛れ込まないよう、読込時に project 部分と results 部分を分離すること)。

## types.ts

```ts
// 結果付き保存ファイルに同梱する計算結果一式 (フロント専用、backend へは送らない)
export interface ResultsBundle {
  version: 1;
  solve?: SolveResult | null;
  mesh?: MeshResult | null;      // Mesh ボタン単独実行の結果
  trace?: TraceResult | null;
  pic?: {
    started: PicStartedMsg;       // mesh を含む (フィールド描画に必須)
    frame: PicFrameMsg | null;    // 最終フレーム (ライブ表示・診断の復元用)
    history: PicDiag[];
    fields: PicFields | null;
    cycle: PicCycle | null;
    collectors: PicCollectorResult[];
  } | null;
  gas?: DsmcResult | null;
}
```

## App.tsx

### 保存

```ts
// 結果付き保存: プロジェクトに results を同梱して1ファイルで保存する。
// 結果 (特に PIC の cycle) は大きくなりうるため、整形なし (compact) で書き出す
const saveProjectWithResults = () => { ... }
```

- ベースは saveProject と同じ toSave (particles/pic 合成) に `results: ResultsBundle` を追加。
- pic 結果は picStarted がある場合のみ同梱 (started が無いと描画できないため)。
- 既定ファイル名 `project_results.json`。
- ボタンは結果が何も無いとき disabled (title で理由を表示)。

### 読込 (loadProject 拡張)

- `obj.results` があれば、commitProject (結果クリア) の**後**に各 state を復元:
  - setResult / setMeshResult / setTraceResult / setGasResult
  - pic: setPicStarted / setPicFrame / setPicHistory / setPicFields /
    setPicCycle / setPicCollectors。
    加えて setPicResultField("live") 等の表示系は既定へ、
    **setPicContinueReady(false)** (サーバーに状態が無いので続き実行は不可)、
    setPicProjectChangedSinceRun(true)。
  - cycle 再生系 (playing/binIndex/viewActive) は既定値へリセット。
- project 部分を state に入れる際、`results` フィールドは取り除く
  (`const { results, ...projectOnly } = obj` の要領。以後 solve 等の API へ
  送られる project に紛れないようにする)。
- 旧形式 (results なし) は従来どおり。

### ツリー・ステータス

- 復元後は既存の派生ロジックだけで ✓完了 バッジ・結果表示が機能するはず
  (追加実装不要のはずだが確認する)。

## UI 文言

- ボタン: 「結果付き保存」 title=「プロジェクト設定に加えて計算結果 (FEM/トレース/PIC/DSMC) も1ファイルに保存します。PIC結果を含むとファイルが大きくなることがあります」
- 読込で結果を復元した場合、特別な通知は不要 (ツリーのバッジと結果ページで分かる)。

## 検証

- `cd frontend && npx tsc --noEmit && npx vite build` が通ること。
- ラウンドトリップの簡易検証: ResultsBundle の保存 JSON を仮データで組み立て、
  loadProject 相当の分離ロジック (results の除去) が project を汚さないことを
  コードレビューで確認する。

## 注意

- コメントは日本語で「なぜ」を書く既存スタイル。
- saveTextFile の既存シグネチャを使う。
- git commit はしない。
