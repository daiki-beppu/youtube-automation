import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { build } from "wxt";

const extensionDir = fileURLToPath(new URL("..", import.meta.url));

function declarationBlocks(css: string, selector: string): Map<string, string>[] {
  const escapedSelector = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return [...css.matchAll(new RegExp(`${escapedSelector}\\{([^{}]*)\\}`, "g"))].map(
    ([, declarations]) =>
      new Map(
        declarations
          .split(";")
          .filter(Boolean)
          .map((declaration) => {
            const separator = declaration.indexOf(":");
            return [declaration.slice(0, separator), declaration.slice(separator + 1)];
          }),
      ),
  );
}

describe("Tailwind 4 build integration", () => {
  it("WXT build は utility、theme token、base style を popup CSS に生成する", async () => {
    await build({ root: extensionDir });

    const assetsDir = fileURLToPath(new URL("../.output/chrome-mv3/assets", import.meta.url));
    const popupCss = readdirSync(assetsDir).find((name) => /^popup-.*\.css$/.test(name));

    expect(popupCss).toBeDefined();
    const css = readFileSync(`${assetsDir}/${popupCss}`, "utf8");
    expect(declarationBlocks(css, ".bg-background")).toContainEqual(
      new Map([["background-color", "var(--background)"]]),
    );
    expect(declarationBlocks(css, ":root")).toContainEqual(
      expect.objectContaining(
        new Map([
          ["--radius", ".625rem"],
          ["--background", "oklch(100% 0 0)"],
        ]),
      ),
    );
    expect(declarationBlocks(css, "*")).toContainEqual(
      new Map([
        ["border-color", "var(--border)"],
        ["outline-color", "var(--ring)"],
      ]),
    );
    expect(declarationBlocks(css, "body")).toContainEqual(
      new Map([
        ["background-color", "var(--background)"],
        ["color", "var(--foreground)"],
      ]),
    );
  });
});
