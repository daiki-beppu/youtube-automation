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

// #822: packages/core は pure domain logic。op (1Password CLI) を含む subprocess
// 起動は cli/service 層 (packages/cli/lib/secrets.ts) に隔離する。core/src 配下で
// `Bun.spawn` / `Bun.spawnSync` / `bun:ffi` を直接呼ぶ regression を error 化する。
const OP_SPAWN_BANNED_IN_CORE = [
  {
    message:
      "#822: subprocess 起動 (op CLI 含む) は packages/cli/lib/secrets.ts に隔離。packages/core/src からの Bun.spawn 直呼びは禁止。",
    object: "Bun",
    property: "spawn",
  },
  {
    message:
      "#822: subprocess 起動 (op CLI 含む) は packages/cli/lib/secrets.ts に隔離。packages/core/src からの Bun.spawnSync 直呼びは禁止。",
    object: "Bun",
    property: "spawnSync",
  },
];

// ADR 0003 §5 / Enforcement: interactiveAuthService は browser open + local server を
// 起動する CLI 専用 service。MCP サーバプロセスは browser を開けず boot 時に hang する
// ため、packages/mcp/** からの `**/oauth/interactive*` import を path-based で error 化
// する (CLI は許可)。subpath import (@tayk/core/oauth/interactive) と相対
// import の両方を捕捉する。
const INTERACTIVE_OAUTH_BANNED_IN_MCP = "**/oauth/interactive*";

// ADR 0004: cli と mcp は互いに独立 (依存方向は core ← cli / core ← mcp のみ)。
// registry は @tayk/core/registry を使い、相互 import を禁止する。
const ADR0004_MUTUAL_BAN_MESSAGE =
  "ADR 0004: cli と mcp は互いに独立。共有したいものは packages/core (例: @tayk/core/registry) に置いてください。";

const MCP_BANNED_IN_CLI = {
  message: ADR0004_MUTUAL_BAN_MESSAGE,
  name: "@tayk/mcp",
};

const CLI_BANNED_IN_MCP = {
  message: ADR0004_MUTUAL_BAN_MESSAGE,
  name: "@tayk/cli",
};

const FFI_BANNED_IN_CORE = {
  paths: [
    {
      message:
        "#822: bun:ffi (native spawn) は packages/core から使用禁止。subprocess は cli/service 層へ。",
      name: "bun:ffi",
    },
  ],
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
      files: ["packages/cli/**"],
      rules: {
        "no-restricted-imports": [
          "error",
          {
            paths: [
              ...HEAVY_DEPS_BANNED_IN_THIN_CLIENTS.paths,
              MCP_BANNED_IN_CLI,
            ],
            patterns: [
              ...HEAVY_DEPS_BANNED_IN_THIN_CLIENTS.patterns,
              "@tayk/mcp/*",
            ],
          },
        ],
      },
    },
    {
      files: ["packages/mcp/**"],
      rules: {
        "no-restricted-imports": [
          "error",
          {
            paths: [
              ...HEAVY_DEPS_BANNED_IN_THIN_CLIENTS.paths,
              CLI_BANNED_IN_MCP,
            ],
            patterns: [
              ...HEAVY_DEPS_BANNED_IN_THIN_CLIENTS.patterns,
              "@tayk/cli/*",
              INTERACTIVE_OAUTH_BANNED_IN_MCP,
            ],
          },
        ],
      },
    },
    {
      files: ["packages/core/src/**"],
      rules: {
        "no-restricted-imports": ["error", FFI_BANNED_IN_CORE],
        "no-restricted-properties": ["error", ...OP_SPAWN_BANNED_IN_CORE],
      },
    },
  ],
});
