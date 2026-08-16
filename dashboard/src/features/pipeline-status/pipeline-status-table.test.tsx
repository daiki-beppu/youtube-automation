import "@testing-library/jest-dom/vitest"

import { render, screen, within } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { PipelineStatusTable } from "./pipeline-status-table"

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
})
