// @vitest-environment jsdom

import { describe, expect, it } from "vitest";
import { fakeBrowser } from "wxt/testing/fake-browser";

import playwrightConfig from "../playwright.config";
import vitestConfig from "../vitest.config";
import { installPointerEventFallback } from "./setup";

describe("distrokid-helper test configuration", () => {
  it("separates Vitest unit files from E2E and keeps aliases and dependency dedupe", () => {
    expect(vitestConfig.test?.setupFiles).toEqual(["./tests/setup.ts"]);
    expect(vitestConfig.test?.include).toEqual(["tests/**/*.test.{ts,tsx}"]);
    expect(vitestConfig.test?.exclude).toEqual(["tests/e2e/**"]);
    expect(vitestConfig.resolve?.alias).toMatchObject({
      "@": expect.stringContaining("extensions/distrokid-helper"),
    });
    expect(vitestConfig.resolve?.dedupe).toEqual([
      "react",
      "react-dom",
      "@base-ui/react",
    ]);
  });

  it("collects E2E from the dedicated directory in the parallel chromium project", () => {
    expect(playwrightConfig.testDir).toBe("./tests/e2e");
    expect(playwrightConfig.fullyParallel).toBe(true);
    expect(playwrightConfig.projects).toHaveLength(1);
    expect(playwrightConfig.projects?.[0]).toMatchObject({
      name: "chromium",
      use: expect.objectContaining({ defaultBrowserType: "chromium" }),
    });
  });

  it("installs extension globals and the PointerEvent fallback", () => {
    expect(Reflect.get(globalThis, "chrome")).toBe(fakeBrowser);
    expect(Reflect.get(globalThis, "browser")).toBe(fakeBrowser);
    expect(Reflect.get(globalThis, "IS_REACT_ACT_ENVIRONMENT")).toBe(true);
    const target: Parameters<typeof installPointerEventFallback>[0] = {
      MouseEvent: window.MouseEvent,
    };
    installPointerEventFallback(target);
    expect(target.PointerEvent).toBe(window.MouseEvent);
  });
});
