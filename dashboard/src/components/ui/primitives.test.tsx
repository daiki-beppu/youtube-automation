import "@testing-library/jest-dom/vitest"

import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "./sheet"
import { ToggleGroup, ToggleGroupItem } from "./toggle-group"

describe("dashboard UI primitive state", () => {
  it.each(["top", "right", "bottom", "left"] as const)(
    "exposes the %s sheet side and close control",
    async (side) => {
      const user = userEvent.setup()
      render(
        <Sheet>
          <SheetTrigger>Open</SheetTrigger>
          <SheetContent side={side}>
            <SheetTitle>Settings</SheetTitle>
          </SheetContent>
        </Sheet>
      )

      await user.click(screen.getByRole("button", { name: "Open" }))

      expect(screen.getByRole("dialog", { name: "Settings" })).toHaveAttribute(
        "data-side",
        side
      )
      expect(screen.getByRole("button", { name: "閉じる" })).toBeInTheDocument()
    }
  )

  it("omits the sheet close control when requested", async () => {
    const user = userEvent.setup()
    render(
      <Sheet>
        <SheetTrigger>Open without close</SheetTrigger>
        <SheetContent showCloseButton={false}>
          <SheetTitle>Settings without close</SheetTitle>
        </SheetContent>
      </Sheet>
    )

    await user.click(screen.getByRole("button", { name: "Open without close" }))

    expect(
      screen.getByRole("dialog", { name: "Settings without close" })
    ).toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: "閉じる" })
    ).not.toBeInTheDocument()
  })

  it("exposes vertical zero-spacing toggle state and selection", async () => {
    const user = userEvent.setup()
    render(
      <ToggleGroup aria-label="layout" orientation="vertical" spacing={0}>
        <ToggleGroupItem value="list">List</ToggleGroupItem>
        <ToggleGroupItem value="grid">Grid</ToggleGroupItem>
      </ToggleGroup>
    )

    const group = screen.getByRole("group", { name: "layout" })
    expect(group).toHaveAttribute("data-orientation", "vertical")
    expect(group).toHaveAttribute("data-spacing", "0")
    expect(screen.getByRole("button", { name: "List" })).toHaveAttribute(
      "data-spacing",
      "0"
    )

    await user.click(screen.getByRole("button", { name: "Grid" }))
    expect(screen.getByRole("button", { name: "Grid" })).toHaveAttribute(
      "aria-pressed",
      "true"
    )
  })
})
