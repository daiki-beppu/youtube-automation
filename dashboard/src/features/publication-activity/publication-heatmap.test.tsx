import "@testing-library/jest-dom/vitest"

import { fireEvent, render, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { PublicationHeatmap } from "./publication-heatmap"

describe("PublicationHeatmap", () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it("places the 365 days ending today into week and weekday positions", () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date("2026-08-08T12:00:00Z"))

    render(<PublicationHeatmap channels={[]} days={{}} />)

    const grid = screen.getByRole("grid", { name: "日別公開本数" })
    const rows = within(grid).getAllByRole("row")
    const cells = within(grid).getAllByRole("gridcell")
    expect(rows).toHaveLength(7)
    expect(cells).toHaveLength(365)
    expect(
      screen.getByRole("gridcell", { name: "2025-08-09: 0本" })
    ).toHaveAttribute("data-week", "0")
    expect(
      screen.getByRole("gridcell", { name: "2025-08-09: 0本" })
    ).toHaveAttribute("data-weekday", "6")
    expect(
      screen.getByRole("gridcell", { name: "2026-08-08: 0本" })
    ).toHaveAttribute("data-week", "52")
    expect(
      screen.getByRole("gridcell", { name: "2026-08-08: 0本" })
    ).toHaveAttribute("data-weekday", "6")

    for (const row of rows) {
      expect(row.parentElement).toBe(grid)
      expect(within(row).getAllByRole("gridcell").length).toBeGreaterThan(0)
      for (const cell of within(row).getAllByRole("gridcell")) {
        expect(cell.parentElement).toBe(row)
      }
    }
  })

  it("shows four non-zero intensity levels and the five-level legend", () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date("2026-08-08T12:00:00Z"))

    render(
      <PublicationHeatmap
        channels={[]}
        days={{
          "2026-08-04": 1,
          "2026-08-05": 2,
          "2026-08-06": 3,
          "2026-08-07": 4,
        }}
      />
    )

    for (const [date, intensity] of [
      ["2026-08-04", "1"],
      ["2026-08-05", "2"],
      ["2026-08-06", "3"],
      ["2026-08-07", "4"],
    ]) {
      expect(
        screen.getByRole("gridcell", { name: new RegExp(date) })
      ).toHaveAttribute("data-intensity", intensity)
    }
    const legend = screen.getByRole("list", { name: "公開本数の凡例" })
    expect(
      within(legend)
        .getAllByRole("listitem")
        .map((item) => item.getAttribute("aria-label"))
    ).toEqual(["0本", "1本", "2本", "3本", "4本以上"])
  })

  it("aligns ordered month labels to their week columns", () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date("2026-08-08T12:00:00Z"))

    render(<PublicationHeatmap channels={[]} days={{}} />)

    const months = screen.getByRole("list", { name: "月" })
    const labels = within(months).getAllByRole("listitem")
    expect(labels.slice(0, 4).map((item) => item.textContent)).toEqual([
      "8月",
      "9月",
      "10月",
      "11月",
    ])
    expect(labels.slice(0, 4).map((item) => item.dataset.week)).toEqual([
      "0",
      "4",
      "8",
      "12",
    ])
    expect(labels.slice(0, 4).map((item) => item.style.gridColumn)).toEqual([
      "1",
      "5",
      "9",
      "13",
    ])

    const weekdays = screen.getByRole("list", { name: "曜日" })
    expect(
      within(weekdays)
        .getAllByRole("listitem")
        .map((item) => item.textContent)
    ).toEqual(["日", "月", "火", "水", "木", "金", "土"])
  })

  it("contains the fixed-width week grid in a horizontal scroll boundary", () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date("2026-08-08T12:00:00Z"))

    render(<PublicationHeatmap channels={[]} days={{}} />)

    const boundary = screen.getByTestId("publication-heatmap-scroll")
    expect(boundary).toHaveStyle({ maxWidth: "100%", overflowX: "auto" })
    expect(screen.getByRole("grid", { name: "日別公開本数" })).toHaveStyle({
      gridTemplateColumns: "repeat(53, 11px)",
    })
  })

  it("shows the same date, total, and channel breakdown on pointer hover and keyboard focus", () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date("2026-08-08T12:00:00Z"))
    const channels = [
      {
        id: "channel-a",
        name: "Night Drive",
        status: "ready",
        fetched_at: "2026-08-08T10:00:00Z",
        timezone: "Asia/Tokyo",
        days: { "2026-08-08": 2 },
        error: null,
      },
      {
        id: "channel-b",
        name: "Morning Focus",
        status: "ready",
        fetched_at: "2026-08-08T10:00:00Z",
        timezone: "Asia/Tokyo",
        days: { "2026-08-08": 1 },
        error: null,
      },
    ]

    render(
      <PublicationHeatmap
        channels={channels}
        days={{ "2026-08-08": 3 }}
      />
    )

    const cell = screen.getByRole("gridcell", {
      name: "2026-08-08: 3本",
    })
    fireEvent.mouseEnter(cell)
    const pointerDetails = screen.getByRole("tooltip")
    expect(pointerDetails).toHaveTextContent("2026-08-08")
    expect(pointerDetails).toHaveTextContent("合計 3本")
    expect(pointerDetails).toHaveTextContent("Night Drive 2本")
    expect(pointerDetails).toHaveTextContent("Morning Focus 1本")
    const pointerContent = pointerDetails.textContent

    fireEvent.mouseLeave(cell)
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument()

    cell.focus()
    fireEvent.focus(cell)
    const focusDetails = screen.getByRole("tooltip")
    expect(focusDetails.textContent).toBe(pointerContent)
    expect(cell).toHaveFocus()
    expect(cell).toHaveAttribute("aria-describedby", focusDetails.id)
  })

  it("shows the hovered cell after another cell received keyboard focus", () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date("2026-08-08T12:00:00Z"))

    render(
      <PublicationHeatmap
        channels={[]}
        days={{ "2026-08-07": 1, "2026-08-08": 2 }}
      />
    )

    const focusedCell = screen.getByRole("gridcell", {
      name: "2026-08-07: 1本",
    })
    const hoveredCell = screen.getByRole("gridcell", {
      name: "2026-08-08: 2本",
    })
    focusedCell.focus()
    fireEvent.focus(focusedCell)

    fireEvent.mouseEnter(hoveredCell)

    expect(screen.getByRole("tooltip")).toHaveTextContent("2026-08-08")
    expect(screen.getByRole("tooltip")).toHaveTextContent("合計 2本")
  })
})
