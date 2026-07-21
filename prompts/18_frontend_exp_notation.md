# サブエージェント指示: 数値入力の指数表記対応

対象リポジトリ: `/home/claude/ES-Sim/frontend`(npm install 済み)

ES-Sim(Tauri 2 + React 18 + TS strict)。ユーザー要望:
「RF周波数、初期密度、dt など指数表記(例: 13.56MHz → 13.56e6)で入力できるようにしてほしい」。
現状は数値入力欄で指数表記が扱えず、大きい値は `100000000000000` のような羅列表示になっている。
必ず現状の `src/CommitInput.tsx` と、その利用箇所(FieldPanel / ParticlePanel / PicPanel / App)を
読んでから着手すること。

## やること(`CommitNumberInput` を拡張。全数値欄に一括適用)

1. **入力**: `<input type="text" inputMode="decimal">` にし、確定時(Enter/blur)に
   `Number(文字列)` でパース。`13.56e6`、`1e14`、`-1.5E-3`、通常の `100` などを受け付ける。
   パース不能(NaN)なら確定せず元の値に戻す
2. **表示**: 値の絶対値が `1e5` 以上、または `0` でなく `1e-3` 未満のときは
   指数表記で表示(例: `1.356e7`、`1e14`、`5.6e-10`)。それ以外は従来の通常表記。
   有効数字は最大6桁程度で末尾ゼロは削る(`parseFloat(v.toExponential(6)).toExponential()` 等、
   見た目が煩雑にならない方法で)
3. min/max やバリデーション等、既存の props・挙動(確定タイミング、履歴連動)は維持する
4. 既存の全利用箇所(mm入力、RF振幅/周波数/位相、密度、温度、dt、電荷密度 ρ など)が
   そのまま恩恵を受けることを確認(利用側の変更が必要なら最小限に)

## 制約

- 新しい npm 依存を追加しない。コメントは日本語。TS strict 維持
- 既存機能を壊さない

## 完了条件

`cd /home/claude/ES-Sim/frontend && npx tsc && npx vite build` 成功。
最後に変更ファイル一覧と動作仕様の要約のみを報告。
