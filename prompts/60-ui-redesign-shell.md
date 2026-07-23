# 60: UI再設計 — 3カラムシェル (プロジェクトツリー / インスペクタ / キャンバス)

## 目的

初めて触る人でも「プリ (形状・条件) → メイン (解析実行) → ポスト (結果確認)」の流れが
分かるように、UI を CAE ツール風の3カラム構成へ作り直す。
**既存機能は一切失わないこと** (最重要制約)。

添付デザインモック (Claude design) の配置イメージ:

```
┌──────────────────────────────────────────────────────────────────┐
│ 上部バー: ES-Sim | 保存 読込 | ↶ ↷ | 座標系 [平面2D▾] | ポート[8317] | backend v0.1.x (CPU) │
├───────────┬──────────────┬───────────────────────────────────────┤
│ プロジェクト │ インスペクタ    │ キャンバスツールバー:                      │
│ ツリー      │ (選択ノードの   │  選択 ポリライン 矩形 円 プロファイル        │
│           │  設定/実行UI)  │  エミッタ コレクタ | 表示[電位V▾] スナップ…  │
│ ▼ジオメトリ │              ├───────────────────────────────────────┤
│  [プリ]    │              │                                       │
│ ▼スタディ   │              │           CadCanvas                   │
│  [メイン]   │              │                                       │
│ ▼結果      │              │                                       │
│  [ポスト]   │              │                                       │
├───────────┴──────────────┴───────────────────────────────────────┤
│ 下部ステータスバー: 実行中の計算の進捗 (例: PIC-MCC 実行中... 62%) / エラー   │
└──────────────────────────────────────────────────────────────────┘
```

## 対象ファイル

- `frontend/src/App.tsx` — レイアウト再構成 (ロジックの state/ハンドラは既存を維持)
- `frontend/src/ProjectTree.tsx` — 新規: プロジェクトツリー
- `frontend/src/panels/FieldPanel.tsx` — セクション表示フィルタ prop の追加 (分割はしない)
- `frontend/src/style.css` — 3カラム用スタイル追加
- ParticlePanel / PicPanel / GasPanel / ProfilePanel / CadCanvas は**変更しない**
  (どうしても必要な場合のみ最小変更)

## 1. ツリー構造 (ProjectTree.tsx)

上部に検索ボックス (ノード名の部分一致でフィルタ、空なら全表示)。
セクション見出しは折りたたみ可能 (▼/▶)。見出し右にフェーズバッジ:
`プリ` (青系) / `メイン` (緑系) / `ポスト` (橙系) の小さいピル。

```
▼ ジオメトリ                                  [プリ]
    ドメイン                (ドメイン寸法・メッシュ表示)
    領域 (N)
      ├ region1  (conductor など type を薄字で)
      └ ...                 ← クリックで選択 (キャンバスの選択と双方向同期)
    境界条件
      ├ 下辺 (エッジ0)  Dirichlet 0V   ← type/電圧の要約を薄字で
      ├ 右辺 (エッジ1)  ...
      ├ 上辺 (エッジ2)
      └ 左辺 (エッジ3)
      (軸対称時は対称軸の辺に「対称軸」表示。エッジ名は FieldPanel の
       EDGE_LABELS_XY/RZ/RZ_X0 と同じ表記を使う)
    メッシュ                (size の要約を薄字で)
    磁場                   (b_field 設定時のみ Bx,By,Bz 要約)
▼ スタディ                                    [メイン]
    静電場 FEM              [状態]
    粒子軌道追跡             [状態]
    PIC-MCC                [状態]
    ガス流れ DSMC           [状態]
▼ 結果                                        [ポスト]
    電位分布 φ
    電場 |E|
    ラインプロファイル
    粒子軌道
    PIC 結果
    ガス流れ結果
```

### スタディの状態バッジ

