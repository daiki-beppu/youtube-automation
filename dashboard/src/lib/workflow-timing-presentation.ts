import type {
  WorkflowTiming,
  WorkflowTimingCollection,
  WorkflowTimingError,
} from "./dashboard-types"

type ReadyPresentation = {
  kind: "ready"
  label: "計測済み"
  collections: WorkflowTimingCollection[]
}

type InProgressPresentation = {
  kind: "in_progress"
  label: "進行中"
  collections: WorkflowTimingCollection[]
}

type UnavailablePresentation =
  | {
      kind: "unconfigured"
      label: "未設定"
      reason: string
    }
  | {
      kind: "unmeasured"
      label: "—"
      reason: string
    }
  | {
      kind: "unavailable"
      label: "利用不可"
      reason: string
    }

type ErrorPresentation = {
  kind: "error"
  label: "エラー"
  error: WorkflowTimingError
}

export type WorkflowTimingPresentation =
  | ReadyPresentation
  | InProgressPresentation
  | UnavailablePresentation
  | ErrorPresentation

function unavailablePresentation(reason: string): UnavailablePresentation {
  switch (reason) {
    case "manual_baseline_unconfigured":
      return { kind: "unconfigured", label: "未設定", reason }
    case "attempt_timing_unavailable":
      return { kind: "unmeasured", label: "—", reason }
    default:
      return { kind: "unavailable", label: "利用不可", reason }
  }
}

export function workflowTimingPresentation(
  workflowTiming: WorkflowTiming
): WorkflowTimingPresentation {
  switch (workflowTiming.status) {
    case "ready":
      return {
        kind: "ready",
        label: "計測済み",
        collections: workflowTiming.collections,
      }
    case "unavailable":
      return unavailablePresentation(workflowTiming.reason)
    case "in_progress":
      return {
        kind: "in_progress",
        label: "進行中",
        collections: workflowTiming.collections,
      }
    case "error":
      return {
        kind: "error",
        label: "エラー",
        error: workflowTiming.error,
      }
  }
}
