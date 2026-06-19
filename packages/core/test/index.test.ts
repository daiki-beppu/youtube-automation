import { expect, test } from "bun:test";

// Imports by the published package name (not a relative path) so the test
// exercises the package `exports` map, not just the source file. A broken
// `exports` entry would fail resolution here instead of slipping past tsc.
import { greeting } from "@youtube-automation/core";

test("greeting() returns the skeleton banner", () => {
  expect(greeting()).toBe(
    "youtube-channels-automation core (TS rewrite skeleton)"
  );
});
