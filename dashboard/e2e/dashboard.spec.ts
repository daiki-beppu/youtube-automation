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
let publicationDate: string

const paletteLightColors = {
  Blue: ["#d9e6ff", "#9db7f9", "#4979f5", "#264af4", "#0017c1"],
  "Light Blue": ["#c0e4ff", "#57b8ff", "#008bf2", "#0066be", "#00428c"],
  Cyan: ["#99f2ff", "#2bc8e4", "#00a3bf", "#008299", "#006173"],
  Green: ["#c2e5d1", "#71c598", "#259d63", "#197a4b", "#115a36"],
  Lime: ["#d0f5a2", "#8cc80c", "#6fa104", "#507500", "#2c4100"],
  Yellow: ["#ffe380", "#ebb700", "#b78f00", "#927200", "#6e5600"],
  Orange: ["#ffdfca", "#ffa66d", "#fb5b01", "#c74700", "#8b3200"],
  Red: ["#ffdada", "#ff9696", "#ff5454", "#ec0000", "#a90000"],
  Magenta: ["#ffd0ff", "#ff8eff", "#f137f1", "#c000c0", "#8b008b"],
  Purple: ["#ecddff", "#cda6ff", "#a565f8", "#8843e1", "#5c10be"],
} as const

function colorChannels(color: string): [number, number, number] {
  const values = color.match(/[\d.]+/g)?.map(Number)
  if (!values || values.length < 3) {
    throw new Error(`色をRGBへ変換できませんでした: ${color}`)
  }
  if (color.startsWith("color(srgb")) {
    return [values[0] * 255, values[1] * 255, values[2] * 255]
  }
  return [values[0], values[1], values[2]]
}

function hexChannels(color: string): [number, number, number] {
  return [
    Number.parseInt(color.slice(1, 3), 16),
    Number.parseInt(color.slice(3, 5), 16),
    Number.parseInt(color.slice(5, 7), 16),
  ]
}

function contrastRatio(foreground: string, background: string): number {
  const luminance = (color: string) =>
    colorChannels(color)
      .map((channel) => channel / 255)
      .map((channel) =>
        channel <= 0.04045
          ? channel / 12.92
          : ((channel + 0.055) / 1.055) ** 2.4
      )
      .reduce(
        (sum, channel, index) =>
          sum + channel * [0.2126, 0.7152, 0.0722][index],
        0
      )
  const values = [luminance(foreground), luminance(background)].sort(
    (left, right) => right - left
  )
  return (values[0] + 0.05) / (values[1] + 0.05)
}

