import assert from "node:assert/strict";
import test from "node:test";
import { extractMarkdownTitle } from "../markdown-title.ts";

test("先頭 H1 を title と本文へ分離し、後続の見出し階層を保つ", () => {
  const markdown = "# Page title\n\nIntroduction\n\n## Details\n\nBody\n";

  const result = extractMarkdownTitle(markdown);

  assert.deepEqual(result, {
    text: "Introduction\n\n## Details\n\nBody\n",
    title: "Page title",
  });
});

test("先頭に H1 がない本文は明示的に拒否する", () => {
  const markdown = "Introduction\n\n## Details\n";

  assert.throws(() => extractMarkdownTitle(markdown), /leading H1/i);
});

test("空の先頭 H1 は明示的に拒否する", () => {
  const markdown = "#   \n\nBody\n";

  assert.throws(() => extractMarkdownTitle(markdown), /leading H1/i);
});
