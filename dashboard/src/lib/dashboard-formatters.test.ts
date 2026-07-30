import { describe, expect, it } from "vitest"

import {
  formatCollectedAt,
  formatDateRange,
  formatInteger,
  formatSignedInteger,
} from "./dashboard-formatters"

describe("dashboard formatters", () => {
  it("keeps zero neutral while formatting positive and negative integers", () => {
    expect(formatInteger(0)).toBe("0")
    expect(formatSignedInteger(0)).toBe("0")
    expect(formatSignedInteger(12)).toBe("+12")
    expect(formatSignedInteger(-4)).toBe("-4")
  })

  it("shows collection fallbacks without hiding an invalid timestamp", () => {
    expect(formatCollectedAt(null)).toBe("未収集")
    expect(formatCollectedAt("not-a-date")).toBe("not-a-date")
  })

  it("preserves whichever date-range endpoint is available", () => {
    expect(formatDateRange(null, null)).toBe("未収集")
    expect(formatDateRange("2026-07-01", null)).toBe("2026/07/01〜未収集")
    expect(formatDateRange(null, "2026-07-20")).toBe("未収集〜2026/07/20")
  })
})