function localDateKey(date: Date): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, "0")
  const day = String(date.getDate()).padStart(2, "0")
  return `${year}-${month}-${day}`
}

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
  publicationDate = localDateKey(new Date())
  fixtureRoot = await mkdtemp(join(tmpdir(), "yt-dashboard-e2e-"))
  const channel = join(fixtureRoot, "night-drive")
  await mkdir(join(channel, "config", "channel"), { recursive: true })
  await mkdir(join(channel, "data"), { recursive: true })
  await writeFile(
    join(channel, "config", "channel", "meta.json"),
    JSON.stringify({
      channel: {
        name: "Night Drive",
        short: "ND",
        youtube_handle: "@nightdrive",
        url: "https://youtube.com/@nightdrive",
      },
    })
  )
  await writeFile(
    join(channel, "config", "channel", "content.json"),
    JSON.stringify({
      genre: { primary: "synthwave", style: "retro", context: "driving" },
      tags: { base: ["synthwave"], themes: {} },
      descriptions: {
        opening: "Night music",
        perfect_for: ["Driving"],
        hashtags: ["#Night"],
      },
      title: { template: "{theme}" },
    })
  )
  await writeFile(
    join(channel, "config", "channel", "youtube.json"),
    JSON.stringify({
      youtube: { category_id: "10", privacy_status: "public", language: "ja" },
    })
  )
  await writeFile(
    join(channel, "config", "channel", "workflow.json"),
    JSON.stringify({
      workflow: { manual_baseline_minutes: { "wf-next": 60 } },
    })
  )
  await writeFile(
    join(channel, "data", "analytics_data_2026-07-20.json"),
    JSON.stringify({
      collection_period: { collected_at: "2026-07-20T12:00:00Z" },
      channel_analytics: {
        daily_metrics: [
          { date: "2026-07-19", views: 120 },
          { date: "2026-07-20", views: 180 },
        ],
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
  await writeFile(
    join(channel, "data", "dashboard_publications.json"),
    JSON.stringify({
      schema_version: 1,
      fetched_at: new Date().toISOString(),
      timezone: "Asia/Tokyo",
      days: { [publicationDate]: 2 },
    })
  )
  const activeCollection = join(channel, "collections", "planning", "active")
  await mkdir(activeCollection, { recursive: true })
  await writeFile(
    join(activeCollection, "workflow-state.json"),
    JSON.stringify({ phase: "planning", created_at: "2026-07-21" })
  )
  const historyDirectory = join(channel, ".automation-run")
  await mkdir(historyDirectory)
  await writeFile(
    join(historyDirectory, "history.json"),
    JSON.stringify({
      schema_version: 2,
      attempts: [
        {
          collection: "collections/planning/active",
          action: "wf-next",
          status: "success",
          timing: {
            segments: [
              {
                kind: "ai",
                started_at: "2026-07-21T00:00:00+00:00",
                ended_at: "2026-07-21T00:10:00+00:00",
                duration_seconds: 600,
              },
              {
                kind: "human",
                started_at: "2026-07-21T00:10:00+00:00",
                ended_at: "2026-07-21T00:15:00+00:00",
                duration_seconds: 300,
              },
            ],
          },
        },
      ],
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
      video_analytics: {
        "video-error": {
          title: "Timing Error Video",
          views: 100,
          likes: 4,
          comments: 1,
          shares: 0,
        },
      },
    })
  )
  await writeFile(
    join(secondChannel, "data", "dashboard_publications.json"),
    JSON.stringify({
      schema_version: 1,
      fetched_at: new Date().toISOString(),
      timezone: "Asia/Tokyo",
      days: { [publicationDate]: 1 },
    })
  )
  const invalidTimingCollection = join(
    secondChannel,
    "collections",
    "planning",
    "active"
  )
  await mkdir(invalidTimingCollection, { recursive: true })
  await writeFile(
    join(invalidTimingCollection, "workflow-state.json"),
    JSON.stringify({ phase: "planning", created_at: "2026-07-21" })
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

test("起動時 snapshot を表示し手動更新操作を提供しない", async ({ page }) => {
  await page.goto(baseURL)

  await expect(page.getByText("直近 30 日")).toBeVisible()
  await expect(page.getByText("対象期間 / 未収集")).toBeVisible()
  await expect(
    page.getByText(
      "起動時に収集した snapshot から、チャンネルと動画のパフォーマンスを確認できます。"
    )
  ).toBeVisible()
  await expect(page.getByRole("button", { name: "データを更新" })).toHaveCount(
    0
  )
  await expect(page.getByText("更新中")).toHaveCount(0)
  await expect(page.getByText("手動更新対応")).toHaveCount(0)
})

test.afterAll(async () => {
  process?.kill("SIGTERM")
  if (fixtureRoot) await rm(fixtureRoot, { recursive: true, force: true })
})

test("初期表示で概況から推移・公開活動・比較の順に表示する", async ({
  page,
}) => {
  await page.goto(baseURL)

  const publicationActivity = page.getByRole("region", {
    name: "過去365日の公開活動",
  })
  const overview = page.getByRole("region", { name: "概況" })
  const comparison = page.getByRole("table", {
    name: "チャンネル横断ストック一覧",
  })
  await expect(publicationActivity).toBeVisible()
  await expect(overview).toBeVisible()
  await expect(comparison).toBeVisible()

  const trend = page.getByRole("region", { name: "日次再生数の推移" })
  await expect(trend).toBeVisible()

  expect(
    await overview.evaluate(
      (activity, laterElement) =>
        Boolean(
          activity.compareDocumentPosition(laterElement) &
          Node.DOCUMENT_POSITION_FOLLOWING
        ),
      await trend.elementHandle()
    )
  ).toBe(true)
  expect(
    await trend.evaluate(
      (activity, laterElement) =>
        Boolean(
          activity.compareDocumentPosition(laterElement) &
          Node.DOCUMENT_POSITION_FOLLOWING
        ),
      await publicationActivity.elementHandle()
    )
  ).toBe(true)
  expect(
    await publicationActivity.evaluate(
      (activity, laterElement) =>
        Boolean(
          activity.compareDocumentPosition(laterElement) &
          Node.DOCUMENT_POSITION_FOLLOWING
        ),
      await comparison.elementHandle()
    )
  ).toBe(true)
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
  await expect(nightDriveRow).toContainText("15時間")
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
  await expect(channel).toBeFocused()
  const stepTable = page.getByRole("table", {
    name: "active の workflow step",
  })
  await expect(stepTable).toBeVisible()
  const stepRow = stepTable.getByRole("row", { name: /wf-next/ })
  await expect(stepRow).toContainText("成功")
  await expect(stepRow).toContainText("+01:00:00")
  await expect(stepRow).toContainText("+00:10:00")
  await expect(stepRow).toContainText("+00:05:00")
  await expect(stepRow).toContainText("+00:15:00")
  await expect(stepRow).toContainText("+00:45:00")
  await expect(stepRow).toContainText("+00:55:00")
  const stepLayout = await stepRow.evaluate((element) => {
    const bounds = element.getBoundingClientRect()
    return {
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
      left: bounds.left,
      right: bounds.right,
      documentWidth: document.documentElement.scrollWidth,
      viewportWidth: document.documentElement.clientWidth,
    }
  })
  expect(stepLayout.scrollWidth).toBeLessThanOrEqual(stepLayout.clientWidth)
  expect(stepLayout.left).toBeGreaterThanOrEqual(0)
  expect(stepLayout.right).toBeLessThanOrEqual(stepLayout.viewportWidth)
  expect(stepLayout.documentWidth).toBeLessThanOrEqual(stepLayout.viewportWidth)
  await page.keyboard.press("Tab")
  await expect(stepTable).toBeFocused()
  await expect(
    page.getByRole("heading", { name: "動画パフォーマンス" })
  ).toBeVisible()
  const videoTable = page.getByRole("table", { name: "動画パフォーマンス" })
  await expect(
    videoTable.getByRole("cell", { name: "Midnight City" })
  ).toBeVisible()
  await expect(videoTable.getByRole("cell", { name: "3,200" })).toBeVisible()
})

test("timing error でも実 HTTP の Analytics 詳細を維持する", async ({
  page,
}) => {
  await page.goto(baseURL)
  await page
    .getByRole("button", { name: "Zero Stock の動画詳細を見る" })
    .click()

  const detailHeading = page.getByRole("heading", {
    name: "Zero Stock の動画詳細",
  })
  await expect(detailHeading).toBeVisible()
  const timingSection = page
    .getByRole("heading", { name: "コレクション時間サマリー" })
    .locator("xpath=..")
    .locator("xpath=..")
  await expect(timingSection.getByRole("alert")).toContainText("エラー")
  await expect(
    page
      .locator("dt")
      .filter({ hasText: /^再生数$/ })
      .locator("..")
  ).toContainText("100")
  await expect(
    page
      .getByRole("table", { name: "動画パフォーマンス" })
      .getByRole("cell", { name: "Timing Error Video" })
  ).toBeVisible()
})

test("削減時間の2式を実 HTTP の数値見出しから確認できる", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto(baseURL)
  await page
    .getByRole("button", { name: "Night Drive の動画詳細を見る" })
    .click()

  const aiFormula = "AI込み削減時間 = 手作業基準 - 総作業時間"
  const humanFormula = "人間が浮いた時間 = 手作業基準 - 人間使用時間"
  const formulaGuide = page.getByRole("note", { name: "削減時間の算出式" })
  await expect(formulaGuide.getByText(aiFormula)).toBeVisible()
  await expect(formulaGuide.getByText(humanFormula)).toBeVisible()

  const stepTable = page.getByRole("table", {
    name: "active の workflow step",
  })
  await expect(
    stepTable.getByRole("columnheader", { name: "AI 込み削減時間" })
  ).toHaveAccessibleDescription(aiFormula)
  await expect(
    stepTable.getByRole("columnheader", { name: "人間が浮いた時間" })
  ).toHaveAccessibleDescription(humanFormula)
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

for (const width of [320, 375, 414]) {
  test(`${width}px 幅で chart・table・sheet・長い名前を境界内に収める`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 844 })
    await page.goto(baseURL)

    const channelName = page.getByText("Night Drive", { exact: true }).first()
    await channelName.evaluate((element) => {
      element.textContent =
        "Night Drive Ambient Music Channel With An Exceptionally Long Name"
    })
    const targets = [
      page.getByRole("region", { name: "日次再生数の推移" }),
      page.getByRole("table", { name: "チャンネル横断ストック一覧" }),
      channelName,
    ]
    for (const target of targets) {
      await expect(target).toBeVisible()
      const bounds = await target.evaluate((element) => {
        const rect = element.getBoundingClientRect()
        return { left: rect.left, right: rect.right }
      })
      expect(bounds.left).toBeGreaterThanOrEqual(0)
      expect(bounds.right).toBeLessThanOrEqual(width)
    }
    await page.getByRole("button", { name: "設定を開く" }).click()
    const dialog = page.getByRole("dialog")
    await expect(dialog).toBeVisible()
    await expect(dialog).toHaveCSS("translate", "none")
    const dialogBounds = await dialog.evaluate((element) => {
      const rect = element.getBoundingClientRect()
      return { left: rect.left, right: rect.right }
    })
    expect(dialogBounds.left).toBeGreaterThanOrEqual(0)
    expect(dialogBounds.right).toBeLessThanOrEqual(width)
    const documentWidth = await page.evaluate(
      () => document.documentElement.scrollWidth
    )
    expect(documentWidth).toBeLessThanOrEqual(width)
  })
}

for (const viewport of [
  { width: 1280, height: 720 },
  { width: 390, height: 844 },
]) {
  for (const colorScheme of ["light", "dark"] as const) {
    test(`${viewport.width}x${viewport.height} ${colorScheme} で横スクロールせず keyboard focus を表示する`, async ({
      page,
    }) => {
      await page.emulateMedia({ colorScheme })
      await page.setViewportSize(viewport)
      await page.goto(baseURL)

      expect(
        await page.evaluate(() => document.documentElement.scrollWidth)
      ).toBeLessThanOrEqual(viewport.width)

      await page.keyboard.press("Tab")
      const focused = page.locator(":focus-visible")
      await expect(focused).toBeVisible()
      const focusStyle = await focused.evaluate((element) => {
        const style = getComputedStyle(element)
        return { outline: style.outlineStyle, boxShadow: style.boxShadow }
      })
      expect(
        focusStyle.outline !== "none" || focusStyle.boxShadow !== "none"
      ).toBe(true)

      await page.getByRole("button", { name: "設定を開く" }).focus()
      await page.keyboard.press("Enter")
      await expect(page.getByRole("dialog")).toBeVisible()
      await page.keyboard.press("Escape")
      await expect(page.getByRole("dialog")).toBeHidden()
    })
  }
}

test("1440px 幅で公開活動が境界いっぱいに広がり横スクロールしない", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto(baseURL)

  const heatmap = page.getByRole("region", { name: "過去365日の公開活動" })
  const scrollBoundary = heatmap.getByTestId("publication-heatmap-scroll")
  const grid = heatmap.getByRole("grid", { name: "日別公開本数" })
  await expect(grid).toBeVisible()

  const layout = await scrollBoundary.evaluate(
    (boundary, renderedGrid) => {
      const boundaryBounds = boundary.getBoundingClientRect()
      const gridBounds = renderedGrid.getBoundingClientRect()
      return {
        boundaryRight: boundaryBounds.right,
        boundaryWidth: boundary.clientWidth,
        contentWidth: boundary.scrollWidth,
        gridRight: gridBounds.right,
      }
    },
    await grid.elementHandle()
  )
  const cssPixelTolerance = 1
  expect(Math.abs(layout.gridRight - layout.boundaryRight)).toBeLessThanOrEqual(
    cssPixelTolerance
  )
  expect(layout.contentWidth).toBeLessThanOrEqual(layout.boundaryWidth)
})

test("描画後の公開活動セルが正方形を保つ", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto(baseURL)

  const heatmap = page.getByRole("region", { name: "過去365日の公開活動" })
  const cell = heatmap.getByRole("gridcell", {
    name: `${publicationDate}: 3本`,
    exact: true,
  })
  await expect(cell).toBeVisible()

  const bounds = await cell.evaluate((element) => {
    const rectangle = element.getBoundingClientRect()
    return { height: rectangle.height, width: rectangle.width }
  })
  const cssPixelTolerance = 1
  expect(Math.abs(bounds.width - bounds.height)).toBeLessThanOrEqual(
    cssPixelTolerance
  )
})

test("狭い画面で公開活動を領域内スクロールと keyboard で確認できる", async ({
  page,
}) => {
  await page.setViewportSize({ width: 640, height: 900 })
  await page.goto(baseURL)

  const heatmap = page.getByRole("region", { name: "過去365日の公開活動" })
  const scrollBoundary = heatmap.getByTestId("publication-heatmap-scroll")
  await expect(scrollBoundary).toBeVisible()

  const layout = await scrollBoundary.evaluate((element) => ({
    boundaryWidth: element.clientWidth,
    contentWidth: element.scrollWidth,
    documentWidth: document.documentElement.scrollWidth,
    viewportWidth: document.documentElement.clientWidth,
  }))
  expect(layout.documentWidth).toBeLessThanOrEqual(layout.viewportWidth)
  expect(layout.contentWidth).toBeGreaterThan(layout.boundaryWidth)

  await scrollBoundary.evaluate((element) => {
    element.scrollLeft = element.scrollWidth
  })
  expect(
    await scrollBoundary.evaluate((element) => element.scrollLeft)
  ).toBeGreaterThan(0)

  const cell = heatmap.getByRole("gridcell", {
    name: `${publicationDate}: 3本`,
    exact: true,
  })
  await cell.focus()
  await expect(cell).toBeFocused()
  const details = heatmap.getByRole("tooltip")
  await expect(details).toContainText(publicationDate)
  await expect(details).toContainText("合計 3本")
  await expect(details).toContainText("Night Drive 2本")
  await expect(details).toContainText("Zero Stock 1本")
  await expect(cell).toHaveAttribute(
    "aria-describedby",
    await details.getAttribute("id")
  )
})

test("公開活動の empty・stale・fatal 状態を切り替えられる", async ({
  page,
}) => {
  let holdResponse = true
  let releaseResponse: (() => void) | undefined
  let response = {
    status: 200,
    body: { days: {}, channels: [] },
  }
  await page.route("**/api/publications", async (route) => {
    if (holdResponse) {
      await new Promise<void>((resolveResponse) => {
        releaseResponse = resolveResponse
      })
    }
    await route.fulfill({
      body: JSON.stringify(response.body),
      contentType: "application/json",
      status: response.status,
    })
  })

  await page.goto(baseURL)
  await expect(
    page.getByRole("status", { name: "公開活動を読み込み中" })
  ).toBeVisible()
  await expect.poll(() => Boolean(releaseResponse)).toBe(true)
  holdResponse = false
  releaseResponse?.()
  await expect(page.getByText("公開活動データがありません")).toBeVisible()
  await expect(page.getByRole("grid", { name: "日別公開本数" })).toHaveCount(0)

  response = {
    status: 200,
    body: {
      days: { [publicationDate]: 2 },
      channels: [
        {
          id: "night-drive",
          name: "Night Drive",
          status: "refresh_failed",
          fetched_at: "2026-08-08T10:00:00Z",
          timezone: "Asia/Tokyo",
          days: { [publicationDate]: 2 },
          error: {
            code: "publication_refresh_failed",
            message: "quota exceeded",
            attempted_at: "2026-08-08T12:00:00Z",
          },
        },
      ],
    },
  }
  await page.reload()
  const heatmap = page.getByRole("region", { name: "過去365日の公開活動" })
  await expect(
    heatmap.getByRole("gridcell", {
      name: `${publicationDate}: 2本`,
      exact: true,
    })
  ).toBeVisible()
  await expect(heatmap.getByText(/^最終更新/)).toBeVisible()
  const staleAlert = heatmap.getByRole("alert", {
    name: "Night Drive の公開活動更新失敗",
  })
  await expect(staleAlert).toBeVisible()
  await expect(staleAlert).toContainText("前回データを表示しています")
  await expect(staleAlert).toContainText("quota exceeded")

  response = { status: 503, body: { error: "failed" } }
  await page.reload()
  const fatalAlert = page.getByRole("alert", {
    name: "公開活動を読み込めませんでした",
  })
  await expect(fatalAlert).toBeVisible()
  await expect(fatalAlert).toContainText("HTTP 503")
  await expect(
    page.getByRole("region", { name: "過去365日の公開活動" })
  ).toHaveCount(0)
})

test("xl viewport で step table の列が見切れず重ならない", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto(baseURL)
  await page
    .getByRole("button", { name: "Night Drive の動画詳細を見る" })
    .click()

  const stepTable = page.getByRole("table", {
    name: "active の workflow step",
  })
  await expect(stepTable).toBeVisible()
  const layout = await stepTable.evaluate((table) => {
    const container = table.parentElement
    if (!container) throw new Error("step table container がありません")
    const containerBounds = container.getBoundingClientRect()
    const contentBounds = (selector: string) =>
      [...table.querySelectorAll(selector)].map((element) => {
        const range = document.createRange()
        range.selectNodeContents(element)
        const rectangle = range.getBoundingClientRect()
        return { left: rectangle.left, right: rectangle.right }
      })
    return {
      clientWidth: table.clientWidth,
      scrollWidth: table.scrollWidth,
      container: {
        left: containerBounds.left,
        right: containerBounds.right,
      },
      headers: contentBounds("thead th"),
      values: contentBounds("tbody tr:first-child td"),
    }
  })
  const expectColumnsToFit = (
    columns: Array<{ left: number; right: number }>
  ) => {
    for (const column of columns) {
      expect(column.left).toBeGreaterThanOrEqual(layout.container.left)
      expect(column.right).toBeLessThanOrEqual(layout.container.right)
    }
    for (const [index, column] of columns.entries()) {
      const next = columns[index + 1]
      if (next) expect(column.right).toBeLessThanOrEqual(next.left)
    }
  }

  expect(layout.scrollWidth).toBeLessThanOrEqual(layout.clientWidth)
  expect(layout.headers).toHaveLength(8)
  expect(layout.values).toHaveLength(8)
  expectColumnsToFit(layout.headers)
  expectColumnsToFit(layout.values)
})

