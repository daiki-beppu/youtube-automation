// image モジュール内部で共有する小さなガード（公開 API ではない）。

/** plain object（非 null の object）かを判定する型ガード。 */
export const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null;
