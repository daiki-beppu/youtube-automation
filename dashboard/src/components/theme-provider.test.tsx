import "@testing-library/jest-dom/vitest"

import { act, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ThemeProvider, useTheme } from "./theme-provider"

function ThemeProbe() {
  const { palette, setPalette, setTheme, theme } = useTheme()
  return (
    <div>
      <output aria-label="theme">{theme}</output>
      <output aria-label="palette">{palette}</output>
      <button onClick={() => setTheme("dark")}>dark</button>
      <button onClick={() => setPalette("green")}>green</button>
      <input aria-label="editor" />
    </div>
  )
}

function matchMediaStub(initialMatches = false) {
  let matches = initialMatches
  let listener: (() => void) | undefined
  const mediaQuery = {
    get matches() {
      return matches
    },
    addEventListener: vi.fn((_event: string, callback: () => void) => {
      listener = callback
    }),
    removeEventListener: vi.fn(),
  }
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => mediaQuery)
  )
  return {
    mediaQuery,
    change(nextMatches: boolean) {
      matches = nextMatches
      act(() => listener?.())
    },
  }
}

function storageEvent(
  key: string,
  newValue: string | null,
  storageArea: Storage = localStorage
) {
  const event = new Event("storage")
  Object.defineProperties(event, {
    key: { value: key },
    newValue: { value: newValue },
    storageArea: { value: storageArea },
  })
  return event
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  document.documentElement.className = ""
  delete document.documentElement.dataset.palette
})

describe("ThemeProvider", () => {
  it("falls back from invalid stored browser values", () => {
    localStorage.setItem("theme", "sepia")
    localStorage.setItem("palette", "infrared")
    matchMediaStub()

    render(
      <ThemeProvider defaultTheme="light" disableTransitionOnChange={false}>
        <ThemeProbe />
      </ThemeProvider>
    )

    expect(screen.getByLabelText("theme")).toHaveTextContent("light")
    expect(screen.getByLabelText("palette")).toHaveTextContent("blue")
    expect(document.documentElement).toHaveClass("light")
    expect(document.documentElement).toHaveAttribute("data-palette", "blue")
  })

  it("tracks system theme changes and removes the media listener", () => {
    const media = matchMediaStub(false)
    const { unmount } = render(
      <ThemeProvider disableTransitionOnChange={false}>
        <ThemeProbe />
      </ThemeProvider>
    )
    expect(document.documentElement).toHaveClass("light")

    media.change(true)
    expect(document.documentElement).toHaveClass("dark")

    unmount()
    expect(media.mediaQuery.removeEventListener).toHaveBeenCalledWith(
      "change",
      expect.any(Function)
    )
  })

  it("ignores theme shortcuts from editable, repeated, and modified key events", () => {
    matchMediaStub(false)
    render(
      <ThemeProvider defaultTheme="light" disableTransitionOnChange={false}>
        <ThemeProbe />
      </ThemeProvider>
    )
    const editor = screen.getByRole("textbox", { name: "editor" })

    act(() => {
      editor.dispatchEvent(
        new KeyboardEvent("keydown", { key: "d", bubbles: true })
      )
      window.dispatchEvent(
        new KeyboardEvent("keydown", { key: "d", repeat: true })
      )
      window.dispatchEvent(
        new KeyboardEvent("keydown", { key: "d", ctrlKey: true })
      )
    })
    expect(screen.getByLabelText("theme")).toHaveTextContent("light")

    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "d" }))
    })
    expect(screen.getByLabelText("theme")).toHaveTextContent("dark")
  })

  it("filters storage events and applies valid external changes", () => {
    matchMediaStub(false)
    render(
      <ThemeProvider defaultTheme="light" disableTransitionOnChange={false}>
        <ThemeProbe />
      </ThemeProvider>
    )

    act(() => {
      window.dispatchEvent(storageEvent("unrelated", "dark"))
      window.dispatchEvent(storageEvent("theme", "dark", sessionStorage))
    })
    expect(screen.getByLabelText("theme")).toHaveTextContent("light")

    act(() => {
      window.dispatchEvent(storageEvent("theme", "dark"))
      window.dispatchEvent(storageEvent("palette", "green"))
    })
    expect(screen.getByLabelText("theme")).toHaveTextContent("dark")
    expect(screen.getByLabelText("palette")).toHaveTextContent("green")

    act(() => {
      window.dispatchEvent(storageEvent("theme", "sepia"))
      window.dispatchEvent(storageEvent("palette", "infrared"))
    })
    expect(screen.getByLabelText("theme")).toHaveTextContent("light")
    expect(screen.getByLabelText("palette")).toHaveTextContent("blue")
  })

  it("rejects useTheme consumers outside the provider", () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {})
    function OutsideConsumer() {
      useTheme()
      return null
    }

    expect(() => render(<OutsideConsumer />)).toThrow(
      "useTheme must be used within a ThemeProvider"
    )
    consoleError.mockRestore()
  })
})
