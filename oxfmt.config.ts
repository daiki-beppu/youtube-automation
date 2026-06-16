import { defineConfig } from "oxfmt";
import ultracite from "ultracite/oxfmt";

export default defineConfig({
  ...ultracite,
  ignorePatterns: [
    ...(ultracite.ignorePatterns ?? []),
    "src/youtube_automation/**",
    "tests/**",
    "pyproject.toml",
    "**/*.py",
    "extensions/**",
    "examples/**",
    "docs/**",
    "infra/**",
    "bench/**",
    "auth/**",
    "config/**",
    "launchd/**",
    "poc/**",
    "**/*.md",
    ".worktrees/**",
    ".claude/**",
    ".agents/**",
    ".takt/**",
    "_skills/**",
    "_claude_md/**",
  ],
});
