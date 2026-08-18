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
})
