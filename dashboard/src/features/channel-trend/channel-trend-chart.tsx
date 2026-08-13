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
import type { TrendsResponse } from "@/lib/dashboard-types"
import { SERIES_COLORS } from "./constants"

export function ChannelTrendChart({ data }: { data: TrendsResponse }) {
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
  const rows = dates.map((date) => ({
    date,
    ...Object.fromEntries(
      ready.map((channel) => [
        channel.id,
        channel.points.find((point) => point.date === date)?.views,
      ])
    ),
  }))
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
    <Card role="region" aria-label="日次再生数の推移">
      <CardHeader>
        <CardTitle>日次再生数の推移</CardTitle>
        <CardDescription>
          全チャンネルの日ごとの再生数を比較します。
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
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
              <YAxis tickLine={false} axisLine={false} />
              <ChartTooltip content={<ChartTooltipContent />} />
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
