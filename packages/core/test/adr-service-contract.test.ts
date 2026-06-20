import { expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const repoRoot = resolve(import.meta.dir, "..", "..", "..");
const adr0003Path = resolve(
  repoRoot,
  "docs",
  "adr",
  "0003-service-boundary-contracts.md"
);

const sectionBetween = (
  markdown: string,
  startMarker: string,
  endMarker: string
): string => {
  const start = markdown.indexOf(startMarker);
  if (start === -1) {
    throw new Error(`missing ADR section: ${startMarker}`);
  }

  const end = markdown.indexOf(endMarker, start + startMarker.length);
  if (end === -1) {
    throw new Error(`missing ADR section: ${endMarker}`);
  }

  return markdown.slice(start, end);
};

test("ADR-0003 googleapis domain service example uses createService", () => {
  const markdown = readFileSync(adr0003Path, "utf-8");
  const googleapisClientSection = sectionBetween(
    markdown,
    "### 7. googleapis client",
    "### 8. schema"
  );

  expect(googleapisClientSection).toContain(
    "export const uploadVideoService = createService("
  );
  expect(googleapisClientSection).not.toMatch(
    /export\s+async\s+function\s+uploadVideoService/u
  );
});
