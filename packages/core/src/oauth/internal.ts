// client_secrets.json から OAuth クライアント資格情報を抽出する内部ヘルパ。
//
// Google Auth Platform の Desktop app client_secrets.json から client_id /
// client_secret を取り出す。ADR-0003 §8 に従い手書きの isRecord / parseX ではなく
// zod で構造検証する。installed ブロックには auth_uri / token_uri / redirect_uris 等
// Google 固有キーが同居するため `.strict()` は付けず、Desktop app 契約上の必須キーのみ見る。

import { z } from "zod";

const ClientSecretsBlock = z.object({
  client_id: z.string(),
  client_secret: z.string(),
  redirect_uris: z.array(z.string()).nonempty(),
});

const ClientSecretsSchema = z.object({
  installed: ClientSecretsBlock.optional(),
});

// 抽出後（camelCase）の戻り値シェイプ。schema 並書ではなく helper の返り値型。
interface ClientCredentials {
  readonly clientId: string;
  readonly clientSecret: string;
}

/**
 * client_secrets.json 文字列から clientId / clientSecret を取り出す。
 *
 * @throws {Error} `config:` prefix — JSON 不正、または installed ブロック欠落
 * @throws {z.ZodError} ブロックに client_id / client_secret / redirect_uris が無い場合
 *   （境界の `toServiceError` が validation ドメインへ変換する）
 */
export const parseClientSecrets = (
  clientSecretsJson: string
): ClientCredentials => {
  let raw: unknown;
  try {
    raw = JSON.parse(clientSecretsJson);
  } catch {
    throw new Error("config: client_secrets.json が JSON として不正です");
  }
  const parsed = ClientSecretsSchema.parse(raw);
  const block = parsed.installed;
  if (!block) {
    throw new Error("config: Desktop app の installed ブロックが必要です");
  }
  return {
    clientId: block.client_id,
    clientSecret: block.client_secret,
  };
};
