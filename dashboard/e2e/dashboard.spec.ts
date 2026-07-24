import { createServer } from "node:net"
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join, resolve } from "node:path"
import { spawn, type ChildProcess } from "node:child_process"

import { expect, test } from "@playwright/test"

let process: ChildProcess
let fixtureRoot: string
let baseURL: string
let serverStderr = ""

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
  throw new Error(
    `dashboard server が起動しませんでした${serverStderr ? `\n${serverStderr}` : ""}`
  )
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
  const secondChannel = join(fixtureRoot, "zero-stock")
  await mkdir(join(secondChannel, "config", "channel"), { recursive: true })
  await mkdir(join(secondChannel, "data"), { recursive: true })
  await writeFile(
    join(secondChannel, "config", "channel", "meta.json"),
    JSON.stringify({ channel: { name: "Zero Stock" } })
  )
  await writeFile(
    join(secondChannel, "data", "analytics_data_2026-07-20.json"),
    JSON.stringify({
      collection_period: { collected_at: "2026-07-20T12:00:00Z" },
      channel_analytics: {
        summary: {
          total_views: 100,
          total_watch_time: 20,
          net_subscribers: 1,
          total_engagement: 5,
        },
      },
      scheduled_videos: { count: 0 },
      video_analytics: {},
    })
  )
  const registry = join(fixtureRoot, "channels.json")
  await writeFile(registry, JSON.stringify([channel, secondChannel]))
  const port = await unusedPort()
  baseURL = `http://127.0.0.1:${port}`
  process = spawn(
    "uv",
    [
      "run",
      "--project",
      "..",
      "yt-dashboard",
      "--skip-refresh",
      "--registry",
      registry,
      "--port",
      String(port),
    ],
    {
      cwd: resolve(import.meta.dirname, ".."),
      stdio: "pipe",
      env: {
        ...globalThis.process.env,
        UV_CACHE_DIR: join(fixtureRoot, "uv-cache"),
      },
    }
  )
  process.stderr?.setEncoding("utf8")
  process.stderr?.on("data", (chunk: string) => {
    serverStderr += chunk
  })
  await waitUntilReady(baseURL)
})

test.afterAll(async () => {
  process?.kill("SIGTERM")
  if (fixtureRoot) await rm(fixtureRoot, { recursive: true, force: true })
})

test("概要から動画詳細まで keyboard で確認できる", async ({ page }) => {
  await page.setViewportSize({ width: 760, height: 900 })
  await page.goto(baseURL)
  const overview = page.getByRole("region", { name: "概況" })
  await expect(overview).toBeVisible()
  await expect(
    overview.getByRole("region", { name: "表示データについて" })
  ).toContainText("対象期間")
  await expect(
    overview.getByRole("region", { name: "指標の見方" })
  ).toContainText("公開予約")
  await expect(
    page.getByRole("heading", { name: "チャンネル概要" })
  ).toHaveCount(0)
  await expect(page.getByText("チャンネルを選択してください")).toHaveCount(0)
  const stockTable = page.getByRole("table", {
    name: "チャンネル横断ストック一覧",
  })
  await expect(stockTable).toBeVisible()
  const zeroStockRow = stockTable.getByRole("row", { name: /Zero Stock/ })
  const nightDriveRow = stockTable.getByRole("row", { name: /Night Drive/ })
  await expect(zeroStockRow.getByText("ストック")).toBeVisible()
  await expect(zeroStockRow).toContainText("0本")
  await expect(nightDriveRow).toContainText("1本")
  await expect(nightDriveRow).toContainText("3,200")
  await expect(nightDriveRow).toContainText("900分")
  await expect(nightDriveRow).toContainText("+32")
  expect(
    await zeroStockRow.evaluate(
      (row, laterRow) =>
        Boolean(
          row.compareDocumentPosition(laterRow) &
          Node.DOCUMENT_POSITION_FOLLOWING
        ),
      await nightDriveRow.elementHandle()
    )
  ).toBe(true)
  const totalSummary = page.getByText("全チャンネル合計 公開予約 1本")
  expect(
    await totalSummary.evaluate(
      (summary, table) =>
        Boolean(
          summary.compareDocumentPosition(table) &
          Node.DOCUMENT_POSITION_FOLLOWING
        ),
      await stockTable.elementHandle()
    )
  ).toBe(true)
  const stockContainer = stockTable.locator("xpath=..").first()
  const stockLayout = await stockContainer.evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
    documentWidth: document.documentElement.scrollWidth,
    viewportWidth: document.documentElement.clientWidth,
  }))
  expect(stockLayout.scrollWidth).toBeLessThanOrEqual(stockLayout.clientWidth)
  expect(stockLayout.documentWidth).toBeLessThanOrEqual(
    stockLayout.viewportWidth
  )
  const channel = nightDriveRow.getByRole("button", { name: /Night Drive/ })
  await expect(channel).toBeVisible()
  const layout = await nightDriveRow.evaluate((element) => {
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
  const videoTable = page.getByRole("table", { name: "動画パフォーマンス" })
  await expect(
    videoTable.getByRole("cell", { name: "Midnight City" })
  ).toBeVisible()
  await expect(videoTable.getByRole("cell", { name: "3,200" })).toBeVisible()
})

test("768px 幅でも比較行と詳細操作が見切れない", async ({ page }) => {
  await page.setViewportSize({ width: 768, height: 900 })
  await page.goto(baseURL)

  const comparisonTable = page.getByRole("table", {
    name: "チャンネル横断ストック一覧",
  })
  const nightDriveRow = comparisonTable.getByRole("row", {
    name: /Night Drive/,
  })
  const detailButton = nightDriveRow.getByRole("button", {
    name: /Night Drive/,
  })
  await expect(detailButton).toBeVisible()

  const layout = await nightDriveRow.evaluate(
    (element, button) => {
      const rowBounds = element.getBoundingClientRect()
      const buttonBounds = button.getBoundingClientRect()
      return {
        documentWidth: document.documentElement.scrollWidth,
        viewportWidth: document.documentElement.clientWidth,
        rowLeft: rowBounds.left,
        rowRight: rowBounds.right,
        buttonLeft: buttonBounds.left,
        buttonRight: buttonBounds.right,
      }
    },
    await detailButton.elementHandle()
  )
  expect(layout.documentWidth).toBeLessThanOrEqual(layout.viewportWidth)
  expect(layout.rowLeft).toBeGreaterThanOrEqual(0)
  expect(layout.rowRight).toBeLessThanOrEqual(layout.viewportWidth)
  expect(layout.buttonLeft).toBeGreaterThanOrEqual(layout.rowLeft)
  expect(layout.buttonRight).toBeLessThanOrEqual(layout.rowRight)
})
