import "@testing-library/jest-dom/vitest"

import { render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { ChartContainer, ChartTooltipContent, type ChartConfig } from "./chart"

const config = {
  views: { label: "再生数", color: "#123456" },
} satisfies ChartConfig

describe("chart boundaries", () => {
  it("rejects tooltip rendering without chart context", () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {})

    expect(() =>
      render(
        <ChartTooltipContent
          active
          payload={[{ graphicalItemId: "views", name: "views", value: 10 }]}
        />
      )
    ).toThrow("useChart must be used within a <ChartContainer />")
    consoleError.mockRestore()
  })

  it("renders no tooltip for inactive or empty payloads", () => {
    const { rerender } = render(
      <ChartContainer config={config}>
        <ChartTooltipContent active={false} payload={[]} />
      </ChartContainer>
    )
    expect(screen.queryByText("再生数")).not.toBeInTheDocument()

    rerender(
      <ChartContainer config={config}>
        <ChartTooltipContent active payload={[]} />
      </ChartContainer>
    )
    expect(screen.queryByText("再生数")).not.toBeInTheDocument()
  })

  it("resolves configured labels and values from tooltip payload", () => {
    render(
      <ChartContainer config={config}>
        <ChartTooltipContent
          active
          payload={[
            {
              dataKey: "views",
              graphicalItemId: "views",
              name: "views",
              value: 1234,
              color: "#123456",
              payload: { views: 1234 },
            },
          ]}
        />
      </ChartContainer>
    )

    expect(screen.getAllByText("再生数")).toHaveLength(2)
    expect(screen.getByText("1,234")).toBeInTheDocument()
  })

  it("uses the formatter output for a populated payload", () => {
    const formatter = vi.fn(() => <strong>custom value</strong>)
    render(
      <ChartContainer config={config}>
        <ChartTooltipContent
          active
          formatter={formatter}
          payload={[
            {
              dataKey: "views",
              graphicalItemId: "views",
              name: "views",
              value: 10,
              payload: { views: 10 },
            },
          ]}
        />
      </ChartContainer>
    )

    expect(screen.getByText("custom value")).toBeInTheDocument()
    expect(formatter).toHaveBeenCalledWith(
      10,
      "views",
      expect.objectContaining({ dataKey: "views" }),
      0,
      { views: 10 }
    )
  })
})
