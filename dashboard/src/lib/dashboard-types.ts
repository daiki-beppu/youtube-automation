export type Summary = {
  views: number
  watch_time_minutes: number
  subscribers_net: number
  engagements: number
  average_view_percentage: number
}

export type ChannelOverview = {
  id: string
  name: string
  status: string
  scheduled_count: number | null
  snapshot: string | null
  collected_at: string | null
  period: { start_date: string | null; end_date: string | null }
  summary: Summary | null
  error: { code: string; message: string } | null
  refresh_error: { code: string; message: string } | null
  video_count: number
}

export type WorkflowTimingMetrics = {
  manual_baseline_seconds: number
  ai_seconds: number
  human_seconds: number
  work_seconds: number
  ai_inclusive_saved_seconds: number
  human_freed_seconds: number
}

export type WorkflowTimingStep = WorkflowTimingMetrics & {
  action: string
  status: "in_progress" | "success" | "failed" | "blocked" | "not_run"
}

export type WorkflowTimingCollection = {
  collection_id: string
  stage: "planning" | "live"
  steps: WorkflowTimingStep[]
  totals: WorkflowTimingMetrics
}

export type WorkflowTiming = {
  collections: WorkflowTimingCollection[]
}
