import "@testing-library/jest-dom/vitest"

import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"

import App from "./App"
import { ThemeProvider } from "./components/theme-provider"

const overview = {
  schema_version: 1,
  channels: [
    {
      id: "channel-a",
      name: "Night Drive",
      status: "ready",
      scheduled_count: 3,
      snapshot: "analytics_data.json",
      collected_at: "2026-07-20T12:00:00Z",
      period: { start_date: "2026-06-20", end_date: "2026-07-20" },
      summary: {
        views: 1200,
        watch_time_minutes: 450,
        subscribers_net: 12,
        engagements: 80,
        average_view_percentage: 42.5,
      },
      error: null,
      refresh_error: null,
      video_count: 1,
    },
  ],
}

const detail = {
  ...overview.channels[0],
  videos: [
    {
      video_id: "video-1",
      title: "Midnight City",
      views: 1200,
      impressions: 8000,
      ctr_percentage: 5.2,
      likes: 70,
      comments: 8,
      shares: 2,
      subscribers_gained: 12,
      average_view_duration_seconds: 180,
      engagements: 80,
    },
  ],
}

beforeAll(() => {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: () => ({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  })
})

afterEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
})

function renderDashboard() {
  return render(
    <ThemeProvider>
      <App />
    </ThemeProvider>
  )
}