test("ダークテーマでも背景とカードの階調を識別できる", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("theme", "dark")
  })
  await page.goto(baseURL)

  const colors = await page.evaluate(() => {
    const rootStyle = getComputedStyle(document.documentElement)
    const lightness = (token: string) => {
      const match = rootStyle
        .getPropertyValue(token)
        .match(/oklch\(([\d.]+)(%?)/)
      if (!match) throw new Error(`${token} is not an OKLCH color`)
      const value = Number(match[1])
      return match[2] === "%" ? value / 100 : value
    }
    return {
      background: lightness("--background"),
      card: lightness("--card"),
    }
  })

  expect(colors.background).toBeGreaterThanOrEqual(0.18)
  expect(colors.card - colors.background).toBeGreaterThanOrEqual(0.04)
})

test("カラーパレットを切り替えて再読み込み後も保持できる", async ({ page }) => {
  await page.goto(baseURL)

  await expect(
    page.getByRole("group", { name: "カラーパレット" })
  ).not.toBeVisible()
  await page.getByRole("button", { name: "設定を開く" }).click()
  const paletteGroup = page.getByRole("group", { name: "カラーパレット" })
  const blue = paletteGroup.getByRole("button", {
    name: "Blue",
    exact: true,
  })
  const green = paletteGroup.getByRole("button", {
    name: "Green",
    exact: true,
  })
  await expect(blue).toHaveAttribute("aria-pressed", "true")

  const dashboardColors = () =>
    page.evaluate(() => {
      const overviewHeading = [...document.querySelectorAll("h2")].find(
        (heading) => heading.textContent === "概況"
      )
      const registeredChannels = [...document.querySelectorAll("dt")].find(
        (term) => term.textContent === "登録チャンネル"
      )
      if (!overviewHeading || !registeredChannels?.parentElement) {
        throw new Error("ダッシュボードの配色対象を取得できませんでした")
      }
      return {
        background: getComputedStyle(document.querySelector("main")!)
          .backgroundImage,
        headingBorder: getComputedStyle(overviewHeading).borderLeftColor,
        metricSurface: getComputedStyle(registeredChannels.parentElement)
          .backgroundColor,
      }
    })
  const blueDashboardColors = await dashboardColors()
  const blueBackground = await blue.evaluate(
    (element) => getComputedStyle(element).backgroundColor
  )
  await green.click()
  await expect(green).toHaveAttribute("aria-pressed", "true")
  const greenBackground = await green.evaluate(
    (element) => getComputedStyle(element).backgroundColor
  )
  expect(greenBackground).not.toBe(blueBackground)
  const greenDashboardColors = await dashboardColors()
  expect(greenDashboardColors.background).not.toBe(
    blueDashboardColors.background
  )
  expect(greenDashboardColors.headingBorder).not.toBe(
    blueDashboardColors.headingBorder
  )
  expect(greenDashboardColors.metricSurface).not.toBe(
    blueDashboardColors.metricSurface
  )

  await page.reload()
  await page.getByRole("button", { name: "設定を開く" }).click()
  await expect(
    page
      .getByRole("group", { name: "カラーパレット" })
      .getByRole("button", { name: "Green" })
  ).toHaveAttribute("aria-pressed", "true")
})

