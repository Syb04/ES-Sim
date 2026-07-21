# サブエージェント指示: フロントエンド スケッチツール・材料割当・保存/読込

対象リポジトリ: `/home/claude/ES-Sim/frontend`(npm install 済み)

## 背景

ES-Sim は 2D静電場FEMアプリ(Tauri 2 + React 18 + TS strict)。現状はハードコードされた
サンプルプロジェクト(`App.tsx` の `SAMPLE`)を表示・求解するだけのビューア。
これを編集可能にする。仕様書 `/home/claude/ES-Sim/docs/SPEC.md` §4 参照。
プロジェクトのデータ型は `src/types.ts`(バックエンドと同期済み。**変更しない**)。

## やること

### 1. App.tsx — プロジェクトを編集可能な state にする

- `SAMPLE` を初期値とする `project` state を導入し、以下のUIを追加:
  - **domain**: 幅・高さの数値入力(m)。domain は原点基準の矩形とする(頂点順: [0,0],[w,0],[w,h],[0,h])
  - **境界条件**: 矩形の4辺(0=下, 1=右, 2=上, 3=左)それぞれに「なし(Neumann)/Dirichlet」の選択と電圧入力
  - **メッシュサイズ**: 数値入力(m)
  - **領域リスト**: 選択中領域のプロパティ編集(id テキスト、type セレクト、voltage / eps_r / rho の数値入力。type に応じて表示切替)、削除ボタン
- ジオメトリ・メッシュ設定が変わったら解析結果を破棄(`setResult(null)`)
- **保存**: プロジェクトJSONをファイルダウンロード(Blob + a.click、ファイル名 `project.json`)
- **読込**: `<input type="file">` でJSONを読み込み project を置換(型は信頼して良い。最低限 `geometry` の存在だけ確認)

### 2. CadCanvas.tsx — 描画ツール

ツールバー(App側)で選択するツール state を props で受け取る:

- **select**: クリックで領域を選択(点内包判定、ray casting)。選択領域はハイライト表示。Delete キーで削除
- **polyline**: クリックで頂点追加、ダブルクリックまたは Enter で閉じて確定(3点以上)、Esc でキャンセル。作図中はラバーバンド表示
- **rect**: 2クリック(対角)で矩形
- **circle**: 中心クリック → 半径クリック。48分割の多角形として登録
- **グリッドスナップ**: チェックボックスでON/OFF(デフォルトON)。スナップ幅は表示中グリッドの 1/10。座標表示もスナップ後の値
- 確定した図形は `onAddRegion(polygon: Point[])` で App に渡す。App 側で `region{n}` の連番IDを振り、デフォルト材料 `{ type: "conductor", voltage: 0 }` で追加
- 既存のパン(中ボタン/Space+左ドラッグ)・ホイールズーム・座標表示・結果カラーマップ描画は**壊さないこと**

### 3. スタイル

`src/style.css` に必要なクラスを追加。既存のダークテーマ(CSS変数)に合わせる。
ツールバーのツールボタンは選択中がわかる見た目(`button.tool.active` など)。

## 制約

- 新しい npm 依存を追加しない
- React 18 関数コンポーネント + hooks、TS strict を維持
- コメントは日本語
- コンポーネント分割は自由(例: `src/panels/SidePanel.tsx` を切り出すのは可)

## 完了条件

`cd /home/claude/ES-Sim/frontend && npx tsc && npx vite build` が成功すること。
最後に変更・追加したファイルの一覧と操作方法の要約だけを報告すること。
