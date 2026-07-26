export type DashboardStatusSeverity = "ready" | "warning" | "error"

type DashboardStatusPresentation = {
  label: string
  severity: DashboardStatusSeverity
}

const STATUS_PRESENTATIONS: Record<string, DashboardStatusPresentation> = {
  ready: { label: "正常", severity: "ready" },
  missing_snapshot: { label: "データ未収集", severity: "warning" },
  invalid_snapshot: { label: "データエラー", severity: "error" },
  invalid_channel: { label: "設定エラー", severity: "error" },
}

export function dashboardStatusPresentation(
  status: string
): DashboardStatusPresentation {
  return STATUS_PRESENTATIONS[status] ?? { label: status, severity: "error" }
}