test("グラフは色だけに頼らず再生数を常時表示する", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("theme", "light")
  })
  await page.goto(baseURL)
  await page
    .getByRole("button", { name: "Night Drive の動画詳細を見る" })
    .click()

  const chart = page.getByTestId("top-videos-chart")
  const valueLabel = chart.getByText("3,200")
  await expect(valueLabel).toBeVisible()

  const expectChartContrast = async () => {
    await expect(valueLabel).toBeVisible()
    await expect(chart.locator(".recharts-bar-rectangle path")).toHaveCount(1)
    const colors = await chart.evaluate((element) => {
      const bar = element.querySelector(".recharts-bar-rectangle path")
      const label = [...element.querySelectorAll("text")].find(
        (candidate) => candidate.textContent === "3,200"
      )
      const surface = element.closest("[data-slot='card']")
      if (!bar || !label || !surface) {
        throw new Error("グラフの検査対象がありません")
      }
      const toSrgb = (color: string) => {
        const sample = document.createElement("span")
        sample.style.color = `color-mix(in srgb, ${color}, ${color})`
        document.body.append(sample)
        const resolved = getComputedStyle(sample).color
        sample.remove()
        return resolved
      }
      return {
        background: toSrgb(getComputedStyle(surface).backgroundColor),
        bar: toSrgb(getComputedStyle(bar).fill),
        label: toSrgb(getComputedStyle(label).fill),
      }
    })
    expect(
      contrastRatio(colors.bar, colors.background),
      JSON.stringify(colors)
    ).toBeGreaterThanOrEqual(3)
    expect(
      contrastRatio(colors.label, colors.background),
      JSON.stringify(colors)
    ).toBeGreaterThanOrEqual(4.5)
  }

  await page.getByRole("button", { name: "設定を開く" }).click()
  for (const palette of Object.keys(paletteLightColors)) {
    await page
      .getByRole("group", { name: "カラーパレット" })
      .getByRole("button", { name: palette, exact: true })
      .click()
    await expectChartContrast()
  }

  await page.getByRole("button", { name: "閉じる" }).click()
  await page.getByRole("button", { name: "ダークモードに切り替え" }).click()
  await page.getByRole("button", { name: "設定を開く" }).click()
  for (const palette of Object.keys(paletteLightColors)) {
    await page
      .getByRole("group", { name: "カラーパレット" })
      .getByRole("button", { name: palette, exact: true })
      .click()
    await expectChartContrast()
  }
})

