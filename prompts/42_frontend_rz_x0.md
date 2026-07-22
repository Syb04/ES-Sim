# サブエージェント指示: 左辺 (x=0) 軸の軸対称モードUI(フロントエンド)

対象リポジトリ: `/home/claude/ES-Sim/frontend`(npm install 済み)

契約は `/home/claude/ES-Sim/prompts/41_backend_rz_x0.md` を参照
(coord: "xy"|"rz"|"rz_x0"。rz_x0 は x=r・y=z、左辺 x=0 が対称軸)。
prompts/40 で実装済みの rz UI(FieldPanel / CadCanvas / App / PicPanel)を読んでから着手すること。

## やること

1. **types.ts**: `Project.coord?: "xy" | "rz" | "rz_x0"`

2. **FieldPanel**: 座標系セレクトを3択に:
   「平面 2D / 軸対称 r-z (下辺が軸) / 軸対称 r-z (左辺が軸)」
   - rz_x0 のラベル: 幅→「半径 r [mm]」、高さ→「長さ z [mm]」
   - 辺ラベル(rz_x0): 左=「対称軸 (r=0)」(セレクト無効・固定)、右=「右 (r=R)」、
     下=「下 (z=0)」、上=「上 (z=L)」。座標系切替時に軸辺の既存BCを除去
     (既存の setCoord のロジックを一般化: 軸になる辺のBCを掃除)
   - ヒントも軸の位置に合わせて出し分け

3. **CadCanvas**: rz_x0 では座標表示を「r: .. mm  z: .. mm」(x が r)、対称軸の
   一点鎖線オーバーレイを**左辺**に描画。ルーラーの表記も対応

4. **App/PicPanel**: PIC 無効化・エネルギー [J] 表示は「rz または rz_x0」で発動するよう
   既存の isRz 判定を共通ヘルパー(例 `isAxisymmetric(coord)`)に一般化

## 制約

新しい npm 依存なし。日本語コメント。TS strict 維持。既存の xy / rz を壊さない。

## 完了条件

`cd /home/claude/ES-Sim/frontend && npx tsc && npx vite build` 成功。
変更ファイル一覧と操作方法の要約のみ報告。
