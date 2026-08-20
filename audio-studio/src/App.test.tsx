import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import App from "./App"

const cleanupSettings = {
  eq: {
    enabled: true,
    muddiness_freq_hz: 350,
    muddiness_gain_db: -2,
    harshness_freq_hz: 8000,
    harshness_gain_db: -1.5,
  },
  loudnorm: { enabled: true, I: -14, LRA: 11, TP: -1.5 },
  limiter: { enabled: true, limit: 0.95 },
  trim_silence: { enabled: true, threshold_db: -50 },
  tail_fade_guard: { enabled: true, fade_sec: 3 },
  volume_smoothing: true,
}

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

  it("opens every cleanup group, previews EQ, and saves the full settings", async () => {
    const requests: Array<{ input: RequestInfo | URL; init?: RequestInit }> = []
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
        requests.push({ input, init })
        if (String(input) === "/api/tracks") {
          return Promise.resolve(
            new Response(
              JSON.stringify({
                collection_name: "Preview collection",
                tracks: [
                  {
                    id: "0123456789abcdef",
                    file_name: "01 Preview.mp3",
                    duration_seconds: 120,
                    extension: "mp3",
                    audio_url: "/api/tracks/0123456789abcdef/audio",
                  },
                ],
              })
            )
          )
        }
        return Promise.resolve(
          new Response(
            JSON.stringify({
              defaults: cleanupSettings,
              settings: cleanupSettings,
              overrides: {},
            })
          )
        )
      })
    )

    const filters: Array<{
      frequency: { value: number }
      gain: { value: number }
      connect: (target: object) => object
      type: string
    }> = []
    class AudioContextMock {
      destination = {}
      createMediaElementSource() {
        return { connect: (target: object) => target }
      }
      createBiquadFilter() {
        const filter = {
          frequency: { value: 0 },
          gain: { value: 0 },
          connect: (target: object) => target,
          type: "",
        }
        filters.push(filter)
        return filter
      }
      resume() {
        return Promise.resolve()
      }
    }
    vi.stubGlobal("AudioContext", AudioContextMock)

    render(<App />)
    fireEvent.click(await screen.findByRole("button", { name: "調整" }))

    expect(
      await screen.findByRole("region", {
        name: "01 Preview.mp3 の cleanup 調整",
      })
    ).toBeInTheDocument()
    expect(
      screen.getByRole("switch", { name: "EQ enabled" })
    ).toBeInTheDocument()
    expect(screen.getByLabelText("Loudnorm I (LUFS)")).toBeInTheDocument()
    expect(screen.getByLabelText("Limiter limit")).toBeInTheDocument()
    expect(screen.getByLabelText("Silence threshold (dB)")).toBeInTheDocument()
    expect(screen.getByLabelText("Tail fade (seconds)")).toBeInTheDocument()
    expect(
      screen.getByRole("switch", { name: "Volume smoothing" })
    ).toBeInTheDocument()
    expect(screen.getByText(/ffmpeg の equalizer/)).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText("Muddiness gain (dB) 数値"), {
      target: { value: "-4" },
    })
    expect(filters[0]?.gain.value).toBe(-4)
    expect(screen.getByText("既定値からの変更があります")).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "差分を保存" }))
    await screen.findByText("保存しました")
    const put = requests.find((request) => request.init?.method === "PUT")
    expect(put).toBeDefined()
    expect(JSON.parse(String(put?.init?.body)).settings.eq.muddiness_gain_db).toBe(
      -4
    )
  })
})
