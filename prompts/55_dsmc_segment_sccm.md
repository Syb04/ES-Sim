# 55: DSMC 流入口の線分指定 + sccm 流量指定

## バックエンド (実装済み・変更しないこと)

`DsmcBoundary` が拡張された (backend/es_sim/schema.py):

- `edges: number[]` は空でもよくなり、代わりに `p1: [x, y]` / `p2: [x, y]`
  (domain 外周上の線分、部分区間指定) で適用範囲を指定できる (両方指定は和集合)。
  電極と外枠の隙間などエッジの一部だけを流入口にする用途
- `flow_sccm?: number | null` — inlet の流量指定 [sccm]。`pressure_pa` と排他
  (どちらか一方が必須)。1 sccm = 4.478e17 分子/s (標準状態換算、2D なので
  奥行き 1 m 換算)。流量指定の inlet は入射粒子を拡散反射壁として扱い、
  正味流量が指定値に厳密一致する

## フロントエンド作業

1. **types.ts**: `DsmcBoundary` を同期:
   ```ts
   edges: number[];            // 空可
   p1?: Point | null;          // 線分指定 (部分区間)。edges と併用可 (和集合)
   p2?: Point | null;
   flow_sccm?: number | null;  // inlet の流量 [sccm] (pressure_pa と排他)
   ```

2. **GasPanel.tsx** の境界条件行を拡張:
   - 適用範囲の指定方法セレクト:「エッジ番号」/「線分 (p1-p2)」
     - エッジ番号: 既存のカンマ区切り入力
     - 線分: p1x, p1y, p2x, p2y の4入力 (mm 単位表示にするなら既存の
       units.ts の mToMm/mmToM の流儀に合わせる。既存パネルが m 直入力なら m でよい)
   - type="inlet" のとき指定モードセレクト:「圧力 [Pa]」/「流量 [sccm]」
     - 圧力: 既存の pressure_pa 入力
     - 流量: flow_sccm 入力 (切替時はもう一方を null にする)
   - ヒント文言: 線分指定は「外周上の線分に載る境界メッシュエッジへ適用
     (電極との隙間など部分区間の指定用)」、流量は「1 sccm = 標準状態の
     1 cm³/min。奥行き1m換算。入射粒子は壁反射になり正味流量が指定値に一致」

3. 既存プロジェクト (edges のみ・pressure_pa のみ) がそのまま表示・編集できること

## 検証

`cd /home/claude/ES-Sim/frontend && npx tsc --noEmit && npx vite build` が通ること。
コミットはしない (呼び出し元が行う)。
