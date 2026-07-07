// config セクション parser 群が共有する構造ガード（公開 API ではない）。
// Python 版が `isinstance(x, dict)` で行っていた object 判定を、配列を object 扱いしない
// 厳密な形で TS へ移植する。

import { z } from "zod";

/** 配列を除外した plain object 判定（Python の `isinstance(x, dict)` 相当）。 */
export const isPlainObject = (
  value: unknown
): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

export const addIssues = (
  ctx: z.RefinementCtx,
  issues: z.ZodIssue[],
  pathPrefix: z.ZodIssue["path"] = []
): void => {
  for (const issue of issues) {
    ctx.addIssue({
      ...issue,
      path: [...pathPrefix, ...issue.path],
    });
  }
};

export const parseWithIssues = <Output>(
  schema: z.ZodType<Output>,
  input: unknown,
  ctx: z.RefinementCtx
): Output => {
  const result = schema.safeParse(input);
  if (result.success) {
    return result.data;
  }
  addIssues(ctx, result.error.issues);
  return z.NEVER;
};
