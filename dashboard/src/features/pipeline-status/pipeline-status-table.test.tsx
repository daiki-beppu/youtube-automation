import "@testing-library/jest-dom/vitest"

import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import type {
  PipelineCollection,
  PipelineResponse,
} from "@/lib/dashboard-types"

import { PipelineStatusTable } from "./pipeline-status-table"

const fixturePhases: Array<NonNullable<PipelineCollection["phase"]>> = [
  "planning",
  "prepared",
  "mastered",
  "publishing",
  "complete",
  "cloud_owned",
]

const phaseFilterData: PipelineResponse = {
  channels: [
    {
      id: "channel-a",
      name: "Night Drive",
      error: null,
      collections: fixturePhases.map((phase) => ({
        collection_id: `collection-${phase}`,
        stage: "planning",
        phase,
        execution_owner: "local",
        handoff_status: "not_started",
        latest_event: null,
        error: null,
      })),
    },
    {
      id: "channel-invalid",
      name: "Invalid State",
      error: null,
      collections: [
        {
          collection_id: "collection-invalid",
          stage: null,
          phase: null,
          execution_owner: null,
          handoff_status: "invalid",
          latest_event: null,
          error: { code: "invalid_state", message: "state 不正" },
        },
      ],
    },
    {
      id: "channel-error",
      name: "Unavailable Channel",
      error: { code: "read_failed", message: "channel error" },
      collections: [],
    },
  ],
}

function phaseLimitData(
  phases: Array<NonNullable<PipelineCollection["phase"]>>
): PipelineResponse {
  return {
    channels: [
      {
        id: "channel-limit",
        name: "Limit Channel",
        error: null,
        collections: phases.map((phase, index) => ({
          collection_id: `item-${phase}-${index + 1}`,
          stage: "planning",
          phase,
          execution_owner: "local",
          handoff_status: "not_started",
          latest_event: null,
          error: null,
        })),
      },
    ],
  }
}

