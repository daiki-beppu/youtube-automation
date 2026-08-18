import { ArrowRightIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  formatCollectedAt,
  formatInteger,
  formatPeriodViewsLabel,
  resolveDashboardPeriod,
  formatSignedInteger,
  formatWatchTime,
} from "@/lib/dashboard-formatters"
import { dashboardStatusPresentation } from "@/lib/dashboard-status"
import type { ChannelOverview } from "@/lib/dashboard-types"

import { STOCK_TABLE_CONTRACT } from "./constants"

function isAvailable(
  channel: ChannelOverview
): channel is ChannelOverview & { scheduled_count: number } {
  return channel.scheduled_count !== null
}

function stockVariant(count: number): "destructive" | "warning" | "default" {
  if (count === STOCK_TABLE_CONTRACT.stockCriticalThreshold) {
    return "destructive"
  }
  if (count < STOCK_TABLE_CONTRACT.stockWarningThreshold) return "warning"
  return "default"
}

function statusText(channel: ChannelOverview): string {
  return channel.refresh_error
    ? STOCK_TABLE_CONTRACT.refreshFailed
    : dashboardStatusPresentation(channel.status).label
}

function statusVariant(
  channel: ChannelOverview
): "destructive" | "warning" | "outline" {
  if (
    channel.refresh_error ||
    dashboardStatusPresentation(channel.status).severity === "error"
  ) {
    return "destructive"
  }
  return dashboardStatusPresentation(channel.status).severity === "warning"
    ? "warning"
    : "outline"
}

function MetricCell({
  channel,
  label,
  metric,
}: {
  channel: ChannelOverview
  label: string
  metric: "views" | "subscribers_net" | "watch_time_minutes"
}) {
  if (!channel.summary) {
    return (
      <TableCell className="flex flex-col gap-1 whitespace-normal lg:table-cell">
        <span className="text-xs text-muted-foreground lg:hidden">{label}</span>
        —
      </TableCell>
    )
  }
  const value = channel.summary[metric]
  const formatted =
    metric === "subscribers_net"
      ? formatSignedInteger(value)
      : metric === "watch_time_minutes"
        ? formatWatchTime(value)
        : formatInteger(value)
  const subscriberTone =
    value > 0 ? "positive" : value < 0 ? "negative" : "neutral"
  return (
    <TableCell className="flex flex-col gap-1 text-left whitespace-normal tabular-nums lg:table-cell lg:text-right">
      <span className="text-xs text-muted-foreground lg:hidden">{label}</span>
      {metric === "subscribers_net" ? (
        <span className="dashboard-signed-value" data-tone={subscriberTone}>
          {formatted}
        </span>
      ) : (
        formatted
      )}
    </TableCell>
  )
}

