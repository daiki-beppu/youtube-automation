import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

// unit テスト（tests/**/*.test.{ts,tsx}）専用。E2E（tests/e2e）は Playwright が担う。
//
// setupFiles で fakeBrowser を chrome/browser グローバルへ注入し、
// lib/messaging.ts（webextension-polyfill のロード時チェック）と
// lib/storage.ts（@wxt-dev/storage の eager getItem）が node 環境で動くようにする。
//
// 既定環境は node。DOM 注入テストはファイル先頭の `// @vitest-environment jsdom` で個別指定する。
export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL(".", import.meta.url)),
    },
  },
  test: {
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}"],
    exclude: ["tests/e2e/**"],
  },
});