describe("dashboard", () => {
  it("presents overview, data context, metric definitions, and comparison in decision order", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(overview), { status: 200 })
    )

    renderDashboard()

    const overviewHeading = await screen.findByRole("heading", {
      name: "概況",
    })
    const comparisonHeading = screen.getByRole("heading", {
      name: "チャンネル比較",
    })
    expect(overviewHeading.compareDocumentPosition(comparisonHeading)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING
    )

    const dataContext = screen.getByRole("region", {
      name: "表示データについて",
    })
    expect(within(dataContext).getByText("対象期間")).toBeInTheDocument()
    expect(
      within(dataContext).getByText("2026/06/20〜2026/07/20")
    ).toBeInTheDocument()
    expect(within(dataContext).getByText("最終更新")).toBeInTheDocument()
    expect(within(dataContext).getByText(/\d{1,2}:\d{2}/)).toBeInTheDocument()

    const metricGuide = screen.getByRole("region", {
      name: "指標の見方",
    })
    expect(within(metricGuide).getByText("公開予約")).toBeInTheDocument()
    expect(
      within(metricGuide).getByText(
        "YouTube で公開日時が設定された未公開動画の本数"
      )
    ).toBeInTheDocument()
    expect(within(metricGuide).getByText("期間再生数")).toBeInTheDocument()
    expect(
      within(metricGuide).getByText("対象期間中に動画が再生された回数")
    ).toBeInTheDocument()
  })

  it("shows channel metrics before a channel is selected", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(overview), { status: 200 })
    )

    renderDashboard()

    const comparisonTable = await screen.findByRole("table", {
      name: "チャンネル横断ストック一覧",
    })
    const channelRow = within(comparisonTable).getByRole("row", {
      name: /Night Drive/,
    })
    expect(within(channelRow).getByText("1,200")).toBeInTheDocument()
    expect(within(channelRow).getByText("450分")).toBeInTheDocument()
    expect(within(channelRow).getByText("+12")).toBeInTheDocument()
    expect(
      within(channelRow).getByRole("button", {
        name: "Night Drive の動画詳細を見る",
      })
    ).toBeInTheDocument()
    expect(
      screen.queryByRole("heading", { name: "チャンネル概要" })
    ).not.toBeInTheDocument()
    expect(
      screen.queryByText("チャンネルを選択してください")
    ).not.toBeInTheDocument()
  })

  it("loads overview and lets a keyboard user inspect video metrics", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input)
      return new Response(
        JSON.stringify(url.endsWith("channel-a") ? detail : overview),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }
      )
    })
    const user = userEvent.setup()

    renderDashboard()

    const channelButton = await screen.findByRole("button", {
      name: /Night Drive/,
    })
    channelButton.focus()
    await user.keyboard("{Enter}")

    expect(
      await screen.findByRole("cell", { name: "Midnight City" })
    ).toBeInTheDocument()
    expect(
      screen.getByRole("heading", { name: "動画パフォーマンス" })
    ).toBeInTheDocument()
    const performanceCard = screen
      .getByRole("heading", { name: "動画パフォーマンス" })
      .closest("[data-slot='card']") as HTMLElement | null
    if (performanceCard === null) throw new Error("performance card is missing")
    expect(
      within(performanceCard).getByRole("cell", { name: "1,200" })
    ).toBeInTheDocument()
    const comparisonRow = screen.getByRole("row", { name: /Night Drive/ })
    expect(within(comparisonRow).getByText("3本")).toBeInTheDocument()
    expect(screen.queryByText("準備完了")).not.toBeInTheDocument()
  })

  it("shows an empty state when no channels are registered", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ schema_version: 1, channels: [] }), {
        status: 200,
      })
    )

    renderDashboard()

    expect(
      await screen.findByText("登録済みチャンネルがありません")
    ).toBeInTheDocument()
  })

  it("counts channels with unavailable data as needing attention", async () => {
    const unavailableOverview = {
      ...overview,
      channels: [
        {
          ...overview.channels[0],
          status: "missing_snapshot",
          scheduled_count: null,
          collected_at: null,
          period: { start_date: null, end_date: null },
          summary: null,
        },
      ],
    }
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(unavailableOverview), { status: 200 })
    )

    renderDashboard()

    const overviewRegion = await screen.findByRole("region", { name: "概況" })
    const attentionMetric = within(overviewRegion)
      .getByText("要確認")
      .closest("div")
    if (attentionMetric === null) throw new Error("要確認 metric is missing")
    expect(within(attentionMetric).getByText("1")).toBeInTheDocument()
    expect(screen.getByText("データ未収集")).toBeInTheDocument()
  })

  it("marks a channel whose startup refresh failed in the overview", async () => {
    const refreshError = {
      code: "refresh_failed",
      message: "Authentication failed",
    }
    const failedOverview = {
      ...overview,
      channels: [{ ...overview.channels[0], refresh_error: refreshError }],
    }
    const failedDetail = { ...detail, refresh_error: refreshError }
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const payload = String(input).endsWith("channel-a")
        ? failedDetail
        : failedOverview
      return new Response(JSON.stringify(payload), { status: 200 })
    })

    renderDashboard()

    expect(
      await screen.findAllByLabelText("更新失敗: Authentication failed")
    ).toHaveLength(1)
    const stockTable = screen.getByRole("table", {
      name: "チャンネル横断ストック一覧",
    })
    const stockRow = within(stockTable).getByRole("row", {
      name: /Night Drive/,
    })
    expect(within(stockRow).getByText("3本")).toBeInTheDocument()
    expect(within(stockRow).queryByText("未取得")).not.toBeInTheDocument()
  })

  it("lets a user preview and keep the dashboard color palette", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(overview), { status: 200 })
    )
    const user = userEvent.setup()

    renderDashboard()

    await screen.findByRole("heading", { name: "概況" })
    expect(
      screen.queryByRole("group", { name: "カラーパレット" })
    ).not.toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "設定を開く" }))

    const settings = screen.getByRole("dialog", { name: "設定" })
    const paletteGroup = within(settings).getByRole("group", {
      name: "カラーパレット",
    })
    const blue = within(paletteGroup).getByRole("button", { name: "Blue" })
    const green = within(paletteGroup).getByRole("button", { name: "Green" })
    expect(blue).toHaveAttribute("aria-pressed", "true")
    expect(
      screen.getByRole("img", {
        name: "Blue の5段階配色。1〜3系列では 100、500、900 を使用",
      })
    ).toBeInTheDocument()

    await user.click(green)

    expect(green).toHaveAttribute("aria-pressed", "true")
    expect(
      screen.getByRole("img", {
        name: "Green の5段階配色。1〜3系列では 100、600、900 を使用",
      })
    ).toBeInTheDocument()
    expect(document.documentElement).toHaveAttribute("data-palette", "green")
    expect(localStorage.getItem("palette")).toBe("green")
  })

  it("shows an alert when the overview request fails", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("failed", { status: 500 })
    )

    renderDashboard()

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        "読み込めませんでした"
      )
    )
  })
})
