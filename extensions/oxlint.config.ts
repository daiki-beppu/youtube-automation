import { defineConfig } from "oxlint";

import core from "ultracite/oxlint/core";
import react from "ultracite/oxlint/react";

export default defineConfig({
  extends: [core, react],
  globals: {
    browser: "readonly",
    chrome: "readonly",
  },
  // WXT の生成物は preset の ignore に含まれないため追加する
  ignorePatterns: [...core.ignorePatterns, "**/.wxt/**"],
  rules: {
    // 旧 .oxlintrc.json のルール水準を維持する（契約:
    // suno-helper/tests/oxlint-react-hooks-contract.test.ts）
    "react/exhaustive-deps": "warn",
    "react/react-compiler": "off",
  },
});
