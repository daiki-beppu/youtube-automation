import type { PublicationActivityResponse } from "@/features/publication-activity/publication-heatmap"

export const DASHBOARD_SCHEMA_VERSION = 2

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

export type WorkflowTimingError = {
  code: string
  message: string
}

export type WorkflowTiming =
  | {
      status: "ready"
      collections: WorkflowTimingCollection[]
    }
  | {
      status: "unavailable"
      reason: string
      collections: []
    }
  | {
      status: "in_progress"
      collections: WorkflowTimingCollection[]
    }
  | {
      status: "error"
      collections: []
      error: WorkflowTimingError
    }

export type Video = {
  video_id: string
  title: string
  views: number
  impressions: number
  ctr_percentage: number
  likes: number
  comments: number
  shares: number
  subscribers_gained: number
  average_view_duration_seconds: number
  engagements: number
}

export type ChannelDetail = Omit<ChannelOverview, "video_count"> & {
  videos: Video[]
  workflow_timing: WorkflowTiming
}
export type OverviewResponse = {
  schema_version: number
  channels: ChannelOverview[]
}
export type TrendsResponse = {
  channels: Array<{
    id: string
    name: string
    status: string
    points: Array<{ date: string; views: number }>
    error: { code: string; message: string } | null
  }>
}
export type PipelineCollection = {
  collection_id: string
  stage: "planning" | "live" | null
  phase:
    | "planning"
    | "prepared"
    | "cloud_owned"
    | "mastered"
    | "publishing"
    | "complete"
    | null
  execution_owner: "local" | "cloud" | null
  handoff_status:
    | "not_started"
    | "pending"
    | "completed"
    | "not_recorded"
    | "not_applicable"
    | "invalid"
  latest_event: {
    kind: "workflow_state_updated"
    occurred_at: string
  } | null
  error: { code: string; message: string } | null
}
export type PipelineResponse = {
  channels: Array<{
    id: string
    name: string
    collections: PipelineCollection[]
    error: { code: string; message: string } | null
  }>
}
export type PublicationActivityState =
  | { status: "loading" }
  | { status: "ready"; data: PublicationActivityResponse }
  | { status: "empty" }
  | { status: "error"; message: string }
