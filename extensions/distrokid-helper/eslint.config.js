import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    // distrokid-helper と sibling の ../shared を 1 回の実行で lint するため cwd=extensions/
    // から `--config` 経由で実行する（lint script 参照）。base path が extensions/ に
    // なるので、生成物の ignore は深さ非依存の `**/` 前置で各拡張配下を捕捉する。
    ignores: ["**/.wxt/**", "**/.output/**", "**/dist/**", "**/node_modules/**"],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    plugins: {
      "react-hooks": reactHooks,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
    },
  },
);
