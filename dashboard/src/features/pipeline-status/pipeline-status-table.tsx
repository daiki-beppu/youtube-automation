import { useState } from "react"

import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import type {
  PipelineCollection,
  PipelineResponse,
} from "@/lib/dashboard-types"

type PhaseFilter =
  "all" | "planning" | "prepared" | "mastered" | "publishing" | "complete"

const phaseFilterOptions: Array<{ value: PhaseFilter; label: string }> = [
  { value: "all", label: "すべて" },
  { value: "planning", label: "planning" },
  { value: "prepared", label: "prepared" },
  { value: "mastered", label: "mastered" },
  { value: "publishing", label: "publishing" },
  { value: "complete", label: "complete" },
]

function isPhaseFilter(value: string | undefined): value is PhaseFilter {
  return phaseFilterOptions.some((option) => option.value === value)
}

const ownerLabels: Record<
  NonNullable<PipelineCollection["execution_owner"]>,
  string
> = {
  local: "ローカル",
  cloud: "クラウド",
}

const handoffLabels: Record<PipelineCollection["handoff_status"], string> = {
  not_started: "未開始",
  pending: "引き渡し待ち",
  completed: "引き渡し済み",
  not_recorded: "引き渡し記録なし",
  not_applicable: "対象外",
  invalid: "state 不正",
}

function eventLabel(collection: PipelineCollection): string {
  if (collection.latest_event === null) return "記録なし"
  return `state 更新 ${new Intl.DateTimeFormat("ja-JP", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(collection.latest_event.occurred_at))}`
}

export function PipelineStatusTable({ data }: { data: PipelineResponse }) {
  const [phaseFilter, setPhaseFilter] = useState<PhaseFilter>("all")
  const visibleChannels =
    phaseFilter === "all"
      ? data.channels
      : data.channels.flatMap((channel) => {
          const collections = channel.collections.filter(
            (collection) => collection.phase === phaseFilter
          )
          return collections.length === 0 ? [] : [{ ...channel, collections }]
        })

  return (
    <Card role="region" aria-labelledby="pipeline-status-title">
      <CardHeader>
        <CardTitle id="pipeline-status-title">パイプライン状況</CardTitle>
        <CardDescription>
          Git 管理の workflow state から、工程所有側と引き渡し状態を表示します。
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <ToggleGroup
          aria-label="phase フィルター"
          value={[phaseFilter]}
          onValueChange={(values) => {
            const nextFilter = values[0]
            if (isPhaseFilter(nextFilter)) setPhaseFilter(nextFilter)
          }}
          variant="outline"
          size="sm"
          className="flex-wrap justify-start"
        >
          {phaseFilterOptions.map((option) => (
            <ToggleGroupItem
              key={option.value}
              value={option.value}
              aria-label={option.label}
            >
              {option.label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        <Table aria-label="パイプライン状況">
          <TableHeader>
            <TableRow>
              <TableHead>チャンネル</TableHead>
              <TableHead>コレクション</TableHead>
              <TableHead>phase</TableHead>
              <TableHead>工程所有側</TableHead>
              <TableHead>引き渡し</TableHead>
              <TableHead>直近イベント</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {visibleChannels.flatMap((channel) =>
              channel.collections.length === 0 ? (
                <TableRow key={channel.id}>
                  <TableCell className="font-medium">{channel.name}</TableCell>
                  <TableCell colSpan={5} className="text-muted-foreground">
                    {channel.error?.message ?? "state なし"}
                  </TableCell>
                </TableRow>
              ) : (
                channel.collections.map((collection, index) => (
                  <TableRow key={`${channel.id}-${collection.collection_id}`}>
                    <TableCell className="font-medium">
                      {index === 0 ? channel.name : null}
                    </TableCell>
                    <TableCell>{collection.collection_id}</TableCell>
                    <TableCell>
                      {collection.phase === null ? (
                        <Badge variant="destructive">不正</Badge>
                      ) : (
                        <Badge variant="outline">{collection.phase}</Badge>
                      )}
                    </TableCell>
                    <TableCell>
                      {collection.execution_owner === null
                        ? "—"
                        : ownerLabels[collection.execution_owner]}
                    </TableCell>
                    <TableCell>
                      {handoffLabels[collection.handoff_status]}
                    </TableCell>
                    <TableCell>
                      {collection.error?.message ?? eventLabel(collection)}
                    </TableCell>
                  </TableRow>
                ))
              )
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}
