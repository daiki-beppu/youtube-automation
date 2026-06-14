// token.json の永続化ヘルパ（ADR-0003 §6 / Python `oauth_handler._save_credentials`
// parity）。secret READ が cli 層へ移った対称として token WRITE も cli が担う。core は
// string in / string out に徹し、ファイル I/O はここで行う。
//
// セキュリティ契約: token.json は 0o600（owner のみ read/write）。新規作成・上書き双方で
// 保証する。通常の書き込み（O_TRUNC）は既存ファイルの mode を保つため、明示 chmod を保険
// として必ず後追いで適用する（Python oauth_handler.py:220）。

import { chmodSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

const TOKEN_FILE_MODE = 0o600;

// ENOENT（ファイル / 親ディレクトリ不在）のみ「token なし」として扱う。権限エラー等は
// 握りつぶさず throw する（fail fast）。
const isNotFound = (error: unknown): boolean =>
  typeof error === "object" &&
  error !== null &&
  "code" in error &&
  error.code === "ENOENT";

/**
 * token.json を 0o600 で書き込む。親ディレクトリが無ければ作成する。
 *
 * `writeFileSync` の mode 指定は新規作成時のみ効くため、既存ファイル上書き時の緩い mode
 * を締め直す chmod を必ず後追いで適用する。
 */
export const writeTokenJson = (path: string, json: string): void => {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, json, { encoding: "utf-8", mode: TOKEN_FILE_MODE });
  chmodSync(path, TOKEN_FILE_MODE);
};

/** token.json の内容文字列を返す。ファイルが無ければ null（初回認証前の合図）。 */
export const readTokenJson = (path: string): string | null => {
  try {
    return readFileSync(path, "utf-8");
  } catch (error) {
    if (isNotFound(error)) {
      return null;
    }
    throw error;
  }
};
