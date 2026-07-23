# 51: 一様磁場 (Boris 法) — バックエンド設計記録 + フロントエンド指示

## バックエンド設計 (実装済み — 本体モデルが直接実装。以下は記録)

- `Project.b_field: {bx, by, bz} [T] | null`。全成分 0 は磁場なしと同値。
  軸対称 (rz / rz_x0) + 非ゼロ b_field は validator でエラー
  (一様な径方向磁場は ∇·B=0 と矛盾するため)
- Boris 法: v⁻ = v + (qΔt/2m)E → 回転 R (前計算した 3×3 行列、厳密ノルム保存)
  → v⁺ + (qΔt/2m)E。回転角は 2·atan(ωcΔt/2)
- trace: B ありでは xy でも速度3成分 (面内 B は vz と結合)。dt 自動推定に
  dt ≤ 0.2/ωc の制約を追加
- PIC: 種ごとに回転行列を前計算 (イオンサブサイクルで dt が異なる)。
  ωce·dt > 0.3 で警告。b_field なしは従来経路とビット単位一致
- 検証: ラーマー半径 (2%以内)、E×B ドリフト速度 (5%以内)、面内 B の x-z 旋回、
  エネルギー厳密保存、回転角の解析式一致 (backend/tests/test_bfield.py)

## フロントエンド作業 (サブエージェント向け指示)

1. **types.ts**: `BField { bx: number; by: number; bz: number }` を追加し、
   `Project` に `b_field?: BField | null` を追加 (日本語コメント)

2. **FieldPanel.tsx**: ソルバー/メッシュ設定の近くに「一様磁場 [T]」セクションを追加:
   - Bx / By / Bz の3入力 (`CommitNumberInput`、指数表記可)
   - 値は project 更新経由: FieldPanel が project を編集する既存の流儀
     (App から渡ってくる更新コールバック) に合わせる。全成分 0 なら
     b_field を undefined にしてもよいし {0,0,0} のままでもよい (バックエンドは同値)
   - ヒント文言: 「粒子軌道追跡・PIC のローレンツ力に適用 (静電場ソルブには影響しない)。
     軸対称モードでは使用不可」
   - 軸対称モード (isAxisymmetric(project.coord)) では入力を disabled にして
     注記を出す

3. **App.tsx**: 必要なら b_field 更新用のコールバックを追加して FieldPanel へ渡す
   (commitProject で project.b_field を更新。Undo/Redo 履歴に乗る)

## 検証

`cd /home/claude/ES-Sim/frontend && npx tsc --noEmit && npx vite build` が通ること。
コミットはしない (呼び出し元が行う)。
