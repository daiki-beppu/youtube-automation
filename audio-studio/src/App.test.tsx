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

const finalizeSettings = {
  ambient_layers: {
    dirname: "rain_layers",
    glob: "rain_*.wav",
    volume_db: -19,
    fadein_s: 0.5,
    fadein_curve: "tri",
    layers: {},
  },
  loudnorm: { enabled: true, mode: "linear", I: -14, LRA: 11, TP: -1.5 },
  mix: { duration: "first", normalize: false },
}

afterEach(() => vi.unstubAllGlobals())

describe("Audio Studio", () => {
  it("renders track names, durations, formats, and audio sources", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((input: RequestInfo | URL) =>
        Promise.resolve(
          new Response(
            JSON.stringify(
              String(input) === "/api/tracks"
                ? {
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
                  }
                : {
                    available: false,
                    audio_url: "/api/master/audio",
                    defaults: {
                      eq: cleanupSettings.eq,
                      loudnorm: cleanupSettings.loudnorm,
                      limiter: cleanupSettings.limiter,
                    },
                    settings: {
                      eq: cleanupSettings.eq,
                      loudnorm: cleanupSettings.loudnorm,
                      limiter: cleanupSettings.limiter,
                    },
                    has_backup: false,
                  }
            )
          )
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
      vi.fn().mockImplementation((input: RequestInfo | URL) =>
        Promise.resolve(
          new Response(
            JSON.stringify(
              String(input) === "/api/tracks"
                ? { collection_name: "Empty collection", tracks: [] }
                : {
                    available: false,
                    audio_url: "/api/master/audio",
                    defaults: {
                      eq: cleanupSettings.eq,
                      loudnorm: cleanupSettings.loudnorm,
                      limiter: cleanupSettings.limiter,
                    },
                    settings: {
                      eq: cleanupSettings.eq,
                      loudnorm: cleanupSettings.loudnorm,
                      limiter: cleanupSettings.limiter,
                    },
                    has_backup: false,
                  }
            )
          )
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
      vi
        .fn()
        .mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
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
    expect(
      JSON.parse(String(put?.init?.body)).settings.eq.muddiness_gain_db
    ).toBe(-4)
  })

  it("reproduces a seeded shuffle, pins tracks first, and saves the exact order", async () => {
    const requests: Array<{ input: RequestInfo | URL; init?: RequestInit }> = []
    const tracks = ["01 First.mp3", "02 Second.mp3", "03 Third.mp3"].map(
      (file_name, index) => ({
        id: `track-${index + 1}`,
        file_name,
        duration_seconds: 60,
        extension: "mp3",
        audio_url: `/api/tracks/track-${index + 1}/audio`,
      })
    )
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
          requests.push({ input, init })
          if (String(input) === "/api/tracks") {
            return Promise.resolve(
              new Response(
                JSON.stringify({ collection_name: "Order test", tracks })
              )
            )
          }
          if (String(input) === "/api/order" && init?.method === "PUT") {
            return Promise.resolve(
              new Response(
                JSON.stringify({
                  ...JSON.parse(String(init.body)),
                  saved: true,
                })
              )
            )
          }
          return Promise.resolve(
            new Response(
              JSON.stringify({
                order: tracks.map((track) => track.file_name),
                shuffle_seed: null,
                pin_first: [],
                saved: false,
              })
            )
          )
        })
    )

    const { container } = render(<App />)
    await screen.findByText("ファイル名順です")
    const firstHandle = screen.getByRole("button", {
      name: "01 First.mp3 をドラッグして並べ替え",
    })
    const secondHandle = screen.getByRole("button", {
      name: "02 Second.mp3 をドラッグして並べ替え",
    })
    fireEvent.pointerDown(firstHandle)
    fireEvent.pointerEnter(secondHandle.closest('[data-slot="card"]')!)
    expect(await screen.findByText("未保存の手動順です")).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText("Shuffle seed"), {
      target: { value: "42" },
    })
    fireEvent.click(screen.getByRole("button", { name: "シャッフル" }))
    const trackTitles = () =>
      Array.from(container.querySelectorAll('[data-slot="card-title"]'))
        .map((element) => element.textContent)
        .filter((title) => title?.includes(".mp3"))
    const firstShuffle = trackTitles()

    fireEvent.click(screen.getByRole("button", { name: "シャッフル" }))
    expect(trackTitles()).toEqual(firstShuffle)

    fireEvent.click(
      screen.getByRole("switch", { name: "03 Third.mp3 を先頭固定" })
    )
    expect(trackTitles()[0]).toContain("03 Third.mp3")
    fireEvent.click(screen.getByRole("button", { name: "曲順を保存" }))
    await screen.findByText("曲順を保存しました")

    const put = requests.find(
      (request) =>
        String(request.input) === "/api/order" && request.init?.method === "PUT"
    )
    const body = JSON.parse(String(put?.init?.body))
    expect(body.order[0]).toBe("03 Third.mp3")
    expect(body.pin_first).toEqual(["03 Third.mp3"])
    expect(body.shuffle_seed).toBeNull()
  })

  it("previews, saves, and applies master settings from the original", async () => {
    const masterSettings = {
      eq: cleanupSettings.eq,
      loudnorm: cleanupSettings.loudnorm,
      limiter: cleanupSettings.limiter,
    }
    const requests: Array<{ input: RequestInfo | URL; init?: RequestInit }> = []
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
          requests.push({ input, init })
          if (String(input) === "/api/tracks") {
            return Promise.resolve(
              new Response(
                JSON.stringify({ collection_name: "Master test", tracks: [] })
              )
            )
          }
          if (
            String(input) === "/api/master/adjustments" &&
            init?.method === "PUT"
          ) {
            return Promise.resolve(
              new Response(
                JSON.stringify({
                  available: true,
                  audio_url: "/api/master/audio",
                  defaults: masterSettings,
                  settings: JSON.parse(String(init.body)).settings,
                  has_backup: false,
                })
              )
            )
          }
          if (String(input) === "/api/master/apply") {
            const put = requests.find(
              (request) =>
                String(request.input) === "/api/master/adjustments" &&
                request.init?.method === "PUT"
            )
            return Promise.resolve(
              new Response(
                JSON.stringify({
                  available: true,
                  audio_url: "/api/master/audio",
                  defaults: masterSettings,
                  settings: JSON.parse(String(put?.init?.body)).settings,
                  has_backup: true,
                  applied: true,
                })
              )
            )
          }
          return Promise.resolve(
            new Response(
              JSON.stringify({
                available: true,
                audio_url: "/api/master/audio",
                defaults: masterSettings,
                settings: masterSettings,
                has_backup: false,
              })
            )
          )
        })
    )
    const filters: Array<{
      gain: { value: number }
      frequency: { value: number }
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
    expect(
      await screen.findByRole("region", { name: "master.mp3 全体調整" })
    ).toBeInTheDocument()
    expect(screen.getByLabelText("master.mp3 を再生")).toHaveAttribute(
      "src",
      "/api/master/audio?revision=0"
    )
    fireEvent.change(screen.getByLabelText("Master muddiness gain (dB) 数値"), {
      target: { value: "-5" },
    })
    expect(filters[0]?.gain.value).toBe(-5)
    fireEvent.click(screen.getByRole("button", { name: "原本から再出力" }))

    await screen.findByText("原本から master.mp3 を再出力しました")
    const put = requests.find((request) => request.init?.method === "PUT")
    expect(
      JSON.parse(String(put?.init?.body)).settings.eq.muddiness_gain_db
    ).toBe(-5)
    expect(
      requests.some(
        (request) =>
          String(request.input) === "/api/master/apply" &&
          request.init?.method === "POST"
      )
    ).toBe(true)
  })

  it("saves ambient overrides and reapplies finalize with master settings", async () => {
    const masterSettings = {
      eq: cleanupSettings.eq,
      loudnorm: cleanupSettings.loudnorm,
      limiter: cleanupSettings.limiter,
    }
    const requests: Array<{ input: RequestInfo | URL; init?: RequestInit }> = []
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
          requests.push({ input, init })
          const url = String(input)
          if (url === "/api/tracks") {
            return Promise.resolve(
              new Response(
                JSON.stringify({ collection_name: "Ambient test", tracks: [] })
              )
            )
          }
          if (url === "/api/master/adjustments") {
            return Promise.resolve(
              new Response(
                JSON.stringify({
                  available: true,
                  audio_url: "/api/master/audio",
                  defaults: masterSettings,
                  settings: masterSettings,
                  has_backup: true,
                })
              )
            )
          }
          if (url === "/api/finalize/adjustments" && init?.method === "PUT") {
            return Promise.resolve(
              new Response(
                JSON.stringify({
                  available: true,
                  reason: null,
                  layers: ["rain_001.wav"],
                  defaults: finalizeSettings,
                  settings: JSON.parse(String(init.body)).settings,
                  has_backup: false,
                })
              )
            )
          }
          if (url === "/api/finalize/apply") {
            const put = requests.find(
              (request) =>
                String(request.input) === "/api/finalize/adjustments" &&
                request.init?.method === "PUT"
            )
            return Promise.resolve(
              new Response(
                JSON.stringify({
                  available: true,
                  reason: null,
                  layers: ["rain_001.wav"],
                  defaults: finalizeSettings,
                  settings: JSON.parse(String(put?.init?.body)).settings,
                  has_backup: true,
                  applied: true,
                  pass_through: false,
                  master_reapplied: true,
                })
              )
            )
          }
          return Promise.resolve(
            new Response(
              JSON.stringify({
                available: true,
                reason: null,
                layers: ["rain_001.wav"],
                defaults: finalizeSettings,
                settings: finalizeSettings,
                has_backup: false,
              })
            )
          )
        })
    )

    render(<App />)
    expect(
      await screen.findByText("Ambient layer finalize")
    ).toBeInTheDocument()
    expect(screen.getAllByText("rain_001.wav").length).toBeGreaterThan(0)
    fireEvent.change(screen.getByLabelText("Ambient volume (dB)"), {
      target: { value: "-26" },
    })
    fireEvent.change(screen.getByLabelText("rain_001.wav volume (dB)"), {
      target: { value: "-30" },
    })
    expect(
      screen.getByRole("button", {
        name: "rain_001.wav volume は共通値を使う",
      })
    ).toBeEnabled()
    fireEvent.click(
      screen.getByRole("button", {
        name: "rain_001.wav volume は共通値を使う",
      })
    )
    expect(
      screen.getAllByRole("option", { name: "nofade" }).length
    ).toBeGreaterThan(0)
    fireEvent.click(
      screen.getByRole("button", { name: "Ambient を原本から再出力" })
    )

    await screen.findByText(
      "ambient と master 全体調整を原本から再出力しました"
    )
    const put = requests.find(
      (request) =>
        String(request.input) === "/api/finalize/adjustments" &&
        request.init?.method === "PUT"
    )
    const saved = JSON.parse(String(put?.init?.body)).settings
    expect(saved.ambient_layers.volume_db).toBe(-26)
    expect(saved.ambient_layers.layers["rain_001.wav"]).toBeUndefined()
  })

  it("disables ambient controls with the pass-through reason when layers are absent", async () => {
    const masterSettings = {
      eq: cleanupSettings.eq,
      loudnorm: cleanupSettings.loudnorm,
      limiter: cleanupSettings.limiter,
    }
    const unavailableFinalizeSettings = {
      ...finalizeSettings,
      ambient_layers: {
        ...finalizeSettings.ambient_layers,
        dirname: "rain_layer",
      },
    }
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
          const url = String(input)
          if (url === "/api/tracks") {
            return Promise.resolve(
              new Response(
                JSON.stringify({ collection_name: "No layers", tracks: [] })
              )
            )
          }
          if (url === "/api/master/adjustments") {
            return Promise.resolve(
              new Response(
                JSON.stringify({
                  available: true,
                  audio_url: "/api/master/audio",
                  defaults: masterSettings,
                  settings: masterSettings,
                  has_backup: false,
                })
              )
            )
          }
          if (url === "/api/finalize/adjustments" && init?.method === "PUT") {
            return Promise.resolve(
              new Response(
                JSON.stringify({
                  available: true,
                  reason: null,
                  layers: ["rain_001.wav"],
                  defaults: finalizeSettings,
                  settings: JSON.parse(String(init.body)).settings,
                  has_backup: false,
                })
              )
            )
          }
          return Promise.resolve(
            new Response(
              JSON.stringify({
                available: false,
                reason: "ambient layer が見つからないため pass-through します",
                layers: [],
                defaults: finalizeSettings,
                settings: unavailableFinalizeSettings,
                has_backup: false,
              })
            )
          )
        })
    )

    render(<App />)
    expect(
      await screen.findByText(
        "ambient layer が見つからないため pass-through します"
      )
    ).toBeInTheDocument()
    expect(screen.getByLabelText("Layer directory")).toBeEnabled()
    expect(
      screen.getByRole("button", { name: "Ambient 設定を保存" })
    ).toBeEnabled()
    expect(screen.getByLabelText("Ambient volume (dB)")).toBeDisabled()
    expect(
      screen.getByRole("button", { name: "Ambient を原本から再出力" })
    ).toBeDisabled()

    fireEvent.change(screen.getByLabelText("Layer directory"), {
      target: { value: "rain_layers" },
    })
    fireEvent.click(screen.getByRole("button", { name: "Ambient 設定を保存" }))

    await screen.findByText("ambient 設定を保存しました")
    expect(screen.getByLabelText("Ambient volume (dB)")).toBeEnabled()
    expect(
      screen.getByRole("button", { name: "Ambient を原本から再出力" })
    ).toBeEnabled()
  })
})