test("ライトでは公式5段階色、ダークでは背景と識別できる色を表示する", async ({
  page,
}) => {
  await page.addInitScript(() => {
    localStorage.setItem("theme", "light")
  })
  await page.goto(baseURL)
  await page.getByRole("button", { name: "設定を開く" }).click()

  const expectDashboardContrast = async () => {
    const colors = await page.evaluate(() => {
      const title = document.querySelector("h1")
      const accentDescription = [...document.querySelectorAll("div")].find(
        (element) =>
          element.textContent === "最後に更新した全チャンネルの集計です。"
      )
      const metricLabel = [...document.querySelectorAll("dt")].find(
        (term) => term.textContent === "登録チャンネル"
      )
      const metricSurface = metricLabel?.parentElement
      if (!title || !accentDescription || !metricLabel || !metricSurface) {
        throw new Error("コントラスト検査対象を取得できませんでした")
      }

      const toSrgb = (color: string) => {
        const sample = document.createElement("span")
        sample.style.color = `color-mix(in srgb, ${color}, ${color})`
        document.body.append(sample)
        const resolved = getComputedStyle(sample).color
        sample.remove()
        return resolved
      }
      const accentSample = document.createElement("span")
      accentSample.style.backgroundColor = "var(--dashboard-accent-surface)"
      document.body.append(accentSample)
      const titleBackground = getComputedStyle(accentSample).backgroundColor
      accentSample.remove()

      return {
        accentDescription: {
          background: toSrgb(titleBackground),
          foreground: toSrgb(getComputedStyle(accentDescription).color),
        },
        metric: {
          background: toSrgb(getComputedStyle(metricSurface).backgroundColor),
          foreground: toSrgb(getComputedStyle(metricLabel).color),
        },
        title: {
          background: toSrgb(titleBackground),
          foreground: toSrgb(getComputedStyle(title).color),
        },
      }
    })

    expect(
      contrastRatio(colors.title.foreground, colors.title.background),
      JSON.stringify(colors.title)
    ).toBeGreaterThanOrEqual(4.5)
    expect(
      contrastRatio(
        colors.accentDescription.foreground,
        colors.accentDescription.background
      ),
      JSON.stringify(colors.accentDescription)
    ).toBeGreaterThanOrEqual(4.5)
    expect(
      contrastRatio(colors.metric.foreground, colors.metric.background),
      JSON.stringify(colors.metric)
    ).toBeGreaterThanOrEqual(4.5)
  }

  for (const [palette, expectedColors] of Object.entries(paletteLightColors)) {
    const option = page
      .getByRole("group", { name: "カラーパレット" })
      .getByRole("button", { name: palette, exact: true })
    await option.click()
    await expect(option).toHaveAttribute("aria-pressed", "true")

    const colors = await Promise.all(
      expectedColors.map((_, index) =>
        page
          .getByTestId(`palette-swatch-${index + 1}`)
          .evaluate((element) => getComputedStyle(element).backgroundColor)
      )
    )
    expect(colors.map(colorChannels)).toEqual(expectedColors.map(hexChannels))
    const selectedColors = await option.evaluate((element) => {
      const style = getComputedStyle(element)
      return {
        background: style.backgroundColor,
        foreground: style.color,
      }
    })
    expect(
      contrastRatio(selectedColors.foreground, selectedColors.background),
      JSON.stringify(selectedColors)
    ).toBeGreaterThanOrEqual(4.5)
    await expectDashboardContrast()
  }

  await page.getByRole("button", { name: "閉じる" }).click()
  await page.getByRole("button", { name: "ダークモードに切り替え" }).click()
  await page.getByRole("button", { name: "設定を開く" }).click()

  for (const palette of Object.keys(paletteLightColors)) {
    const option = page
      .getByRole("group", { name: "カラーパレット" })
      .getByRole("button", { name: palette, exact: true })
    await option.click()
    const swatches = await Promise.all(
      Array.from({ length: 5 }, (_, index) =>
        page.getByTestId(`palette-swatch-${index + 1}`).evaluate((element) => {
          const surface = element.closest("[data-slot='sheet-content']")
          if (!surface) throw new Error("palette settings surface is missing")
          return {
            background: getComputedStyle(surface).backgroundColor,
            color: getComputedStyle(element).backgroundColor,
          }
        })
      )
    )
    expect(new Set(swatches.map(({ color }) => color)).size).toBe(5)
    for (const swatch of swatches) {
      expect(
        contrastRatio(swatch.color, swatch.background)
      ).toBeGreaterThanOrEqual(3)
    }
    await expectDashboardContrast()
  }
})
