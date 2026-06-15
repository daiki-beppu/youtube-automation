// 型ガードの共用基盤（internal/case.ts と同じく src 外の cross-cutting helper）。
// 公開 API（package.json exports）には含めず、core 内部からのみ相対 import する。

/** plain object（非 null の object）かを判定する型ガード。 */
export const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null;
