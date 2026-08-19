import { render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import App from "./App"

afterEach(() => vi.unstubAllGlobals())

describe("Audio Studio", () => {
  it("renders track names, durations, formats, and audio sources", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            collection_name: "夜明け前のローファイ",
            tracks: [
              {
                id: "track-1",
                file_name: "01 Morning.mp3",
                duration_seconds: 185,
                extension: "mp3",
                audio_url: "/api/tracks/track-1/audio",
              },
            ],
          })
        )
      )
    )

    render(<App />)

    expect(await screen.findByText("01 · 01 Morning.mp3")).toBeInTheDocument()
    expect(screen.getByText("再生時間 3:05")).toBeInTheDocument()
    expect(screen.getByText("MP3")).toBeInTheDocument()
    expect(screen.getByLabelText("01 Morning.mp3 を再生")).toHaveAttribute(
      "src",
      "/api/tracks/track-1/audio"
    )
  })

  it("renders the shadcn empty state for a collection without tracks", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(
            JSON.stringify({ collection_name: "Empty collection", tracks: [] })
          )
        )
    )

    render(<App />)

    expect(
      await screen.findByText("トラックはまだありません")
    ).toBeInTheDocument()
  })

  it("renders a destructive alert when the API fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(null, { status: 500 }))
    )

    render(<App />)

    await waitFor(() =>
      expect(
        screen.getByText("トラックを読み込めませんでした")
      ).toBeInTheDocument()
    )
  })
})