describe("pipeline status table", () => {
  it("shows every channel with phase, owner, handoff, and latest event", () => {
    render(
      <PipelineStatusTable
        data={{
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
                  latest_event: {
                    kind: "workflow_state_updated",
                    occurred_at: "2026-08-16T09:00:00Z",
                  },
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
        }}
      />
    )

    const table = screen.getByRole("table", { name: "パイプライン状況" })
    expect(within(table).getByText("Night Drive")).toBeInTheDocument()
    expect(within(table).getByText("Quiet Piano")).toBeInTheDocument()
    expect(within(table).getByText("prepared")).toBeInTheDocument()
    expect(within(table).getByText("ローカル")).toBeInTheDocument()
    expect(within(table).getByText("引き渡し待ち")).toBeInTheDocument()
    expect(within(table).getByText(/state 更新/)).toBeInTheDocument()
    expect(within(table).getByText("state なし")).toBeInTheDocument()
  })

  it("shows ongoing pipeline information by default", () => {
    // Given
    const data = phaseFilterData

    // When
    render(<PipelineStatusTable data={data} />)

    // Then
    expect(screen.getByRole("button", { name: "進行中" })).toHaveAttribute(
      "aria-pressed",
      "true"
    )
    const table = screen.getByRole("table", { name: "パイプライン状況" })
    for (const visibleCollection of [
      "collection-planning",
      "collection-prepared",
      "collection-mastered",
      "collection-publishing",
      "collection-cloud_owned",
      "collection-invalid",
    ]) {
      expect(within(table).getByText(visibleCollection)).toBeInTheDocument()
    }
    expect(within(table).getByText("channel error")).toBeInTheDocument()
    expect(
      within(table).queryByText("collection-complete")
    ).not.toBeInTheDocument()
  })

  it.each(["planning", "prepared", "mastered", "publishing", "complete"])(
    "shows only collections whose phase exactly matches %s",
    async (phase) => {
      // Given
      const user = userEvent.setup()
      render(<PipelineStatusTable data={phaseFilterData} />)

      // When
      await user.click(screen.getByRole("button", { name: phase }))

      // Then
      const table = screen.getByRole("table", { name: "パイプライン状況" })
      expect(within(table).getByText(`collection-${phase}`)).toBeInTheDocument()
      for (const hiddenCollection of [
        "collection-planning",
        "collection-prepared",
        "collection-mastered",
        "collection-publishing",
        "collection-complete",
        "collection-cloud_owned",
        "collection-invalid",
      ]) {
        if (hiddenCollection !== `collection-${phase}`) {
          expect(
            within(table).queryByText(hiddenCollection)
          ).not.toBeInTheDocument()
        }
      }
      expect(within(table).queryByText("channel error")).not.toBeInTheDocument()
    }
  )

  it("shows every API row again when all phases is selected", async () => {
    // Given
    const user = userEvent.setup()
    render(<PipelineStatusTable data={phaseFilterData} />)
    await user.click(screen.getByRole("button", { name: "prepared" }))

    // When
    await user.click(screen.getByRole("button", { name: "すべて" }))

    // Then
    const table = screen.getByRole("table", { name: "パイプライン状況" })
    for (const visibleCollection of [
      "collection-planning",
      "collection-prepared",
      "collection-mastered",
      "collection-publishing",
      "collection-complete",
      "collection-cloud_owned",
      "collection-invalid",
    ]) {
      expect(within(table).getByText(visibleCollection)).toBeInTheDocument()
    }
    expect(within(table).getByText("channel error")).toBeInTheDocument()
  })

  it("shows no more button when the selected phase has no collections", async () => {
    // Given
    const user = userEvent.setup()
    render(<PipelineStatusTable data={phaseLimitData(["planning"])} />)

    // When
    await user.click(screen.getByRole("button", { name: "complete" }))

    // Then
    const table = screen.getByRole("table", { name: "パイプライン状況" })
    expect(within(table).getAllByRole("row")).toHaveLength(1)
    expect(
      screen.queryByRole("button", { name: /もっと見る/ })
    ).not.toBeInTheDocument()
  })

  it("shows all ten collections without a more button", async () => {
    // Given
    const user = userEvent.setup()
    const data = phaseLimitData(Array.from({ length: 10 }, () => "prepared"))
    render(<PipelineStatusTable data={data} />)

    // When
    await user.click(screen.getByRole("button", { name: "prepared" }))

    // Then
    const table = screen.getByRole("table", { name: "パイプライン状況" })
    expect(within(table).getAllByRole("row")).toHaveLength(11)
    expect(
      screen.queryByRole("button", { name: /もっと見る/ })
    ).not.toBeInTheDocument()
  })

  it("expands all collections when an eleventh matching row remains", async () => {
    // Given
    const user = userEvent.setup()
    const data = phaseLimitData(Array.from({ length: 11 }, () => "prepared"))
    render(<PipelineStatusTable data={data} />)
    await user.click(screen.getByRole("button", { name: "prepared" }))

    // When
    await user.click(
      screen.getByRole("button", { name: "もっと見る（残り1件）" })
    )

    // Then
    const table = screen.getByRole("table", { name: "パイプライン状況" })
    expect(within(table).getAllByRole("row")).toHaveLength(12)
    expect(within(table).getByText("item-prepared-11")).toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: /もっと見る/ })
    ).not.toBeInTheDocument()
  })

  it("limits each mixed phase independently after switching filters", async () => {
    // Given
    const user = userEvent.setup()
    const data = phaseLimitData([
      ...Array.from({ length: 11 }, () => "prepared" as const),
      ...Array.from({ length: 12 }, () => "planning" as const),
    ])
    render(<PipelineStatusTable data={data} />)
    await user.click(screen.getByRole("button", { name: "prepared" }))
    await user.click(
      screen.getByRole("button", { name: "もっと見る（残り1件）" })
    )

    // When
    await user.click(screen.getByRole("button", { name: "planning" }))

    // Then
    const table = screen.getByRole("table", { name: "パイプライン状況" })
    expect(within(table).getAllByRole("row")).toHaveLength(11)
    expect(
      screen.getByRole("button", { name: "もっと見る（残り2件）" })
    ).toBeInTheDocument()
    expect(within(table).queryByText(/item-prepared/)).not.toBeInTheDocument()
  })
})
