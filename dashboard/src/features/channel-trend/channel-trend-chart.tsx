import { useState } from "react"
import { CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import type { TrendPoint, TrendsResponse } from "@/lib/dashboard-types"
import { SERIES_COLORS } from "./constants"

type TrendMetric = Exclude<keyof TrendPoint, "date">

type TrendMetricDefinition = {
  key: TrendMetric
  label: string
  title: string
  description: string
  format: (value: number) => string
}

const integerFormatter = new Intl.NumberFormat("ja-JP", {
  maximumFractionDigits: 0,
})
const hourFormatter = new Intl.NumberFormat("ja-JP", {
  maximumFractionDigits: 1,
})

const trendMetrics: readonly TrendMetricDefinition[] = [
  {
    key: "views",
    label: "再生数",
    title: "日次再生数の推移",
    description: "全チャンネルの日ごとの再生数を比較します。",
    format: (value) => integerFormatter.format(value),
  },
  {
    key: "watch_time_minutes",
    label: "再生時間",
    title: "日次再生時間の推移",
    description: "全チャンネルの日ごとの再生時間を比較します。",
    format: (value) => `${hourFormatter.format(value / 60)}時間`,
  },
  {
    key: "subscribers_net",
    label: "チャンネル登録者",
    title: "日次チャンネル登録者の推移",
    description: "全チャンネルの日ごとの登録者純増減を比較します。",
    format: (value) =>
      `${value > 0 ? "+" : ""}${integerFormatter.format(value)}人`,
  },
  {
    key: "impressions",
    label: "インプレッション数",
    title: "日次インプレッション数の推移",
    description: "全チャンネルの日ごとのインプレッション数を比較します。",
    format: (value) => `${integerFormatter.format(value)}回`,
  },
]

export function ChannelTrendChart({ data }: { data: TrendsResponse }) {
  const [selectedMetric, setSelectedMetric] = useState<TrendMetric>("views")
  const metric = trendMetrics.find(
    (candidate) => candidate.key === selectedMetric
  )
  if (!metric) throw new Error(`Unknown trend metric: ${selectedMetric}`)
  const channels = (Array.isArray(data.channels) ? data.channels : []).map(
    (channel) => ({
      ...channel,
      points: Array.isArray(channel.points) ? channel.points : [],
    })
  )
  const ready = channels.filter((channel) => channel.status === "ready")
  const unavailable = channels.filter((channel) => channel.status !== "ready")
  const dates = [
    ...new Set(
      ready.flatMap((channel) => channel.points.map((point) => point.date))
    ),
  ].sort()
  const rows = dates.map((date) => {
    const values = ready.map((channel) => {
      const point = channel.points.find((candidate) => candidate.date === date)
      return [channel.id, point ? point[selectedMetric] : null]
    })
    return { date, ...Object.fromEntries(values) }
  })
  const config = Object.fromEntries(
    ready.map((channel, index) => [
      channel.id,
      {
        label: channel.name,
        color: SERIES_COLORS[index % SERIES_COLORS.length],
      },
    ])
  ) satisfies ChartConfig

  return (
    <Card role="region" aria-label={metric.title}>
      <CardHeader>
        <CardTitle>{metric.title}</CardTitle>
        <CardDescription>{metric.description}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        <ToggleGroup
          aria-label="表示指標"
          variant="outline"
          spacing={0}
          value={[selectedMetric]}
          onValueChange={(values) => {
            const selected = trendMetrics.find(
              (candidate) => candidate.key === values.at(-1)
            )
            if (selected) setSelectedMetric(selected.key)
          }}
        >
          {trendMetrics.map((candidate) => (
            <ToggleGroupItem key={candidate.key} value={candidate.key}>
              {candidate.label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        {unavailable.map((channel) => (
          <Alert key={channel.id}>
            <AlertTitle>{channel.name} の推移を表示できません</AlertTitle>
            <AlertDescription>
              {channel.error?.message ?? "Analytics snapshot がありません"}
            </AlertDescription>
          </Alert>
        ))}
        {ready.length > 0 ? (
          <ChartContainer config={config} className="min-h-72 w-full">
            <LineChart data={rows} accessibilityLayer>
              <CartesianGrid vertical={false} />
              <XAxis dataKey="date" tickLine={false} axisLine={false} />
              <YAxis
                tickLine={false}
                axisLine={false}
                tickFormatter={metric.format}
              />
              <ChartTooltip
                content={
                  <ChartTooltipContent
                    formatter={(value, name, item) => (
                      <div className="flex flex-1 items-center justify-between gap-2 leading-none">
                        <div className="flex items-center gap-1.5">
                          <span
                            className="size-2.5 rounded-[2px]"
                            style={{ backgroundColor: item.color }}
                          />
                          <span className="text-muted-foreground">
                            {String(name)}
                          </span>
                        </div>
                        <span className="font-mono font-medium tabular-nums">
                          {typeof value === "number"
                            ? metric.format(value)
                            : String(value)}
                        </span>
                      </div>
                    )}
                  />
                }
              />
              <ChartLegend content={<ChartLegendContent />} />
              {ready.map((channel, index) => (
                <Line
                  key={channel.id}
                  dataKey={channel.id}
                  name={channel.name}
                  stroke={SERIES_COLORS[index % SERIES_COLORS.length]}
                  strokeWidth={2}
                  dot={false}
                  connectNulls={false}
                />
              ))}
            </LineChart>
          </ChartContainer>
        ) : null}
      </CardContent>
    </Card>
  )
}
