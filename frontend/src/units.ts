// 長さ単位の換算ヘルパー。
// 内部データ (project) はこれまで通り m 単位で保持し、UI の入出力のみ表示単位
// (mm または µm、App の lengthUnit state) に変換する。変換をここに集約することで、
// 表示側・保存側で計算式がずれないようにする。

export type LengthUnit = "mm" | "um";

// 表示ラベル (µ は U+00B5)
export const LENGTH_UNIT_LABEL: Record<LengthUnit, string> = { mm: "mm", um: "µm" };

// m -> 表示単位への倍率
const FACTOR: Record<LengthUnit, number> = { mm: 1e3, um: 1e6 };

// m -> 表示単位 (表示用)。丸め誤差で値がわずかに揺れて見えないよう、
// 有効桁数を適度に丸めてから返す (toPrecision(10))。
export function mToUnit(m: number, unit: LengthUnit): number {
  return parseFloat((m * FACTOR[unit]).toPrecision(10));
}

// 表示単位 -> m (確定/保存用)
export function unitToM(v: number, unit: LengthUnit): number {
  return v / FACTOR[unit];
}
