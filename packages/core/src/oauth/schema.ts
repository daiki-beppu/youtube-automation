// OAuth サービス境界の入力 / 出力 schema（ADR-0003 §8: zod を source of truth）。
//
// refresh / interactive いずれも呼び出し側が組み立てる in-process な値（JSON 文字列・
// scope 配列）を受け取る。config / API レスポンス由来の JSON ではないため snake_case
// → camelCase の `.transform()` は不要で camelCase のまま declare する。型は `z.infer`
// で導出し並書の `interface` は持たない。`.strict()` で未知キーを reject（fail fast）。

import { z } from "zod";

/** refreshTokenService の入力（pure・MCP / CLI 両用）。 */
export const RefreshTokenInput = z
  .object({
    clientSecretsJson: z.string(),
    tokenJson: z.string(),
  })
  .strict();
export type RefreshTokenInput = z.infer<typeof RefreshTokenInput>;

/** OAuth service の共通出力（発行・更新済み token.json 文字列）。 */
export const OAuthTokenOutput = z
  .object({
    tokenJson: z.string(),
  })
  .strict();
export type OAuthTokenOutput = z.infer<typeof OAuthTokenOutput>;

/** interactiveAuthService の入力（CLI 専用・browser + local server）。 */
export const InteractiveAuthInput = z
  .object({
    clientSecretsJson: z.string(),
    scopes: z.array(z.string()),
  })
  .strict();
export type InteractiveAuthInput = z.infer<typeof InteractiveAuthInput>;
