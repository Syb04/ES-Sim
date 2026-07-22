# サブエージェント指示: RF1周期アニメーションUI(フロントエンド)

対象リポジトリ: `/home/claude/ES-Sim/frontend`(npm install 済み)

バックエンドのスキーマ契約は `/home/claude/ES-Sim/prompts/28_backend_cycle_animation.md` を参照し
型を一致させること。types.ts / App.tsx / canvas/CadCanvas.tsx / panels/PicPanel.tsx
(結果フィールド表示 picFieldView の実装)を読んでから着手すること。

## やること

1. **types.ts**: `PicCycle`(bins / period_s / phi / n_e / n_i / particles)を追加、
   `PicDoneMsg.cycle?: PicCycle`。`PicSettings.phase_bins?: number` を追加

2. **PIC設定UI**: 「位相ビン数(周期アニメ用、0=無効)」入力を計算設定に追加(既定40)

3. **周期アニメーションプレイヤー**(PicPanel に「PIC: 周期アニメーション」セクション。
   done で cycle を受信した場合のみ表示):
   - 表示フィールド選択: 電位 / 電子密度 / イオン密度(対数チェックは既存を流用または同等品)
   - **再生/一時停止ボタン**、**位相スライダー**(0〜bins-1、位相角 0〜360° とビン内時刻を表示)、
     再生速度セレクト(例 5/10/20 fps)
   - 再生は setInterval/requestAnimationFrame でビンを順送りしループ
   - **カラースケールは全ビンの min/max で固定**(フレーム間で色が暴れないように)
   - 粒子スナップショット(該当ビンの electron/ion 位置)をドットでオーバーレイ
     (表示トグル付き)
   - アニメーション表示中は既存の「結果表示」フィールドやライブ表示より優先して描画。
     App 側の描画優先順位を整理し、CadCanvas へは既存の `picFieldView` を拡張または
     同形の prop で「現在ビンの値+固定min/max+粒子」を渡す形にする
     (CadCanvas に本質的な新描画コードをなるべく増やさない)
   - 新しい実行開始でアニメーション状態をリセット

## 制約

新しい npm 依存なし。日本語コメント。TS strict 維持。既存機能を壊さない。

## 完了条件

`cd /home/claude/ES-Sim/frontend && npx tsc && npx vite build` 成功。
変更ファイル一覧と操作方法の要約のみ報告。
