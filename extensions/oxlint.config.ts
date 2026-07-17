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
    // suno-helper/tests/oxlint-react-hooks-contract.test.ts）。
    // rules-of-hooks は preset にも含まれるが、oxlint 1.x の TS config では
    // extends 経由の指定が解決済み config へ反映されないため root で明示する。
    "react/exhaustive-deps": "warn",
    "react/react-compiler": "off",
    "react/rules-of-hooks": "error",

    // ── 以下は preset 導入時点で既存コードに違反が残るルール。
    // 本移行は「既存ルール水準の維持 + preset 移行」に絞るため（#2154）、
    // 旧構成で未適用だった水準に合わせて off にする。段階的な有効化は別 issue で行う。
    // eslint
    "arrow-body-style": "off",
    complexity: "off",
    curly: "off",
    eqeqeq: "off",
    "func-style": "off",
    "max-classes-per-file": "off",
    "no-await-in-loop": "off",
    "no-duplicate-imports": "off",
    "no-empty-function": "off",
    "no-eq-null": "off",
    "no-inline-comments": "off",
    "no-lonely-if": "off",
    "no-loop-func": "off",
    "no-negated-condition": "off",
    "no-nested-ternary": "off",
    "no-param-reassign": "off",
    "no-plusplus": "off",
    "no-promise-executor-return": "off",
    "no-shadow": "off",
    "no-use-before-define": "off",
    "no-useless-concat": "off",
    "prefer-destructuring": "off",
    "prefer-named-capture-group": "off",
    "prefer-object-has-own": "off",
    "prefer-template": "off",
    "require-await": "off",
    "require-unicode-regexp": "off",
    "sort-keys": "off",
    // import
    "import/consistent-type-specifier-style": "off",
    "import/first": "off",
    "import/no-duplicates": "off",
    // promise
    "promise/avoid-new": "off",
    "promise/no-multiple-resolved": "off",
    "promise/param-names": "off",
    "promise/prefer-await-to-callbacks": "off",
    "promise/prefer-await-to-then": "off",
    "promise/prefer-catch": "off",
    // typescript
    "typescript/array-type": "off",
    "typescript/consistent-generic-constructors": "off",
    "typescript/consistent-type-definitions": "off",
    "typescript/consistent-type-imports": "off",
    "typescript/method-signature-style": "off",
    "typescript/no-dynamic-delete": "off",
    "typescript/no-invalid-void-type": "off",
    "typescript/no-non-null-assertion": "off",
    "typescript/parameter-properties": "off",
    // unicorn
    "unicorn/catch-error-name": "off",
    "unicorn/consistent-existence-index-check": "off",
    "unicorn/consistent-function-scoping": "off",
    "unicorn/custom-error-definition": "off",
    "unicorn/filename-case": "off",
    "unicorn/import-style": "off",
    "unicorn/no-array-for-each": "off",
    "unicorn/no-array-sort": "off",
    "unicorn/no-await-expression-member": "off",
    "unicorn/no-instanceof-array": "off",
    "unicorn/no-instanceof-builtins": "off",
    "unicorn/no-negated-condition": "off",
    "unicorn/no-nested-ternary": "off",
    "unicorn/no-object-as-default-parameter": "off",
    "unicorn/no-useless-fallback-in-spread": "off",
    "unicorn/no-useless-promise-resolve-reject": "off",
    "unicorn/no-useless-undefined": "off",
    "unicorn/numeric-separators-style": "off",
    "unicorn/prefer-array-find": "off",
    "unicorn/prefer-at": "off",
    "unicorn/prefer-code-point": "off",
    "unicorn/prefer-dom-node-append": "off",
    "unicorn/prefer-dom-node-dataset": "off",
    "unicorn/prefer-import-meta-properties": "off",
    "unicorn/prefer-math-min-max": "off",
    "unicorn/prefer-query-selector": "off",
    "unicorn/prefer-response-static-json": "off",
    "unicorn/prefer-set-has": "off",
    "unicorn/prefer-spread": "off",
    "unicorn/prefer-string-replace-all": "off",
    "unicorn/prefer-type-error": "off",
    "unicorn/relative-url-style": "off",
    "unicorn/switch-case-braces": "off",
    "unicorn/text-encoding-identifier-case": "off",
  },
});
