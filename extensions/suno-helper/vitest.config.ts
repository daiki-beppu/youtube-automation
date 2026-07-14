import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

// content script / API client / origin allowlist の unit テスト (要件8)。
// jsdom が必要なテストはファイル先頭の `// @vitest-environment jsdom` で個別指定する。
export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL(".", import.meta.url)),
    },
  },
  test: {
    environment: "node",
    include: ["tests/**/*.test.{ts,tsx}"],
    // Playwright の e2e spec は別 runner (test:e2e) で実行する。
    exclude: ["tests/e2e/**", "node_modules/**"],
  },
});
