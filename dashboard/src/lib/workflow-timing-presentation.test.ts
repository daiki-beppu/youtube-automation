import { describe, expect, it } from "vitest"

import type { WorkflowTiming } from "./dashboard-types"
import { workflowTimingPresentation } from "./workflow-timing-presentation"

describe("workflow timing presentation", () => {
  it.each([
    ["manual_baseline_unconfigured", "unconfigured", "未設定"],
    ["attempt_timing_unavailable", "unmeasured", "—"],
    ["history_schema_v1", "unavailable", "利用不可"],
  ] as const)(
    "maps unavailable reason %s without collapsing distinct states",
    (reason, kind, label) => {
      const workflowTiming: WorkflowTiming = {
        status: "unavailable",
        reason,
        collections: [],
      }

      const presentation = workflowTimingPresentation(workflowTiming)

      expect(presentation).toEqual({ kind, label, reason })
    }
  )

  it("keeps ready zero metrics as numbers for duration formatting", () => {
    const workflowTiming: WorkflowTiming = {
      status: "ready",
      collections: [
        {
          collection_id: "active",
          stage: "planning",
          steps: [],
          totals: {
            manual_baseline_seconds: 0,
            ai_seconds: 0,
            human_seconds: 0,
            work_seconds: 0,
            ai_inclusive_saved_seconds: 0,
            human_freed_seconds: 0,
          },
        },
      ],
    }

    const presentation = workflowTimingPresentation(workflowTiming)

    expect(presentation.kind).toBe("ready")
    if (presentation.kind !== "ready") {
      throw new Error("ready presentation expected")
    }
    expect(presentation.label).toBe("計測済み")
    expect(presentation.collections[0]?.totals.work_seconds).toBe(0)
    expect(typeof presentation.collections[0]?.totals.work_seconds).toBe(
      "number"
    )
  })

  it("keeps in-progress distinct while preserving measured collections", () => {
    const collections = [
      {
        collection_id: "active",
        stage: "planning" as const,
        steps: [],
        totals: {
          manual_baseline_seconds: 60,
          ai_seconds: 10,
          human_seconds: 20,
          work_seconds: 30,
          ai_inclusive_saved_seconds: 30,
          human_freed_seconds: 40,
        },
      },
    ]

    const workflowTiming: WorkflowTiming = {
      status: "in_progress",
      collections,
    }

    const presentation = workflowTimingPresentation(workflowTiming)

    expect(presentation).toEqual({
      kind: "in_progress",
      label: "進行中",
      collections,
    })
  })

  it("keeps the structured error for a local error presentation", () => {
    const error = {
      code: "workflow_timing_invalid",
      message: "workflow timing の status が不正です",
    }

    const workflowTiming: WorkflowTiming = {
      status: "error",
      collections: [],
      error,
    }

    const presentation = workflowTimingPresentation(workflowTiming)

    expect(presentation).toEqual({ kind: "error", label: "エラー", error })
  })
})
