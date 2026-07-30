import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

const rootUrl = new URL(".", import.meta.url);
const rootPath =
  rootUrl.protocol === "file:" ? fileURLToPath(rootUrl) : rootUrl.pathname;

export default defineConfig({
  resolve: {
    alias: {
      "@": rootPath,
    },
    dedupe: ["react", "react-dom", "@base-ui/react"],
  },
  test: {
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}"],
    exclude: ["tests/e2e/**"],
  },
});
