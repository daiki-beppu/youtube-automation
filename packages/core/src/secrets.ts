// アプリ層で秘密値を取得するヘルパー (Python `utils/secrets.py::get_secret` の移植)。
//
// 設計方針:
// - 秘密はシェル環境変数や .env に常時存在させず、必要になった瞬間に取得する
// - 取得経路は次の順で試行する
//     1. `process.env` にあればそれを使う (OSS 利用者の .env / 既存 export 経由)
//     2. `op` (1Password CLI) が利用可能なら `op read` で取得する
//     3. どちらも失敗したら ConfigError を throw する
//
// Python 版の lru_cache メモ化は移植しない: テスト契約が同一プロセスで env を
// 差し替えながら resolveSecret を繰り返し呼ぶため、都度解決する必要がある。

import { ConfigError } from "./errors.ts";

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
 * @throws {ConfigError} 未登録の名前、または全ての取得経路で失敗した場合
 */
export const resolveSecret = async (name: string): Promise<string> => {
  if (!Object.hasOwn(SECRET_REFS, name)) {
    throw new ConfigError(`未登録のシークレット名: ${name}`);
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

  throw new ConfigError(
    `${name} を取得できませんでした。\n` +
      `  → .env に ${name}=... を設定するか、\n` +
      `  → 1Password の ${opRef} に登録してください`
  );
};
