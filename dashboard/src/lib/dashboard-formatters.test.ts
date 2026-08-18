import { describe, expect, it } from "vitest"

import {
  formatCollectedAt,
  formatDateRange,
  formatInteger,
  formatPeriodViewsLabel,
  formatSignedDuration,
  formatSignedInteger,
  formatWatchTime,
} from "./dashboard-formatters"

describe("dashboard formatters", () => {
  it("keeps zero neutral while formatting positive and negative integers", () => {
    expect(formatInteger(0)).toBe("0")
    expect(formatSignedInteger(0)).toBe("0")
    expect(formatSignedInteger(12)).toBe("+12")
    expect(formatSignedInteger(-4)).toBe("-4")
  })

  it("formats signed seconds as a comparable hours timestamp", () => {
    expect(formatSignedDuration(3661)).toBe("+01:01:01")
    expect(formatSignedDuration(0)).toBe("00:00:00")
    expect(formatSignedDuration(-61)).toBe("-00:01:01")
  })

  it.each([
    [450, "7時間30分"],
    [120, "2時間"],
    [45, "45分"],
    [0, "0分"],
    [74100, "1,235時間"],
    [450.6, "7時間31分"],
  ])("formats %s watch-time minutes as %s", (minutes, expected) => {
    expect(formatWatchTime(minutes)).toBe(expected)
  })

  it("rounds fractional durations to the nearest second", () => {
    expect(formatSignedDuration(59.5)).toBe("+00:01:00")
    expect(formatSignedDuration(-0.4)).toBe("00:00:00")
  })

  it.each([Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY])(
    "rejects a non-finite duration: %s",
    (value) => {
      expect(() => formatSignedDuration(value)).toThrow(RangeError)
    }
  )

  it("shows collection fallbacks without hiding an invalid timestamp", () => {
    expect(formatCollectedAt(null)).toBe("未収集")
    expect(formatCollectedAt("not-a-date")).toBe("not-a-date")
  })

  it("preserves whichever date-range endpoint is available", () => {
    expect(formatDateRange(null, null)).toBe("未収集")
    expect(formatDateRange("2026-07-01", null)).toBe("2026/07/01〜未収集")
    expect(formatDateRange(null, "2026-07-20")).toBe("未収集〜2026/07/20")
  })

  it("formats a compact period views label only for two valid dates", () => {
    expect(formatPeriodViewsLabel("2026-04-01", "2026-06-30")).toBe(
      "期間再生数 (04/01 ~ 06/30)"
    )
    expect(formatPeriodViewsLabel(null, "2026-06-30")).toBe("期間再生数")
    expect(formatPeriodViewsLabel("2026-02-30", "2026-06-30")).toBe(
      "期間再生数"
    )
  })
})
