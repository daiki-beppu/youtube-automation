import { expect, test } from "bun:test";

test("guardrail bootstrap: bun:test runs", () => {
  expect(1 + 1).toBe(2);
});
