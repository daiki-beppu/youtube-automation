import { expect, test, chromium, type BrowserContext } from "@playwright/test";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const extensionPath = join(here, "..", "..", ".output", "chrome-mv3");

test("実ビルドした overlay は drag・最小化・automation selector 契約を維持する", async () => {
  const profile = await mkdtemp(join(tmpdir(), "suno-helper-overlay-e2e-"));
  let context: BrowserContext | undefined;
  try {
    context = await chromium.launchPersistentContext(profile, {
      channel: "chromium",
      headless: false,
      args: [`--disable-extensions-except=${extensionPath}`, `--load-extension=${extensionPath}`],
    });
    let worker = context.serviceWorkers()[0];
    worker ??= await context.waitForEvent("serviceworker");
    expect(worker.url()).toContain("chrome-extension://");

    await context.route("https://suno.com/create", (route) =>
      route.fulfill({ status: 200, contentType: "text/html", body: "<!doctype html><title>Suno fixture</title>" }),
    );
    const page = await context.newPage();
    await page.goto("https://suno.com/create");

    const card = page.locator('[data-slot="card"]');
    const header = card.locator('[data-slot="card-header"]');
    const content = card.locator('[data-slot="card-content"]');
    await expect(card).toBeVisible();
    await expect(header).toHaveClass(/flex-row/);

    const before = await card.evaluate((element) => ({ left: element.style.left, top: element.style.top }));
    await header.dispatchEvent("pointerdown", { clientX: 100, clientY: 100 });
    await page.evaluate(() => window.dispatchEvent(new PointerEvent("pointermove", { clientX: 160, clientY: 140 })));
    await page.evaluate(() => window.dispatchEvent(new PointerEvent("pointerup")));
    await expect
      .poll(() => card.evaluate((element) => ({ left: element.style.left, top: element.style.top })))
      .not.toEqual(before);

    await card.getByRole("button", { name: "最小化" }).click();
    await expect(content).toHaveCSS("display", "none");
    await expect(card.getByRole("button", { name: "展開" })).toBeVisible();
    await card.getByRole("button", { name: "展開" }).click();
    await expect(content).toHaveCSS("display", "block");

    const panel = content.locator(':scope > [data-suno-helper="control-panel"]');
    // 実拡張はローカル配信元が無い fixture では fail-loud に error 状態へ遷移する。
    await expect(panel).toHaveAttribute("data-suno-phase", "error");
    await expect(panel).toHaveAttribute("data-suno-running", "false");
    await expect(panel).toHaveAttribute("data-suno-error", "true");
    const status = panel.getByRole("status");
    await expect(status).toHaveAttribute("aria-live", "polite");
    await expect(status).toHaveAttribute("data-suno-status", "error");
  } finally {
    await context?.close();
    await rm(profile, { recursive: true, force: true });
  }
});
