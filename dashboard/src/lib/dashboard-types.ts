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
