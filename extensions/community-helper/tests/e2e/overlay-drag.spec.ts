import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test, chromium, type BrowserContext } from "@playwright/test";

const here = dirname(fileURLToPath(import.meta.url));
const extensionPath = join(here, "..", "..", ".output", "chrome-mv3");

test("実ビルドした Community overlay は drag・最小化・reload 復元する", async () => {
  const profile = await mkdtemp(join(tmpdir(), "community-overlay-e2e-"));
  let context: BrowserContext | undefined;
  try {
    context = await chromium.launchPersistentContext(profile, {
      channel: "chromium",
      headless: false,
      args: [
        `--disable-extensions-except=${extensionPath}`,
        `--load-extension=${extensionPath}`,
      ],
    });
    let worker = context.serviceWorkers()[0];
    worker ??= await context.waitForEvent("serviceworker");
    expect(worker.url()).toContain("chrome-extension://");

    const postsUrl = "https://www.youtube.com/channel/test-channel/posts";
    await context.route(postsUrl, (route) =>
      route.fulfill({
        status: 200,
        contentType: "text/html",
        body: "<!doctype html><title>YouTube posts fixture</title>",
      })
    );
    const page = await context.newPage();
    await page.goto(postsUrl);
    await page.evaluate(() => {
      document.documentElement.style.fontSize = "10px";
    });

    const shell = page.locator("[data-overlay-shell]");
    const handle = page.locator("[data-overlay-handle]");
    const content = page.locator("[data-overlay-content]");
    await expect(shell).toBeVisible();
    await expect(shell).toContainText("Community Helper");
    await expect(handle).toHaveCSS("background-color", "rgb(201, 0, 40)");
    await expect(handle).toHaveCSS("color", "rgb(255, 255, 255)");

    const main = page.locator("[data-overlay-content] main");
    const input = page.locator('input[name="serverUrl"]');
    const startButton = page.getByRole("button", { name: "Start" });
    const readSizes = async () => {
      const [shellStyle, handleStyle, mainStyle, inputStyle, buttonStyle] =
        await Promise.all(
          [shell, handle, main, input, startButton].map((locator) =>
            locator.evaluate((element) => {
              const style = getComputedStyle(element);
              return {
                width: style.width,
                borderRadius: style.borderRadius,
                fontSize: style.fontSize,
                paddingTop: style.paddingTop,
                height: style.height,
              };
            })
          )
        );
      return {
        shellWidth: shellStyle.width,
        shellRadius: shellStyle.borderRadius,
        handleFontSize: handleStyle.fontSize,
        handlePaddingTop: handleStyle.paddingTop,
        mainPadding: mainStyle.paddingTop,
        inputFontSize: inputStyle.fontSize,
        inputRadius: inputStyle.borderRadius,
        buttonHeight: buttonStyle.height,
      };
    };

    const youtubeRootSizes = await readSizes();
    expect(youtubeRootSizes).toEqual({
      shellWidth: "360px",
      shellRadius: "10px",
      handleFontSize: "14px",
      handlePaddingTop: "8px",
      mainPadding: "16px",
      inputFontSize: "14px",
      inputRadius: "8px",
      buttonHeight: "36px",
    });
    await page.evaluate(() => {
      document.documentElement.style.fontSize = "16px";
    });
    expect(await readSizes()).toEqual(youtubeRootSizes);

    const toggleOverlay = () =>
      worker.evaluate(async () => {
        const extensionChrome = (
          globalThis as typeof globalThis & {
            chrome: {
              tabs: {
                query: (query: {
                  active: boolean;
                  lastFocusedWindow: boolean;
                }) => Promise<Array<{ id?: number }>>;
                sendMessage: (tabId: number, message: object) => Promise<void>;
              };
            };
          }
        ).chrome;
        const [tab] = await extensionChrome.tabs.query({
          active: true,
          lastFocusedWindow: true,
        });
        if (typeof tab?.id !== "number") {
          throw new Error("Community posts tab was not found");
        }
        await extensionChrome.tabs.sendMessage(tab.id, {
          id: Date.now(),
          type: "toggleOverlay",
          timestamp: Date.now(),
        });
      });
    await toggleOverlay();
    await expect(shell).toBeHidden();
    await toggleOverlay();
    await expect(shell).toBeVisible();

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
