// interactiveAuthService の実装内部ヘルパ（ADR-0003 §5）。実 OAuth 往復なしに unit
// test できるよう分解しているが、ドメイン操作ではなく実装詳細なので公開 subpath
// （package.json exports）には載せない。interactive.ts が相対 import で利用し、テストも
// 相対 import で直接検証する。公開 API 面に出るのは interactiveAuthService のみに保つ
// （internal.ts / refresh.ts の確立済み規約と同形）。

import type { Credentials, OAuth2Client } from "google-auth-library";

/** generateAuthUrl で offline access（refresh_token 発行）を要求する consent URL を作る。 */
export const buildAuthUrl = (client: OAuth2Client, scopes: string[]): string =>
  client.generateAuthUrl({ access_type: "offline", scope: scopes });

/** authorization code を発行済み credentials に交換する。失敗は呼び出し側へ伝播する。 */
export const exchangeCode = async (
  client: OAuth2Client,
  code: string
): Promise<Credentials> => {
  const { tokens } = await client.getToken(code);
  return tokens;
};
