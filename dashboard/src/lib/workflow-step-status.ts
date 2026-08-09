import type { WorkflowTimingStep } from "./dashboard-types"

export type WorkflowStepStatusVariant =
  | "default"
  | "secondary"
  | "destructive"
  | "warning"
  | "outline"

export type WorkflowStepStatusPresentation = {
  label: string
  variant: WorkflowStepStatusVariant
}

const WORKFLOW_STEP_STATUS_PRESENTATIONS: Record<
  WorkflowTimingStep["status"],
  WorkflowStepStatusPresentation
> = {
  in_progress: { label: "進行中", variant: "default" },
  success: { label: "成功", variant: "secondary" },
  failed: { label: "失敗", variant: "destructive" },
  blocked: { label: "ブロック中", variant: "warning" },
  not_run: { label: "未実行", variant: "outline" },
}

export function workflowStepStatusPresentation(
  status: WorkflowTimingStep["status"]
): WorkflowStepStatusPresentation {
  return WORKFLOW_STEP_STATUS_PRESENTATIONS[status]
}
