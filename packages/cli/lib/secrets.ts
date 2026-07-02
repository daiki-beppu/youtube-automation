// アプリ層で秘密値を取得するヘルパー (Python `utils/secrets.py::get_secret` および
// `auth/oauth_handler` の client_secrets 探索の移植)。
//
// #822 で `packages/core/src/secrets.ts` から cli 層へ移設した。op (1Password CLI)
// の subprocess 起動はインフラ依存であり、ADR 0002 の「core は pure domain logic /
// 重い依存・subprocess は cli/service 層に隔離」方針に従う。core から op を直接
// 呼ぶ regression は oxlint (`packages/core/src/**`) で error 化して防ぐ。
//
// 設計方針:
// - 秘密はシェル環境変数や .env に常時存在させず、必要になった瞬間に取得する
// - 取得経路は次の順で試行する
//     1. `process.env` にあればそれを使う (OSS 利用者の .env / 既存 export 経由)
//     2. `op` (1Password CLI) が利用可能なら `op read` で取得する
//     3. どちらも失敗したら `config:` prefix 付き Error を throw する
//
// Python 版の lru_cache メモ化は移植しない: テスト契約が同一プロセスで env を
// 差し替えながら resolveSecret を繰り返し呼ぶため、都度解決する必要がある。

import { existsSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { channelDir } from "@youtube-automation/core/config";
// 具体キーを保持して既知名の参照を `string` 型に確定させつつ、`satisfies` で
// 値の型 (URI 文字列) を担保する。
/** 登録済みシークレット名と 1Password 参照 URI のテーブル (Python `_SECRET_REFS` の移植)。 */
export const SECRET_REFS = {
  CLIENT_SECRETS_JSON: "op://Personal/YouTube_OAuth_Client_Secrets/credential",
  DISCORD_WEBHOOK_URL: "op://Personal/YouTube_Stream_Discord_Webhook/url",
  OPENAI_API_KEY: "op://Personal/OpenAI_API_Key/credential",
  STREAM_WEBHOOK_URL: "op://Personal/Stream_Notification_Webhook/url",
  VULTR_API_KEY: "op://Personal/Vultr/api_key",
  YOUTUBE_STREAM_KEY: "op://Personal/YouTube/stream_key",
} satisfies Record<string, string>;

const OP_BIN = "op";
const OP_READ_TIMEOUT_MS = 10_000;

// `op read <ref>` を実行して値を返す。op が値を供給しなかった場合 (PATH 不在は
// 呼び出し側で判定済み・非ゼロ終了・空出力) は null を返し、上位の throw に委ねる。
const readFromOp = async (opRef: string): Promise<string | null> => {
  const proc = Bun.spawn([OP_BIN, "read", opRef], {
    // stderr は読まないため drain 不要の "ignore" にする (op のエラー出力は抑止)。
    stderr: "ignore",
    stdout: "pipe",
    timeout: OP_READ_TIMEOUT_MS,
  });
  const exitCode = await proc.exited;
  if (exitCode !== 0) {
    return null;
  }
  const stdout = await new Response(proc.stdout).text();
  const value = stdout.trim();
  return value === "" ? null : value;
};

/**
 * 登録済みシークレット名を解決する。
 *
 * @param name `SECRET_REFS` に登録されたシークレット名
 * @returns 解決した値
 * @throws {Error} `config:` prefix — 未登録の名前、または全ての取得経路で失敗した場合
 */
export const resolveSecret = async (name: string): Promise<string> => {
  if (!Object.hasOwn(SECRET_REFS, name)) {
    throw new Error(`config: 未登録のシークレット名: ${name}`);
  }
  const opRef = SECRET_REFS[name as keyof typeof SECRET_REFS];

  const envValue = process.env[name];
  if (envValue) {
    return envValue;
  }

  if (Bun.which(OP_BIN)) {
    const value = await readFromOp(opRef);
    if (value !== null) {
      return value;
    }
  }

  throw new Error(
    `config: ${name} を取得できませんでした。\n` +
      `  → .env に ${name}=... を設定するか、\n` +
      `  → 1Password の ${opRef} に登録してください`
  );
};

const CLIENT_SECRETS_FILENAME = "client_secrets.json";

const readClientSecretsFile = (filePath: string): string | null => {
  if (!existsSync(filePath)) {
    return null;
  }
  if (!statSync(filePath).isFile()) {
    throw new Error(
      `config: client_secrets.json は通常ファイルである必要があります: ${filePath}`
    );
  }
  return readFileSync(filePath, "utf-8");
};

/**
 * OAuth client_secrets.json の **中身** (JSON 文字列) を解決する。
 *
 * Python `auth/oauth_handler` の探索順を踏襲した fallback chain:
 *   1. `CLIENT_SECRETS_DIR/client_secrets.json` 明示 override
 *   2. `<channel>/auth/client_secrets.json` ファイル
 *   3. `<channel>/automation/auth/client_secrets.json` ファイル
 *   4. `CLIENT_SECRETS_JSON` env / `op read SECRET_REFS.CLIENT_SECRETS_JSON`
 *
 * @returns client_secrets.json の内容文字列 (パスではなく content)
 * @throws {Error} `config:` prefix — 全ての取得経路で失敗した場合
 */
export const resolveClientSecretsJson = async (): Promise<string> => {
  const clientSecretsDir = process.env.CLIENT_SECRETS_DIR;
  if (clientSecretsDir) {
    const overridePath = join(clientSecretsDir, CLIENT_SECRETS_FILENAME);
    const content = readClientSecretsFile(overridePath);
    if (content !== null) {
      return content;
    }
    throw new Error(
      `config: CLIENT_SECRETS_DIR に client_secrets.json が見つかりません: ${overridePath}`
    );
  }

  const dir = channelDir();
  for (const filePath of [
    join(dir, "auth", CLIENT_SECRETS_FILENAME),
    join(dir, "automation", "auth", CLIENT_SECRETS_FILENAME),
  ]) {
    const content = readClientSecretsFile(filePath);
    if (content !== null) {
      return content;
    }
  }

  // file が無ければ env / op 経路 (+ 最終 throw) を resolveSecret に委ねる。
  return await resolveSecret("CLIENT_SECRETS_JSON");
};
