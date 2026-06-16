// Shared test helper: extracts a file's permission bits for 0o600 assertions.
//
// Both the token persistence suite (token.test.ts) and the getYouTubeClient
// glue suite (oauth.test.ts) verify the 0o600 security contract, so the
// statSync mask lives here once rather than being copy-pasted per file.
//
// Not a `*.test.ts` file, so bun does not run it directly; it is imported by the
// token/oauth suites (mirrors the config-fixtures.ts convention).

import { statSync } from "node:fs";

// 0o777 マスクで permission bits を取り出す（ファイル mode のビット演算は
// no-bitwise の対象外用途）。
export const permissionBits = (path: string): number => {
  const { mode } = statSync(path);
  // oxlint-disable-next-line no-bitwise
  return mode & 0o777;
};
