// 長さ単位の換算ヘルパー。
// 内部データ (project) はこれまで通り m 単位で保持し、UI の入出力のみ mm に変換する。
// 変換をここに集約することで、表示側・保存側で計算式がずれないようにする。

// m -> mm (表示用)。丸め誤差で値がわずかに揺れて見えないよう、
// 有効桁数を適度に丸めてから返す。
export function mToMm(m: number): number {
  return parseFloat((m * 1000).toPrecision(10));
}

// mm -> m (確定/保存用)
export function mmToM(mm: number): number {
  return mm / 1000;
}
