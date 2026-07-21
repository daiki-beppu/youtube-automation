import { mkdtemp } from "node:fs/promises";
import { createServer, type Server } from "node:http";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test, chromium, type BrowserContext } from "@playwright/test";

const here = dirname(fileURLToPath(import.meta.url));
const extensionPath = join(here, "..", "..", ".output", "chrome-mv3");
const releasePayload = {
  profile: {
    artist: "Midnight Echoes",
    language: "Japanese",
    main_genre: "Electronic",
    sub_genre: null,
    songwriter: null,
    ai_disclosure: {
      enabled: false,
      lyrics: false,
      music: false,
      recording_scope: "full",
      partial_audio_type: null,
      artist_persona: false,
      apply_to_all: true,
    },
    credits: { performer_role: "Synthesizer", producer_role: "Producer" },
  },
  release: {
    album_title: "Neon Skyline",
    tracks: [
      {
        title: "First Light",
        filename: "01-first-light.mp3",
        asset_path: "/distrokid/assets/track",
      },
    ],
    cover: { filename: "cover.jpg", asset_path: "/distrokid/assets/cover" },
    release_date: "2026-08-01",
  },
};

function listen(server: Server, port = 0): Promise<number> {
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, "127.0.0.1", () => {
      server.removeListener("error", reject);
      const address = server.address();
      if (address === null || typeof address === "string")
        throw new Error("HTTP test server has no TCP port");
      resolve(address.port);
    });
  });
}

function close(server: Server): Promise<void> {
  return new Promise((resolve, reject) =>
    server.close((error) => (error ? reject(error) : resolve()))
  );
}

test("最初の開操作では停止済み menu を開かず、検出完了後に更新済み候補を提示する", async () => {
  const liveServers: Server[] = [];
  let context: BrowserContext | undefined;
  let registry: Server | undefined;
  let releaseFails = false;
  try {
    const makeLiveServer = async (
      label: string
    ): Promise<{ url: string; info: Record<string, unknown> }> => {
      const server = createServer((request, response) => {
        response.setHeader("Content-Type", "application/json");
        response.setHeader(
          "Access-Control-Allow-Origin",
          request.headers.origin ?? "*"
        );
        if (request.url === "/server-info") {
          response.end(JSON.stringify(info));
          return;
        }
        if (
          request.url === "/version" ||
          request.url === "/distrokid/collections"
        ) {
          response.statusCode = 404;
          response.end("{}");
          return;
        }
        if (request.url === "/distrokid/release.json") {
          response.statusCode = releaseFails ? 500 : 200;
          response.end(
            JSON.stringify(
              releaseFails ? { error: "release unavailable" } : releasePayload
            )
          );
          return;
        }
        response.statusCode = 404;
        response.end("{}");
      });
      const port = await listen(server);
      liveServers.push(server);
      const url = `http://127.0.0.1:${port}`;
      const info = {
        channel_name: label,
        channel_short: label.toLowerCase(),
        hostname: "127.0.0.1",
        port,
        base_url: url,
        label,
      };
      return { url, info };
    };
    const oldServer = await makeLiveServer("Old");
    const newServer = await makeLiveServer("New");
    let active = oldServer;
    let delayNextResponse = false;
    registry = createServer((request, response) => {
      if (request.url !== "/.well-known/yt-collection-serve") {
        response.statusCode = 404;
        response.end("{}");
        return;
      }
      const send = (): void => {
        response.setHeader("Content-Type", "application/json");
        response.setHeader(
          "Access-Control-Allow-Origin",
          request.headers.origin ?? "*"
        );
        response.end(
          JSON.stringify({
            schema_version: 1,
            ttl_seconds: 30,
            servers: [
              {
                instance_id: active.info.label,
                expires_at: Date.now() / 1000 + 30,
                server_info: active.info,
              },
            ],
          })
        );
      };
      if (delayNextResponse) {
        delayNextResponse = false;
        setTimeout(send, 250);
      } else {
        send();
      }
    });
    await listen(registry, 7872);

    const profile = await mkdtemp(join(tmpdir(), "distrokid-helper-e2e-"));
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
    await context.route("https://distrokid.com/new", (route) =>
      route.fulfill({
        status: 200,
        contentType: "text/html",
        body: "<!doctype html><title>DistroKid fixture</title>",
      })
    );
    const page = await context.newPage();
    await page.goto("https://distrokid.com/new");
    const trigger = page.locator("#server-url");
    const sourceField = page.locator("[data-source-values]");
    await expect(sourceField).toHaveAttribute(
      "data-source-values",
      new RegExp(oldServer.url)
    );
    await trigger.click();
    await page.getByRole("option", { name: /Old/ }).click();
    await expect(page.locator('[data-slot="card-title"]')).toHaveText(
      releasePayload.release.album_title
    );
    const reviewCard = page.locator(
      '[data-slot="card"]:not([data-overlay-shell])',
      {
        has: page.getByText(releasePayload.release.album_title, {
          exact: true,
        }),
      }
    );
    await expect(reviewCard).toContainText("Japanese");
    await expect(reviewCard).toContainText("cover.jpg");

    active = newServer;
    delayNextResponse = true;
    await trigger.click();
    await expect(trigger).toBeDisabled();
    await expect(sourceField).toHaveAttribute(
      "data-source-values",
      new RegExp(oldServer.url)
    );
    await expect(trigger).toHaveText("稼働中の配信元を更新中…");

    await expect(trigger).toBeEnabled();
    const options = page.getByRole("option");
    await expect(options).toContainText([
      "YouTube Automation (default)",
      "New",
    ]);
    await expect(options.filter({ hasText: "Old" })).toHaveCount(0);
    expect(
      await options
        .first()
        .evaluate((option) => option.getRootNode() instanceof ShadowRoot)
    ).toBe(true);

    releaseFails = true;
    await page.getByRole("option", { name: /New/ }).click();
    await expect(page.getByRole("alert")).toHaveText(/HTTP 500/);
  } finally {
    await context?.close();
    if (registry?.listening) await close(registry);
    await Promise.all(
      liveServers.filter((server) => server.listening).map(close)
    );
  }
});
