import { describe, expect, it } from "vitest"

import { workflowStepStatusPresentation } from "./workflow-step-status"

describe("workflow step status presentation", () => {
  it.each([
    ["in_progress", "進行中", "default"],
    ["success", "成功", "secondary"],
    ["failed", "失敗", "destructive"],
    ["blocked", "ブロック中", "warning"],
    ["not_run", "未実行", "outline"],
  ] as const)(
    "maps %s to its Japanese label and badge variant",
    (status, label, variant) => {
      expect(workflowStepStatusPresentation(status)).toEqual({ label, variant })
    }
  )
})
