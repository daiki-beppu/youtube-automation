// config セクション parser 群が共有する構造ガード。
// Python 版が `isinstance(x, dict)` / `x or {}` で行っていた object 判定を、
// 配列を object 扱いしない厳密な形で TS へ移植する。

/** 配列を除外した plain object 判定（Python の `isinstance(x, dict)` 相当）。 */
export const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

/**
 * optional セクションを object として読む。
 *
 * Python の `merged.get(key) or {}` を踏襲し、未設定（`undefined` / `null`）は
 * 空 object へ畳む。非 object（配列・スカラー）は `label` を文脈に Fail Fast する。
 */
export const asRecord = (
  value: unknown,
  label: string
): Record<string, unknown> => {
  if (value === undefined || value === null) {
    return {};
  }
  if (!isRecord(value)) {
    throw new Error(`config: ${label} は object でなければなりません`);
  }
  return value;
};
