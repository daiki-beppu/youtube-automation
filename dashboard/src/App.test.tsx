import "@testing-library/jest-dom/vitest"

import { render, screen, waitFor } from "@testing-library/react"
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
    expect(screen.getByRole("cell", { name: "1,200" })).toBeInTheDocument()
    expect(screen.getAllByText("公開予約 3本")).not.toHaveLength(0)
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
      await screen.findByLabelText("更新失敗: Authentication failed")
    ).toBeInTheDocument()
    expect(screen.getAllByText("公開予約 3本")).not.toHaveLength(0)
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
