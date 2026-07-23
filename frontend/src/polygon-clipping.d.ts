// polygon-clipping 同梱の型定義 (dist/polygon-clipping.d.ts) は名前付きエクスポート
// (`export function union` 等) の形で書かれているが、Vite が実際に読み込む ESM ビルド
// (dist/polygon-clipping.esm.js) は `export { index as default }` のみで、union 等は
// default エクスポートしたオブジェクトのプロパティとしてしか存在しない。
// 型定義と実行時の形が食い違っているため、ここで default エクスポートの型を追記する
// (declare module は同名モジュールの宣言同士がマージされるため、同梱の named export
// 宣言と衝突しない)。
declare module "polygon-clipping" {
  interface PolygonClippingApi {
    union: typeof union;
    intersection: typeof intersection;
    xor: typeof xor;
    difference: typeof difference;
  }
  const polygonClipping: PolygonClippingApi;
  export default polygonClipping;
}
