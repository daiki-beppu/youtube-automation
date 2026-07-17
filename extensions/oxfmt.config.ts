import { defineConfig } from "oxfmt";

import ultracite from "ultracite/oxfmt";

export default defineConfig({
  ...ultracite,
  // WXT の生成物は preset の ignore に含まれないため追加する
  ignorePatterns: [...ultracite.ignorePatterns, "**/.wxt/**"],
});
