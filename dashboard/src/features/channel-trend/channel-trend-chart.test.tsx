import "@testing-library/jest-dom/vitest"

import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import { ChannelTrendChart } from "./channel-trend-chart"

describe("ChannelTrendChart", () => {
  it("renders ready series and identifies unavailable channels", () => {
    render(
      <ChannelTrendChart
        data={{
          channels: [
            {
              id: "night",
              name: "Night Drive",
              status: "ready",
              points: [
                {
                  date: "2026-08-01",
                  views: 48,
                  watch_time_minutes: 90,
                  subscribers_net: 3,
                  impressions: 2400,
                },
              ],
              error: null,
            },
            {
              id: "missing",
              name: "Morning Focus",
              status: "missing_snapshot",
              points: [],
              error: { code: "snapshot_missing", message: "snapshot missing" },
            },
          ],
        }}
      />
    )

    expect(
      screen.getByRole("region", { name: "日次再生数の推移" })
    ).toBeInTheDocument()
    expect(screen.getByText("Night Drive")).toBeInTheDocument()
    expect(
      screen.getByText("Morning Focus の推移を表示できません")
    ).toBeInTheDocument()
  })

  it("switches the same channel series across all daily metrics", async () => {
    const user = userEvent.setup()
    const { container } = render(
      <ChannelTrendChart
        data={{
          channels: [
            {
              id: "night",
              name: "Night Drive",
              status: "ready",
              points: [
                {
                  date: "2026-08-01",
                  views: 120,
                  watch_time_minutes: 90,
                  subscribers_net: 3,
                  impressions: 2400,
                },
              ],
              error: null,
            },
          ],
        }}
      />
    )

    const metricGroup = screen.getByRole("group", { name: "表示指標" })
    const tooltip = () => {
      const element = container.querySelector(".recharts-tooltip-wrapper")
      if (!(element instanceof HTMLElement)) {
        throw new Error("trend chart tooltip is missing")
      }
      return element
    }
    const yAxisText = () =>
      container.querySelector(".recharts-yAxis-tick-labels")?.textContent
    expect(
      within(metricGroup)
        .getAllByRole("button")
        .map((button) => button.textContent)
    ).toEqual(["再生数", "再生時間", "チャンネル登録者", "インプレッション数"])
    expect(
      within(metricGroup).getByRole("button", {
        name: "再生数",
        pressed: true,
      })
    ).toBeInTheDocument()
    expect(
      screen.getByRole("region", { name: "日次再生数の推移" })
    ).toBeInTheDocument()
    expect(yAxisText()).toContain("120")

    await user.click(
      within(metricGroup).getByRole("button", { name: "再生時間" })
    )
    screen.getByRole("application").focus()
    await user.keyboard("{ArrowRight}")
    expect(
      screen.getByRole("region", { name: "日次再生時間の推移" })
    ).toBeInTheDocument()
    expect(within(tooltip()).getByText("1.5時間")).toBeInTheDocument()
    expect(yAxisText()).toContain("時間")

    await user.click(
      within(metricGroup).getByRole("button", { name: "チャンネル登録者" })
    )
    expect(
      screen.getByRole("region", { name: "日次チャンネル登録者の推移" })
    ).toBeInTheDocument()
    expect(yAxisText()).toContain("人")

    await user.click(
      within(metricGroup).getByRole("button", { name: "インプレッション数" })
    )
    expect(
      screen.getByRole("region", { name: "日次インプレッション数の推移" })
    ).toBeInTheDocument()
    expect(yAxisText()).toContain("回")
  })

  it("does not connect a channel line across a missing metric value", async () => {
    const user = userEvent.setup()
    const { container } = render(
      <ChannelTrendChart
        data={{
          channels: [
            {
              id: "night",
              name: "Night Drive",
              status: "ready",
              points: [
                {
                  date: "2026-08-01",
                  views: 10,
                  watch_time_minutes: 10,
                  subscribers_net: 1,
                  impressions: 100,
                },
                {
                  date: "2026-08-02",
                  views: 20,
                  watch_time_minutes: 20,
                  subscribers_net: 2,
                  impressions: null,
                },
                {
                  date: "2026-08-03",
                  views: 30,
                  watch_time_minutes: 30,
                  subscribers_net: 3,
                  impressions: 300,
                },
              ],
              error: null,
            },
          ],
        }}
      />
    )

    await user.click(screen.getByRole("button", { name: "インプレッション数" }))

    const linePath = container.querySelector(".recharts-line-curve")
    expect(linePath?.getAttribute("d")?.match(/M/g)).toHaveLength(2)
  })
})
