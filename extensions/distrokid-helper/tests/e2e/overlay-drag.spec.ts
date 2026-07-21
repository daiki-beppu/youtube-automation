import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test, chromium, type BrowserContext } from "@playwright/test";
import { rgbContrastRatio } from "@youtube-automation/ui";

const here = dirname(fileURLToPath(import.meta.url));
const extensionPath = join(here, "..", "..", ".output", "chrome-mv3");

test("実ビルドした DistroKid overlay は drag・最小化・reload 復元する", async () => {
  const profile = await mkdtemp(join(tmpdir(), "distrokid-overlay-e2e-"));
  let context: BrowserContext | undefined;
  try {
    context = await chromium.launchPersistentContext(profile, {
      channel: "chromium",
      headless: false,
      args: [
        `--disable-extensions-except=${extensionPath}`,
        `--load-extension=${extensionPath}`,
        "--host-resolver-rules=MAP youtube-automation.localhost ~NOTFOUND,MAP localhost ~NOTFOUND",
      ],
    });
    let worker = context.serviceWorkers()[0];
    worker ??= await context.waitForEvent("serviceworker");
    expect(worker.url()).toContain("chrome-extension://");

    await context.route("https://distrokid.com/new", (route) =>
      route.fulfill({
        status: 200,
        contentType: "text/html",
        body: "<!doctype html><title>DistroKid fixture</title>",
      })
    );
    const page = await context.newPage();
    await page.goto("https://distrokid.com/new");

    const shell = page.locator("[data-overlay-shell]");
    const handle = page.locator("[data-overlay-handle]");
    const content = page.locator("[data-overlay-content]");
    await expect(shell).toBeVisible();
    await expect(shell).toContainText("DistroKid Helper");
    expect(
      await shell.evaluate((element) => ({
        headerBackground: element.style.getPropertyValue(
          "--overlay-header-background"
        ),
        headerForeground: element.style.getPropertyValue(
          "--overlay-header-foreground"
        ),
        primary: element.style.getPropertyValue("--primary"),
        primaryForeground: element.style.getPropertyValue(
          "--primary-foreground"
        ),
      }))
    ).toEqual({
      headerBackground: "oklch(0.8703 0.1962 116.38)",
      headerForeground: "oklch(0.205 0 0)",
      primary: "oklch(0.8703 0.1962 116.38)",
      primaryForeground: "oklch(0.205 0 0)",
    });
    const paintedColors = await handle.evaluate((element) => {
      const canvas = document.createElement("canvas");
      canvas.width = 1;
      canvas.height = 1;
      const context = canvas.getContext("2d", { willReadFrequently: true })!;
      const sample = (color: string) => {
        context.clearRect(0, 0, 1, 1);
        context.fillStyle = "white";
        context.fillRect(0, 0, 1, 1);
        context.fillStyle = color;
        context.fillRect(0, 0, 1, 1);
        const [red, green, blue] = context.getImageData(0, 0, 1, 1).data;
        return [red, green, blue] as const;
      };
      const style = getComputedStyle(element);
      return {
        background: sample(style.backgroundColor),
        foreground: sample(style.color),
      };
    });
    expect(
      rgbContrastRatio(paintedColors.background, paintedColors.foreground)
    ).toBeGreaterThanOrEqual(4.5);
    const primaryControl = shell.locator("button.bg-primary").first();
    await expect(primaryControl).toBeVisible();
    expect(
      await primaryControl.evaluate(
        (element) => getComputedStyle(element).backgroundColor
      )
    ).toBe(
      await handle.evaluate(
        (element) => getComputedStyle(element).backgroundColor
      )
    );

    const before = await shell.evaluate((element) => ({
      left: element.style.left,
      top: element.style.top,
    }));
    await handle.dispatchEvent("pointerdown", { clientX: 100, clientY: 100 });
    await page.evaluate(() =>
      window.dispatchEvent(
        new PointerEvent("pointermove", { clientX: 160, clientY: 140 })
      )
    );
    await page.evaluate(() =>
      window.dispatchEvent(new PointerEvent("pointerup"))
    );
    await expect
      .poll(() =>
        shell.evaluate((element) => ({
          left: element.style.left,
          top: element.style.top,
        }))
      )
      .not.toEqual(before);

    await shell.getByRole("button", { name: "最小化" }).click();
    await expect(content).toHaveCSS("display", "none");
    const savedPosition = await shell.evaluate((element) => ({
      left: element.style.left,
      top: element.style.top,
    }));

    await page.reload();
    await expect(shell).toBeVisible();
    await expect(content).toHaveCSS("display", "none");
    await expect
      .poll(() =>
        shell.evaluate((element) => ({
          left: element.style.left,
          top: element.style.top,
        }))
      )
      .toEqual(savedPosition);
  } finally {
    await context?.close();
    await rm(profile, { recursive: true, force: true });
  }
});
