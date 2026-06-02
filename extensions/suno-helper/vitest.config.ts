import { defineConfig } from "vitest/config";

// content script / API client / origin allowlist の unit テスト (要件8)。
// jsdom が必要なテストはファイル先頭の `// @vitest-environment jsdom` で個別指定する。
export default defineConfig({
  test: {
    environment: "node",
    include: ["tests/**/*.test.ts"],
    // Playwright の e2e spec は別 runner (test:e2e) で実行する。
    exclude: ["tests/e2e/**", "node_modules/**"],
  },
});
