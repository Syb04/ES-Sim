import { useCallback, useRef, useState } from "react";

// 履歴の上限エントリ数 (超えたら古いものから破棄)
const HISTORY_LIMIT = 100;

/**
 * スナップショット方式の Undo/Redo 履歴管理フック。
 *
 * 状態そのものは呼び出し側 (App.tsx) が useState で保持し、このフックは
 * 「編集確定前の状態」を past に積み、undo/redo でスタックの出し入れを
 * 行うだけの薄いユーティリティ。past/future の中身は ref に置き、
 * ボタンの disabled 切り替えなど再レンダーが必要な箇所のためだけに
 * 内部の tick state を更新する。
 */
export function useHistory<T>(limit: number = HISTORY_LIMIT) {
  const past = useRef<T[]>([]);
  const future = useRef<T[]>([]);
  // canUndo/canRedo を再計算させるための再レンダー用トリガー
  const [, setTick] = useState(0);
  const bump = useCallback(() => setTick((t) => (t + 1) % 1_000_000), []);

  // 編集確定前の状態 (prev) を履歴に積む。redo 用の future はクリアする。
  const push = useCallback(
    (prev: T) => {
      past.current.push(prev);
      if (past.current.length > limit) past.current.shift();
      future.current = [];
      bump();
    },
    [limit, bump],
  );

  // current (undo 実行直前の最新状態) を future に退避し、直前の状態を返す。
  // 履歴が空なら null を返し何もしない。
  const undo = useCallback(
    (current: T): T | null => {
      const prev = past.current.pop();
      if (prev === undefined) return null;
      future.current.push(current);
      bump();
      return prev;
    },
    [bump],
  );

  // current (redo 実行直前の最新状態) を past に戻し、取り消されていた状態を返す。
  const redo = useCallback(
    (current: T): T | null => {
      const next = future.current.pop();
      if (next === undefined) return null;
      past.current.push(current);
      bump();
      return next;
    },
    [bump],
  );

  // Undo/Redo とは無関係に履歴自体を空にしたい場合 (通常は未使用)
  const clear = useCallback(() => {
    past.current = [];
    future.current = [];
    bump();
  }, [bump]);

  return {
    push,
    undo,
    redo,
    clear,
    canUndo: past.current.length > 0,
    canRedo: future.current.length > 0,
  };
}
