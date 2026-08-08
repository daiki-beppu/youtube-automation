import { useState } from "react"

export type PublicationActivityError = {
  code: string
  message: string
  attempted_at: string
}

export type PublicationActivityChannel = {
  id: string
  name: string
  status: string
  fetched_at: string | null
  timezone: string | null
  days: Record<string, number>
  error: PublicationActivityError | null
}

export type PublicationActivityResponse = {
  days: Record<string, number>
  channels: PublicationActivityChannel[]
}

const DAY_COUNT = 365
const WEEKDAYS = ["日", "月", "火", "水", "木", "金", "土"]
const INTENSITY_COLORS = [
  "var(--muted)",
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
]

function dateKey(date: Date): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, "0")
  const day = String(date.getDate()).padStart(2, "0")
  return `${year}-${month}-${day}`
}

function intensity(count: number): number {
  if (count <= 0) return 0
  if (count >= 4) return 4
  if (count >= 3) return 3
  if (count >= 2) return 2
  return 1
}

function activityDays(days: Record<string, number>) {
  const now = new Date()
  const end = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const start = new Date(end)
  start.setDate(start.getDate() - (DAY_COUNT - 1))

  return Array.from({ length: DAY_COUNT }, (_, index) => {
    const date = new Date(start)
    date.setDate(start.getDate() + index)
    const key = dateKey(date)
    return {
      key,
      count: days[key] ?? 0,
      weekday: date.getDay(),
      week: Math.floor((index + start.getDay()) / 7),
      month: date.getMonth() + 1,
      showMonth: index === 0 || date.getDate() === 1,
    }
  })
}

export type PublicationHeatmapProps = {
  channels: PublicationActivityResponse["channels"]
  days: PublicationActivityResponse["days"]
}

export function PublicationHeatmap({
  channels,
  days,
}: PublicationHeatmapProps) {
  const [focusedDate, setFocusedDate] = useState<string | null>(null)
  const [hoveredDate, setHoveredDate] = useState<string | null>(null)
  const activity = activityDays(days)
  const weekCount = activity.at(-1)!.week + 1
  const weekColumns = `repeat(${weekCount}, 11px)`
  const activeDate = hoveredDate ?? focusedDate
  const activeDay = activeDate
    ? activity.find((day) => day.key === activeDate)
    : undefined
  const activeChannels = activeDate
    ? channels
        .map((channel) => ({
          count: channel.days[activeDate] ?? 0,
          id: channel.id,
          name: channel.name,
        }))
        .filter((channel) => channel.count > 0)
    : []
  const detailsId = activeDate
    ? `publication-activity-details-${activeDate}`
    : undefined

  return (
    <section aria-label="過去365日の公開活動">
      <div
        data-testid="publication-heatmap-scroll"
        style={{
          maxWidth: "100%",
          overflowX: "auto",
        }}
      >
        <div
          style={{
            display: "grid",
            columnGap: 8,
            gridTemplateColumns: "max-content max-content",
            width: "max-content",
          }}
        >
          <span aria-hidden="true" />
          <ol
            aria-label="月"
            style={{
              display: "grid",
              gap: 3,
              gridTemplateColumns: weekColumns,
              listStyle: "none",
              margin: 0,
              padding: 0,
            }}
          >
            {activity
              .filter((day) => day.showMonth)
              .map((day) => (
                <li
                  data-week={day.week}
                  key={day.key}
                  style={{ gridColumn: day.week + 1, gridRow: 1 }}
                >
                  {day.month}月
                </li>
              ))}
          </ol>
          <ol
            aria-label="曜日"
            style={{
              display: "grid",
              gap: 3,
              gridTemplateRows: "repeat(7, 11px)",
              listStyle: "none",
              margin: 0,
              padding: 0,
            }}
          >
            {WEEKDAYS.map((weekday) => (
              <li key={weekday}>{weekday}</li>
            ))}
          </ol>
          <div
            aria-label="日別公開本数"
            role="grid"
            style={{
              display: "grid",
              gap: 3,
              gridTemplateColumns: weekColumns,
              gridTemplateRows: "repeat(7, 11px)",
            }}
          >
            {WEEKDAYS.map((_, weekday) => (
              <div
                key={weekday}
                role="row"
                style={{
                  display: "grid",
                  gap: 3,
                  gridColumn: "1 / -1",
                  gridRow: weekday + 1,
                  gridTemplateColumns: weekColumns,
                }}
              >
                {activity
                  .filter((day) => day.weekday === weekday)
                  .map((day) => {
                    const level = intensity(day.count)
                    return (
                      <span
                        aria-describedby={
                          activeDate === day.key ? detailsId : undefined
                        }
                        aria-label={`${day.key}: ${day.count}本`}
                        data-count={day.count}
                        data-date={day.key}
                        data-intensity={level}
                        data-week={day.week}
                        data-weekday={day.weekday}
                        key={day.key}
                        onBlur={() => setFocusedDate(null)}
                        onFocus={() => setFocusedDate(day.key)}
                        onMouseEnter={() => setHoveredDate(day.key)}
                        onMouseLeave={() => setHoveredDate(null)}
                        role="gridcell"
                        style={{
                          backgroundColor: INTENSITY_COLORS[level],
                          borderRadius: 2,
                          gridColumn: day.week + 1,
                          height: 11,
                          width: 11,
                        }}
                        tabIndex={0}
                      />
                    )
                  })}
              </div>
            ))}
          </div>
        </div>
      </div>
      {activeDate && activeDay && detailsId ? (
        <div
          className="mt-3 max-w-sm rounded-md border bg-popover p-3 text-sm text-popover-foreground shadow-md"
          id={detailsId}
          role="tooltip"
        >
          <p className="font-medium">{activeDate}</p>
          <p>合計 {activeDay.count}本</p>
          {activeChannels.length > 0 ? (
            <ul aria-label="チャンネル別内訳" className="mt-2 grid gap-1">
              {activeChannels.map((channel) => (
                <li key={channel.id}>
                  {channel.name} {channel.count}本
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-muted-foreground">公開チャンネルなし</p>
          )}
        </div>
      ) : null}
      <ol
        aria-label="公開本数の凡例"
        style={{
          display: "flex",
          gap: 4,
          listStyle: "none",
          margin: 0,
          padding: 0,
        }}
      >
        {INTENSITY_COLORS.map((color, level) => (
          <li aria-label={level === 4 ? "4本以上" : `${level}本`} key={color}>
            <span
              aria-hidden="true"
              style={{
                backgroundColor: color,
                borderRadius: 2,
                display: "block",
                height: 11,
                width: 11,
              }}
            />
          </li>
        ))}
      </ol>
    </section>
  )
}
