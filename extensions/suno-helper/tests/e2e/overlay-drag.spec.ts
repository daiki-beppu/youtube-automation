import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test, chromium, type BrowserContext } from "@playwright/test";
import { rgbContrastRatio } from "@youtube-automation/ui";

const here = dirname(fileURLToPath(import.meta.url));
const extensionPath = join(here, "..", "..", ".output", "chrome-mv3");

test("実ビルドした overlay は drag・最小化・automation selector 契約を維持する", async () => {
  const profile = await mkdtemp(join(tmpdir(), "suno-helper-overlay-e2e-"));
  let context: BrowserContext | undefined;
  try {
    context = await chromium.launchPersistentContext(profile, {
      channel: "chromium",
      headless: false,
      args: [
        `--disable-extensions-except=${extensionPath}`,
        `--load-extension=${extensionPath}`,
        // 拡張 service worker の fetch は context.route を通らないため、
        // 開発マシンで稼働中の yt-collection-serve（7873/7872）を DNS 層で遮断して
        // 「ローカル配信元なし」の前提を環境に依存せず成立させる。
        "--host-resolver-rules=MAP youtube-automation.localhost ~NOTFOUND,MAP localhost ~NOTFOUND",
      ],
    });
    let worker = context.serviceWorkers()[0];
    worker ??= await context.waitForEvent("serviceworker");
    expect(worker.url()).toContain("chrome-extension://");

    await context.route("https://suno.com/create", (route) =>
      route.fulfill({
        status: 200,
        contentType: "text/html",
        body: "<!doctype html><title>Suno fixture</title>",
      })
    );
    const page = await context.newPage();
    await page.goto("https://suno.com/create");

    const card = page.locator('[data-slot="card"]');
    const header = card.locator('[data-slot="card-header"]');
    const content = card.locator('[data-slot="card-content"]');
    await expect(card).toBeVisible();
    await expect(header).toHaveClass(/flex-row/);
    expect(
      await card.evaluate((element) => ({
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
      headerBackground: "oklch(0.753 0.2067 57.6 / 96.4%)",
      headerForeground: "oklch(0.205 0 0)",
      primary: "oklch(0.753 0.2067 57.6 / 96.4%)",
      primaryForeground: "oklch(0.205 0 0)",
    });
    const paintedColors = await header.evaluate((element) => {
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
    const before = await card.evaluate((element) => ({
      left: element.style.left,
      top: element.style.top,
    }));
    await header.dispatchEvent("pointerdown", { clientX: 100, clientY: 100 });
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
        card.evaluate((element) => ({
          left: element.style.left,
          top: element.style.top,
        }))
      )
      .not.toEqual(before);

    await card.getByRole("button", { name: "最小化" }).click();
    await expect(content).toHaveCSS("display", "none");
    await expect(card.getByRole("button", { name: "展開" })).toBeVisible();
    await card.getByRole("button", { name: "展開" }).click();
    await expect(content).toHaveCSS("display", "block");

    const panel = content.locator(
      ':scope > [data-suno-helper="control-panel"]'
    );
    // 実拡張はローカル配信元が無い fixture では fail-loud に error 状態へ遷移する。
    await expect(panel).toHaveAttribute("data-suno-phase", "error");
    await expect(panel).toHaveAttribute("data-suno-running", "false");
    await expect(panel).toHaveAttribute("data-suno-error", "true");
    const status = panel.getByRole("status");
    await expect(status).toHaveAttribute("aria-live", "polite");
    await expect(status).toHaveAttribute("data-suno-status", "error");

    const collectionsTrigger = panel.locator(
      '[data-suno-control="collections-collapsible-trigger"]'
    );
    const entriesTrigger = panel.locator(
      '[data-suno-control="entries-collapsible-trigger"]'
    );
    await expect(collectionsTrigger).toContainText("コレクション (0)");
    await expect(entriesTrigger).toContainText("楽曲 (0)");
    await expect(collectionsTrigger).toHaveAttribute("aria-expanded", "false");
    await expect(entriesTrigger).toHaveAttribute("aria-expanded", "false");
    await collectionsTrigger.press("Space");
    await expect(collectionsTrigger).toHaveAttribute("aria-expanded", "true");
    await expect(entriesTrigger).toHaveAttribute("aria-expanded", "false");
  } finally {
    await context?.close();
    await rm(profile, { recursive: true, force: true });
  }
});
