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

export function formatWatchTime(value: number): string {
  const totalMinutes = Math.round(value)
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  const hoursText = hours > 0 ? `${formatInteger(hours)}時間` : ""
  const minutesText = minutes > 0 || hours === 0 ? `${minutes}分` : ""
  return `${hoursText}${minutesText}`
}

export function formatSignedDuration(value: number): string {
  if (!Number.isFinite(value)) {
    throw new RangeError("duration must be finite")
  }

  const totalSeconds = Math.round(Math.abs(value))
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  const sign = totalSeconds === 0 ? "" : value > 0 ? "+" : "-"

  return `${sign}${hours.toString().padStart(2, "0")}:${minutes
    .toString()
    .padStart(2, "0")}:${seconds.toString().padStart(2, "0")}`
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
