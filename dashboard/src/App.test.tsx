import "@testing-library/jest-dom/vitest"

import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"

import App from "./App"
import { ThemeProvider } from "./components/theme-provider"

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((promiseResolve) => {
    resolve = promiseResolve
  })
  return { promise, resolve }
}

const overview = {
  schema_version: 1,
  channels: [
    {
      id: "channel-a",
      name: "Night Drive",
      status: "ready",
      scheduled_count: 3,
      snapshot: "analytics_data.json",
      collected_at: "2026-07-20T12:00:00Z",
      period: { start_date: "2026-06-20", end_date: "2026-07-20" },
      summary: {
        views: 1200,
        watch_time_minutes: 450,
        subscribers_net: 12,
        engagements: 80,
        average_view_percentage: 42.5,
      },
      error: null,
      refresh_error: null,
      video_count: 1,
    },
  ],
}

const detail = {
  ...overview.channels[0],
  workflow_timing: {
    status: "ready",
    collections: [
      {
        collection_id: "active",
        stage: "planning",
        steps: [
          {
            action: "wf-next",
            status: "in_progress",
            manual_baseline_seconds: 7200,
            ai_seconds: 600,
            human_seconds: 1200,
            work_seconds: 1800,
            ai_inclusive_saved_seconds: 5400,
            human_freed_seconds: 6000,
          },
          {
            action: "video-upload",
            status: "success",
            manual_baseline_seconds: 3600,
            ai_seconds: 300,
            human_seconds: 600,
            work_seconds: 900,
            ai_inclusive_saved_seconds: 2700,
            human_freed_seconds: 3000,
          },
          {
            action: "post-publish",
            status: "failed",
            manual_baseline_seconds: 1800,
            ai_seconds: 120,
            human_seconds: 300,
            work_seconds: 420,
            ai_inclusive_saved_seconds: 1380,
            human_freed_seconds: 1500,
          },
          {
            action: "metadata-audit",
            status: "blocked",
            manual_baseline_seconds: 900,
            ai_seconds: 60,
            human_seconds: 180,
            work_seconds: 240,
            ai_inclusive_saved_seconds: 660,
            human_freed_seconds: 720,
          },
          {
            action: "community-post",
            status: "not_run",
            manual_baseline_seconds: 600,
            ai_seconds: 0,
            human_seconds: 0,
            work_seconds: 0,
            ai_inclusive_saved_seconds: 600,
            human_freed_seconds: 600,
          },
        ],
        totals: {
          manual_baseline_seconds: 7200,
          ai_seconds: 600,
          human_seconds: 1200,
          work_seconds: 2222,
          ai_inclusive_saved_seconds: 5400,
          human_freed_seconds: 6000,
        },
      },
      {
        collection_id: "latest",
        stage: "live",
        steps: [],
        totals: {
          manual_baseline_seconds: 3600,
          ai_seconds: 300,
          human_seconds: 900,
          work_seconds: 1333,
          ai_inclusive_saved_seconds: 2400,
          human_freed_seconds: 2700,
        },
      },
    ],
  },
  videos: [
    {
      video_id: "video-1",
      title: "Midnight City",
      views: 1200,
      impressions: 8000,
      ctr_percentage: 5.2,
      likes: 70,
      comments: 8,
      shares: 2,
      subscribers_gained: 12,
      average_view_duration_seconds: 180,
      engagements: 80,
    },
  ],
}

const publicationActivity = {
  days: { "2026-08-08": 3 },
  channels: [],
}

beforeAll(() => {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: () => ({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  })
})

afterEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
})

function renderDashboard() {
  return render(
    <ThemeProvider>
      <App />
    </ThemeProvider>
  )
}

