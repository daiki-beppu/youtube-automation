// CLI 専用のインタラクティブ OAuth サービス（ADR-0003 §5）。内部で consent 用の
// ブラウザを開き、ローカルコールバックサーバを起動して authorization code を受け取る。
// MCP サーバプロセスは browser を開けず boot 時に hang するため、oxlint の
// no-restricted-imports が `packages/mcp/**` からの本モジュール import を error にする
// （CLI からの import は許可）。
//
// 公開 service は interactiveAuthService のみ。consent URL 生成 / code 交換の実装内部
// ヘルパ（buildAuthUrl / exchangeCode）は ./interactive-internal.ts に分離し、公開
// subpath には載せない（実 OAuth fixture は不可なので full flow は test しない / order.md。
// 内部ヘルパは相対 import で unit test する）。

import { spawn } from "node:child_process";

import { OAuth2Client } from "google-auth-library";
import type { Credentials } from "google-auth-library";

import type { ServiceError } from "../errors.ts";
import type { Result } from "../result.ts";
import { createService } from "../service.ts";
import {
  buildAuthUrl,
  exchangeCode as defaultExchangeCode,
  generateOAuthState,
  parseOAuthCallback,
} from "./interactive-internal.ts";
import { parseClientSecrets } from "./internal.ts";
import { InteractiveAuthInput, OAuthTokenOutput } from "./schema.ts";

interface InteractiveOAuthClient {
  generateAuthUrl(options: {
    access_type: "offline";
    scope: string[];
    state: string;
  }): string;
  getToken(code: string): Promise<{ tokens: Credentials }>;
}

interface OAuthCallbackServer {
  readonly port?: number;
  stop(force: boolean): Promise<void> | void;
}

interface OAuthCallbackServerOptions {
  fetch: (request: Request) => Response | Promise<Response>;
  hostname: string;
  port: number;
}

interface InteractiveDeps {
  createOAuthClient: (config: {
    clientId: string;
    clientSecret: string;
    redirectUri: string;
  }) => InteractiveOAuthClient;
  exchangeCode: (
    client: InteractiveOAuthClient,
    code: string
  ) => Promise<Credentials>;
  generateState: () => string;
  openBrowser: (url: string) => void;
  serve: (options: OAuthCallbackServerOptions) => OAuthCallbackServer;
}

// OS のブラウザを開くコマンド（pure JS では開けないため subprocess を起動する）。
// interactive は CLI 専用で、lint が MCP からの import を遮断しているため許容する。
const browserOpener = (): { args: readonly string[]; command: string } => {
  if (process.platform === "darwin") {
    return { args: [], command: "open" };
  }
  if (process.platform === "win32") {
    return { args: ["/c", "start", ""], command: "cmd" };
  }
  return { args: [], command: "xdg-open" };
};

// consent URL をブラウザで開く。失敗してもプロセスを巻き込まないよう detach + stdio
// 無視で起動し、ハンドルを unref する。
const openBrowser = (url: string): void => {
  const { args, command } = browserOpener();
  const child = spawn(command, [...args, url], {
    detached: true,
    stdio: "ignore",
  });
  child.unref();
};

const defaultDeps: InteractiveDeps = {
  createOAuthClient: ({ clientId, clientSecret, redirectUri }) =>
    new OAuth2Client({ clientId, clientSecret, redirectUri }),
  exchangeCode: (client, code) =>
    defaultExchangeCode(client as OAuth2Client, code),
  generateState: generateOAuthState,
  openBrowser,
  serve: (options) => Bun.serve(options),
};

const requireCallbackServerPort = (server: OAuthCallbackServer): number => {
  if (server.port === undefined) {
    throw new Error("io: OAuth callback server did not expose a port");
  }
  return server.port;
};

const exchangeAuthCode = async (
  deps: InteractiveDeps,
  client: InteractiveOAuthClient,
  code: string
): Promise<Credentials> => {
  try {
    return await deps.exchangeCode(client, code);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(`auth: code exchange failed: ${message}`, { cause: error });
  }
};

const handleOAuthCallback = (
  request: Request,
  expectedState: string,
  resolve: (code: string) => void,
  reject: (error: Error) => void
): Response => {
  const callback = parseOAuthCallback(request, expectedState);
  if (callback.status === "not_found") {
    return new Response(null, { status: 404 });
  }
  if (callback.status === "error") {
    reject(callback.error);
    return new Response("認証に失敗しました。このタブを閉じてください。");
  }
  resolve(callback.code);
  return new Response("認証が完了しました。このタブを閉じてください。");
};

// ローカルコールバックサーバを ephemeral port で起動し、redirect の code を 1 回受け
// 取って token.json 文字列を返す。consent 拒否（error param）は auth エラーへ寄せる。
const runInteractiveFlow = async (
  clientSecretsJson: string,
  scopes: string[],
  deps: InteractiveDeps
): Promise<string> => {
  const { clientId, clientSecret } = parseClientSecrets(clientSecretsJson);
  const { promise, reject, resolve } = Promise.withResolvers<string>();
  const state = deps.generateState();

  const server = deps.serve({
    fetch: (request) => handleOAuthCallback(request, state, resolve, reject),
    hostname: "127.0.0.1",
    port: 0,
  });

  try {
    const redirectUri = `http://localhost:${requireCallbackServerPort(server)}/`;
    const client = deps.createOAuthClient({
      clientId,
      clientSecret,
      redirectUri,
    });
    deps.openBrowser(buildAuthUrl(client as OAuth2Client, scopes, state));
    const code = await promise;
    const tokens = await exchangeAuthCode(deps, client, code);
    return JSON.stringify(tokens);
  } finally {
    await server.stop(true);
  }
};

const interactiveAuthBoundary = createService(
  InteractiveAuthInput,
  OAuthTokenOutput,
  async ({ clientSecretsJson, scopes }, deps: InteractiveDeps) => ({
    tokenJson: await runInteractiveFlow(clientSecretsJson, scopes, deps),
  })
);

/**
 * ブラウザ consent でユーザーを認証し、発行された credentials を token.json 文字列で
 * 返す（CLI 専用）。入力・出力検証と Result 変換は `createService` に集約する。
 */
export const interactiveAuthService = (
  input: InteractiveAuthInput,
  deps: InteractiveDeps = defaultDeps
): Promise<Result<OAuthTokenOutput, ServiceError>> =>
  interactiveAuthBoundary(input, deps);
