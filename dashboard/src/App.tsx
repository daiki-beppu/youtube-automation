import { useEffect, useMemo, useRef, useState } from "react"
import {
  CalendarRangeIcon,
  AlertCircleIcon,
  BarChart3Icon,
  DatabaseIcon,
  InfoIcon,
  MoonIcon,
  RefreshCwIcon,
  SettingsIcon,
  SunIcon,
} from "lucide-react"
import { Bar, BarChart, CartesianGrid, LabelList, XAxis, YAxis } from "recharts"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { PaletteSwitcher } from "@/components/palette-switcher"
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
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet"
import { ChannelStockTable } from "@/features/channel-stock/channel-stock-table"
import { ChannelTrendChart } from "@/features/channel-trend/channel-trend-chart"
import {
  PublicationHeatmap,
  type PublicationActivityChannel,
  type PublicationActivityError,
  type PublicationActivityResponse,
} from "@/features/publication-activity/publication-heatmap"
import { PipelineStatusTable } from "@/features/pipeline-status/pipeline-status-table"
import {
  WorkflowTimingFormulaGuide,
  WorkflowTimingMetricsList,
  WorkflowStepTable,
} from "@/features/workflow-timing/workflow-step-table"
import type {
  ChannelDetail,
  ChannelOverview,
  OverviewResponse,
  PublicationActivityState,
  PipelineResponse,
  Summary,
  TrendsResponse,
  WorkflowTiming,
  WorkflowTimingCollection,
} from "@/lib/dashboard-types"
import {
  formatCollectedAt,
  formatDateRange,
  formatInteger,
  formatSignedInteger,
} from "@/lib/dashboard-formatters"
import { dashboardStatusPresentation } from "@/lib/dashboard-status"
import {
  workflowTimingPresentation,
  type WorkflowTimingPresentation,
} from "@/lib/workflow-timing-presentation"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

const chartConfig = {
  views: { label: "再生数", color: "var(--chart-3)" },
} satisfies ChartConfig

