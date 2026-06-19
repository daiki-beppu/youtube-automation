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

import { createService } from "../service-frame.ts";
import { buildAuthUrl, exchangeCode } from "./interactive-internal.ts";
import { parseClientSecrets } from "./internal.ts";
import { InteractiveAuthInput, OAuthTokenOutput } from "./schema.ts";

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

// ローカルコールバックサーバを ephemeral port で起動し、redirect の code を 1 回受け
// 取って token.json 文字列を返す。consent 拒否（error param）は auth エラーへ寄せる。
const runInteractiveFlow = async (
  clientSecretsJson: string,
  scopes: string[]
): Promise<string> => {
  const { clientId, clientSecret } = parseClientSecrets(clientSecretsJson);
  const { promise, reject, resolve } = Promise.withResolvers<string>();

  const server = Bun.serve({
    fetch: (request) => {
      const { searchParams } = new URL(request.url);
      const code = searchParams.get("code");
      const denied = searchParams.get("error");
      if (code) {
        resolve(code);
        return new Response("認証が完了しました。このタブを閉じてください。");
      }
      if (denied) {
        reject(new Error(`auth: consent denied: ${denied}`));
        return new Response("認証に失敗しました。このタブを閉じてください。");
      }
      return new Response(null, { status: 404 });
    },
    hostname: "127.0.0.1",
    port: 0,
  });

  try {
    const redirectUri = `http://localhost:${server.port}/`;
    const client = new OAuth2Client({ clientId, clientSecret, redirectUri });
    openBrowser(buildAuthUrl(client, scopes));
    const code = await promise;
    const tokens = await exchangeCode(client, code);
    return JSON.stringify(tokens);
  } finally {
    await server.stop(true);
  }
};

/**
 * ブラウザ consent でユーザーを認証し、発行された credentials を token.json 文字列で
 * 返す（CLI 専用）。入力 / 出力検証と `ServiceError` 変換は `createService` 境界が
 * 担う（throw しない）。
 */
export const interactiveAuthService = createService(
  InteractiveAuthInput,
  OAuthTokenOutput,
  async ({ clientSecretsJson, scopes }) => {
    const tokenJson = await runInteractiveFlow(clientSecretsJson, scopes);
    return { tokenJson };
  }
);