export function ChannelStockTable({
  channels,
  onSelect,
  selectedId,
}: {
  channels: ChannelOverview[]
  onSelect?: (id: string) => void
  selectedId?: string | null
}) {
  const sortedChannels = [...channels].sort((left, right) => {
    const leftAvailable = isAvailable(left)
    const rightAvailable = isAvailable(right)
    if (leftAvailable && rightAvailable) {
      return left.scheduled_count - right.scheduled_count
    }
    if (leftAvailable) return -1
    if (rightAvailable) return 1
    return 0
  })
  const unavailableCount = channels.length - channels.filter(isAvailable).length
  const total = channels
    .filter(isAvailable)
    .reduce((sum, channel) => sum + channel.scheduled_count, 0)
  const { startDate, endDate } = resolveDashboardPeriod(
    channels.map((channel) => channel.period)
  )
  const viewsLabel = formatPeriodViewsLabel(startDate, endDate)

  return (
    <section aria-labelledby="channel-stock-title" className="grid gap-4">
      <div>
        <h2
          id="channel-stock-title"
          className="dashboard-section-heading text-2xl font-semibold"
        >
          {STOCK_TABLE_CONTRACT.title}
        </h2>
        <p className="text-sm text-muted-foreground">
          {STOCK_TABLE_CONTRACT.description}
        </p>
      </div>
      <div className="text-sm text-muted-foreground">
        <p>
          {STOCK_TABLE_CONTRACT.summary.prefix} {formatInteger(total)}本
        </p>
        {unavailableCount > 0 ? (
          <p>
            {STOCK_TABLE_CONTRACT.unavailable} {unavailableCount}
            {STOCK_TABLE_CONTRACT.summary.excludedSuffix}
          </p>
        ) : null}
      </div>
      <div className="min-w-0 overflow-hidden rounded-lg border">
        <Table
          aria-label={STOCK_TABLE_CONTRACT.ariaLabel}
          className="block max-w-full min-w-0 table-fixed overflow-hidden lg:table"
        >
          <TableHeader className="hidden lg:table-header-group">
            <TableRow>
              <TableHead>{STOCK_TABLE_CONTRACT.columns.channel}</TableHead>
              <TableHead>{STOCK_TABLE_CONTRACT.columns.status}</TableHead>
              <TableHead>{STOCK_TABLE_CONTRACT.columns.collectedAt}</TableHead>
              <TableHead>{STOCK_TABLE_CONTRACT.columns.stock}</TableHead>
              <TableHead className="text-right">{viewsLabel}</TableHead>
              <TableHead className="text-right">
                {STOCK_TABLE_CONTRACT.columns.subscribersNet}
              </TableHead>
              <TableHead className="text-right">
                {STOCK_TABLE_CONTRACT.columns.watchTime}
              </TableHead>
              {onSelect ? (
                <TableHead className="text-right">詳細</TableHead>
              ) : null}
            </TableRow>
          </TableHeader>
          <TableBody className="grid gap-3 p-3 lg:table-row-group lg:p-0">
            {sortedChannels.map((channel) => {
              const available = isAvailable(channel)
              return (
                <TableRow
                  key={channel.id}
                  className="grid grid-cols-2 gap-x-4 gap-y-3 rounded-lg border p-4 lg:table-row lg:rounded-none lg:border-x-0 lg:p-0"
                >
                  <TableCell className="col-span-2 flex items-center justify-between p-0 font-medium whitespace-normal lg:table-cell lg:p-2">
                    <span>{channel.name}</span>{" "}
                    <span className="text-xs font-normal text-muted-foreground lg:hidden">
                      {formatCollectedAt(channel.collected_at)}
                    </span>
                  </TableCell>
                  <TableCell className="flex flex-col gap-1 p-0 whitespace-normal lg:table-cell lg:p-2">
                    <span className="text-xs text-muted-foreground lg:hidden">
                      {STOCK_TABLE_CONTRACT.columns.status}
                    </span>
                    <Badge
                      variant={statusVariant(channel)}
                      aria-label={
                        channel.refresh_error
                          ? `更新失敗: ${channel.refresh_error.message}`
                          : undefined
                      }
                    >
                      {statusText(channel)}
                    </Badge>
                  </TableCell>
                  <TableCell className="hidden lg:table-cell">
                    {formatCollectedAt(channel.collected_at)}
                  </TableCell>
                  <TableCell className="flex flex-col gap-1 p-0 whitespace-normal lg:table-cell lg:p-2">
                    <span className="text-xs text-muted-foreground lg:hidden">
                      {STOCK_TABLE_CONTRACT.columns.stock}
                    </span>
                    <Badge
                      variant={
                        available
                          ? stockVariant(channel.scheduled_count)
                          : "outline"
                      }
                    >
                      {available
                        ? `${formatInteger(channel.scheduled_count)}本`
                        : STOCK_TABLE_CONTRACT.unavailable}
                    </Badge>
                  </TableCell>
                  <MetricCell
                    channel={channel}
                    label={viewsLabel}
                    metric="views"
                  />
                  <MetricCell
                    channel={channel}
                    label={STOCK_TABLE_CONTRACT.columns.subscribersNet}
                    metric="subscribers_net"
                  />
                  <MetricCell
                    channel={channel}
                    label={STOCK_TABLE_CONTRACT.columns.watchTime}
                    metric="watch_time_minutes"
                  />
                  {onSelect ? (
                    <TableCell className="col-span-2 p-0 text-right lg:table-cell lg:p-2">
                      <Button
                        variant={
                          selectedId === channel.id ? "secondary" : "outline"
                        }
                        size="sm"
                        className="w-full lg:w-auto"
                        aria-pressed={selectedId === channel.id}
                        aria-label={`${channel.name} の動画詳細を見る`}
                        onClick={() => onSelect(channel.id)}
                      >
                        動画詳細
                        <ArrowRightIcon data-icon="inline-end" />
                      </Button>
                    </TableCell>
                  ) : null}
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </div>
    </section>
  )
}
