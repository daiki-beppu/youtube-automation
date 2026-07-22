import { createServer } from "node:net"
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join, resolve } from "node:path"
import { spawn, type ChildProcess } from "node:child_process"

import { expect, test } from "@playwright/test"

let process: ChildProcess
let fixtureRoot: string
let baseURL: string

async function unusedPort(): Promise<number> {
  return new Promise((resolvePort, reject) => {
    const server = createServer()
    server.once("error", reject)
    server.listen(0, "127.0.0.1", () => {
      const address = server.address()
      if (!address || typeof address === "string") {
        server.close()
        reject(new Error("空き port を取得できませんでした"))
        return
      }
      server.close(() => resolvePort(address.port))
    })
  })
}

async function waitUntilReady(url: string): Promise<void> {
  const deadline = Date.now() + 20_000
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${url}/api/channels`)
      if (response.ok) return
    } catch {
      // 起動中は再試行する。
    }
    await new Promise((resolveWait) => setTimeout(resolveWait, 100))
  }
  throw new Error("dashboard server が起動しませんでした")
}

test.beforeAll(async () => {
  fixtureRoot = await mkdtemp(join(tmpdir(), "yt-dashboard-e2e-"))
  const channel = join(fixtureRoot, "night-drive")
  await mkdir(join(channel, "config", "channel"), { recursive: true })
  await mkdir(join(channel, "data"), { recursive: true })
  await writeFile(
    join(channel, "config", "channel", "meta.json"),
    JSON.stringify({ channel: { name: "Night Drive" } })
  )
  await writeFile(
    join(channel, "data", "analytics_data_2026-07-20.json"),
    JSON.stringify({
      collection_period: { collected_at: "2026-07-20T12:00:00Z" },
      channel_analytics: {
        summary: {
          total_views: 3200,
          total_watch_time: 900,
          net_subscribers: 32,
          total_engagement: 170,
        },
      },
      scheduled_videos: { count: 1 },
      video_analytics: {
        "video-1": {
          title: "Midnight City",
          views: 3200,
          likes: 150,
          comments: 15,
          shares: 5,
        },
      },
    })
  )
  const registry = join(fixtureRoot, "channels.json")
  await writeFile(registry, JSON.stringify([channel]))
  const port = await unusedPort()
  baseURL = `http://127.0.0.1:${port}`
  process = spawn(
    "uv",
    [
      "run",
      "--project",
      "..",
      "yt-dashboard",
      "--registry",
      registry,
      "--port",
      String(port),
    ],
    {
      cwd: resolve(import.meta.dirname, ".."),
      stdio: "pipe",
    }
  )
  await waitUntilReady(baseURL)
})

test.afterAll(async () => {
  process?.kill("SIGTERM")
  if (fixtureRoot) await rm(fixtureRoot, { recursive: true, force: true })
})

test("概要から動画詳細まで keyboard で確認できる", async ({ page }) => {
  await page.setViewportSize({ width: 760, height: 900 })
  await page.goto(baseURL)
  const overviewCard = page.getByRole("article", {
    name: "Night Drive の概要",
  })
  await expect(overviewCard).toBeVisible()
  await expect(overviewCard.getByText("3,200")).toBeVisible()
  await expect(overviewCard.getByText("900分")).toBeVisible()
  await expect(overviewCard.getByText("+32")).toBeVisible()
  await expect(overviewCard.getByText("分析動画")).toBeVisible()
  await expect(page.getByText("チャンネルを選択してください")).toHaveCount(0)
  const channel = page.getByRole("button", { name: /Night Drive/ })
  await expect(channel).toBeVisible()
  await expect(page.getByText("更新失敗", { exact: true })).toBeVisible()
  await expect(page.getByText("公開予約 1本")).toBeVisible()
  const layout = await overviewCard.evaluate((element) => {
    const bounds = element.getBoundingClientRect()
    return {
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
      left: bounds.left,
      right: bounds.right,
      viewportWidth: document.documentElement.clientWidth,
    }
  })
  expect(layout.scrollWidth).toBeLessThanOrEqual(layout.clientWidth)
  expect(layout.left).toBeGreaterThanOrEqual(0)
  expect(layout.right).toBeLessThanOrEqual(layout.viewportWidth)
  await channel.focus()
  await page.keyboard.press("Enter")
  await expect(
    page.getByRole("heading", { name: "動画パフォーマンス" })
  ).toBeVisible()
  await expect(page.getByRole("cell", { name: "Midnight City" })).toBeVisible()
  await expect(page.getByRole("cell", { name: "3,200" })).toBeVisible()
})
