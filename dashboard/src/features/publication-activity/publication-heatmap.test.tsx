import "@testing-library/jest-dom/vitest"

import { fireEvent, render, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { formatCollectedAt } from "@/lib/dashboard-formatters"

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

  it("omits month and weekday axis labels", () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date("2026-08-08T12:00:00Z"))

    render(<PublicationHeatmap channels={[]} days={{}} />)

    expect(screen.queryByRole("list", { name: "月" })).not.toBeInTheDocument()
    expect(screen.queryByRole("list", { name: "曜日" })).not.toBeInTheDocument()
    expect(
      screen.getByRole("grid", { name: "日別公開本数" })
    ).toBeInTheDocument()
  })

  it("fills the scroll boundary with week columns that keep an 11px minimum", () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date("2026-08-08T12:00:00Z"))

    render(<PublicationHeatmap channels={[]} days={{}} />)

    const boundary = screen.getByTestId("publication-heatmap-scroll")
    expect(boundary).toHaveStyle({ maxWidth: "100%", overflowX: "auto" })
    const grid = screen.getByRole("grid", { name: "日別公開本数" })
    expect(grid).toHaveStyle({
      gridTemplateColumns: "repeat(53, minmax(11px, 1fr))",
      minWidth: "calc(583px + 156px)",
      width: "100%",
    })
    expect(within(grid).getAllByRole("gridcell")[0]).toHaveStyle({
      aspectRatio: "1 / 1",
      minWidth: "11px",
      width: "100%",
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
      <PublicationHeatmap channels={channels} days={{ "2026-08-08": 3 }} />
    )

    const cell = screen.getByRole("gridcell", {
      name: "2026-08-08: 3本",
    })
    const grid = screen.getByRole("grid", { name: "日別公開本数" })
    fireEvent.mouseEnter(cell)
    const pointerDetails = screen.getByRole("tooltip")
    expect(pointerDetails).toHaveTextContent("2026-08-08")
    expect(pointerDetails).toHaveTextContent("合計 3本")
    expect(pointerDetails).toHaveTextContent("Night Drive 2本")
    expect(pointerDetails).toHaveTextContent("Morning Focus 1本")
    const pointerContent = pointerDetails.textContent

    fireEvent.mouseLeave(cell, { relatedTarget: grid })
    expect(screen.getByRole("tooltip")).toBeInTheDocument()

    fireEvent.mouseLeave(grid)
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument()

    cell.focus()
    fireEvent.focus(cell)
    const focusDetails = screen.getByRole("tooltip")
    expect(focusDetails.textContent).toBe(pointerContent)
    expect(cell).toHaveFocus()
    expect(cell).toHaveAttribute("aria-describedby", focusDetails.id)
  })

  it("keeps hover details out of document flow and visible across cell gaps", () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date("2026-08-08T12:00:00Z"))
    render(
      <PublicationHeatmap
        channels={[]}
        days={{ "2026-08-07": 1, "2026-08-08": 2 }}
      />
    )
    const grid = screen.getByRole("grid", { name: "日別公開本数" })
    expect(screen.getByTestId("publication-heatmap-anchor")).toHaveStyle({
      minWidth: "0",
      position: "relative",
      width: "100%",
    })
    const first = screen.getByRole("gridcell", { name: "2026-08-07: 1本" })
    const second = screen.getByRole("gridcell", { name: "2026-08-08: 2本" })

    fireEvent.mouseEnter(first)
    fireEvent.mouseLeave(first, { relatedTarget: grid })
    expect(screen.getByRole("tooltip")).toHaveTextContent("2026-08-07")
    fireEvent.mouseEnter(second)
    const details = screen.getByRole("tooltip")
    expect(details).toHaveTextContent("2026-08-08")
    expect(details).toHaveStyle({ position: "absolute" })

    fireEvent.mouseLeave(grid)
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument()
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

  it("keeps stale publication days while announcing refresh failures and the latest fetched time", () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date("2026-08-08T12:00:00Z"))
    const channels = [
      {
        id: "channel-a",
        name: "Night Drive",
        status: "refresh_failed",
        fetched_at: "2026-08-08T10:00:00Z",
        timezone: "Asia/Tokyo",
        days: { "2026-08-08": 2 },
        error: {
          code: "publication_refresh_failed",
          message: "quota exceeded",
          attempted_at: "2026-08-08T12:00:00Z",
        },
      },
      {
        id: "channel-b",
        name: "Morning Focus",
        status: "ready",
        fetched_at: "2026-08-08T11:00:00Z",
        timezone: "Asia/Tokyo",
        days: { "2026-08-08": 1 },
        error: null,
      },
    ]

    render(
      <PublicationHeatmap channels={channels} days={{ "2026-08-08": 3 }} />
    )

    const alert = screen.getByRole("alert", {
      name: "Night Drive の公開活動更新失敗",
    })
    expect(alert).toHaveTextContent("quota exceeded")
    expect(alert).toHaveTextContent("前回データを表示しています")
    expect(screen.getByText(/^最終更新/)).toHaveTextContent(
      /2026\/08\/08.*\d{1,2}:\d{2}/
    )

    const cell = screen.getByRole("gridcell", {
      name: "2026-08-08: 3本",
    })
    cell.focus()
    fireEvent.focus(cell)
    expect(screen.getByRole("tooltip")).toHaveTextContent("Night Drive 2本")
    expect(screen.getByRole("tooltip")).toHaveTextContent("Morning Focus 1本")
  })

  it("does not synthesize a fetched time when channels have none", () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date("2026-08-08T12:00:00Z"))

    render(
      <PublicationHeatmap
        channels={[
          {
            id: "channel-a",
            name: "Night Drive",
            status: "missing",
            fetched_at: null,
            timezone: null,
            days: {},
            error: null,
          },
        ]}
        days={{}}
      />
    )

    expect(screen.queryByText(/^最終更新/)).not.toBeInTheDocument()
    expect(screen.queryByRole("alert")).not.toBeInTheDocument()
    expect(
      screen.getByRole("grid", { name: "日別公開本数" })
    ).toBeInTheDocument()
  })

  it("selects the latest fetched time by instant across offsets", () => {
    const laterTimestamp = "2026-08-08T23:30:00-07:00"

    render(
      <PublicationHeatmap
        channels={[
          {
            id: "channel-a",
            name: "Night Drive",
            status: "ready",
            fetched_at: laterTimestamp,
            timezone: "America/Los_Angeles",
            days: {},
            error: null,
          },
          {
            id: "channel-b",
            name: "Morning Focus",
            status: "ready",
            fetched_at: "2026-08-09T01:00:00+09:00",
            timezone: "Asia/Tokyo",
            days: {},
            error: null,
          },
        ]}
        days={{}}
      />
    )

    expect(screen.getByText(/^最終更新/)).toHaveTextContent(
      `最終更新 ${formatCollectedAt(laterTimestamp)}`
    )
  })
})
