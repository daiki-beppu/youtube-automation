import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";
import { build } from "wxt";

const extensionDir = fileURLToPath(new URL("..", import.meta.url));

describe("Community overlay build", () => {
  it("emits Shadow DOM CSS and no popup HTML", async () => {
    await build({ root: extensionDir });
    const outputDir = fileURLToPath(
      new URL("../.output/chrome-mv3", import.meta.url)
    );
    const overlayCss = `${outputDir}/content-scripts/overlay.css`;
    expect(existsSync(overlayCss)).toBe(true);
    expect(existsSync(`${outputDir}/popup.html`)).toBe(false);
    expect(readFileSync(overlayCss, "utf8")).toContain("--background");
  });
});
