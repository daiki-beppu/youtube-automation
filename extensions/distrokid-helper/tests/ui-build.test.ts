import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";
import { build } from "wxt";

const extensionDir = fileURLToPath(new URL("..", import.meta.url));

function declarationBlocks(
  css: string,
  selector: string
): Map<string, string>[] {
  const escapedSelector = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return [
    ...css.matchAll(new RegExp(`${escapedSelector}\\{([^{}]*)\\}`, "g")),
  ].map(
    ([, declarations]) =>
      new Map(
        declarations
          .split(";")
          .filter(Boolean)
          .map((declaration) => {
            const separator = declaration.indexOf(":");
            return [
              declaration.slice(0, separator),
              declaration.slice(separator + 1),
            ];
          })
      )
  );
}

describe("Tailwind 4 build integration", () => {
  it("WXT build は Shadow DOM overlay CSS を生成し popup を生成しない", async () => {
    await build({ root: extensionDir });

    const outputDir = fileURLToPath(
      new URL("../.output/chrome-mv3", import.meta.url)
    );
    const overlayCss = `${outputDir}/content-scripts/overlay.css`;
    expect(existsSync(overlayCss)).toBe(true);
    expect(existsSync(`${outputDir}/popup.html`)).toBe(false);
    const css = readFileSync(overlayCss, "utf8");
    expect(declarationBlocks(css, ".bg-background")).toContainEqual(
      new Map([["background-color", "var(--background)"]])
    );
    expect(declarationBlocks(css, ":root,:host")).toContainEqual(
      expect.objectContaining(
        new Map([
          ["--radius", ".625rem"],
          ["--background", "oklch(97% 0 0)"],
        ])
      )
    );
    expect(declarationBlocks(css, "*")).toContainEqual(
      new Map([
        ["border-color", "var(--border)"],
        ["outline-color", "var(--ring)"],
      ])
    );
    expect(declarationBlocks(css, "body")).toContainEqual(
      new Map([
        ["background-color", "var(--background)"],
        ["color", "var(--foreground)"],
      ])
    );
  });
});
