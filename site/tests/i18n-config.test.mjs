import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("Blume の検索 index と UI に日本語 locale を指定する", async () => {
  const config = await readFile(new URL("../blume.config.ts", import.meta.url), "utf8");

  assert.match(
    config,
    /i18n:\s*\{\s*defaultLocale:\s*["']ja["'],\s*locales:\s*\[\s*\{\s*code:\s*["']ja["'],\s*label:\s*["']日本語["']\s*\}\s*\],?\s*\}/
  );
});
