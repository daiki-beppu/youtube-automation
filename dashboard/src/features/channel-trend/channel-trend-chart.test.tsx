import "@testing-library/jest-dom/vitest"

import { render, screen } from "@testing-library/react"
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
              points: [{ date: "2026-08-01", views: 48 }],
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
})
