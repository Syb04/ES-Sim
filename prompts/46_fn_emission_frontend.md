# 46: FN 電界放出のフロントエンド UI

## 背景

バックエンドに Fowler–Nordheim (FN) 電界放出を実装済み (`backend/es_sim/fn.py`,
`schema.py` の `FnEmission`)。粒子追跡 (trace) と PIC の両方で使える。
フロントエンド (React + TS, `frontend/src/`) に設定 UI と結果表示を追加する。

## バックエンドのスキーマ契約 (実装済み・変更しないこと)

`FnEmission` (particles.fn / pic.fn、null = 無効):

```ts
interface FnEmission {
  edges: number[];        // domain 外周のエッジ番号 (dirichlet 辺から選ぶ)
  regions: string[];      // conductor 領域の id
  phi_ev: number;         // 仕事関数 φ [eV] 既定 4.5
  beta: number;           // 電界増倍係数 β 既定 1.0
  n: number;              // trace 時の放出マクロ粒子総数 既定 200
  init_energy_ev: number; // 放出電子の初期エネルギー [eV] 既定 0.1
  macro_weight?: number | null; // PIC のみ: マクロ重み。null なら初期プラズマと同じ
  seed: number;           // PIC の放出位置乱数シード 既定 0
}
```

- edges か regions の少なくとも一方が必要 (両方空はバックエンドが 422)
- particles.fn 指定時は emitter は無視され、放出種は常に電子 (species も無視)
- TraceResult に追加フィールド: `currents: number[] | null` (粒子ごとの担持電流)、
  `fn_current: number | null` (総放出電流。単位は xy: A/m、rz/rz_x0: A)
- PIC の diag (フレーム/履歴) に追加キー: `fn_i` (そのステップの総放出電流 A/m)、
  `fn_events` (累計放出マクロ電子数)

## やること

1. **types.ts**: `FnEmission` 型を追加。`ParticleSettings` に `fn?: FnEmission | null`、
   `PicSettings` に `fn?: FnEmission | null`、`TraceResult` に `currents`/`fn_current`、
   `PicDiag` に `fn_i`/`fn_events` (optional) を追加。既存フィールドは変更しない。

2. **ParticlePanel.tsx** (粒子追跡タブ): 「FN電界放出」セクションを追加。
   - 有効/無効チェックボックス (無効なら particles.fn = undefined/null で送る)
   - 有効時: φ [eV]、β、粒子数 n、初期エネルギー [eV] の入力
     (指数表記が要る値は既存の `CommitInput` を使う)
   - 放出面の選択 UI:
     - domain 外周の dirichlet 境界 (project.geometry.boundaries の type==="dirichlet"
       エントリの edges) をチェックボックス列挙。表示例: 「エッジ 3 (0 V)」
     - conductor 領域 (project.geometry.regions の type==="conductor") を id で列挙
   - 有効時はエミッタ設定セクションを畳む/無効表示にして「FN 使用時はエミッタ・
     粒子種は使われません (電子固定)」の注記を出す
   - trace 実行後、結果表示に総放出電流を追加: `fn_current` を指数表記で。
     単位は座標系で切替 (xy: "A/m"、rz/rz_x0: "A")。isAxisymmetric() を利用

3. **PicPanel.tsx** (PIC タブ): 同様の「FN電界放出」セクションを追加。
   - φ、β、初期エネルギー、macro_weight (空欄なら null = 初期プラズマと同じ)、seed
   - 放出面選択は ParticlePanel と同じ UI (共通コンポーネント化してよい)
   - 実行中/完了後の診断表示に fn_i (放出電流 A/m) を1行追加 (diag に fn_i が
     あるときのみ表示)

4. **App.tsx**: particles / pic の state に fn を通す。保存/読込 (JSON) は
   スキーマどおり素通しなので、state に持たせれば自動で保存される。
   trace 結果の fn_current を ParticlePanel へ渡す。

## 注意

- 既存の見た目・挙動を壊さない (FN 無効時は完全に従来どおり)
- コードコメントは日本語、既存スタイルに合わせる
- 検証: `cd frontend && npx tsc --noEmit && npx vite build` が通ること
- コミットはしない (呼び出し元が行う)
