import { defineConfig } from "oxlint";
import core from "ultracite/oxlint/core";

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
});
