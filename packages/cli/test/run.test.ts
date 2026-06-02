import { expect, spyOn, test } from "bun:test";
import process from "node:process";

// Importing core by its package name from the *cli* package is the actual
// cli→core `workspace:*` resolution under test: bun must link
// @youtube-automation/core into the cli workspace for this to resolve at
// `bun test` runtime. Broken workspace wiring fails here instead of silently
// degrading to a manual `bun bin/yt.ts` check.
import { greeting } from "@youtube-automation/core";

import { run } from "../src/index.ts";

test("run() prints the core greeting across the workspace boundary", () => {
  const writes: string[] = [];
  const spy = spyOn(process.stdout, "write").mockImplementation((chunk) => {
    writes.push(
      typeof chunk === "string" ? chunk : new TextDecoder().decode(chunk)
    );
    return true;
  });

  try {
    run();
  } finally {
    spy.mockRestore();
  }

  expect(writes.join("")).toBe(`${greeting()}\n`);
});