async function requestJson<T>(
  path: string,
  method = "GET",
  body?: object
): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: {
      Accept: "application/json",
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`)
  }
  return response.clone().json() as Promise<T>
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function isPublicationDays(value: unknown): value is Record<string, number> {
  return (
    isRecord(value) &&
    Object.values(value).every(
      (count) =>
        typeof count === "number" && Number.isFinite(count) && count >= 0
    )
  )
}

function isTrendsResponse(value: unknown): value is TrendsResponse {
  return (
    isRecord(value) &&
    Array.isArray(value.channels) &&
    value.channels.every(
      (channel) => isRecord(channel) && Array.isArray(channel.points)
    )
  )
}

function isPipelineEvent(value: unknown): boolean {
  return (
    value === null ||
    (isRecord(value) &&
      value.kind === "workflow_state_updated" &&
      typeof value.occurred_at === "string" &&
      !Number.isNaN(Date.parse(value.occurred_at)))
  )
}

function isPipelineError(value: unknown): boolean {
  return (
    value === null ||
    (isRecord(value) &&
      typeof value.code === "string" &&
      typeof value.message === "string")
  )
}

function isPipelineResponse(value: unknown): value is PipelineResponse {
  return (
    isRecord(value) &&
    Array.isArray(value.channels) &&
    value.channels.every(
      (channel) =>
        isRecord(channel) &&
        typeof channel.id === "string" &&
        typeof channel.name === "string" &&
        isPipelineError(channel.error) &&
        Array.isArray(channel.collections) &&
        channel.collections.every(
          (collection) =>
            isRecord(collection) &&
            typeof collection.collection_id === "string" &&
            (collection.stage === "planning" ||
              collection.stage === "live" ||
              collection.stage === null) &&
            (collection.phase === "planning" ||
              collection.phase === "prepared" ||
              collection.phase === "cloud_owned" ||
              collection.phase === "mastered" ||
              collection.phase === "publishing" ||
              collection.phase === "complete" ||
              collection.phase === null) &&
            (collection.execution_owner === "local" ||
              collection.execution_owner === "cloud" ||
              collection.execution_owner === null) &&
            (collection.handoff_status === "not_started" ||
              collection.handoff_status === "pending" ||
              collection.handoff_status === "completed" ||
              collection.handoff_status === "not_recorded" ||
              collection.handoff_status === "not_applicable" ||
              collection.handoff_status === "invalid") &&
            isPipelineEvent(collection.latest_event) &&
            isPipelineError(collection.error)
        )
    )
  )
}

function isPublicationError(
  value: unknown
): value is PublicationActivityError | null {
  if (value === null) return true
  return (
    isRecord(value) &&
    typeof value.code === "string" &&
    typeof value.message === "string" &&
    typeof value.attempted_at === "string"
  )
}

function isPublicationChannel(
  value: unknown
): value is PublicationActivityChannel {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.name === "string" &&
    typeof value.status === "string" &&
    (value.fetched_at === null || typeof value.fetched_at === "string") &&
    (value.timezone === null || typeof value.timezone === "string") &&
    isPublicationDays(value.days) &&
    isPublicationError(value.error)
  )
}

function isPublicationActivityResponse(
  value: unknown
): value is PublicationActivityResponse {
  return (
    isRecord(value) &&
    isPublicationDays(value.days) &&
    Array.isArray(value.channels) &&
    value.channels.every(isPublicationChannel)
  )
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

function PublicationActivityPanel({
  state,
}: {
  state: PublicationActivityState
}) {
  if (state.status === "loading") {
    return (
      <Card role="status" aria-label="公開活動を読み込み中">
        <CardHeader>
          <Skeleton className="h-5 w-40" />
          <Skeleton className="h-4 w-56" />
        </CardHeader>
        <CardContent>
          <Skeleton className="h-24 w-full" />
        </CardContent>
      </Card>
    )
  }
  if (state.status === "empty") {
    return (
      <Empty className="border">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <CalendarRangeIcon />
          </EmptyMedia>
          <EmptyTitle>公開活動データがありません</EmptyTitle>
          <EmptyDescription>
            公開済み動画が取得されると日別の公開本数を表示します。
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  }
  if (state.status === "error") {
    return (
      <Alert variant="destructive" aria-label="公開活動を読み込めませんでした">
        <AlertCircleIcon />
        <AlertTitle>公開活動を読み込めませんでした</AlertTitle>
        <AlertDescription>{state.message}</AlertDescription>
      </Alert>
    )
  }
  return (
    <PublicationHeatmap channels={state.data.channels} days={state.data.days} />
  )
}

function DashboardOverview({
  channels,
  selectedDays,
}: {
  channels: ChannelOverview[]
  selectedDays: number
}) {
  const scheduledChannels = channels.filter(
    (channel) => channel.scheduled_count !== null
  )
  const scheduledTotal = scheduledChannels.reduce(
    (total, channel) => total + (channel.scheduled_count ?? 0),
    0
  )
  const attentionCount = channels.filter(
    (channel) => channel.refresh_error !== null || channel.status !== "ready"
  ).length
  const startDates = channels.flatMap((channel) =>
    channel.period.start_date ? [channel.period.start_date] : []
  )
  const endDates = channels.flatMap((channel) =>
    channel.period.end_date ? [channel.period.end_date] : []
  )
  const collectedDates = channels.flatMap((channel) =>
    channel.collected_at ? [channel.collected_at] : []
  )
  const startDate = startDates.length > 0 ? startDates.sort()[0] : null
  const endDate = endDates.length > 0 ? (endDates.sort().at(-1) ?? null) : null
  const collectedAt =
    collectedDates.length > 0 ? (collectedDates.sort().at(-1) ?? null) : null

  return (
    <section aria-labelledby="dashboard-overview-title" className="grid gap-4">
      <div>
        <h2
          id="dashboard-overview-title"
          className="dashboard-section-heading text-2xl font-semibold"
        >
          概況
        </h2>
        <p className="text-sm text-muted-foreground">
          まず全体の状態を確認し、次にチャンネル間の差を比較します。
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(18rem,1fr)]">
        <Card variant="accent">
          <CardHeader>
            <CardTitle>現在の状態</CardTitle>
            <CardDescription>
              最後に更新した全チャンネルの集計です。
            </CardDescription>
          </CardHeader>
          <CardContent>
            <dl className="grid gap-3 sm:grid-cols-3">
              <div className="dashboard-metric-surface rounded-lg p-4">
                <dt className="text-xs text-foreground">登録チャンネル</dt>
                <dd className="mt-1 text-2xl font-semibold tabular-nums">
                  {formatInteger(channels.length)}
                  <span className="ml-1 text-sm font-normal text-foreground">
                    件
                  </span>
                </dd>
              </div>
              <div className="dashboard-metric-surface rounded-lg p-4">
                <dt className="text-xs text-foreground">公開予約 合計</dt>
                <dd className="mt-1 text-2xl font-semibold tabular-nums">
                  {formatInteger(scheduledTotal)}
                  <span className="ml-1 text-sm font-normal text-foreground">
                    本
                  </span>
                </dd>
              </div>
              <div className="dashboard-metric-surface rounded-lg p-4">
                <dt className="text-xs text-foreground">要確認</dt>
                <dd className="mt-1 text-2xl font-semibold tabular-nums">
                  {formatInteger(attentionCount)}
                  <span className="ml-1 text-sm font-normal text-foreground">
                    件
                  </span>
                </dd>
              </div>
            </dl>
          </CardContent>
          <CardFooter className="text-xs text-muted-foreground">
            公開予約未取得:
            {formatInteger(channels.length - scheduledChannels.length)}件
          </CardFooter>
        </Card>

        <Card role="region" aria-label="表示データについて">
          <CardHeader>
            <CardTitle>表示データについて</CardTitle>
            <CardDescription>判断の前提となる期間と鮮度です。</CardDescription>
          </CardHeader>
          <CardContent>
            <dl className="grid gap-4 text-sm">
              <div className="flex gap-3">
                <CalendarRangeIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                <div>
                  <dt className="font-medium">選択期間</dt>
                  <dd className="text-muted-foreground">
                    直近 {selectedDays} 日
                  </dd>
                </div>
              </div>
              <div className="flex gap-3">
                <CalendarRangeIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                <div>
                  <dt className="font-medium">対象期間</dt>
                  <dd className="text-muted-foreground">
                    {formatDateRange(startDate, endDate)}
                  </dd>
                </div>
              </div>
              <div className="flex gap-3">
                <RefreshCwIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                <div>
                  <dt className="font-medium">最終更新</dt>
                  <dd className="text-muted-foreground">
                    {formatCollectedAt(collectedAt)}
                  </dd>
                </div>
              </div>
            </dl>
          </CardContent>
          <CardFooter className="text-xs text-muted-foreground">
            期間と更新時刻はチャンネルごとに異なる場合があります。
          </CardFooter>
        </Card>
      </div>

      <Card role="region" aria-label="指標の見方">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <InfoIcon className="size-4" />
            指標の見方
          </CardTitle>
          <CardDescription>
            比較表で使用する主要指標の定義です。
          </CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="grid gap-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <dt className="font-medium">公開予約</dt>
              <dd className="mt-1 text-muted-foreground">
                YouTube で公開日時が設定された未公開動画の本数
              </dd>
            </div>
            <div>
              <dt className="font-medium">期間再生数</dt>
              <dd className="mt-1 text-muted-foreground">
                対象期間中に動画が再生された回数
              </dd>
            </div>
            <div>
              <dt className="font-medium">純増登録者</dt>
              <dd className="mt-1 text-muted-foreground">
                対象期間中の登録者増加数から減少数を引いた値
              </dd>
            </div>
            <div>
              <dt className="font-medium">総再生時間</dt>
              <dd className="mt-1 text-muted-foreground">
                対象期間中に視聴された時間の合計
              </dd>
            </div>
          </dl>
        </CardContent>
      </Card>
    </section>
  )
}

function SummaryMetrics({ summary }: { summary: Summary }) {
  const subscriberTone =
    summary.subscribers_net > 0
      ? "positive"
      : summary.subscribers_net < 0
        ? "negative"
        : "neutral"

  return (
    <dl className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <div className="dashboard-metric-surface rounded-lg p-4">
        <dt className="text-xs text-foreground">再生数</dt>
        <dd className="text-2xl font-semibold tabular-nums">
          {formatInteger(summary.views)}
        </dd>
      </div>
      <div className="dashboard-metric-surface rounded-lg p-4">
        <dt className="text-xs text-foreground">総再生時間</dt>
        <dd className="text-2xl font-semibold tabular-nums">
          {formatInteger(summary.watch_time_minutes)}
          <span className="ml-1 text-sm font-normal text-foreground">分</span>
        </dd>
      </div>
      <div
        className="dashboard-metric-surface rounded-lg p-4"
        data-tone={subscriberTone}
      >
        <dt className="text-xs text-foreground">純増登録者</dt>
        <dd className="text-2xl font-semibold tabular-nums">
          {formatSignedInteger(summary.subscribers_net)}
        </dd>
      </div>
      <div className="dashboard-metric-surface rounded-lg p-4">
        <dt className="text-xs text-foreground">エンゲージメント</dt>
        <dd className="text-2xl font-semibold tabular-nums">
          {formatInteger(summary.engagements)}
        </dd>
      </div>
    </dl>
  )
}

function collectionStageLabel(
  stage: WorkflowTimingCollection["stage"]
): string {
  switch (stage) {
    case "planning":
      return "進行中コレクション"
    case "live":
      return "最新公開コレクション"
  }
}

function WorkflowTimingCard({
  collection,
}: {
  collection: WorkflowTimingCollection
}) {
  const stageLabel = collectionStageLabel(collection.stage)
  return (
    <Card
      role="region"
      aria-label={`${stageLabel} ${collection.collection_id}`}
    >
      <CardHeader>
        <CardTitle>{stageLabel}</CardTitle>
        <CardDescription>{collection.collection_id}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        <WorkflowTimingMetricsList totals={collection.totals} />
        {collection.steps.length > 0 ? (
          <WorkflowStepTable
            collectionId={collection.collection_id}
            steps={collection.steps}
          />
        ) : null}
      </CardContent>
    </Card>
  )
}

function WorkflowTimingSummary({
  workflowTiming,
}: {
  workflowTiming: WorkflowTiming
}) {
  const presentation = workflowTimingPresentation(workflowTiming)
  const collections =
    presentation.kind === "ready" || presentation.kind === "in_progress"
      ? presentation.collections
      : []

  return (
    <section aria-labelledby="workflow-timing-title" className="grid gap-4">
      <div>
        <h3 id="workflow-timing-title" className="text-xl font-semibold">
          コレクション時間サマリー
        </h3>
        <p className="text-sm text-muted-foreground">
          API が集計した作業時間と削減時間をコレクション単位で比較します。
        </p>
      </div>
      <WorkflowTimingFormulaGuide />
      <WorkflowTimingState presentation={presentation} />
      <div className="grid gap-4">
        {collections.map((collection) => (
          <WorkflowTimingCard
            key={`${collection.stage}-${collection.collection_id}`}
            collection={collection}
          />
        ))}
      </div>
    </section>
  )
}

function WorkflowTimingState({
  presentation,
}: {
  presentation: WorkflowTimingPresentation
}) {
  switch (presentation.kind) {
    case "ready":
      return null
    case "in_progress":
      return (
        <div
          role="status"
          aria-label="workflow timing 進行中"
          className="flex items-center gap-3 rounded-lg border p-4"
        >
          <Badge>進行中</Badge>
          <p className="text-sm text-muted-foreground">
            現在の計測結果を表示しています。
          </p>
        </div>
      )
    case "error":
      return (
        <Alert variant="destructive">
          <AlertCircleIcon />
          <AlertTitle>{presentation.label}</AlertTitle>
          <AlertDescription>{presentation.error.message}</AlertDescription>
        </Alert>
      )
    case "unconfigured":
    case "unmeasured":
    case "unavailable":
      return (
        <div
          role="status"
          aria-label={`workflow timing ${presentation.label}`}
          className="dashboard-metric-surface rounded-lg p-4"
        >
          <p className="font-semibold tabular-nums">{presentation.label}</p>
        </div>
      )
  }
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
          <AlertTitle>
            {dashboardStatusPresentation(detail.status).label}
          </AlertTitle>
          <AlertDescription>{detail.error.message}</AlertDescription>
        </Alert>
      ) : null}
      {detail.summary ? <SummaryMetrics summary={detail.summary} /> : null}
      <WorkflowTimingSummary workflowTiming={detail.workflow_timing} />
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
              <ChartContainer
                config={chartConfig}
                className="min-h-64 w-full"
                data-testid="top-videos-chart"
              >
                <BarChart
                  accessibilityLayer
                  data={chartData}
                  layout="vertical"
                  margin={{ left: 8, right: 64 }}
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
                  <Bar dataKey="views" fill="var(--color-views)" radius={4}>
                    <LabelList
                      dataKey="views"
                      position="right"
                      fill="var(--foreground)"
                      formatter={(value) =>
                        typeof value === "number"
                          ? formatInteger(value)
                          : String(value ?? "")
                      }
                    />
                  </Bar>
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
              <Table aria-label="動画パフォーマンス">
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
                        {formatInteger(video.views)}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {formatInteger(video.impressions)}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {video.ctr_percentage.toFixed(1)}%
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {formatInteger(video.engagements)}
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
  const [publicationActivity, setPublicationActivity] =
    useState<PublicationActivityState>({ status: "loading" })
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<ChannelDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [selectedDays, setSelectedDays] = useState(30)
  const [trends, setTrends] = useState<TrendsResponse | null>(null)
  const [pipeline, setPipeline] = useState<PipelineResponse | null>(null)
  const [pipelineError, setPipelineError] = useState<string | null>(null)
  const detailRequestId = useRef(0)

  useEffect(() => {
    void requestJson<OverviewResponse>("/api/channels")
      .then((response) => setChannels(response.channels))
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : String(reason))
      })

    void requestJson<unknown>("/api/publications")
      .then((response) => {
        if (!isPublicationActivityResponse(response)) {
          throw new Error("応答形式が不正です")
        }
        const publicationCount = Object.values(response.days).reduce(
          (total, count) => total + count,
          0
        )
        setPublicationActivity(
          publicationCount === 0
            ? { status: "empty" }
            : { status: "ready", data: response }
        )
      })
      .catch((reason: unknown) => {
        setPublicationActivity({
          status: "error",
          message: reason instanceof Error ? reason.message : String(reason),
        })
      })
    void requestJson<TrendsResponse>("/api/trends")
      .then((response) => {
        if (isTrendsResponse(response)) setTrends(response)
      })
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : String(reason))
      })
    void requestJson<unknown>("/api/pipeline")
      .then((response) => {
        if (!isPipelineResponse(response)) {
          throw new Error("応答形式が不正です")
        }
        setPipeline(response)
      })
      .catch((reason: unknown) => {
        setPipelineError(
          reason instanceof Error ? reason.message : String(reason)
        )
      })
  }, [])

  async function refreshDashboard(days = selectedDays) {
    setRefreshing(true)
    setError(null)
    try {
      await requestJson<OverviewResponse>("/api/refresh", "POST", { days })
      const [
        overviewResponse,
        publicationsResponse,
        trendsResponse,
        detailResponse,
      ] = await Promise.all([
        requestJson<OverviewResponse>("/api/channels"),
        requestJson<unknown>("/api/publications"),
        requestJson<TrendsResponse>("/api/trends"),
        selectedId
          ? requestJson<ChannelDetail>(
              `/api/channels/${encodeURIComponent(selectedId)}`
            )
          : Promise.resolve(null),
      ])
      if (!isPublicationActivityResponse(publicationsResponse)) {
        throw new Error("応答形式が不正です")
      }
      setChannels(overviewResponse.channels)
      if (isTrendsResponse(trendsResponse)) setTrends(trendsResponse)
      setDetail(detailResponse)
      try {
        const pipelineResponse = await requestJson<unknown>("/api/pipeline")
        if (!isPipelineResponse(pipelineResponse)) {
          throw new Error("pipeline 応答形式が不正です")
        }
        setPipeline(pipelineResponse)
        setPipelineError(null)
      } catch (reason) {
        setPipelineError(
          reason instanceof Error ? reason.message : String(reason)
        )
      }
      const publicationCount = Object.values(publicationsResponse.days).reduce(
        (total, count) => total + count,
        0
      )
      setPublicationActivity(
        publicationCount === 0
          ? { status: "empty" }
          : { status: "ready", data: publicationsResponse }
      )
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setRefreshing(false)
    }
  }

  async function selectChannel(channelId: string) {
    const requestId = detailRequestId.current + 1
    detailRequestId.current = requestId
    setSelectedId(channelId)
    setDetail(null)
    setError(null)
    setDetailLoading(true)
    try {
      const response = await requestJson<ChannelDetail>(
        `/api/channels/${encodeURIComponent(channelId)}`
      )
      if (detailRequestId.current === requestId) {
        setDetail(response)
      }
    } catch (reason) {
      if (detailRequestId.current === requestId) {
        setError(reason instanceof Error ? reason.message : String(reason))
      }
    } finally {
      if (detailRequestId.current === requestId) {
        setDetailLoading(false)
      }
    }
  }

  return (
    <main className="dashboard-palette-background min-h-svh">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-8 p-4 sm:p-8">
        <header className="flex items-start justify-between gap-4">
          <div className="flex flex-col gap-2">
            <Badge variant="secondary" className="gap-1">
              <DatabaseIcon data-icon="inline-start" />
              手動更新対応
            </Badge>
            <h1 className="text-3xl font-semibold tracking-tight text-primary sm:text-4xl">
              YouTube Analytics Dashboard
            </h1>
            <p className="max-w-2xl text-muted-foreground">
              全チャンネルを更新し、チャンネルと動画の最新パフォーマンスを確認できます。
            </p>
          </div>
          <div className="flex items-center gap-2">
            <ToggleGroup
              aria-label="集計期間"
              variant="outline"
              spacing={0}
              value={[String(selectedDays)]}
              disabled={refreshing}
              onValueChange={(values) => {
                const value = values.at(-1)
                if (!value) return
                const days = Number(value)
                setSelectedDays(days)
                void refreshDashboard(days)
              }}
            >
              {[7, 30, 90].map((days) => (
                <ToggleGroupItem key={days} value={String(days)}>
                  {days} 日
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
            <Button
              variant="outline"
              disabled={refreshing}
              onClick={() => void refreshDashboard()}
            >
              <RefreshCwIcon
                className={refreshing ? "animate-spin" : undefined}
              />
              {refreshing ? "更新中" : "データを更新"}
            </Button>
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
            <Sheet>
              <SheetTrigger
                render={
                  <Button
                    variant="outline"
                    size="icon"
                    aria-label="設定を開く"
                  />
                }
              >
                <SettingsIcon />
              </SheetTrigger>
              <SheetContent>
                <SheetHeader>
                  <SheetTitle>設定</SheetTitle>
                  <SheetDescription>
                    ダッシュボードの表示を調整します。
                  </SheetDescription>
                </SheetHeader>
                <section
                  aria-labelledby="palette-settings-title"
                  className="flex flex-col gap-3 px-4"
                >
                  <div>
                    <h2 id="palette-settings-title" className="font-medium">
                      カラーパレット
                    </h2>
                    <p className="text-sm text-muted-foreground">
                      ダッシュボードのテーマカラーを選択できます。
                    </p>
                  </div>
                  <PaletteSwitcher />
                </section>
              </SheetContent>
            </Sheet>
          </div>
        </header>

        <PublicationActivityPanel state={publicationActivity} />
        {trends ? <ChannelTrendChart data={trends} /> : null}

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
            <DashboardOverview
              channels={channels}
              selectedDays={selectedDays}
            />
            <ChannelStockTable
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
                    <h2 className="dashboard-section-heading text-2xl font-semibold">
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
        {pipeline ? <PipelineStatusTable data={pipeline} /> : null}
        {pipelineError && channels !== null ? (
          <Card role="status">
            <CardHeader>
              <CardTitle>パイプライン状況を読み込めませんでした</CardTitle>
              <CardDescription>{pipelineError}</CardDescription>
            </CardHeader>
          </Card>
        ) : null}
      </div>
    </main>
  )
}

export default App
