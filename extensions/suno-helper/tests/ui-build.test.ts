import { existsSync, readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { build } from "wxt";

import { MANIFEST_PERMISSIONS } from "@/lib/manifest";

const extensionDir = fileURLToPath(new URL("..", import.meta.url));
const outputDir = fileURLToPath(new URL("../.output/chrome-mv3", import.meta.url));

function findCssFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = `${directory}/${entry.name}`;
    return entry.isDirectory() ? findCssFiles(path) : entry.name.endsWith(".css") ? [path] : [];
  });
}

describe("Tailwind 4 build integration", () => {
  it("WXT build は Shadow DOM 用 overlay CSS と既存 manifest 契約を生成する", async () => {
    await build({ root: extensionDir });

    const cssFiles = findCssFiles(outputDir);
    expect(cssFiles).not.toHaveLength(0);
    const overlayCss = cssFiles.map((path) => readFileSync(path, "utf8")).find((css) => css.includes("--radius"));
    expect(overlayCss).toBeDefined();
    expect(overlayCss).toContain("--background:oklch(100% 0 0)");
    expect(overlayCss).toContain(":host");
    expect(overlayCss).toContain(".flex");
    expect(overlayCss).toContain(".text-gray-900");

    const manifest = JSON.parse(readFileSync(`${outputDir}/manifest.json`, "utf8")) as {
      action?: { default_popup?: string };
      content_scripts?: { js?: string[]; matches?: string[] }[];
      permissions?: string[];
    };
    expect(manifest.permissions).toEqual([...MANIFEST_PERMISSIONS]);
    expect(manifest.action?.default_popup).toBeUndefined();
    expect(manifest.content_scripts?.some(({ js }) => js?.some((path) => path.includes("overlay")))).toBe(true);
    expect(existsSync(`${outputDir}/popup.html`)).toBe(false);
  });
});
