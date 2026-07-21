# サブエージェント指示: Maxwell分布ソース + 衝突角度の表示(フロントエンド)

対象リポジトリ: `/home/claude/ES-Sim/frontend`(npm install 済み)

ES-Sim(Tauri 2 + React 18 + TS strict)の粒子UIへの機能追加2件。
バックエンドに並行実装される機能のスキーマ契約は
`/home/claude/ES-Sim/prompts/13_backend_maxwell_angle.md` を参照し、型を完全一致させること。
必ず現状のコード(types.ts / panels/ParticlePanel.tsx / App.tsx)を読んでから着手すること。

## やること

1. **types.ts**: `Emitter` に `energy_dist?: "mono" | "maxwell"`、`temperature_ev?: number`、
   `seed?: number` を追加。`TraceResult` に `final_angle_deg: number[]` を追加
2. **ParticlePanel**:
   - 「エネルギー分布」セレクト(単一エネルギー / Maxwell)を追加
   - Maxwell 選択時のみ「温度 kT [eV]」「乱数シード」入力欄を表示
     (mono時は従来のエネルギー・広がり半角。Maxwell時は広がり半角入力を無効化し
     「Maxwell分布では熱運動が方向広がりを与えます」等の注記を出す。
     エネルギー[eV]はドリフトエネルギーとして引き続き有効)
   - 結果サマリに**吸収粒子の入射角統計**を追加: 平均・標準偏差・min/max [deg]
     (`final_angle_deg` を `status == "absorbed"` の粒子で集計)
3. 保存/読込(project.particles)に新フィールドが含まれること(既存の合成/復元ロジックを確認)

## 制約

- 新しい npm 依存を追加しない。コメントは日本語。TS strict 維持
- 既存機能を壊さない

## 完了条件

`cd /home/claude/ES-Sim/frontend && npx tsc && npx vite build` 成功。
最後に変更ファイル一覧と操作方法の要約のみを報告。
