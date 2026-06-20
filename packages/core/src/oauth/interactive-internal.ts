// interactiveAuthService の実装内部ヘルパ（ADR-0003 §5）。実 OAuth 往復なしに unit
// test できるよう分解しているが、ドメイン操作ではなく実装詳細なので公開 subpath
// （package.json exports）には載せない。interactive.ts が相対 import で利用し、テストも
// 相対 import で直接検証する。公開 API 面に出るのは interactiveAuthService のみに保つ
// （internal.ts / refresh.ts の確立済み規約と同形）。

import { randomBytes } from "node:crypto";

import type { Credentials, OAuth2Client } from "google-auth-library";

const OAUTH_CALLBACK_CODE_PARAM = "code";
const OAUTH_CALLBACK_ERROR_PARAM = "error";
const OAUTH_CALLBACK_STATE_PARAM = "state";
export const OAUTH_STATE_MISMATCH_MESSAGE =
  "auth: OAuth callback state mismatch";

export type OAuthCallbackResult =
  | { code: string; status: "code" }
  | { error: Error; status: "error" }
  | { status: "not_found" };

/** CSRF 防止用の OAuth callback state を生成する。 */
export const generateOAuthState = (): string =>
  randomBytes(32).toString("base64url");

/** OAuth callback の state が consent URL 発行時の値と一致することを検証する。 */
const validateOAuthCallbackState = (
  actualState: string | null,
  expectedState: string
): void => {
  if (actualState !== expectedState) {
    throw new Error(OAUTH_STATE_MISMATCH_MESSAGE);
  }
};

/** generateAuthUrl で offline access（refresh_token 発行）を要求する consent URL を作る。 */
export const buildAuthUrl = (
  client: OAuth2Client,
  scopes: string[],
  state: string
): string =>
  client.generateAuthUrl({ access_type: "offline", scope: scopes, state });

export const parseOAuthCallback = (
  request: Request,
  expectedState: string
): OAuthCallbackResult => {
  const { searchParams } = new URL(request.url);
  const code = searchParams.get(OAUTH_CALLBACK_CODE_PARAM);
  const denied = searchParams.get(OAUTH_CALLBACK_ERROR_PARAM);
  if (!code && !denied) {
    return { status: "not_found" };
  }
  try {
    validateOAuthCallbackState(
      searchParams.get(OAUTH_CALLBACK_STATE_PARAM),
      expectedState
    );
  } catch (error) {
    return {
      error: error instanceof Error ? error : new Error(String(error)),
      status: "error",
    };
  }
  if (code) {
    return { code, status: "code" };
  }
  return {
    error: new Error(`auth: consent denied: ${denied}`),
    status: "error",
  };
};

/** authorization code を発行済み credentials に交換する。失敗は呼び出し側へ伝播する。 */
export const exchangeCode = async (
  client: OAuth2Client,
  code: string
): Promise<Credentials> => {
  const { tokens } = await client.getToken(code);
  return tokens;
};
