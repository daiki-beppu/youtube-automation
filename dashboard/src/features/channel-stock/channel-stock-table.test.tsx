import "@testing-library/jest-dom/vitest"

import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

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
  it("lets the user open channel details from the comparison row", async () => {
    const onSelect = vi.fn()
    const user = userEvent.setup()

    render(
      <ChannelStockTable
        channels={[channel("Night Drive", 3)]}
        onSelect={onSelect}
        selectedId={null}
      />
    )

    await user.click(
      screen.getByRole("button", {
        name: "Night Drive の動画詳細を見る",
      })
    )

    expect(onSelect).toHaveBeenCalledOnce()
    expect(onSelect).toHaveBeenCalledWith("night-drive")
  })

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
      "期間再生数 (06/20 ~ 07/20)",
      "純増登録者",
      "総再生時間",
    ])
    const row = within(table).getByRole("row", { name: /Night Drive/ })
    expect(within(row).getByText("正常")).toBeInTheDocument()
    expect(within(row).getByText("1,200")).toBeInTheDocument()
    expect(within(row).getByText("+12")).toBeInTheDocument()
    expect(within(row).getByText("7時間30分")).toBeInTheDocument()
    expect(
      within(row).getByText("期間再生数 (06/20 ~ 07/20)")
    ).toBeInTheDocument()
  })

  it("shows the earliest start and latest end when channel periods differ", () => {
    const channels = [
      {
        ...channel("Later period", 3),
        period: { start_date: "2026-05-02", end_date: "2026-05-31" },
      },
      {
        ...channel("Wider period", 4),
        period: { start_date: "2026-04-01", end_date: "2026-06-30" },
      },
      {
        ...channel("Invalid period", 5),
        period: { start_date: "not-a-date", end_date: "2026-02-30" },
      },
    ]

    render(<ChannelStockTable channels={channels} />)

    expect(
      screen.getByRole("columnheader", {
        name: "期間再生数 (04/01 ~ 06/30)",
      })
    ).toBeInTheDocument()
  })

  it("uses the base views label when either period endpoint is unavailable", () => {
    const channels = [
      {
        ...channel("Missing period", 3),
        period: { start_date: null, end_date: "2026-07-20" },
      },
    ]

    render(<ChannelStockTable channels={channels} />)

    expect(
      screen.getByRole("columnheader", { name: "期間再生数" })
    ).toBeInTheDocument()
    expect(
      within(screen.getByRole("row", { name: /Missing period/ })).getByText(
        "期間再生数"
      )
    ).toBeInTheDocument()
  })

  it("keeps the sign visible while exposing subscriber change semantics", () => {
    const channels = [
      channel("Growing", 3),
      {
        ...channel("Declining", 3),
        summary: { ...summary, subscribers_net: -4 },
      },
    ]
    render(<ChannelStockTable channels={channels} />)

    expect(screen.getByText("+12")).toHaveAttribute("data-tone", "positive")
    expect(screen.getByText("-4")).toHaveAttribute("data-tone", "negative")
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
      .map(
        (row) =>
          within(row).getAllByRole("cell")[0].querySelector("span")?.textContent
      )
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
      .map(
        (row) =>
          within(row).getAllByRole("cell")[0].querySelector("span")?.textContent
      )
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

  it("distinguishes unavailable analytics data from a healthy channel", () => {
    const channels = [
      {
        ...channel("Not ready", null),
        status: "missing_snapshot",
      },
    ]

    render(<ChannelStockTable channels={channels} />)

    const row = screen.getByRole("row", { name: /Not ready/ })
    expect(within(row).getByText("データ未収集")).toBeInTheDocument()
    expect(within(row).getByText("未取得")).toBeInTheDocument()
    expect(within(row).queryByText("正常")).not.toBeInTheDocument()
  })

  it.each([
    ["invalid_snapshot", "データエラー"],
    ["invalid_channel", "設定エラー"],
    ["future_status", "future_status"],
  ])("renders %s as a destructive user-visible status", (status, label) => {
    render(
      <ChannelStockTable channels={[{ ...channel("Broken", null), status }]} />
    )

    const badge = within(screen.getByRole("row", { name: /Broken/ })).getByText(
      label
    )
    expect(badge).toHaveClass("bg-destructive/10")
  })

  it("keeps equal stock counts in registry order", () => {
    render(
      <ChannelStockTable
        channels={[
          channel("First registered", 2),
          channel("Second registered", 2),
          channel("Third registered", 2),
        ]}
      />
    )

    const names = screen
      .getAllByRole("row")
      .slice(1)
      .map(
        (row) =>
          within(row).getAllByRole("cell")[0].querySelector("span")?.textContent
      )
    expect(names).toEqual([
      "First registered",
      "Second registered",
      "Third registered",
    ])
  })

  it("reports zero total when every channel stock value is unavailable", () => {
    render(
      <ChannelStockTable
        channels={[
          channel("First unavailable", null),
          channel("Second unavailable", null),
        ]}
      />
    )

    expect(
      screen.getByText("全チャンネル合計 公開予約 0本")
    ).toBeInTheDocument()
    expect(screen.getByText("未取得 2件を除く")).toBeInTheDocument()
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
