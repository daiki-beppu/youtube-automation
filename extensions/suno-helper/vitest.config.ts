import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

const reactPath = fileURLToPath(
  new URL("./node_modules/react", import.meta.url)
);
const reactDomPath = fileURLToPath(
  new URL("./node_modules/react-dom", import.meta.url)
);

// content script / API client / origin allowlist の unit テスト (要件8)。
// jsdom が必要なテストはファイル先頭の `// @vitest-environment jsdom` で個別指定する。
export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL(".", import.meta.url)),
      react: reactPath,
      "react-dom": reactDomPath,
    },
    // Use the renderer's React for linked shared-ui primitives as well.
    dedupe: ["react", "react-dom"],
  },
  test: {
    environment: "node",
    server: {
      deps: {
        // Radix packages are otherwise externalized before the React alias applies.
        inline: [/@radix-ui/],
      },
    },
    include: ["tests/**/*.test.{ts,tsx}"],
    // Playwright の e2e spec は別 runner (test:e2e) で実行する。
    exclude: ["tests/e2e/**", "node_modules/**"],
  },
});
