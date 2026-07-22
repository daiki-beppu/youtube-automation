import "@testing-library/jest-dom/vitest"

import { render, screen, within } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { ChannelStockTable } from "./channel-stock-table"

type Channel = Parameters<typeof ChannelStockTable>[0]["channels"][number]

const summary = {
  views: 1200,
  watch_time_minutes: 450,
  subscribers_net: 12,
  engagements: 80,
  average_view_percentage: 42.5,
}

function channel(name: string, scheduledCount: number | null): Channel {
  return {
    id: name.toLowerCase().replaceAll(" ", "-"),
    name,
    status: "ready",
    scheduled_count: scheduledCount,
    snapshot: "analytics_data.json",
    collected_at: "2026-07-20T12:00:00Z",
    period: { start_date: "2026-06-20", end_date: "2026-07-20" },
    summary,
    error: null,
    refresh_error: null,
    video_count: 1,
  }
}

describe("ChannelStockTable", () => {
  it("shows the seven contracted columns and card-compatible metrics", () => {
    const channels = [channel("Night Drive", 3)]
    render(<ChannelStockTable channels={channels} />)
    const table = screen.getByRole("table", {
      name: "チャンネル横断ストック一覧",
    })
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((header) => header.textContent)
    ).toEqual([
      "チャンネル",
      "状態",
      "収集時刻",
      "ストック",
      "期間再生数",
      "純増登録者",
      "総再生時間",
    ])
    const row = within(table).getByRole("row", { name: /Night Drive/ })
    expect(within(row).getByText("正常")).toBeInTheDocument()
    expect(within(row).getByText("1,200")).toBeInTheDocument()
    expect(within(row).getByText("+12")).toBeInTheDocument()
    expect(within(row).getByText("450分")).toBeInTheDocument()
  })

  it("places the total summary before the table", () => {
    render(<ChannelStockTable channels={[channel("Night Drive", 3)]} />)

    const summary = screen.getByText("全チャンネル合計 公開予約 3本")
    const table = screen.getByRole("table", {
      name: "チャンネル横断ストック一覧",
    })

    expect(summary.compareDocumentPosition(table)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING
    )
  })

  it("orders numeric stock from zero upward and keeps unavailable channels last", () => {
    const channels = [
      channel("Unavailable", null),
      channel("Three", 3),
      {
        ...channel("Refresh failed", 8),
        refresh_error: {
          code: "refresh_failed",
          message: "Authentication failed",
        },
      },
      channel("Zero", 0),
      channel("Two", 2),
      channel("One", 1),
    ]

    render(<ChannelStockTable channels={channels} />)
    const rows = screen
      .getAllByRole("row")
      .slice(1)
      .map((row) => within(row).getAllByRole("cell")[0].textContent)
    expect(rows).toEqual([
      "Zero",
      "One",
      "Two",
      "Three",
      "Refresh failed",
      "Unavailable",
    ])
  })

  it("keeps stale numeric stock available when refresh fails", () => {
    const channels = [
      channel("Known", 2),
      {
        ...channel("Refresh failed", 8),
        refresh_error: {
          code: "refresh_failed",
          message: "Authentication failed",
        },
      },
      channel("Missing", null),
    ]

    render(<ChannelStockTable channels={channels} />)

    const rows = screen
      .getAllByRole("row")
      .slice(1)
      .map((row) => within(row).getAllByRole("cell")[0].textContent)
    expect(rows).toEqual(["Known", "Refresh failed", "Missing"])
    expect(
      screen.getByText("全チャンネル合計 公開予約 10本")
    ).toBeInTheDocument()
  })

  it.each([
    [0, "destructive"],
    [1, "warning"],
    [2, "warning"],
    [3, "default"],
  ] as const)(
    "uses the %s stock variant for %s scheduled videos",
    (count, variant) => {
      const channels = [channel(`Channel ${count}`, count)]
      render(<ChannelStockTable channels={channels} />)
      const row = screen.getByRole("row", {
        name: new RegExp(`Channel ${count}`),
      })
      const badge = within(row).getByText(`${count}本`)
      if (variant === "destructive") {
        expect(badge).toHaveClass("bg-destructive/10")
      } else if (variant === "warning") {
        expect(badge).toHaveClass("bg-warning/10")
      } else {
        expect(badge).toHaveClass("bg-primary")
      }
    }
  )

  it("shows unavailable stock distinctly and excludes it from the total", () => {
    const failed = {
      ...channel("Refresh failed", 8),
      refresh_error: {
        code: "refresh_failed",
        message: "Authentication failed",
      },
    }
    const channels = [channel("Known", 2), failed, channel("Missing", null)]

    render(<ChannelStockTable channels={channels} />)
    const unavailableBadges = screen.getAllByText("未取得")
    expect(unavailableBadges).toHaveLength(1)
    expect(unavailableBadges[0]).toHaveClass("border-border")
    expect(unavailableBadges[0]).not.toHaveClass("bg-destructive/10")
    expect(
      screen.getByText("全チャンネル合計 公開予約 10本")
    ).toBeInTheDocument()
    expect(screen.getByText(/未取得 1件を除く/)).toBeInTheDocument()
    const failedRow = screen.getByRole("row", { name: /Refresh failed/ })
    expect(within(failedRow).getByText("更新失敗")).toBeInTheDocument()
    expect(
      within(failedRow).getByLabelText("更新失敗: Authentication failed")
    ).toBeInTheDocument()
    expect(within(failedRow).getByText("8本")).toBeInTheDocument()
  })

  it("uses the refresh error contract for status labels", () => {
    const channels = [
      {
        ...channel("Not ready", null),
        status: "missing_snapshot",
      },
    ]

    render(<ChannelStockTable channels={channels} />)

    const row = screen.getByRole("row", { name: /Not ready/ })
    expect(within(row).getByText("正常")).toBeInTheDocument()
    expect(within(row).getByText("未取得")).toBeInTheDocument()
    expect(within(row).queryByText("データ未取得")).not.toBeInTheDocument()
  })

  it("renders all channels without truncating a larger channel set", () => {
    const channels = Array.from({ length: 10 }, (_, index) =>
      channel(`Channel ${index + 1}`, index % 4)
    )

    render(<ChannelStockTable channels={channels} />)
    expect(screen.getAllByRole("row")).toHaveLength(11)
    for (const item of channels) {
      expect(
        screen.getByRole("row", {
          name: new RegExp(`^${item.name}(?:\\s|$)`),
        })
      ).toBeInTheDocument()
    }
  })
})