- 静電場 FEM: `busy` → 「実行中」 / `result` あり → 「✓完了」 / それ以外 「未実行」
- 粒子軌道追跡: 同様に `traceResult`
- PIC-MCC: `picRunning` → 「実行中 NN%」 (picFrame.step / picStarted.n_steps) /
  `picError` → 「エラー」(赤) / `picFields || picHistory.length>0` → 「✓完了」 / 「未実行」
- ガス流れ DSMC: `gasRunning` → 「実行中 NN%」 (gasProgress.step / nSteps) /
  `gasError` → 「エラー」 / `gasResult` → 「✓完了」 / 「未実行」

## 2. ノード選択とインスペクタ

App の `activeTab` を `activeNode` に置き換える (型は文字列 union):

```
type TreeNode =
  | "domain" | "regions" | "boundary" | "mesh" | "bfield"     // プリ
  | "study-fem" | "study-trace" | "study-pic" | "study-gas"   // メイン
  | "result-phi" | "result-e" | "result-profile"
  | "result-trace" | "result-pic" | "result-gas";             // ポスト
```

インスペクタ (中カラム) の内容 — **全ページ mount したまま display:none 切替**
(現行タブと同じ方式。PIC の WebSocket・チャート履歴・編集状態をアンマウントで失わないため):

| ノード | インスペクタ表示 |
|---|---|
| domain | FieldPanel (sections={["domain"]}) — 座標系 select もここに残す |
| regions / 領域の子 | FieldPanel (sections={["regions"]}) — 領域一覧+選択領域プロパティ |
| boundary / 辺の子 | FieldPanel (sections={["boundary"]}) — 辺の子選択時は該当エッジのみ表示 (edgeFilter prop) |
| mesh | FieldPanel (sections={["mesh"]}) |
| bfield | FieldPanel (sections={["bfield"]}) |
| study-fem | FieldPanel (sections={["solve"]}) — Mesh/Solve ボタン (現在上部バーにあるもの) + 解析結果サマリ |
| study-trace | ParticlePanel (そのまま) |
| study-pic | PicPanel (そのまま) |
| study-gas | GasPanel (そのまま) |
| result-phi | 選択時に fieldView="v" に設定。インスペクタには表示オプション (等電位線/ベクトル チェック) と解析結果サマリ |
| result-e | 同上で fieldView="e_abs" |
| result-profile | 選択時に tool="profile" へ切替。インスペクタに使い方ヒント (「キャンバス上で2点クリック」)。ProfilePanel (オーバーレイ) は現行のまま |
| result-trace | 軌道表示チェック (showTrajectories) + トレース結果サマリ → 実体は ParticlePanel と同じページを表示で良い (study-trace と同じページを指す) |
| result-pic | PicPanel と同じページを表示 (study-pic と共有) |
| result-gas | GasPanel と同じページを表示 (study-gas と共有) |

実装単純化のため: result-trace/result-pic/result-gas は「同じインスペクタページを指す
別ノード」として扱って良い (ページ id は "trace"/"pic"/"gas" の3つに正規化)。
result-phi / result-e は専用の小ページ (表示オプション+結果サマリ) を新設する。

### FieldPanel の変更

- prop `sections?: Array<"domain"|"boundary"|"mesh"|"bfield"|"regions"|"solve">` を追加。
  未指定なら従来通り全表示 (後方互換)。指定時は該当 `<h2>` ブロックのみ render。
- prop `edgeFilter?: number | null` を追加。boundary セクションで指定エッジのみ表示。
- 「解析結果」サマリは "solve" セクション扱いにする。
- Mesh/Solve/メッシュ表示ボタンは App から props (runMesh/runSolve/busy/canRun/
  showMesh/onToggleShowMesh) で受け取り "solve" セクションに表示する。

### 既存の連動挙動の維持 (置き換え表)

