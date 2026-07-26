const integerFormatter = new Intl.NumberFormat("ja-JP")
const dateTimeFormatter = new Intl.DateTimeFormat("ja-JP", {
  dateStyle: "medium",
  timeStyle: "short",
})

export function formatInteger(value: number): string {
  return integerFormatter.format(value)
}

export function formatSignedInteger(value: number): string {
  return value > 0 ? `+${formatInteger(value)}` : formatInteger(value)
}

export function formatCollectedAt(value: string | null): string {
  if (!value) return "未収集"
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : dateTimeFormatter.format(date)
}

function formatCalendarDate(value: string | null): string {
  return value ? value.replaceAll("-", "/") : "未収集"
}

export function formatDateRange(
  startDate: string | null,
  endDate: string | null
): string {
  if (!startDate && !endDate) return "未収集"
  return `${formatCalendarDate(startDate)}〜${formatCalendarDate(endDate)}`
}
