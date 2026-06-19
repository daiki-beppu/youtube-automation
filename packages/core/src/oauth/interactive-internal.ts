// interactiveAuthService の実装内部ヘルパ（ADR-0003 §5）。実 OAuth 往復なしに unit
// test できるよう分解しているが、ドメイン操作ではなく実装詳細なので公開 subpath
// （package.json exports）には載せない。interactive.ts が相対 import で利用し、テストも
// 相対 import で直接検証する。公開 API 面に出るのは interactiveAuthService のみに保つ
// （internal.ts / refresh.ts の確立済み規約と同形）。

import { randomBytes } from "node:crypto";

import type { Credentials, OAuth2Client } from "google-auth-library";

const OAUTH_STATE_BYTES = 32;

type CallbackResult =
  | { code: string; kind: "code" }
  | { kind: "authError"; message: string }
  | { kind: "notFound" };

export const generateOAuthState = (): string =>
  randomBytes(OAUTH_STATE_BYTES).toString("base64url");

export const buildAuthUrl = (
  client: OAuth2Client,
  scopes: string[],
  state: string
): string =>
  client.generateAuthUrl({ access_type: "offline", scope: scopes, state });

export const resolveCallbackQuery = (
  searchParams: URLSearchParams,
  expectedState: string
): CallbackResult => {
  const code = searchParams.get("code");
  const denied = searchParams.get("error");
  if (!code && !denied) {
    return { kind: "notFound" };
  }

  const actualState = searchParams.get("state");
  if (!actualState) {
    return { kind: "authError", message: "missing OAuth state" };
  }
  if (actualState !== expectedState) {
    return { kind: "authError", message: "OAuth state mismatch" };
  }
  if (denied) {
    return { kind: "authError", message: `consent denied: ${denied}` };
  }
  if (!code) {
    return { kind: "notFound" };
  }
  return { code, kind: "code" };
};

export const exchangeCode = async (
  client: OAuth2Client,
  code: string
): Promise<Credentials> => {
  const { tokens } = await client.getToken(code);
  return tokens;
};