- `setActiveTab("particle")` (エミッタ配置確定時) → `setActiveNode("study-trace")`
- `setActiveTab("pic")` (コレクタ配置確定時) → `setActiveNode("study-pic")`
- `selectRegionFromCanvas` (キャンバスで領域選択) → `setActiveNode("regions")` + selectedRegionId
- ツリーで領域子ノードをクリック → selectedRegionId 設定 + activeNode="regions"
- ツリーで辺の子ノードをクリック → activeNode="boundary" + edgeFilter にそのエッジ
- `gasFieldView` の表示条件 `activeTab === "gas"` → `activeNode が "study-gas" か "result-gas"`

## 3. 上部バー

左から: `ES-Sim` ロゴ / 保存 / 読込 / ↶Undo / ↷Redo / セパレータ /
座標系 select (FieldPanel にもあるが上部バーにも置く — 実体は同じ setCoord。
二重管理にならないよう value は project.coord から) / spacer /
ポート入力 / backend 接続状態 (現行と同じ)。

- Mesh/Solve/メッシュ表示ボタンは上部バーから **study-fem インスペクタへ移動**
  (機能は失わない)。
- 保存/読込は現在サイドパネル上部にある → 上部バーへ移動。

## 4. キャンバスツールバー (キャンバス直上、右カラム内)

現行 tool-toolbar の内容をそのまま右カラム上部に置く:
選択/ポリライン/矩形/円/プロファイル/エミッタ/コレクタ、グリッドスナップ、
ルーラー文字、表示 (電位V/|E|)、等電位線、ベクトル。変更不要 (置き場所のみ)。

## 5. 下部ステータスバー

高さ 24px 程度の1行バー。優先順位順に:

1. エラーがあれば赤字で先頭に (error / picError / gasError のうち直近のもの。
   ここでは簡単のため error → picError → gasError の順で最初の非null)
2. busy → 「静電場FEM/トレース 計算中...」
3. picRunning → 「PIC-MCC 実行中... NN% (step/total)」+ 細いプログレスバー
4. gasRunning → 「ガス流れDSMC 実行中... NN%」+ プログレスバー
5. 何もなければ 「準備完了」+ 現在のツール名

エラー表示は現行どおり各パネル内にも残す (二重でも構わない)。
App.tsx 末尾の `{error && ...}` ブロック (side-tab-content 内) は撤去して良い
(ステータスバー + FieldPanel solve セクションへ移す)。

## 6. レイアウト / CSS

- `.app` を grid rows: topbar / main / statusbar に。
- main は flex: `.tree-col` (幅 230px、リサイズ不要) + `.inspector-col`
  (既存 side の CSS を流用、幅 sideWidth、既存リサイザを tree との間ではなく
  inspector と canvas の間に置く) + `.canvas-col` (flex:1、上にツールバー)。
- 順序はモック通り **左: ツリー、中: インスペクタ、右: キャンバス**。
  既存 `.side` は右配置だったので並び替えに注意 (リサイザのドラッグ方向:
  `startW + (ev.clientX - startX)` に反転が必要)。
- ダーク基調の現行テーマを踏襲。ツリーは `font-size: 12px`、選択ノードは
  アクセント色背景、hover で薄背景。バッジは 10px の丸ピル。
- インスペクタ上部に現在ノードのタイトル (例: 「境界条件 — 右辺 (エッジ1)」) を表示。

## 7. 検証

- `cd frontend && npx tsc --noEmit && npx vite build` が通ること。
- 機能チェックリスト (コードレビューで確認):
  保存/読込/Undo/Redo/ポート設定/座標系切替/領域編集/BC編集 (RF・SEE含む)/
  メッシュ設定/磁場/Mesh/Solve/表示切替/プロファイル/エミッタ/コレクタ配置/
  Trace/PIC start/stop/continue/周期アニメ/コレクタ結果/DSMC run/stop/進捗/
  ガス結果表示/エラー表示 — すべて到達可能な UI があること。

## 注意

- コメントは日本語で、既存コードのスタイル (「なぜ」を書く) に合わせる。
- ParticlePanel/PicPanel/GasPanel の props は変えない。
- 既存 state 名・ハンドラ名はできるだけ維持し、diff を追いやすくする。
