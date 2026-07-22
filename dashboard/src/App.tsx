import { useEffect, useMemo, useState } from "react"
import {
  AlertCircleIcon,
  BarChart3Icon,
  DatabaseIcon,
  MoonIcon,
  SunIcon,
} from "lucide-react"
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { useTheme } from "@/components/theme-provider"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

type Summary = {
  views: number
  watch_time_minutes: number
  subscribers_net: number
  engagements: number
  average_view_percentage: number
}

type DashboardError = { code: string; message: string }

type ChannelOverview = {
  id: string
  name: string
  status: string
  scheduled_count: number | null
  snapshot: string | null
  collected_at: string | null
  period: { start_date: string | null; end_date: string | null }
  summary: Summary | null
  error: DashboardError | null
  refresh_error: DashboardError | null
  video_count: number
}

type Video = {
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

type ChannelDetail = Omit<ChannelOverview, "video_count"> & { videos: Video[] }
type OverviewResponse = { schema_version: number; channels: ChannelOverview[] }

const integer = new Intl.NumberFormat("ja-JP")
const dateTime = new Intl.DateTimeFormat("ja-JP", {
  dateStyle: "medium",
  timeStyle: "short",
})
const chartConfig = {
  views: { label: "再生数", color: "var(--chart-1)" },
} satisfies ChartConfig

async function requestJson<T>(path: string): Promise<T> {
  const response = await fetch(path, {
    headers: { Accept: "application/json" },
  })
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`)
  }
  return response.json() as Promise<T>
}

function formatCollectedAt(value: string | null): string {
  if (!value) return "未収集"
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : dateTime.format(date)
}

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    ready: "準備完了",
    missing_snapshot: "データ未収集",
    invalid_snapshot: "データエラー",
    invalid_channel: "設定エラー",
  }
  return labels[status] ?? status
}

function channelBadgeLabel(channel: ChannelOverview): string {
  if (channel.status !== "ready") return statusLabel(channel.status)
  if (channel.scheduled_count === null) return "公開予約 未取得"
  return `公開予約 ${integer.format(channel.scheduled_count)}本`
}

function signedInteger(value: number): string {
  return value > 0 ? `+${integer.format(value)}` : integer.format(value)
}

function LoadingState() {
  return (
    <div aria-label="読み込み中" className="grid gap-4 lg:grid-cols-3">
      {[0, 1, 2].map((item) => (
        <Card key={item}>
          <CardHeader>
            <Skeleton className="h-5 w-36" />
            <Skeleton className="h-4 w-52" />
          </CardHeader>
          <CardContent>
            <Skeleton className="h-20 w-full" />
          </CardContent>
        </Card>
      ))}
    </div>
  )
}

function SummaryMetrics({ summary }: { summary: Summary }) {
  return (
    <dl className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <div className="rounded-lg bg-muted p-4">
        <dt className="text-xs text-muted-foreground">再生数</dt>
        <dd className="text-2xl font-semibold tabular-nums">
          {integer.format(summary.views)}
        </dd>
      </div>
      <div className="rounded-lg bg-muted p-4">
        <dt className="text-xs text-muted-foreground">総再生時間</dt>
        <dd className="text-2xl font-semibold tabular-nums">
          {integer.format(summary.watch_time_minutes)}
          <span className="ml-1 text-sm font-normal text-muted-foreground">
            分
          </span>
        </dd>
      </div>
      <div className="rounded-lg bg-muted p-4">
        <dt className="text-xs text-muted-foreground">純増登録者</dt>
        <dd className="text-2xl font-semibold tabular-nums">
          {integer.format(summary.subscribers_net)}
        </dd>
      </div>
      <div className="rounded-lg bg-muted p-4">
        <dt className="text-xs text-muted-foreground">エンゲージメント</dt>
        <dd className="text-2xl font-semibold tabular-nums">
          {integer.format(summary.engagements)}
        </dd>
      </div>
    </dl>
  )
}

function ChannelOverviewGrid({
  channels,
  selectedId,
  onSelect,
}: {
  channels: ChannelOverview[]
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  return (
    <section aria-labelledby="channel-overview-title" className="grid gap-4">
      <div>
        <h2 id="channel-overview-title" className="text-2xl font-semibold">
          チャンネル概要
        </h2>
        <p className="text-sm text-muted-foreground">
          選択しなくても、全チャンネルの主要指標を比較できます。
        </p>
      </div>
      <div className="grid items-stretch gap-4 md:grid-cols-2 xl:grid-cols-3">
        {channels.map((channel) => (
          <Card
            key={channel.id}
            role="article"
            aria-label={`${channel.name} の概要`}
            className="min-w-0"
          >
            <CardHeader className="gap-3">
              <div className="min-w-0">
                <CardTitle className="break-words text-lg">
                  {channel.name}
                </CardTitle>
                <CardDescription>
                  収集: {formatCollectedAt(channel.collected_at)}
                </CardDescription>
              </div>
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                {channel.refresh_error ? (
                  <Badge
                    variant="destructive"
                    aria-label={`更新失敗: ${channel.refresh_error.message}`}
                  >
                    更新失敗
                  </Badge>
                ) : null}
                <Badge
                  variant={
                    channel.status === "ready" ? "default" : "destructive"
                  }
                >
                  {channelBadgeLabel(channel)}
                </Badge>
              </div>
            </CardHeader>
            <CardContent>
              <dl className="grid grid-cols-2 gap-3">
                <div className="rounded-lg bg-muted p-3">
                  <dt className="text-xs text-muted-foreground">期間再生数</dt>
                  <dd className="text-lg font-semibold tabular-nums">
                    {channel.summary
                      ? integer.format(channel.summary.views)
                      : "—"}
                  </dd>
                </div>
                <div className="rounded-lg bg-muted p-3">
                  <dt className="text-xs text-muted-foreground">純増登録者</dt>
                  <dd className="text-lg font-semibold tabular-nums">
                    {channel.summary
                      ? signedInteger(channel.summary.subscribers_net)
                      : "—"}
                  </dd>
                </div>
                <div className="rounded-lg bg-muted p-3">
                  <dt className="text-xs text-muted-foreground">総再生時間</dt>
                  <dd className="text-lg font-semibold tabular-nums">
                    {channel.summary
                      ? `${integer.format(channel.summary.watch_time_minutes)}分`
                      : "—"}
                  </dd>
                </div>
                <div className="rounded-lg bg-muted p-3">
                  <dt className="text-xs text-muted-foreground">分析動画</dt>
                  <dd className="text-lg font-semibold tabular-nums">
                    {integer.format(channel.video_count)}本
                  </dd>
                </div>
              </dl>
            </CardContent>
            <CardFooter className="mt-auto">
              <Button
                variant={selectedId === channel.id ? "secondary" : "outline"}
                size="sm"
                className="w-full"
                onClick={() => onSelect(channel.id)}
                aria-pressed={selectedId === channel.id}
                aria-label={`${channel.name} の動画詳細を見る`}
              >
                動画詳細を見る
              </Button>
            </CardFooter>
          </Card>
        ))}
      </div>
    </section>
  )
}

function Detail({ detail }: { detail: ChannelDetail }) {
  const chartData = useMemo(
    () =>
      detail.videos
        .slice(0, 8)
        .map((video) => ({ name: video.title, views: video.views })),
    [detail]
  )
  return (
    <div className="grid gap-6">
      {detail.refresh_error ? (
        <Alert>
          <AlertCircleIcon />
          <AlertTitle>最新データへ更新できませんでした</AlertTitle>
          <AlertDescription>
            前回の収集データを表示しています。{detail.refresh_error.message}
          </AlertDescription>
        </Alert>
      ) : null}
      {detail.error ? (
        <Alert variant="destructive">
          <AlertCircleIcon />
          <AlertTitle>{statusLabel(detail.status)}</AlertTitle>
          <AlertDescription>{detail.error.message}</AlertDescription>
        </Alert>
      ) : null}
      {detail.summary ? <SummaryMetrics summary={detail.summary} /> : null}
      {detail.videos.length === 0 ? (
        <Empty className="border">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <BarChart3Icon />
            </EmptyMedia>
            <EmptyTitle>動画データがありません</EmptyTitle>
            <EmptyDescription>
              Analytics を収集すると動画別の指標が表示されます。
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <>
          <Card>
            <CardHeader>
              <CardTitle>再生数トップ動画</CardTitle>
              <CardDescription>
                最新 snapshot の上位 {chartData.length} 本
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ChartContainer config={chartConfig} className="min-h-64 w-full">
                <BarChart
                  accessibilityLayer
                  data={chartData}
                  layout="vertical"
                  margin={{ left: 8 }}
                >
                  <CartesianGrid horizontal={false} />
                  <YAxis
                    dataKey="name"
                    type="category"
                    tickLine={false}
                    axisLine={false}
                    width={100}
                    tickFormatter={(value: string) =>
                      value.length > 14 ? `${value.slice(0, 14)}…` : value
                    }
                  />
                  <XAxis type="number" hide />
                  <ChartTooltip
                    cursor={false}
                    content={<ChartTooltipContent />}
                  />
                  <Bar dataKey="views" fill="var(--color-views)" radius={4} />
                </BarChart>
              </ChartContainer>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>
                <h2>動画パフォーマンス</h2>
              </CardTitle>
              <CardDescription>
                再生・リーチ・反応を動画単位で比較できます。
              </CardDescription>
            </CardHeader>
            <CardContent className="px-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>動画</TableHead>
                    <TableHead className="text-right">再生数</TableHead>
                    <TableHead className="text-right">表示回数</TableHead>
                    <TableHead className="text-right">CTR</TableHead>
                    <TableHead className="text-right">反応</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {detail.videos.map((video) => (
                    <TableRow key={video.video_id}>
                      <TableCell className="max-w-72 font-medium whitespace-normal">
                        {video.title}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {integer.format(video.views)}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {integer.format(video.impressions)}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {video.ctr_percentage.toFixed(1)}%
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {integer.format(video.engagements)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}

export function App() {
  const { theme, setTheme } = useTheme()
  const [channels, setChannels] = useState<ChannelOverview[] | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<ChannelDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  useEffect(() => {
    requestJson<OverviewResponse>("/api/channels")
      .then((response) => setChannels(response.channels))
      .catch((reason: unknown) =>
        setError(reason instanceof Error ? reason.message : String(reason))
      )
  }, [])

  async function selectChannel(channelId: string) {
    setSelectedId(channelId)
    setDetail(null)
    setError(null)
    setDetailLoading(true)
    try {
      setDetail(
        await requestJson<ChannelDetail>(
          `/api/channels/${encodeURIComponent(channelId)}`
        )
      )
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setDetailLoading(false)
    }
  }

  return (
    <main className="min-h-svh bg-background">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-8 p-4 sm:p-8">
        <header className="flex items-start justify-between gap-4">
          <div className="flex flex-col gap-2">
            <Badge variant="secondary" className="gap-1">
              <DatabaseIcon data-icon="inline-start" />
              起動時更新
            </Badge>
            <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
              YouTube Analytics Dashboard
            </h1>
            <p className="max-w-2xl text-muted-foreground">
              起動時に全チャンネルを更新し、チャンネルと動画のパフォーマンスを確認します。
            </p>
          </div>
          <Button
            variant="outline"
            size="icon"
            aria-label={
              theme === "dark"
                ? "ライトモードに切り替え"
                : "ダークモードに切り替え"
            }
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          >
            {theme === "dark" ? <SunIcon /> : <MoonIcon />}
          </Button>
        </header>

        {error ? (
          <Alert variant="destructive">
            <AlertCircleIcon />
            <AlertTitle>読み込めませんでした</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}
        {channels === null && !error ? <LoadingState /> : null}
        {channels?.length === 0 ? (
          <Empty className="border">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <DatabaseIcon />
              </EmptyMedia>
              <EmptyTitle>登録済みチャンネルがありません</EmptyTitle>
              <EmptyDescription>
                ~/.config/tayk/channels.json にチャンネルの絶対 path
                を追加してください。
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : null}
        {channels && channels.length > 0 ? (
          <div className="grid gap-8">
            <ChannelOverviewGrid
              channels={channels}
              selectedId={selectedId}
              onSelect={selectChannel}
            />
            <section aria-live="polite" className="min-w-0">
              {detailLoading ? (
                <Card>
                  <CardHeader>
                    <Skeleton className="h-6 w-48" />
                    <Skeleton className="h-4 w-64" />
                  </CardHeader>
                  <CardContent>
                    <Skeleton className="h-64 w-full" />
                  </CardContent>
                </Card>
              ) : null}
              {detail ? (
                <div className="grid gap-4">
                  <div>
                    <h2 className="text-2xl font-semibold">
                      {detail.name} の動画詳細
                    </h2>
                    <p className="text-sm text-muted-foreground">
                      最新 snapshot の動画別パフォーマンスです。
                    </p>
                  </div>
                  <Detail detail={detail} />
                </div>
              ) : null}
            </section>
          </div>
        ) : null}
      </div>
    </main>
  )
}

export default App
