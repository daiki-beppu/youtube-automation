import { defineConfig } from "oxlint";
import core from "ultracite/oxlint/core";

// ADR 0002 (service-first architecture) で確定した「packages/{cli,mcp}/** からの重い依存
// 直 import 禁止」を mechanical に enforce する rule 定義。core から service を呼ばせる。
const HEAVY_DEPS_BANNED_IN_THIN_CLIENTS = {
  paths: [
    {
      message:
        "ADR 0002: googleapis は packages/core の service 経由でのみ使用。packages/cli・packages/mcp は service を呼ぶ thin client にしてください。",
      name: "googleapis",
    },
    {
      message:
        "ADR 0002: auth handling は packages/core/auth の service にカプセル化。cli/mcp からの直 import は禁止。",
      name: "google-auth-library",
    },
    {
      message:
        "ADR 0002: image processing は packages/core/image の service 経由で使用。cli/mcp からの直 import は禁止。",
      name: "sharp",
    },
    {
      message:
        "ADR 0002: MCP SDK は packages/mcp/server.ts の MCP server entry でのみ使用。それ以外 (CLI / core) から直接 import しないでください。",
      name: "@modelcontextprotocol/sdk",
    },
  ],
  patterns: ["googleapis/*"],
};

export default defineConfig({
  extends: [core],
  ignorePatterns: [
    ...(core.ignorePatterns ?? []),
    "src/youtube_automation/**",
    "tests/**",
    "extensions/**",
    "examples/**",
    "docs/**",
    "poc/**",
    ".worktrees/**",
    ".claude/worktrees/**",
    "_skills/**",
  ],
  overrides: [
    {
      files: ["packages/cli/**", "packages/mcp/**"],
      rules: {
        "no-restricted-imports": ["error", HEAVY_DEPS_BANNED_IN_THIN_CLIENTS],
      },
    },
  ],
});
