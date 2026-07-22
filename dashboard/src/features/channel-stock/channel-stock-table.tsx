import { Badge } from "@/components/ui/badge"
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
  formatSignedInteger,
} from "@/lib/dashboard-formatters"
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
    ? STOCK_TABLE_CONTRACT.status.refreshFailed
    : STOCK_TABLE_CONTRACT.status.ready
}

function MetricCell({
  channel,
  metric,
}: {
  channel: ChannelOverview
  metric: "views" | "subscribers_net" | "watch_time_minutes"
}) {
  if (!channel.summary) return <TableCell>—</TableCell>
  const value = channel.summary[metric]
  const formatted =
    metric === "subscribers_net"
      ? formatSignedInteger(value)
      : formatInteger(value)
  return (
    <TableCell className="text-right tabular-nums">
      {formatted}
      {metric === "watch_time_minutes" ? "分" : ""}
    </TableCell>
  )
}

export function ChannelStockTable({
  channels,
}: {
  channels: ChannelOverview[]
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

  return (
    <section aria-labelledby="channel-stock-title" className="grid gap-4">
      <div>
        <h2 id="channel-stock-title" className="text-2xl font-semibold">
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
          className="min-w-max"
        >
          <TableHeader>
            <TableRow>
              <TableHead>{STOCK_TABLE_CONTRACT.columns.channel}</TableHead>
              <TableHead>{STOCK_TABLE_CONTRACT.columns.status}</TableHead>
              <TableHead>{STOCK_TABLE_CONTRACT.columns.collectedAt}</TableHead>
              <TableHead>{STOCK_TABLE_CONTRACT.columns.stock}</TableHead>
              <TableHead className="text-right">
                {STOCK_TABLE_CONTRACT.columns.views}
              </TableHead>
              <TableHead className="text-right">
                {STOCK_TABLE_CONTRACT.columns.subscribersNet}
              </TableHead>
              <TableHead className="text-right">
                {STOCK_TABLE_CONTRACT.columns.watchTime}
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sortedChannels.map((channel) => {
              const available = isAvailable(channel)
              return (
                <TableRow key={channel.id}>
                  <TableCell className="font-medium">{channel.name}</TableCell>
                  <TableCell>
                    <Badge
                      variant={
                        channel.refresh_error ? "destructive" : "outline"
                      }
                      aria-label={
                        channel.refresh_error
                          ? `更新失敗: ${channel.refresh_error.message}`
                          : undefined
                      }
                    >
                      {statusText(channel)}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    {formatCollectedAt(channel.collected_at)}
                  </TableCell>
                  <TableCell>
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
                  <MetricCell channel={channel} metric="views" />
                  <MetricCell channel={channel} metric="subscribers_net" />
                  <MetricCell channel={channel} metric="watch_time_minutes" />
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </div>
    </section>
  )
}
