import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { formatSignedDuration } from "@/lib/dashboard-formatters"
import type {
  WorkflowTimingMetrics,
  WorkflowTimingStep,
} from "@/lib/dashboard-types"
import { workflowStepStatusPresentation } from "@/lib/workflow-step-status"

const WORKFLOW_TIMING_METRICS = [
  { key: "manual_baseline_seconds", label: "手作業基準" },
  { key: "ai_seconds", label: "AI 実行時間" },
  { key: "human_seconds", label: "人間使用時間" },
  { key: "work_seconds", label: "総作業時間" },
  { key: "ai_inclusive_saved_seconds", label: "AI 込み削減時間" },
  { key: "human_freed_seconds", label: "人間が浮いた時間" },
] as const satisfies ReadonlyArray<{
  key: keyof WorkflowTimingMetrics
  label: string
}>

function StepMetricCell({
  step,
  metric,
}: {
  step: WorkflowTimingStep
  metric: (typeof WORKFLOW_TIMING_METRICS)[number]
}) {
  return (
    <TableCell className="flex flex-col gap-1 p-0 whitespace-normal tabular-nums xl:table-cell xl:p-2 xl:text-right">
      <span className="text-xs text-muted-foreground xl:hidden">
        {metric.label}
      </span>
      {formatSignedDuration(step[metric.key])}
    </TableCell>
  )
}

export function WorkflowTimingMetricsList({
  totals,
}: {
  totals: WorkflowTimingMetrics
}) {
  return (
    <dl
      role="group"
      aria-label="collection totals"
      className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3"
    >
      {WORKFLOW_TIMING_METRICS.map((metric) => (
        <div
          key={metric.key}
          className="dashboard-metric-surface rounded-lg p-3"
        >
          <dt className="text-xs text-foreground">{metric.label}</dt>
          <dd className="mt-1 font-semibold tabular-nums">
            {formatSignedDuration(totals[metric.key])}
          </dd>
        </div>
      ))}
    </dl>
  )
}

export function WorkflowStepTable({
  collectionId,
  steps,
}: {
  collectionId: string
  steps: WorkflowTimingStep[]
}) {
  return (
    <div className="min-w-0 overflow-hidden rounded-lg border">
      <Table
        aria-label={`${collectionId} の workflow step`}
        tabIndex={0}
        className="block max-w-full min-w-0 table-fixed overflow-hidden outline-none focus-visible:ring-2 focus-visible:ring-ring xl:table"
      >
        <TableHeader className="hidden xl:table-header-group">
          <TableRow>
            <TableHead>step</TableHead>
            <TableHead>状態</TableHead>
            {WORKFLOW_TIMING_METRICS.map((metric) => (
              <TableHead key={metric.key} className="text-right">
                {metric.label}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody className="grid gap-3 p-3 xl:table-row-group xl:p-0">
          {steps.map((step) => {
            const status = workflowStepStatusPresentation(step.status)
            return (
              <TableRow
                key={step.action}
                className="grid grid-cols-2 gap-x-4 gap-y-3 rounded-lg border p-4 xl:table-row xl:rounded-none xl:border-x-0 xl:p-0"
              >
                <TableCell className="col-span-2 p-0 font-medium whitespace-normal xl:table-cell xl:p-2">
                  {step.action}
                </TableCell>
                <TableCell className="col-span-2 flex flex-col items-start gap-1 p-0 whitespace-normal xl:table-cell xl:p-2">
                  <span className="text-xs text-muted-foreground xl:hidden">
                    状態
                  </span>
                  <Badge variant={status.variant}>{status.label}</Badge>
                </TableCell>
                {WORKFLOW_TIMING_METRICS.map((metric) => (
                  <StepMetricCell
                    key={metric.key}
                    step={step}
                    metric={metric}
                  />
                ))}
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </div>
  )
}
