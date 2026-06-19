// 純粋な OAuth リフレッシュサービス（ADR-0003 §5）。browser も local server も使わ
// ないため MCP / CLI 双方から利用できる。
//
// service は `Promise<Result<{ tokenJson }, ServiceError>>` を返し、境界を越えて throw
// しない。google-auth-library の OAuth2Client は `deps.createOAuthClient` 注入 seam 経由
// で到達する（image service の deps パターンと同形）。production default は実 OAuth2Client
// を生成し、テストは fake client を差し込んでネットワークに触れない。
//
// seam contract:
//   deps.createOAuthClient({ clientId, clientSecret }) -> client
//   client.setCredentials(credentials)   // stored refresh_token を seed
//   await client.refreshAccessToken()    // -> { credentials }

import { OAuth2Client } from "google-auth-library";
import type { Credentials } from "google-auth-library";

import { toServiceError } from "../errors.ts";
import type { ServiceError } from "../errors.ts";
import { err, ok } from "../result.ts";
import type { Result } from "../result.ts";
import { parseClientSecrets } from "./internal.ts";
import { RefreshTokenInput } from "./schema.ts";

/** refresh が必要とする OAuth2Client の最小シェイプ（注入 seam）。 */
interface RefreshOAuthClient {
  refreshAccessToken(): Promise<{ credentials: Credentials }>;
  setCredentials(credentials: Credentials): void;
}

/** refreshTokenService の注入依存。省略時は実 OAuth2Client を生成する。 */
export interface RefreshDeps {
  createOAuthClient: (config: {
    clientId: string;
    clientSecret: string;
  }) => RefreshOAuthClient;
}

const defaultDeps: RefreshDeps = {
  createOAuthClient: ({ clientId, clientSecret }) =>
    new OAuth2Client({ clientId, clientSecret }),
};

// refresh の失敗を auth ドメインへ寄せる。OAuth2Client.refreshAccessToken は grant 失効・
// 取り消し時に invalid_grant を throw するが、message は prefix 規約に従わないため、ここで
// `auth:` を付与してから境界（toServiceError）に渡して domain "auth" に確定させる。
const refreshCredentials = async (
  client: RefreshOAuthClient
): Promise<Credentials> => {
  try {
    const { credentials } = await client.refreshAccessToken();
    return credentials;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(`auth: token refresh failed: ${message}`, { cause: error });
  }
};

/**
 * 保存済み token を refresh し、更新後の credentials を token.json 文字列で返す。
 *
 * client_secrets から clientId / clientSecret を取り出して OAuth2Client を構築し、stored
 * refresh_token を seed してから refresh する。入力は `.strict()` schema で先に検証する
 * ため、未知キーは refresh に到達せず validation エラーになる。
 */
export const refreshTokenService = async (
  input: RefreshTokenInput,
  deps: RefreshDeps = defaultDeps
): Promise<Result<{ tokenJson: string }, ServiceError>> => {
  try {
    const { clientSecretsJson, tokenJson } = RefreshTokenInput.parse(input);
    const { clientId, clientSecret } = parseClientSecrets(clientSecretsJson);
    const client = deps.createOAuthClient({ clientId, clientSecret });
    client.setCredentials(JSON.parse(tokenJson) as Credentials);
    const credentials = await refreshCredentials(client);
    return ok({ tokenJson: JSON.stringify(credentials) });
  } catch (error) {
    return err(toServiceError(error));
  }
};
