// config セクション parser 群が共有する構造ガード（公開 API ではない）。
// Python 版が `isinstance(x, dict)` で行っていた object 判定を、配列を object 扱いしない
// 厳密な形で TS へ移植する。

/** 配列を除外した plain object 判定（Python の `isinstance(x, dict)` 相当）。 */
export const isPlainObject = (
  value: unknown
): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