describe("dashboard", () => {
  it("loads the same-origin pipeline API and shows every registered channel", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const path = String(input)
      if (path === "/api/pipeline") {
        return new Response(
          JSON.stringify({
            channels: [
              {
                id: "channel-a",
                name: "Night Drive",
                error: null,
                collections: [
                  {
                    collection_id: "rain",
                    stage: "planning",
                    phase: "prepared",
                    execution_owner: "local",
                    handoff_status: "pending",
                    latest_event: null,
                    error: null,
                  },
                ],
              },
              {
                id: "channel-b",
                name: "Quiet Piano",
                collections: [],
                error: null,
              },
            ],
          })
        )
      }
      if (path === "/api/publications") {
        return new Response(JSON.stringify(publicationActivity))
      }
      if (path === "/api/trends") {
        return new Response(JSON.stringify({ channels: [] }))
      }
      return new Response(JSON.stringify(overview))
    })

    renderDashboard()

    const pipeline = await screen.findByRole("region", {
      name: "パイプライン状況",
    })
    expect(within(pipeline).getByText("Night Drive")).toBeInTheDocument()
    expect(within(pipeline).getByText("Quiet Piano")).toBeInTheDocument()
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/pipeline",
      expect.any(Object)
    )
  })

  it("places pipeline status after channel comparison and selected video detail", async () => {
    // Given
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const path = String(input)
      if (path === "/api/pipeline") {
        return new Response(JSON.stringify({ channels: [] }))
      }
      if (path === "/api/publications") {
        return new Response(JSON.stringify(publicationActivity))
      }
      if (path === "/api/trends") {
        return new Response(JSON.stringify({ channels: [] }))
      }
      return new Response(
        JSON.stringify(path.endsWith("channel-a") ? detail : overview)
      )
    })
    const user = userEvent.setup()
    renderDashboard()

    // When
    await user.click(
      await screen.findByRole("button", {
        name: "Night Drive の動画詳細を見る",
      })
    )

    // Then
    const comparisonHeading = screen.getByRole("heading", {
      name: "チャンネル比較",
    })
    const detailHeading = await screen.findByRole("heading", {
      name: "Night Drive の動画詳細",
    })
    const pipeline = await screen.findByRole("region", {
      name: "パイプライン状況",
    })
    expect(comparisonHeading.compareDocumentPosition(detailHeading)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING
    )
    expect(detailHeading.compareDocumentPosition(pipeline)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING
    )
  })

  it("places a pipeline error after channel comparison and selected video detail", async () => {
    // Given
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const path = String(input)
      if (path === "/api/pipeline") {
        return new Response(null, { status: 503 })
      }
      if (path === "/api/publications") {
        return new Response(JSON.stringify(publicationActivity))
      }
      if (path === "/api/trends") {
        return new Response(JSON.stringify({ channels: [] }))
      }
      return new Response(
        JSON.stringify(path.endsWith("channel-a") ? detail : overview)
      )
    })
    const user = userEvent.setup()
    renderDashboard()

    // When
    await user.click(
      await screen.findByRole("button", {
        name: "Night Drive の動画詳細を見る",
      })
    )

    // Then
    const comparisonHeading = screen.getByRole("heading", {
      name: "チャンネル比較",
    })
    const detailHeading = await screen.findByRole("heading", {
      name: "Night Drive の動画詳細",
    })
    const pipelineError = await screen.findByRole("status")
    expect(
      within(pipelineError).getByText("パイプライン状況を読み込めませんでした")
    ).toBeInTheDocument()
    expect(comparisonHeading.compareDocumentPosition(detailHeading)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING
    )
    expect(detailHeading.compareDocumentPosition(pipelineError)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING
    )
  })

  it("refreshes every dashboard read model and disables the button while running", async () => {
    const refreshResponse = deferred<Response>()
    const updatedOverview = {
      ...overview,
      channels: [
        {
          ...overview.channels[0],
          summary: { ...overview.channels[0].summary, views: 2400 },
        },
      ],
    }
    let refreshRequested = false
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const path = String(input)
      if (path === "/api/refresh" && init?.method === "POST") {
        refreshRequested = true
        return refreshResponse.promise
      }
      if (path === "/api/publications") {
        return Promise.resolve(
          new Response(JSON.stringify(publicationActivity), { status: 200 })
        )
      }
      return Promise.resolve(
        new Response(
          JSON.stringify(
            path === "/api/channels" && refreshRequested
              ? updatedOverview
              : overview
          ),
          { status: 200 }
        )
      )
    })
    const user = userEvent.setup()
    renderDashboard()
    const refreshButton = await screen.findByRole("button", {
      name: "データを更新",
    })

    await user.click(refreshButton)
    expect(screen.getByRole("button", { name: "更新中" })).toBeDisabled()
    expect(screen.getByRole("button", { name: "7 日" })).toBeDisabled()
    refreshResponse.resolve(
      new Response(JSON.stringify(updatedOverview), { status: 200 })
    )

    expect(await screen.findByText("2,400")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "データを更新" })).toBeEnabled()
  })

  it("defaults to 30 days and refreshes with the selected period", async () => {
    const requests: Array<{ path: string; method?: string; body?: string }> = []
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const path = String(input)
      requests.push({ path, method: init?.method, body: init?.body as string })
      if (path === "/api/publications") {
        return new Response(JSON.stringify(publicationActivity), {
          status: 200,
        })
      }
      return new Response(JSON.stringify(overview), { status: 200 })
    })
    const user = userEvent.setup()
    renderDashboard()

    expect(
      await screen.findByRole("button", { name: "30 日", pressed: true })
    ).toBeInTheDocument()
    expect(await screen.findByText("直近 30 日")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "7 日" }))

    await waitFor(() =>
      expect(
        requests.some(
          (request) =>
            request.path === "/api/refresh" &&
            request.method === "POST" &&
            request.body === JSON.stringify({ days: 7 })
        )
      ).toBe(true)
    )
    expect(screen.getByText("直近 7 日")).toBeInTheDocument()
  })

  it("presents overview, data context, metric definitions, and comparison in decision order", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(overview), { status: 200 })
    )

    renderDashboard()

    const overviewHeading = await screen.findByRole("heading", {
      name: "概況",
    })
    const comparisonHeading = screen.getByRole("heading", {
      name: "チャンネル比較",
    })
    expect(overviewHeading.compareDocumentPosition(comparisonHeading)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING
    )

    const dataContext = screen.getByRole("region", {
      name: "表示データについて",
    })
    expect(within(dataContext).getByText("対象期間")).toBeInTheDocument()
    expect(
      within(dataContext).getByText("2026/06/20〜2026/07/20")
    ).toBeInTheDocument()
    expect(within(dataContext).getByText("最終更新")).toBeInTheDocument()
    expect(within(dataContext).getByText(/\d{1,2}:\d{2}/)).toBeInTheDocument()

    const metricGuide = screen.getByRole("region", {
      name: "指標の見方",
    })
    expect(within(metricGuide).getByText("公開予約")).toBeInTheDocument()
    expect(
      within(metricGuide).getByText(
        "YouTube で公開日時が設定された未公開動画の本数"
      )
    ).toBeInTheDocument()
    expect(within(metricGuide).getByText("期間再生数")).toBeInTheDocument()
    expect(
      within(metricGuide).getByText("対象期間中に動画が再生された回数")
    ).toBeInTheDocument()
  })

  it("shows channel metrics before a channel is selected", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(overview), { status: 200 })
    )

    renderDashboard()

    const comparisonTable = await screen.findByRole("table", {
      name: "チャンネル横断ストック一覧",
    })
    const channelRow = within(comparisonTable).getByRole("row", {
      name: /Night Drive/,
    })
    expect(within(channelRow).getByText("1,200")).toBeInTheDocument()
    expect(within(channelRow).getByText("7時間30分")).toBeInTheDocument()
    expect(within(channelRow).getByText("+12")).toBeInTheDocument()
    expect(
      within(channelRow).getByRole("button", {
        name: "Night Drive の動画詳細を見る",
      })
    ).toBeInTheDocument()
    expect(
      screen.queryByRole("heading", { name: "チャンネル概要" })
    ).not.toBeInTheDocument()
    expect(
      screen.queryByText("チャンネルを選択してください")
    ).not.toBeInTheDocument()
  })

  it("loads overview and lets a keyboard user inspect video metrics", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input)
      return new Response(
        JSON.stringify(url.endsWith("channel-a") ? detail : overview),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }
      )
    })
    const user = userEvent.setup()

    renderDashboard()

    const channelButton = await screen.findByRole("button", {
      name: /Night Drive/,
    })
    channelButton.focus()
    await user.keyboard("{Enter}")

    expect(
      await screen.findByRole("cell", { name: "Midnight City" })
    ).toBeInTheDocument()
    expect(
      screen.getByRole("heading", { name: "動画パフォーマンス" })
    ).toBeInTheDocument()
    const performanceCard = screen
      .getByRole("heading", { name: "動画パフォーマンス" })
      .closest("[data-slot='card']") as HTMLElement | null
    if (performanceCard === null) throw new Error("performance card is missing")
    expect(
      within(performanceCard).getByRole("cell", { name: "1,200" })
    ).toBeInTheDocument()
    const subscriberMetric = screen
      .getAllByText("純増登録者")
      .at(-1)
      ?.closest("[data-tone]")
    expect(subscriberMetric).toHaveAttribute("data-tone", "positive")
    expect(
      within(subscriberMetric as HTMLElement).getByText("+12")
    ).toBeInTheDocument()
    expect(screen.getAllByText("7時間30分")).toHaveLength(2)
    const comparisonRow = screen.getByRole("row", { name: /Night Drive/ })
    expect(within(comparisonRow).getByText("3本")).toBeInTheDocument()
    expect(screen.queryByText("準備完了")).not.toBeInTheDocument()
  })

  it("shows the six server-provided timing totals for active and latest collections", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const payload = String(input).endsWith("channel-a") ? detail : overview
      return new Response(JSON.stringify(payload), { status: 200 })
    })
    const user = userEvent.setup()

    renderDashboard()

    await user.click(
      await screen.findByRole("button", {
        name: "Night Drive の動画詳細を見る",
      })
    )

    const active = await screen.findByRole("region", {
      name: "進行中コレクション active",
    })
    const activeTotals = within(active).getByRole("group", {
      name: "collection totals",
    })
    expect(within(activeTotals).getByText("手作業基準")).toBeInTheDocument()
    expect(within(activeTotals).getByText("+02:00:00")).toBeInTheDocument()
    expect(within(activeTotals).getByText("AI 実行時間")).toBeInTheDocument()
    expect(within(activeTotals).getByText("+00:10:00")).toBeInTheDocument()
    expect(within(activeTotals).getByText("人間使用時間")).toBeInTheDocument()
    expect(within(activeTotals).getByText("+00:20:00")).toBeInTheDocument()
    expect(within(activeTotals).getByText("総作業時間")).toBeInTheDocument()
    expect(within(activeTotals).getByText("+00:37:02")).toBeInTheDocument()
    expect(
      within(activeTotals).getByText("AI 込み削減時間")
    ).toBeInTheDocument()
    expect(within(activeTotals).getByText("+01:30:00")).toBeInTheDocument()
    expect(
      within(activeTotals).getByText("人間が浮いた時間")
    ).toBeInTheDocument()
    expect(within(activeTotals).getByText("+01:40:00")).toBeInTheDocument()

    const latest = screen.getByRole("region", {
      name: "最新公開コレクション latest",
    })
    const latestTotals = within(latest).getByRole("group", {
      name: "collection totals",
    })
    expect(within(latestTotals).getByText("+01:00:00")).toBeInTheDocument()
    expect(within(latestTotals).getByText("+00:05:00")).toBeInTheDocument()
    expect(within(latestTotals).getByText("+00:15:00")).toBeInTheDocument()
    expect(within(latestTotals).getByText("+00:22:13")).toBeInTheDocument()
    expect(within(latestTotals).getByText("+00:40:00")).toBeInTheDocument()
    expect(within(latestTotals).getByText("+00:45:00")).toBeInTheDocument()
  })

  it("explains both saved-time formulas and associates them with card and table metrics", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const payload = String(input).endsWith("channel-a") ? detail : overview
      return new Response(JSON.stringify(payload), { status: 200 })
    })
    const user = userEvent.setup()

    renderDashboard()
    await user.click(
      await screen.findByRole("button", {
        name: "Night Drive の動画詳細を見る",
      })
    )

    const aiFormula = "AI込み削減時間 = 手作業基準 - 総作業時間"
    const humanFormula = "人間が浮いた時間 = 手作業基準 - 人間使用時間"
    const formulaGuide = screen.getByRole("note", {
      name: "削減時間の算出式",
    })
    expect(within(formulaGuide).getByText(aiFormula)).toBeInTheDocument()
    expect(within(formulaGuide).getByText(humanFormula)).toBeInTheDocument()

    const active = screen.getByRole("region", {
      name: "進行中コレクション active",
    })
    const activeTotals = within(active).getByRole("group", {
      name: "collection totals",
    })
    expect(
      within(activeTotals).getByText("AI 込み削減時間").closest("dt")
    ).toHaveAccessibleDescription(aiFormula)
    expect(
      within(activeTotals).getByText("人間が浮いた時間").closest("dt")
    ).toHaveAccessibleDescription(humanFormula)

    const stepTable = within(active).getByRole("table", {
      name: "active の workflow step",
    })
    expect(
      within(stepTable).getByRole("columnheader", {
        name: "AI 込み削減時間",
      })
    ).toHaveAccessibleDescription(aiFormula)
    expect(
      within(stepTable).getByRole("columnheader", {
        name: "人間が浮いた時間",
      })
    ).toHaveAccessibleDescription(humanFormula)
  })

  it.each([
    ["manual_baseline_unconfigured", "未設定"],
    ["attempt_timing_unavailable", "—"],
  ] as const)(
    "shows unavailable reason %s as %s in the workflow timing section",
    async (reason, label) => {
      const unavailableDetail = {
        ...detail,
        workflow_timing: {
          status: "unavailable",
          reason,
          collections: [],
        },
      }
      vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
        const payload = String(input).endsWith("channel-a")
          ? unavailableDetail
          : overview
        return new Response(JSON.stringify(payload), { status: 200 })
      })
      const user = userEvent.setup()

      renderDashboard()
      await user.click(
        await screen.findByRole("button", {
          name: "Night Drive の動画詳細を見る",
        })
      )

      const timingSection = screen
        .getByRole("heading", { name: "コレクション時間サマリー" })
        .closest("section") as HTMLElement
      expect(within(timingSection).getByText(label)).toBeInTheDocument()
      expect(
        within(timingSection).queryByRole("region", {
          name: /コレクション/,
        })
      ).not.toBeInTheDocument()
    }
  )

  it("shows measured zero seconds as a duration instead of an unavailable state", async () => {
    const zeroMetrics = {
      manual_baseline_seconds: 0,
      ai_seconds: 0,
      human_seconds: 0,
      work_seconds: 0,
      ai_inclusive_saved_seconds: 0,
      human_freed_seconds: 0,
    }
    const zeroDetail = {
      ...detail,
      workflow_timing: {
        status: "ready",
        collections: [
          {
            collection_id: "zero",
            stage: "live",
            steps: [],
            totals: zeroMetrics,
          },
        ],
      },
    }
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const payload = String(input).endsWith("channel-a")
        ? zeroDetail
        : overview
      return new Response(JSON.stringify(payload), { status: 200 })
    })
    const user = userEvent.setup()

    renderDashboard()
    await user.click(
      await screen.findByRole("button", {
        name: "Night Drive の動画詳細を見る",
      })
    )

    const totals = within(
      screen.getByRole("region", { name: "最新公開コレクション zero" })
    ).getByRole("group", { name: "collection totals" })
    expect(within(totals).getAllByText("00:00:00")).toHaveLength(6)
    expect(screen.queryByText("未設定")).not.toBeInTheDocument()
  })

  it("shows an in-progress timing state without hiding measured collections", async () => {
    const inProgressDetail = {
      ...detail,
      workflow_timing: {
        status: "in_progress",
        collections: detail.workflow_timing.collections,
      },
    }
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const payload = String(input).endsWith("channel-a")
        ? inProgressDetail
        : overview
      return new Response(JSON.stringify(payload), { status: 200 })
    })
    const user = userEvent.setup()

    renderDashboard()
    await user.click(
      await screen.findByRole("button", {
        name: "Night Drive の動画詳細を見る",
      })
    )

    const timingSection = screen
      .getByRole("heading", { name: "コレクション時間サマリー" })
      .closest("section") as HTMLElement
    expect(
      within(timingSection).getByRole("status", {
        name: "workflow timing 進行中",
      })
    ).toHaveTextContent("進行中")
    expect(
      within(timingSection).getByRole("region", {
        name: "進行中コレクション active",
      })
    ).toBeInTheDocument()
  })

  it("shows a local timing error while preserving Analytics summary and videos", async () => {
    const errorDetail = {
      ...detail,
      workflow_timing: {
        status: "error",
        collections: [],
        error: {
          code: "workflow_timing_invalid",
          message: "workflow timing を読み込めません",
        },
      },
    }
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const payload = String(input).endsWith("channel-a")
        ? errorDetail
        : overview
      return new Response(JSON.stringify(payload), { status: 200 })
    })
    const user = userEvent.setup()

    renderDashboard()
    await user.click(
      await screen.findByRole("button", {
        name: "Night Drive の動画詳細を見る",
      })
    )

    const timingSection = screen
      .getByRole("heading", { name: "コレクション時間サマリー" })
      .closest("section") as HTMLElement
    expect(within(timingSection).getByRole("alert")).toHaveTextContent(
      "workflow timing を読み込めません"
    )
    const detailRegion = screen.getByRole("heading", {
      name: "Night Drive の動画詳細",
    }).parentElement?.parentElement
    if (detailRegion === undefined || detailRegion === null) {
      throw new Error("channel detail region is missing")
    }
    expect(
      within(detailRegion).getByText("再生数", { selector: "dt" })
    ).toBeInTheDocument()
    expect(
      screen.getByRole("cell", { name: "Midnight City" })
    ).toBeInTheDocument()
  })

  it("shows each workflow step action, status, and six timing metrics", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const payload = String(input).endsWith("channel-a") ? detail : overview
      return new Response(JSON.stringify(payload), { status: 200 })
    })
    const user = userEvent.setup()

    renderDashboard()

    await user.click(
      await screen.findByRole("button", {
        name: "Night Drive の動画詳細を見る",
      })
    )

    const stepTable = await screen.findByRole("table", {
      name: "active の workflow step",
    })
    const inProgress = within(stepTable).getByRole("row", { name: /wf-next/ })
    expect(within(inProgress).getByText("進行中")).toBeInTheDocument()
    expect(within(inProgress).getByText("+02:00:00")).toBeInTheDocument()
    expect(within(inProgress).getByText("+00:10:00")).toBeInTheDocument()
    expect(within(inProgress).getByText("+00:20:00")).toBeInTheDocument()
    expect(within(inProgress).getByText("+00:30:00")).toBeInTheDocument()
    expect(within(inProgress).getByText("+01:30:00")).toBeInTheDocument()
    expect(within(inProgress).getByText("+01:40:00")).toBeInTheDocument()
    expect(
      within(
        within(stepTable).getByRole("row", { name: /video-upload/ })
      ).getByText("成功")
    ).toBeInTheDocument()
    expect(
      within(
        within(stepTable).getByRole("row", { name: /post-publish/ })
      ).getByText("失敗")
    ).toBeInTheDocument()
    expect(
      within(
        within(stepTable).getByRole("row", { name: /metadata-audit/ })
      ).getByText("ブロック中")
    ).toBeInTheDocument()
    expect(
      within(
        within(stepTable).getByRole("row", { name: /community-post/ })
      ).getByText("未実行")
    ).toBeInTheDocument()
  })

  it("shows an empty state when no channels are registered", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ schema_version: 1, channels: [] }), {
        status: 200,
      })
    )

    renderDashboard()

    expect(
      await screen.findByText("登録済みチャンネルがありません")
    ).toBeInTheDocument()
  })

  it("shows publication loading without delaying the overview", async () => {
    const publicationResponse = deferred<Response>()
    vi.spyOn(globalThis, "fetch").mockImplementation((input) =>
      String(input) === "/api/publications"
        ? publicationResponse.promise
        : Promise.resolve(
            new Response(JSON.stringify(overview), { status: 200 })
          )
    )

    renderDashboard()

    expect(
      await screen.findByRole("region", { name: "概況" })
    ).toBeInTheDocument()
    expect(
      screen.getByRole("status", { name: "公開活動を読み込み中" })
    ).toBeInTheDocument()

    publicationResponse.resolve(
      new Response(JSON.stringify(publicationActivity), { status: 200 })
    )
  })

  it("shows a publication empty state instead of an empty heatmap", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const payload =
        String(input) === "/api/publications"
          ? { days: {}, channels: [] }
          : overview
      return new Response(JSON.stringify(payload), { status: 200 })
    })

    renderDashboard()

    expect(
      await screen.findByText("公開活動データがありません")
    ).toBeInTheDocument()
    expect(
      screen.queryByRole("grid", { name: "日別公開本数" })
    ).not.toBeInTheDocument()
  })

  it("treats zero-valued publication days as empty", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const payload =
        String(input) === "/api/publications"
          ? { days: { "2026-08-08": 0 }, channels: [] }
          : overview
      return new Response(JSON.stringify(payload), { status: 200 })
    })

    renderDashboard()

    expect(
      await screen.findByText("公開活動データがありません")
    ).toBeInTheDocument()
    expect(
      screen.queryByRole("grid", { name: "日別公開本数" })
    ).not.toBeInTheDocument()
  })

  it.each([
    [
      "request failure",
      () => new Response("failed", { status: 503 }),
      "HTTP 503",
    ],
    [
      "schema failure",
      () => new Response(JSON.stringify({ days: null, channels: [] })),
      "応答形式が不正です",
    ],
    [
      "null channel",
      () =>
        new Response(
          JSON.stringify({ days: { "2026-08-08": 1 }, channels: [null] })
        ),
      "応答形式が不正です",
    ],
    [
      "negative day count",
      () =>
        new Response(
          JSON.stringify({ days: { "2026-08-08": -1 }, channels: [] })
        ),
      "応答形式が不正です",
    ],
    [
      "non-finite day count",
      () => new Response('{"days":{"2026-08-08":1e999},"channels":[]}'),
      "応答形式が不正です",
    ],
  ])(
    "shows a publication fatal alert for %s without hiding the overview",
    async (_caseName, publicationResponse, expectedMessage) => {
      vi.spyOn(globalThis, "fetch").mockImplementation(async (input) =>
        String(input) === "/api/publications"
          ? publicationResponse()
          : new Response(JSON.stringify(overview), { status: 200 })
      )

      renderDashboard()

      expect(
        await screen.findByRole("region", { name: "概況" })
      ).toBeInTheDocument()
      const alert = await screen.findByRole("alert", {
        name: "公開活動を読み込めませんでした",
      })
      expect(alert).toHaveTextContent(expectedMessage)
      expect(
        screen.queryByRole("region", { name: "過去365日の公開活動" })
      ).not.toBeInTheDocument()
    }
  )

  it("counts channels with unavailable data as needing attention", async () => {
    const unavailableOverview = {
      ...overview,
      channels: [
        {
          ...overview.channels[0],
          status: "missing_snapshot",
          scheduled_count: null,
          collected_at: null,
          period: { start_date: null, end_date: null },
          summary: null,
        },
      ],
    }
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(unavailableOverview), { status: 200 })
    )

    renderDashboard()

    const overviewRegion = await screen.findByRole("region", { name: "概況" })
    const attentionMetric = within(overviewRegion)
      .getByText("要確認")
      .closest("div")
    if (attentionMetric === null) throw new Error("要確認 metric is missing")
    expect(within(attentionMetric).getByText("1")).toBeInTheDocument()
    expect(screen.getByText("データ未収集")).toBeInTheDocument()
  })

  it("marks a channel whose startup refresh failed in the overview", async () => {
    const refreshError = {
      code: "refresh_failed",
      message: "Authentication failed",
    }
    const failedOverview = {
      ...overview,
      channels: [{ ...overview.channels[0], refresh_error: refreshError }],
    }
    const failedDetail = { ...detail, refresh_error: refreshError }
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const payload = String(input).endsWith("channel-a")
        ? failedDetail
        : failedOverview
      return new Response(JSON.stringify(payload), { status: 200 })
    })

    renderDashboard()

    expect(
      await screen.findAllByLabelText("更新失敗: Authentication failed")
    ).toHaveLength(1)
    const stockTable = screen.getByRole("table", {
      name: "チャンネル横断ストック一覧",
    })
    const stockRow = within(stockTable).getByRole("row", {
      name: /Night Drive/,
    })
    expect(within(stockRow).getByText("3本")).toBeInTheDocument()
    expect(within(stockRow).queryByText("未取得")).not.toBeInTheDocument()
  })

  it("lets a user preview and keep the dashboard color palette", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(overview), { status: 200 })
    )
    const user = userEvent.setup()

    renderDashboard()

    await screen.findByRole("heading", { name: "概況" })
    expect(
      screen.queryByRole("group", { name: "カラーパレット" })
    ).not.toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "設定を開く" }))

    const settings = screen.getByRole("dialog", { name: "設定" })
    const paletteGroup = within(settings).getByRole("group", {
      name: "カラーパレット",
    })
    const blue = within(paletteGroup).getByRole("button", { name: "Blue" })
    const green = within(paletteGroup).getByRole("button", { name: "Green" })
    expect(
      within(paletteGroup)
        .getAllByRole("button")
        .map((button) => button.getAttribute("aria-label"))
    ).toEqual([
      "Blue",
      "Light Blue",
      "Cyan",
      "Green",
      "Lime",
      "Yellow",
      "Orange",
      "Red",
      "Magenta",
      "Purple",
    ])
    expect(blue).toHaveAttribute("aria-pressed", "true")
    expect(
      screen.getByRole("img", {
        name: "Blue の5段階配色。1〜3系列では 100、500、900 を使用",
      })
    ).toBeInTheDocument()

    await user.click(green)

    expect(green).toHaveAttribute("aria-pressed", "true")
    expect(
      screen.getByRole("img", {
        name: "Green の5段階配色。1〜3系列では 100、600、900 を使用",
      })
    ).toBeInTheDocument()
    expect(document.documentElement).toHaveAttribute("data-palette", "green")
    expect(localStorage.getItem("palette")).toBe("green")
  })

  it("shows an alert when the overview request fails", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) =>
      String(input) === "/api/publications"
        ? new Response(JSON.stringify({ days: {}, channels: [] }), {
            status: 200,
          })
        : new Response("failed", { status: 500 })
    )

    renderDashboard()

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        "読み込めませんでした"
      )
    )
  })

  it("leaves detail loading after a selected channel request fails", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const path = String(input)
      if (path === "/api/publications") {
        return new Response(JSON.stringify({ days: {}, channels: [] }), {
          status: 200,
        })
      }
      if (path === "/api/channels") {
        return new Response(JSON.stringify(overview), { status: 200 })
      }
      return new Response("detail failed", { status: 500 })
    })
    const user = userEvent.setup()
    const { container } = renderDashboard()

    await user.click(
      await screen.findByRole("button", {
        name: "Night Drive の動画詳細を見る",
      })
    )

    expect(await screen.findByRole("alert")).toHaveTextContent("HTTP 500")
    await waitFor(() =>
      expect(container.querySelector("[data-slot='skeleton']")).toBeNull()
    )
  })

  it("keeps the current selection when an older detail response arrives last", async () => {
    const secondChannel = {
      ...overview.channels[0],
      id: "channel-b",
      name: "Morning Focus",
    }
    const twoChannels = {
      ...overview,
      channels: [overview.channels[0], secondChannel],
    }
    const firstResponse = deferred<Response>()
    const secondResponse = deferred<Response>()
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input)
      if (url === "/api/channels") {
        return Promise.resolve(
          new Response(JSON.stringify(twoChannels), { status: 200 })
        )
      }
      return url.endsWith("channel-a")
        ? firstResponse.promise
        : secondResponse.promise
    })
    const user = userEvent.setup()
    renderDashboard()

    await user.click(
      await screen.findByRole("button", {
        name: "Night Drive の動画詳細を見る",
      })
    )
    await user.click(
      screen.getByRole("button", {
        name: "Morning Focus の動画詳細を見る",
      })
    )
    secondResponse.resolve(
      new Response(
        JSON.stringify({
          ...detail,
          id: "channel-b",
          name: "Morning Focus",
        }),
        { status: 200 }
      )
    )
    expect(
      await screen.findByRole("heading", {
        name: "Morning Focus の動画詳細",
      })
    ).toBeInTheDocument()

    firstResponse.resolve(
      new Response(JSON.stringify(detail), {
        status: 200,
      })
    )
    await waitFor(() =>
      expect(
        screen.queryByRole("heading", {
          name: "Night Drive の動画詳細",
        })
      ).not.toBeInTheDocument()
    )
  })

  it("does not refetch the overview when channel details are selected", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input) => {
        const payload = String(input) === "/api/channels" ? overview : detail
        return new Response(JSON.stringify(payload), { status: 200 })
      })
    const user = userEvent.setup()
    renderDashboard()

    const detailButton = await screen.findByRole("button", {
      name: "Night Drive の動画詳細を見る",
    })
    await user.click(detailButton)
    await screen.findByRole("heading", {
      name: "Night Drive の動画詳細",
    })
    await user.click(detailButton)
    await screen.findByRole("heading", {
      name: "Night Drive の動画詳細",
    })

    expect(
      fetchMock.mock.calls.filter(
        ([input]) => String(input) === "/api/channels"
      )
    ).toHaveLength(1)
  })
})
